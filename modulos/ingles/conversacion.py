"""Fase 2, punto 5 (paso 2): modo ingles para conversar (Telegram y voz).

- Una sesion por canal ('telegram' o 'voz'), guardada en la tabla 'ingles_sesiones' (sobrevive reinicios
  y la comparten el bot y la voz: el bot cierra las sesiones olvidadas y envia las correcciones).
- Durante la charla el "profesor" NO corrige (para no cortar el ritmo): solo conversa y pregunta.
- Al terminar, la IA revisa SOLO lo que escribio/dijo el usuario y devuelve errores, version mejor,
  expresiones utiles y un consejo. Las expresiones se pueden guardar como tarjetas (vocab).
"""
import json
import re
from contextlib import closing
from datetime import datetime

import requests

from modulos.comun import db
from modulos.comun.base import NOMBRE, ZONA, ahora, registro
from modulos.ingles import vocab

log = registro("ingles")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ingles_sesiones (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    canal        TEXT NOT NULL,              -- telegram | voz
    tema         TEXT DEFAULT '',
    inicio       TEXT NOT NULL,              -- ISO con zona
    ultimo       TEXT NOT NULL,              -- ultimo mensaje
    estado       TEXT DEFAULT 'abierta',     -- abierta | cerrada
    turnos       TEXT DEFAULT '[]',          -- [{"role": "user"|"assistant", "content": "..."}]
    minutos      REAL DEFAULT 0,
    correcciones TEXT DEFAULT ''             -- JSON del resultado final
);
"""

PIDE_PRACTICA = re.compile(r"let'?s practi[cs]e|practi(?:quemos|car|ca) (?:el |en )?ingl[eé]s|modo ingl[eé]s|"
                           r"hablemos (?:en )?ingl[eé]s|english practi[cs]e|practice english", re.I)
FIN_PRACTICA = re.compile(r"^(?:that'?s all|that is all|let'?s stop|let'?s finish|stop(?: the)? practi[cs]e|"
                          r"end(?: the)? practi[cs]e|finish(?: the)? practi[cs]e|we'?re done|i'?m done|"
                          r"terminamos|eso es todo|nada m[aá]s|fin de la pr[aá]ctica|stop|finish|the end)$", re.I)
_RELLENO = re.compile(r"\b(?:ok(?:ay)?|well|so|jarvis|please|thanks|thank you|for today|for now|sir|se[nñ]or|"
                      r"gracias|por hoy|bueno)\b|[^\w' ]", re.I)


def es_fin(texto):
    """True solo si TODO el mensaje es una despedida ('That's all, Jarvis.', 'Ok, let's stop for today').
    Asi 'I finish work at six' no corta la practica."""
    limpio = " ".join(_RELLENO.sub(" ", texto).split())
    return bool(FIN_PRACTICA.match(limpio))

MAX_TURNOS = 24


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def _ahora_iso():
    return ahora().isoformat(timespec="seconds")


def obtener(sid):
    with closing(_con()) as con:
        return con.execute("SELECT * FROM ingles_sesiones WHERE id = ?", (sid,)).fetchone()


def abierta(canal):
    with closing(_con()) as con:
        return con.execute("SELECT * FROM ingles_sesiones WHERE canal = ? AND estado = 'abierta' "
                           "ORDER BY id DESC LIMIT 1", (canal,)).fetchone()


def abrir(canal, tema=""):
    with closing(_con()) as con, con:
        return con.execute("INSERT INTO ingles_sesiones (canal, tema, inicio, ultimo) VALUES (?, ?, ?, ?)",
                           (canal, tema.strip()[:80], _ahora_iso(), _ahora_iso())).lastrowid


def _guardar_turnos(sid, turnos):
    with closing(_con()) as con, con:
        con.execute("UPDATE ingles_sesiones SET turnos = ?, ultimo = ? WHERE id = ?",
                    (json.dumps(turnos, ensure_ascii=False), _ahora_iso(), sid))


def turnos(sid):
    return json.loads(obtener(sid)["turnos"] or "[]")


def vencidas(minutos=10):
    """Sesiones abiertas sin mensajes hace mas de 'minutos'."""
    with closing(_con()) as con:
        filas = con.execute("SELECT * FROM ingles_sesiones WHERE estado = 'abierta'").fetchall()
    limite = ahora().timestamp() - minutos * 60
    return [f for f in filas if datetime.fromisoformat(f["ultimo"]).timestamp() < limite]


# ------------------------------------------------------------------ IA ---
def _sistema(tema, canal):
    cfg = vocab.ajustes()
    texto = ("You are JARVIS, " + NOMBRE + "'s English conversation partner. " + NOMBRE + " is "
             + cfg.get("perfil_en", "an English learner") + ", level " + cfg["nivel"] + ", aiming for C1. Interests: " + ", ".join(cfg["temas"]) + ". "
             "Talk ONLY in natural English, friendly and a bit witty, and call him 'sir' now and then. "
             "Keep each reply to 1-3 short sentences and almost always end with ONE open question to keep him talking. "
             "Do NOT correct his mistakes during the conversation (corrections come at the end); just answer naturally. "
             "If he writes a word in Spanish, give him the English word in brackets and continue. "
             "Use vocabulary slightly above his level, but stay clear. ")
    if tema:
        texto += "Today's topic: " + tema + ". "
    if canal == "voz":
        texto += "Your reply will be spoken aloud: no lists, no emojis, no symbols, no markdown."
    else:
        texto += "Plain text, no markdown."
    return texto


def _chat(mensajes, largo=220, temperatura=0.7):
    from modulos.ia import cerebro
    conf = cerebro.config()
    if conf.get("modo_ligero"):
        raise RuntimeError("modo juego/diseño activo")
    cuerpo = {"model": conf["modelo"], "messages": mensajes, "stream": False, "think": False,
              "keep_alive": conf["keep_alive"], "options": {"num_predict": largo, "temperature": temperatura}}
    r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=180)
    if r.status_code == 400:
        cuerpo.pop("think", None)
        r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=180)
    r.raise_for_status()
    texto = r.json()["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", texto, flags=re.S).replace("**", "").strip()


def saludo(sid):
    """Primera frase del profesor: saluda y propone el tema con una pregunta."""
    s = obtener(sid)
    texto = _chat([{"role": "system", "content": _sistema(s["tema"], s["canal"])},
                   {"role": "user", "content": "(Start the practice: greet me in one short sentence and ask me an "
                                               "interesting opening question" + (" about " + s["tema"] if s["tema"] else
                                               " about my day or one of my interests") + ".)"}])
    _guardar_turnos(sid, [{"role": "assistant", "content": texto}])
    return texto


def responder(sid, texto):
    s = obtener(sid)
    lista = turnos(sid) + [{"role": "user", "content": texto.strip()}]
    respuesta = _chat([{"role": "system", "content": _sistema(s["tema"], s["canal"])}] + lista[-MAX_TURNOS:])
    lista.append({"role": "assistant", "content": respuesta})
    _guardar_turnos(sid, lista)
    return respuesta


ESQUEMA_CORRECCION = {"type": "object", "properties": {
    "errores": {"type": "array", "items": {"type": "object", "properties": {
        "dijo": {"type": "string"}, "mejor": {"type": "string"}, "explicacion": {"type": "string"}},
        "required": ["dijo", "mejor", "explicacion"]}},
    "expresiones": {"type": "array", "items": vocab.ESQUEMA_PALABRA},
    "bien": {"type": "string"}, "consejo": {"type": "string"}},
    "required": ["errores", "expresiones", "bien", "consejo"]}


def cerrar(sid):
    """Cierra la sesion y pide las correcciones. Devuelve el dict (o None si el usuario no dijo nada)."""
    s = obtener(sid)
    lista = turnos(sid)
    suyas = [t["content"] for t in lista if t["role"] == "user"]
    minutos = max(0.0, (datetime.fromisoformat(s["ultimo"]) - datetime.fromisoformat(s["inicio"])).total_seconds() / 60)
    resultado = None
    if suyas:
        charla = "\n".join((NOMBRE.upper() + ": " if t["role"] == "user" else "JARVIS: ") + t["content"] for t in lista)
        instruccion = (
            "You are an English teacher reviewing a practice conversation. El usuario is level " + vocab.ajustes()["nivel"]
            + " (goal C1). Review ONLY the user's lines" + (" (they come from speech recognition, so ignore punctuation, "
            "capitalisation and obvious transcription glitches)" if s["canal"] == "voz" else "") + ".\n\n" + charla +
            "\n\nReturn JSON:\n"
            "- errores: up to 6 REAL mistakes (grammar, word choice, unnatural phrasing). 'dijo' = his exact words, "
            "'mejor' = a natural correct version, 'explicacion' = short explanation IN SPANISH (max 15 words). "
            "If there are no real mistakes, return an empty list. Never invent mistakes.\n"
            "- expresiones: 2-3 useful English words or expressions related to what he wanted to say, that would make "
            "him sound more natural (frente, significado in Spanish, ejemplo in English max 14 words).\n"
            "- bien: one sentence IN SPANISH about something he did well.\n"
            "- consejo: one practical tip IN SPANISH for next time (max 25 words).")
        try:
            from modulos.ia import cerebro
            conf = cerebro.config()
            cuerpo = {"model": conf["modelo"], "messages": [{"role": "user", "content": instruccion}], "stream": False,
                      "think": False, "format": ESQUEMA_CORRECCION, "keep_alive": conf["keep_alive"],
                      "options": {"num_predict": 1200, "temperature": 0.2}}
            r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=240)
            if r.status_code == 400:
                cuerpo.pop("think", None)
                r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=240)
            r.raise_for_status()
            resultado = json.loads(r.json()["message"]["content"])
        except Exception as exc:
            log.warning("No pude corregir la sesion %s: %s", sid, exc)
            resultado = {"errores": [], "expresiones": [], "bien": "", "consejo": "", "fallo": str(exc)[:100]}
    resultado = resultado or {"errores": [], "expresiones": [], "bien": "", "consejo": "", "vacia": True}
    resultado["mensajes"] = len(suyas)
    with closing(_con()) as con, con:
        con.execute("UPDATE ingles_sesiones SET estado = 'cerrada', minutos = ?, correcciones = ? WHERE id = ?",
                    (round(minutos, 1), json.dumps(resultado, ensure_ascii=False), sid))
    log.info("Sesion de ingles %s cerrada: %.1f min, %d mensajes", sid, minutos, len(suyas))
    return resultado


def correcciones(sid):
    s = obtener(sid)
    return json.loads(s["correcciones"]) if s and s["correcciones"] else None


# ------------------------------------------------------------------ textos ---
def texto_correcciones(sid):
    """(html, expresiones_que_aun_no_son_tarjeta) para enviar por Telegram."""
    from html import escape
    s = obtener(sid)
    c = correcciones(sid) or {}
    cabeza = ("\U0001F4DD <b>Correcciones de su práctica</b> (" + ("voz" if s["canal"] == "voz" else "Telegram")
              + ", " + str(max(1, round(s["minutos"]))) + " min, " + str(c.get("mensajes", 0)) + " mensajes)")
    if c.get("vacia"):
        return cabeza + "\n\nNo llegó a decir nada, señor. Práctica cerrada sin correcciones.", []
    if c.get("fallo"):
        return cabeza + "\n\nNo pude preparar las correcciones (" + escape(c["fallo"]) + ").", []
    partes = [cabeza]
    if c.get("errores"):
        partes.append("\n✏️ <b>Para mejorar</b>")
        for e in c["errores"]:
            partes.append("• <s>" + escape(e.get("dijo", "")) + "</s>\n   → <b>" + escape(e.get("mejor", ""))
                          + "</b>\n   <i>" + escape(e.get("explicacion", "")) + "</i>")
    else:
        partes.append("\n✏️ Sin errores importantes. \U0001F44F")
    nuevas = [x for x in c.get("expresiones", []) if x.get("frente") and not vocab.buscar(x["frente"])]
    if c.get("expresiones"):
        partes.append("\n\U0001F4A1 <b>Expresiones útiles</b>")
        for x in c["expresiones"]:
            partes.append("• <b>" + escape(x.get("frente", "")) + "</b> – " + escape(x.get("significado", ""))
                          + ("\n   <i>" + escape(x["ejemplo"]) + "</i>" if x.get("ejemplo") else ""))
    if c.get("bien"):
        partes.append("\n✅ " + escape(c["bien"]))
    if c.get("consejo"):
        partes.append("\U0001F3AF " + escape(c["consejo"]))
    if nuevas:
        partes.append("\nToque ➕ para guardar una expresión como tarjeta de repaso.")
    return "\n".join(partes), nuevas


def botones_expresiones(sid, nuevas):
    """Filas de botones (formato crudo de la API) para guardar expresiones como tarjetas."""
    c = correcciones(sid) or {}
    todas = c.get("expresiones", [])
    return [[{"text": "➕ " + x["frente"], "callback_data": "voc:exp:" + str(sid) + ":" + str(todas.index(x))}]
            for x in nuevas]


def resumen_para_voz(sid):
    """Frase corta en espanol para decir por voz al terminar."""
    s = obtener(sid)
    c = correcciones(sid) or {}
    n = len(c.get("errores", []))
    minutos = max(1, round(s["minutos"]))
    if c.get("vacia"):
        return "Muy bien, señor. Cerré la práctica de inglés."
    return ("Listo, señor. Practicamos " + str(minutos) + (" minuto" if minutos == 1 else " minutos") + ". "
            + ("Anoté " + str(n) + (" cosa" if n == 1 else " cosas") + " para mejorar. " if n else
               "No encontré errores importantes. ")
            + "Le envié las correcciones a Telegram.")
