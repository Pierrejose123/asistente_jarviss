"""Fase 2, punto 5 (paso 1): vocabulario de ingles con repaso espaciado (SM-2).

- Tarjetas en la base local (tabla 'tarjetas'): palabra o frase en ingles, significado y un ejemplo.
- el usuario agrega las suyas (/palabra) y el asistente propone algunas cada dia (el usuario acepta o descarta).
- Cada repaso se califica: Otra vez / Dificil / Bien / Facil. El CODIGO calcula cuando vuelve cada
  tarjeta (algoritmo SM-2); la IA solo redacta significados y ejemplos.
- Cada repaso queda guardado (tabla 'repasos') para el resumen semanal.
"""
import json
import re
from contextlib import closing
from datetime import date, timedelta

import requests

from modulos.comun import db
from modulos.comun.base import CONFIG, NOMBRE, PERFIL, ahora, leer_json, registro

log = registro("ingles")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tarjetas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    frente       TEXT NOT NULL,             -- palabra o frase en ingles
    significado  TEXT DEFAULT '',           -- en espanol
    ejemplo      TEXT DEFAULT '',           -- frase de ejemplo en ingles
    origen       TEXT DEFAULT 'usuario',    -- usuario | asistente
    estado       TEXT DEFAULT 'activa',     -- propuesta | activa | descartada | borrada
    facilidad    REAL DEFAULT 2.5,          -- SM-2
    intervalo    INTEGER DEFAULT 0,         -- dias
    repeticiones INTEGER DEFAULT 0,
    proxima      TEXT,                      -- AAAA-MM-DD; vacio = nueva (nunca repasada)
    creada       TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS repasos (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    tarjeta  INTEGER NOT NULL,
    fecha    TEXT NOT NULL,                 -- AAAA-MM-DD
    nota     INTEGER NOT NULL,              -- 1 otra vez, 2 dificil, 3 bien, 4 facil
    nueva    INTEGER DEFAULT 0,             -- 1 si era la primera vez que se veia
    cuando   TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

NOTAS = {1: "Otra vez", 2: "Difícil", 3: "Bien", 4: "Fácil"}


def ajustes():
    base = {"nuevas_por_dia": 5, "propuestas_por_dia": 5, "maximo_repaso": 30, "hora_respaldo": "21:45",
            "nivel": "B1-B2", "temas": ["diseño gráfico", "tecnología", "videojuegos"]}
    if (CONFIG / "ingles.json").exists():
        base.update(leer_json("ingles.json"))
    return base


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def hoy():
    return ahora().date().isoformat()


def _limpio(texto):
    return " ".join((texto or "").strip().strip("\"'«»").split())


# ------------------------------------------------------------------ tarjetas ---
def obtener(tid):
    with closing(_con()) as con:
        return con.execute("SELECT * FROM tarjetas WHERE id = ?", (tid,)).fetchone()


def buscar(frente):
    with closing(_con()) as con:
        return con.execute("SELECT * FROM tarjetas WHERE lower(frente) = lower(?) AND estado != 'borrada'",
                           (_limpio(frente),)).fetchone()


def crear(frente, significado="", ejemplo="", origen="usuario", estado="activa"):
    with closing(_con()) as con, con:
        return con.execute("INSERT INTO tarjetas (frente, significado, ejemplo, origen, estado) VALUES (?, ?, ?, ?, ?)",
                           (_limpio(frente)[:80], _limpio(significado)[:200], _limpio(ejemplo)[:250],
                            origen, estado)).lastrowid


def actualizar(tid, **campos):
    with closing(_con()) as con, con:
        con.execute("UPDATE tarjetas SET " + ", ".join(k + " = ?" for k in campos) + " WHERE id = ?",
                    (*campos.values(), tid))


def todas_las_palabras():
    with closing(_con()) as con:
        return [r[0].lower() for r in con.execute("SELECT frente FROM tarjetas")]


def activas():
    with closing(_con()) as con:
        return con.execute("SELECT * FROM tarjetas WHERE estado = 'activa' ORDER BY id DESC").fetchall()


# ------------------------------------------------------------------ repaso ---
def nuevas_vistas_hoy():
    with closing(_con()) as con:
        return con.execute("SELECT COUNT(*) FROM repasos WHERE fecha = ? AND nueva = 1", (hoy(),)).fetchone()[0]


def para_repasar():
    """Tarjetas que tocan hoy: las vencidas y, ademas, las nuevas hasta el limite diario."""
    cfg = ajustes()
    with closing(_con()) as con:
        vencidas = con.execute("SELECT * FROM tarjetas WHERE estado = 'activa' AND proxima IS NOT NULL "
                               "AND proxima <= ? ORDER BY proxima, id", (hoy(),)).fetchall()
        cupo = max(0, int(cfg["nuevas_por_dia"]) - nuevas_vistas_hoy())
        nuevas = con.execute("SELECT * FROM tarjetas WHERE estado = 'activa' AND proxima IS NULL "
                             "ORDER BY id LIMIT ?", (cupo,)).fetchall()
    return (list(vencidas) + list(nuevas))[:int(cfg["maximo_repaso"])]


def sm2(t, nota):
    """Calcula (facilidad, intervalo, repeticiones) despues de calificar. nota: 1..4."""
    q = {1: 1, 2: 3, 3: 4, 4: 5}[nota]
    facilidad = max(1.3, t["facilidad"] + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
    if q < 3:                                    # no la recordo: vuelve manana
        return facilidad, 1, 0
    reps = t["repeticiones"] + 1
    if reps == 1:
        intervalo = 1
    elif reps == 2:
        intervalo = 3
    else:
        intervalo = round(t["intervalo"] * facilidad)
    if nota == 2:                                # dificil: crece poco
        intervalo = max(1, round(max(t["intervalo"], 1) * 1.2)) if reps > 2 else intervalo
    if nota == 4:                                # facil: un empujon extra
        intervalo = max(intervalo + 1, round(intervalo * 1.3))
    return facilidad, min(intervalo, 365), reps


def calificar(tid, nota):
    """Guarda la calificacion y devuelve el intervalo en dias hasta el proximo repaso."""
    t = obtener(tid)
    facilidad, intervalo, reps = sm2(t, nota)
    proxima = (date.fromisoformat(hoy()) + timedelta(days=intervalo)).isoformat()
    actualizar(tid, facilidad=round(facilidad, 3), intervalo=intervalo, repeticiones=reps, proxima=proxima)
    with closing(_con()) as con, con:
        con.execute("INSERT INTO repasos (tarjeta, fecha, nota, nueva) VALUES (?, ?, ?, ?)",
                    (tid, hoy(), nota, 1 if t["proxima"] is None else 0))
    return intervalo


def resumen_hoy():
    with closing(_con()) as con:
        filas = con.execute("SELECT nota, COUNT(*) FROM repasos WHERE fecha = ? GROUP BY nota", (hoy(),)).fetchall()
    return {r[0]: r[1] for r in filas}


def estadisticas():
    with closing(_con()) as con:
        total = con.execute("SELECT COUNT(*) FROM tarjetas WHERE estado = 'activa'").fetchone()[0]
        aprendidas = con.execute("SELECT COUNT(*) FROM tarjetas WHERE estado = 'activa' AND intervalo >= 21").fetchone()[0]
        nuevas = con.execute("SELECT COUNT(*) FROM tarjetas WHERE estado = 'activa' AND proxima IS NULL").fetchone()[0]
        semana = con.execute("SELECT COUNT(*) FROM repasos WHERE fecha >= ?",
                             ((date.fromisoformat(hoy()) - timedelta(days=6)).isoformat(),)).fetchone()[0]
    return {"total": total, "aprendidas": aprendidas, "sin_ver": nuevas, "repasos_semana": semana,
            "para_hoy": len(para_repasar())}


# ------------------------------------------------------------------ IA (solo redacta) ---
ESQUEMA_PALABRA = {"type": "object", "properties": {
    "frente": {"type": "string"}, "significado": {"type": "string"}, "ejemplo": {"type": "string"}},
    "required": ["frente", "significado", "ejemplo"]}
ESQUEMA_LISTA = {"type": "object", "properties": {"palabras": {"type": "array", "items": ESQUEMA_PALABRA}},
                 "required": ["palabras"]}


def _pedir_json(instruccion, esquema, largo=600):
    from modulos.ia import cerebro
    conf = cerebro.config()
    if conf.get("modo_ligero"):
        raise RuntimeError("modo juego/diseño activo")
    cuerpo = {"model": conf["modelo"], "messages": [{"role": "user", "content": instruccion}], "stream": False,
              "think": False, "format": esquema, "keep_alive": conf["keep_alive"],
              "options": {"num_predict": largo, "temperature": 0.4}}
    r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=180)
    if r.status_code == 400:
        cuerpo.pop("think", None)
        r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=180)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def completar(frente):
    """Pide a la IA significado (espanol) y un ejemplo (ingles) para una palabra o frase."""
    d = _pedir_json("Palabra o expresion en ingles: \"" + _limpio(frente) + "\".\n"
                    "Devuelve: frente (la misma expresion, corregida si tiene un error de ortografia, en minusculas "
                    "salvo nombres propios), significado (traduccion corta al espanol, 1 a 6 palabras; si tiene "
                    "varios, los 2 mas comunes separados por ' / ') y ejemplo (una frase natural en ingles, nivel B1-B2, "
                    "maximo 14 palabras, que use la expresion).", ESQUEMA_PALABRA, 200)
    return _limpio(d.get("frente")) or _limpio(frente), _limpio(d.get("significado")), _limpio(d.get("ejemplo"))


def proponer(cantidad=None):
    """La IA propone palabras utiles nuevas; se guardan como 'propuesta' hasta que el usuario decida."""
    cfg = ajustes()
    cantidad = cantidad or int(cfg["propuestas_por_dia"])
    vistas = set(todas_las_palabras())
    d = _pedir_json("Eres profesor de ingles de " + NOMBRE + (" (" + PERFIL + ")" if PERFIL else "") + ", nivel " + cfg["nivel"]
                    + " con meta C1. Propone " + str(cantidad + 3) + " palabras o expresiones en ingles UTILES y de uso "
                    "real (no basicas como 'computer' o 'color'), sobre: " + ", ".join(cfg["temas"]) + ". Mezcla "
                    "verbos, phrasal verbs, adjetivos y expresiones. Para cada una: frente, significado (espanol, corto) "
                    "y ejemplo (frase natural en ingles, maximo 14 palabras). No repitas ninguna de estas: "
                    + ", ".join(sorted(vistas)[-200:]), ESQUEMA_LISTA, 900)
    nuevas = []
    for p in d.get("palabras", []):
        frente = _limpio(p.get("frente"))
        if not frente or frente.lower() in vistas or not re.match(r"^[A-Za-z][A-Za-z '\-]{1,60}$", frente):
            continue
        vistas.add(frente.lower())
        nuevas.append(crear(frente, p.get("significado", ""), p.get("ejemplo", ""), "asistente", "propuesta"))
        if len(nuevas) >= cantidad:
            break
    log.info("Propuestas nuevas: %s", nuevas)
    return nuevas


def propuestas_pendientes():
    with closing(_con()) as con:
        return con.execute("SELECT * FROM tarjetas WHERE estado = 'propuesta' ORDER BY id").fetchall()
