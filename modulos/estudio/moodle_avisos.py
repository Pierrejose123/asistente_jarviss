"""Notificaciones, avisos de profesores y entregas de Moodle (SOLO LECTURA).

Usa la "clave de servicio" de la app de Moodle (MOODLE_TOKEN en .env, creada con conectar_moodle.py).
Solo se llaman funciones de LECTURA (lista PERMITIDAS); cualquier otra se rechaza en el codigo.
El texto que viene de Moodle se reenvia tal cual al usuario: nunca se ejecuta ni se toma como orden.
"""
import os
import re
import time
from contextlib import closing
from datetime import datetime, timedelta
from html import escape, unescape

import requests

from modulos.comun import db
from modulos.comun.base import ZONA, ahora, registro
from modulos.estudio import moodle
from modulos.tareas import tareas

log = registro("moodle")
SITIO = (os.getenv("MOODLE_SITIO") or "").strip().rstrip("/")   # ej. https://campus.su-instituto.edu
PERMITIDAS = {"core_webservice_get_site_info", "message_popup_get_popup_notifications", "core_enrol_get_users_courses",
              "mod_forum_get_forums_by_courses", "mod_forum_get_forum_discussions",
              "core_calendar_get_calendar_event_by_id", "mod_assign_get_submission_status", "mod_assign_get_assignments",
              "core_course_get_contents"}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS moodle_vistos (
    tipo  TEXT NOT NULL,          -- notificacion | aviso | entrega
    id    TEXT NOT NULL,
    visto TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tipo, id)
);
CREATE TABLE IF NOT EXISTS moodle_entregas (     -- lo último que dijo Moodle de cada deber (para el panel)
    tarea_id INTEGER PRIMARY KEY,
    estado   TEXT,                -- submitted | draft | new | ...
    revisado TEXT
);
CREATE TABLE IF NOT EXISTS moodle_revision (     -- una sola fila: cómo salió la última revisión de entregas
    id       INTEGER PRIMARY KEY CHECK (id = 1),
    cuando   TEXT,
    revisados INTEGER,
    entregados INTEGER,
    errores  INTEGER,
    ultimo_error TEXT
);
"""
_info = {}


class SinConexion(Exception):
    pass


class Ocupado(RuntimeError):
    """Moodle respondió 429 (demasiadas consultas seguidas): hay que esperar y reintentar luego."""


def token():
    return (os.getenv("MOODLE_TOKEN") or "").strip()


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def visto(tipo, ident):
    with closing(_con()) as con:
        return con.execute("SELECT 1 FROM moodle_vistos WHERE tipo = ? AND id = ?", (tipo, str(ident))).fetchone() is not None


def marcar(tipo, ident):
    with closing(_con()) as con, con:
        con.execute("INSERT OR IGNORE INTO moodle_vistos (tipo, id) VALUES (?, ?)", (tipo, str(ident)))


def llamar(funcion, **params):
    if funcion not in PERMITIDAS:
        raise PermissionError("Funcion de Moodle no permitida: " + funcion)
    datos = {"wstoken": token(), "wsfunction": funcion, "moodlewsrestformat": "json"}
    for k, v in params.items():
        if isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                datos[k + "[" + str(i) + "]"] = x
        else:
            datos[k] = v
    r = requests.post(SITIO + "/webservice/rest/server.php", data=datos, timeout=45)
    if r.status_code == 429:                       # Moodle pide calma: una espera corta y un solo reintento
        try:
            espera = min(20, max(3, int(r.headers.get("Retry-After", "10"))))
        except ValueError:
            espera = 10
        time.sleep(espera)
        r = requests.post(SITIO + "/webservice/rest/server.php", data=datos, timeout=45)
        if r.status_code == 429:
            raise Ocupado("Moodle pidió esperar (demasiadas consultas seguidas)")
    r.raise_for_status()
    res = r.json()
    if isinstance(res, dict) and res.get("exception"):
        if res.get("errorcode") in ("invalidtoken", "accessexception"):
            raise SinConexion(res.get("message", "clave de servicio no valida"))
        raise RuntimeError(res.get("message", res.get("errorcode", "error de Moodle")))
    return res


def _usuario():
    if not _info:
        _info.update(llamar("core_webservice_get_site_info"))
    return _info["userid"]


def _limpio(html, largo=350):
    texto = unescape(re.sub(r"<br\s*/?>|</p>", "\n", html or "", flags=re.I))
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", texto)).strip()
    return texto if len(texto) <= largo else texto[:largo].rsplit(" ", 1)[0] + "…"


def _fecha(ts):
    return datetime.fromtimestamp(int(ts), ZONA).strftime("%d/%m %H:%M")


# ------------------------------------------------------------------ notificaciones ---
def notificaciones_nuevas():
    res = llamar("message_popup_get_popup_notifications", useridto=_usuario(), newestfirst=1, limit=30, offset=0)
    nuevas = []
    for n in res.get("notifications", []):
        if visto("notificacion", n["id"]):
            continue
        marcar("notificacion", n["id"])
        nuevas.append(n)
    return sorted(nuevas, key=lambda n: n.get("timecreated", 0))


# ------------------------------------------------------------------ avisos de profesores ---
def _cursos():
    return llamar("core_enrol_get_users_courses", userid=_usuario())


def avisos_nuevos():
    cursos = {c["id"]: c for c in _cursos()}
    if not cursos:
        return []
    foros = llamar("mod_forum_get_forums_by_courses", courseids=list(cursos))
    nuevos = []
    for f in foros:
        if f.get("type") != "news":                          # solo el foro de "Avisos" de cada curso
            continue
        res = llamar("mod_forum_get_forum_discussions", forumid=f["id"], sortorder=-1, page=0, perpage=10)
        curso = cursos.get(f["course"], {})
        materia = moodle.materia_de(curso.get("shortname", "")) or curso.get("fullname", "")
        for d in res.get("discussions", []):
            if visto("aviso", d["discussion"]):
                continue
            marcar("aviso", d["discussion"])
            nuevos.append({"materia": materia, "titulo": d.get("name") or d.get("subject", ""),
                           "texto": _limpio(d.get("message", "")), "autor": d.get("userfullname", ""),
                           "cuando": d.get("timemodified") or d.get("created", 0),
                           "enlace": SITIO + "/mod/forum/discuss.php?d=" + str(d["discussion"])})
    return sorted(nuevos, key=lambda a: a["cuando"])


# ------------------------------------------------------------------ entregas ---
DIAS_ATRAS = 45      # también revisa deberes ya vencidos (pudo entregarlos tarde o Jarvis no se enteró)


def _mapa_tareas():
    """{numero de actividad (cmid): numero de tarea (assign id)} de todos sus cursos, en una sola consulta.
    El calendario de Moodle devuelve en 'instance' el número de la ACTIVIDAD, no el de la tarea."""
    mapa, ids = {}, set()
    for c in llamar("mod_assign_get_assignments").get("courses", []):
        for a in c.get("assignments", []):
            ids.add(a["id"])
            if a.get("cmid"):
                mapa[a["cmid"]] = a["id"]
    return mapa, ids


def _id_tarea(ev, mapa, ids):
    inst = ev.get("instance")
    if inst in mapa:
        return mapa[inst]
    return inst if inst in ids else None


def _guardar_estado(tarea_id, estado):
    with closing(_con()) as con, con:
        con.execute("INSERT OR REPLACE INTO moodle_entregas (tarea_id, estado, revisado) VALUES (?, ?, ?)",
                    (tarea_id, estado, ahora().isoformat(timespec="minutes")))


def _guardar_revision(revisados, entregados, errores, ultimo_error):
    with closing(_con()) as con, con:
        con.execute("INSERT OR REPLACE INTO moodle_revision (id, cuando, revisados, entregados, errores, ultimo_error) "
                    "VALUES (1, ?, ?, ?, ?, ?)", (ahora().isoformat(timespec="minutes"), revisados, entregados, errores,
                                                  (ultimo_error or "")[:200]))


def entregas_hechas():
    """Deberes de Moodle pendientes en el asistente que ya figuran ENTREGADOS en Moodle -> se marcan hechos."""
    desde = (ahora().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=DIAS_ATRAS)).isoformat()
    with closing(moodle._con()) as con:
        filas = con.execute("SELECT * FROM moodle_eventos WHERE tipo = 'deber' AND tarea_id IS NOT NULL "
                            "AND vence >= ?", (desde,)).fetchall()
    hechas, revisadas, mapa, errores, ultimo_error = [], set(), None, 0, ""
    for f in filas:
        if f["tarea_id"] in revisadas:
            continue
        t = tareas.obtener(f["tarea_id"])
        if not t or t["estado"] != "pendiente" or visto("entrega", f["uid"]):
            continue
        evento_id = f["uid"].split("@")[0]
        if not evento_id.isdigit():
            continue
        try:
            ev = llamar("core_calendar_get_calendar_event_by_id", eventid=int(evento_id)).get("event", {})
            if ev.get("modulename") != "assign":
                continue
            if mapa is None:
                mapa = _mapa_tareas()
            assignid = _id_tarea(ev, *mapa)
            if not assignid:
                log.info("No encontré en Moodle la tarea de %s (actividad %s)", f["titulo"], ev.get("instance"))
                errores, ultimo_error = errores + 1, "No encontré la tarea de " + f["titulo"]
                continue
            estado = llamar("mod_assign_get_submission_status", assignid=assignid)
        except SinConexion:
            raise
        except Exception as exc:
            log.info("No pude ver la entrega de %s: %s", f["titulo"], exc)
            errores, ultimo_error = errores + 1, str(exc)
            continue
        revisadas.add(f["tarea_id"])
        intento = estado.get("lastattempt") or {}
        envios = [intento.get("submission") or {}, intento.get("teamsubmission") or {}]
        estados = [e.get("status") for e in envios if e.get("status")]
        entregado = "submitted" in estados
        _guardar_estado(t["id"], "submitted" if entregado else (estados[0] if estados else "new"))
        if entregado:
            marcar("entrega", f["uid"])
            tareas.cambiar_estado(t["id"], "hecha")
            try:
                tareas.subir(t["id"], hecha=True)
            except Exception as exc:
                log.info("No se actualizo en Google: %s", exc)
            hechas.append(t)
        time.sleep(0.3)
    _guardar_revision(len(revisadas), len(hechas), errores, ultimo_error)
    return hechas


# ------------------------------------------------------------------ borradores sin enviar ---
HORAS_BORRADOR = 24          # avisa una sola vez si un borrador sigue sin enviar y el cierre está a menos de esto


def _fecha_local(iso):
    f = datetime.fromisoformat(iso)
    return f if f.tzinfo else f.replace(tzinfo=ZONA)


def borradores_por_cerrar():
    """Deberes con BORRADOR en Moodle (subió algo pero no pulsó «Enviar») cuyo último momento para entregar (cierre,
    o la entrega si no hay cierre) cae en las próximas HORAS_BORRADOR horas. Cada uno se avisa una sola vez."""
    with closing(_con()) as con:
        borradores = {f["tarea_id"] for f in con.execute("SELECT tarea_id FROM moodle_entregas WHERE estado = 'draft'")}
    if not borradores:
        return []
    with closing(moodle._con()) as con:
        filas = [dict(f) for f in con.execute("SELECT * FROM moodle_eventos WHERE tipo IN ('deber', 'cierre')")]
    cierres = {}
    for f in filas:
        if f["tipo"] == "cierre":
            clave = (moodle._clave(f["titulo"]), f.get("curso", ""))
            cierres[clave] = max(cierres.get(clave, f["vence"]), f["vence"])
    ahora_ = ahora()
    salida, vistos = [], set()
    for f in filas:
        tid = f["tarea_id"]
        if f["tipo"] != "deber" or tid not in borradores or tid in vistos:
            continue
        t = tareas.obtener(tid)
        if not t or t["estado"] != "pendiente":
            continue
        limite = _fecha_local(max(f["vence"], cierres.get((moodle._clave(f["titulo"]), f.get("curso", "")), f["vence"])))
        horas = (limite - ahora_).total_seconds() / 3600
        clave = str(tid) + "|" + limite.isoformat(timespec="minutes")
        if 0 < horas <= HORAS_BORRADOR and not visto("borrador", clave):
            marcar("borrador", clave)
            vistos.add(tid)
            salida.append({"tarea": t, "limite": limite, "horas": horas})
    return salida


def _textos_borradores(lista):
    textos = []
    for b in lista:
        t, limite = b["tarea"], b["limite"]
        dia = "hoy" if limite.date() == ahora().date() else "mañana"
        textos.append("\U0001F4DD <b>Borrador sin enviar</b>: " + escape(t["titulo"])
                      + (" (" + escape(t["materia"]) + ")" if t["materia"] != "General" else "")
                      + "\nCierra " + dia + " a las " + limite.strftime("%H:%M")
                      + ". En Moodle falta pulsar <b>«Enviar tarea»</b>; si no, el profesor no lo recibe.")
    return textos


# ------------------------------------------------------------------ todo junto ---
def revisar():
    """Devuelve la lista de mensajes HTML para Telegram."""
    if not token():
        return []
    primera = not db.aviso_enviado("moodle|avisos_inicial")
    notis, avisos = notificaciones_nuevas(), avisos_nuevos()
    hechas = entregas_hechas()
    try:
        borradores = _textos_borradores(borradores_por_cerrar())
    except Exception as exc:
        log.info("No pude revisar borradores: %s", exc)
        borradores = []
    mensajes = []
    if primera:
        db.marcar_aviso("moodle|avisos_inicial")
        sin_leer = [n for n in notis if not n.get("read")]
        texto = ("\U0001F514 <b>Conecté las notificaciones de Moodle.</b>\nDesde ahora le reenvío las nuevas y los "
                 "avisos de sus profesores.")
        if sin_leer:
            texto += "\n\nTiene " + str(len(sin_leer)) + " sin leer; las últimas:"
            for n in sin_leer[-3:]:
                texto += "\n• " + escape(_limpio(n.get("subject", ""), 140)) + " <i>(" + _fecha(n["timecreated"]) + ")</i>"
        if avisos:
            texto += "\n\n\U0001F4E2 Últimos avisos de profesores:"
            for a in avisos[-3:]:
                texto += ("\n• <b>" + escape(a["materia"]) + "</b>: " + escape(a["titulo"])
                          + " <i>(" + _fecha(a["cuando"]) + ")</i>")
        return [texto] + _textos_hechas(hechas) + borradores
    for n in notis:
        texto = "\U0001F514 <b>Moodle</b>: " + escape(_limpio(n.get("subject", ""), 200))
        cuerpo = _limpio(n.get("smallmessage") or n.get("fullmessage", ""), 300)
        if cuerpo and cuerpo not in texto:
            texto += "\n" + escape(cuerpo)
        if n.get("contexturl"):
            texto += '\n<a href="' + escape(n["contexturl"]) + '">Abrir en Moodle</a>'
        mensajes.append(texto)
    for a in avisos:
        texto = ("\U0001F4E2 <b>Aviso de " + escape(a["materia"] or "un curso") + "</b>\n<b>" + escape(a["titulo"]) + "</b>"
                 + (" – " + escape(a["autor"]) if a["autor"] else "") + "\n" + escape(a["texto"])
                 + '\n<a href="' + escape(a["enlace"]) + '">Leer completo</a>')
        mensajes.append(texto)
    return mensajes + _textos_hechas(hechas) + borradores


def _textos_hechas(hechas):
    return ["✅ Vi en Moodle que entregó <b>" + escape(t["titulo"]) + "</b>"
            + (" (" + escape(t["materia"]) + ")" if t["materia"] != "General" else "")
            + ". La marqué como hecha. \U0001F44F" for t in hechas]
