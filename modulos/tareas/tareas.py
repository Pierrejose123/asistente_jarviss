"""Fase 1, paso 4: deberes y tareas.

- Se guardan en la base local (tabla 'tareas') y se replican en Google Calendar
  como evento de dia completo en la fecha de entrega, con avisos 2 dias antes y
  el dia anterior a las 19:00 (llegan al celular aunque la PC este apagada).
- Formato:  /tarea <materia opcional> <descripcion> <fecha> [hora]
  Fechas validas: 23/10, 23/10/2026, hoy, manana, pasado manana, lunes..domingo.
"""
import re
import unicodedata
from contextlib import closing
from datetime import date, timedelta

from modulos.comun import db
from modulos.comun.base import DIAS, ahora, leer_json, registro

log = registro("tareas")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tareas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    materia   TEXT NOT NULL,
    titulo    TEXT NOT NULL,
    entrega   TEXT NOT NULL,          -- AAAA-MM-DD
    hora      TEXT,                   -- HH:MM opcional
    estado    TEXT DEFAULT 'pendiente',  -- pendiente | hecha | borrada
    creada    TEXT DEFAULT CURRENT_TIMESTAMP,
    hecha     TEXT
);
"""
AVISOS_GOOGLE = [300, 1740]   # minutos antes de las 00:00 del dia: 19:00 del dia anterior y de 2 dias antes


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def _sin_tildes(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------- lectura del texto ---
def _fecha(token, siguiente=None, hoy=None):
    hoy = hoy or ahora().date()
    t = _sin_tildes(token)
    if t == "hoy":
        return hoy, 1
    if t == "manana":
        return hoy + timedelta(days=1), 1
    if t == "pasado" and siguiente and _sin_tildes(siguiente) == "manana":
        return hoy + timedelta(days=2), 2
    if t in DIAS:
        dias = (DIAS.index(t) - hoy.weekday()) % 7 or 7
        return hoy + timedelta(days=dias), 1
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", t)
    if m:
        d, mes, anio = int(m.group(1)), int(m.group(2)), m.group(3)
        anio = int(anio) + (2000 if anio and len(anio) == 2 else 0) if anio else hoy.year
        f = date(anio, mes, d)
        if not m.group(3) and (hoy - f).days > 60:     # fecha muy pasada: es del proximo anio
            f = date(anio + 1, mes, d)
        return f, 1
    return None, 0


def _materia(palabras):
    """Busca la materia al inicio del texto. Devuelve (nombre_oficial, palabras_usadas)."""
    clases = leer_json("horario_clases.json")["clases"]
    texto = [_sin_tildes(p) for p in palabras]
    mejor = (None, 0)
    for c in clases:
        nombre = _sin_tildes(c["materia"]).split()
        # coincidencia de las primeras palabras de la materia (minimo 1 palabra de 4+ letras)
        n = 0
        while n < len(nombre) and n < len(texto) and texto[n].rstrip(":,") == nombre[n]:
            n += 1
        if n and (n == len(nombre) or len(nombre[0]) >= 4) and n > mejor[1]:
            mejor = (c["materia"], n)
    if not mejor[0] and texto:
        # alias: una palabra distintiva de la materia, ej. "animacion" -> Introduccion a la Animacion
        for c in clases:
            if texto[0].rstrip(":,") in [w for w in _sin_tildes(c["materia"]).split() if len(w) >= 5]:
                return c["materia"], 1
    return mejor


def interpretar(texto, hoy=None):
    """'Grafica Digital III informe de color 23/10 23:59' -> dict o error (str)."""
    palabras = texto.split()
    if not palabras:
        return "vacio"
    hora = None
    if re.fullmatch(r"\d{1,2}:\d{2}", palabras[-1]):
        hora = "%05s" % palabras.pop()
        hora = hora.replace(" ", "0")
    if not palabras:
        return "sin fecha"
    fecha, usadas = (None, 0)
    if len(palabras) >= 2:
        fecha, usadas = _fecha(palabras[-2], palabras[-1], hoy=hoy)   # "pasado manana"
        if usadas != 2:
            fecha, usadas = None, 0
    if not fecha:
        fecha, usadas = _fecha(palabras[-1], hoy=hoy)
    if not fecha:
        return "sin fecha"
    palabras = palabras[:-usadas]
    while palabras and _sin_tildes(palabras[-1]) in ("para", "el", "hasta", "del", "de", "al", "en"):
        palabras = palabras[:-1]
    materia, n = _materia(palabras)
    titulo = " ".join(palabras[n:]).strip(" :,-") if materia else " ".join(palabras).strip(" :,-")
    if not titulo:
        return "sin descripcion"
    return {"materia": materia or "General", "titulo": titulo[:1].upper() + titulo[1:],
            "entrega": fecha.isoformat(), "hora": hora}


# ---------------------------------------------------------------- base de datos ---
def crear(materia, titulo, entrega, hora=None):
    with closing(_con()) as con, con:
        cur = con.execute("INSERT INTO tareas (materia, titulo, entrega, hora) VALUES (?, ?, ?, ?)",
                          (materia, titulo, entrega, hora))
        return cur.lastrowid


def obtener(tid):
    with closing(_con()) as con:
        return con.execute("SELECT * FROM tareas WHERE id = ?", (tid,)).fetchone()


def pendientes(hasta=None):
    with closing(_con()) as con:
        if hasta:
            return con.execute("SELECT * FROM tareas WHERE estado = 'pendiente' AND entrega <= ? "
                               "ORDER BY entrega, hora", (hasta,)).fetchall()
        return con.execute("SELECT * FROM tareas WHERE estado = 'pendiente' ORDER BY entrega, hora").fetchall()


def para_fecha(dia):
    with closing(_con()) as con:
        return con.execute("SELECT * FROM tareas WHERE estado = 'pendiente' AND entrega = ? ORDER BY hora",
                           (dia,)).fetchall()


def cambiar_estado(tid, estado):
    with closing(_con()) as con, con:
        con.execute("UPDATE tareas SET estado = ?, hecha = CASE WHEN ? = 'hecha' THEN CURRENT_TIMESTAMP END "
                    "WHERE id = ?", (estado, estado, tid))


def cambiar_entrega(tid, entrega):
    with closing(_con()) as con, con:
        con.execute("UPDATE tareas SET entrega = ? WHERE id = ?", (entrega, tid))


# ---------------------------------------------------------------- Google Calendar ---
def _cuerpo(t, hecha=False):
    dia = date.fromisoformat(t["entrega"])
    titulo = ("✅ " if hecha else "\U0001F4DD ") + "Entrega: " + t["titulo"]
    if t["materia"] != "General":
        titulo += " (" + t["materia"] + ")"
    desc = "Tarea #" + str(t["id"]) + " del asistente."
    if t["hora"]:
        desc += "\nHora límite: " + t["hora"]
    return {
        "summary": titulo,
        "description": desc,
        "start": {"date": dia.isoformat()},
        "end": {"date": (dia + timedelta(days=1)).isoformat()},
        "reminders": {"useDefault": False,
                      "overrides": [] if hecha else [{"method": "popup", "minutes": m} for m in AVISOS_GOOGLE]},
        "colorId": "2" if hecha else "11",
        "transparency": "transparent",
        "extendedProperties": {"private": {"asistente_clave": "tarea:" + str(t["id"])}},
    }


def subir(tid, hecha=False):
    """Crea o actualiza la tarea en Google Calendar (sin duplicados)."""
    from modulos.calendario import google_cal as gc
    t = obtener(tid)
    srv = gc.servicio(interactivo=False)
    cal_id = gc.id_calendario(srv)
    clave = "tarea:" + str(tid)
    fila = db.obtener_evento(clave)
    cuerpo = _cuerpo(t, hecha)
    if fila and fila["google_id"]:
        srv.events().update(calendarId=cal_id, eventId=fila["google_id"], body=cuerpo).execute()
        google_id = fila["google_id"]
    else:
        google_id = srv.events().insert(calendarId=cal_id, body=cuerpo).execute()["id"]
    db.guardar_evento(clave, "tarea", cuerpo["summary"], google_id, "")
    return google_id


def quitar_de_google(tid):
    from modulos.calendario import google_cal as gc
    fila = db.obtener_evento("tarea:" + str(tid))
    if not fila or not fila["google_id"]:
        return
    srv = gc.servicio(interactivo=False)
    try:
        srv.events().delete(calendarId=gc.id_calendario(srv), eventId=fila["google_id"]).execute()
    except Exception as exc:
        log.info("No se pudo borrar en Google (quiza ya no existe): %s", exc)
    db.marcar_estado("tarea:" + str(tid), "borrado")


# ---------------------------------------------------------------- textos ---
def fecha_bonita(entrega, hoy=None):
    from modulos.comun.base import DIAS_BONITO
    hoy = hoy or ahora().date()
    d = date.fromisoformat(entrega)
    dif = (d - hoy).days
    if dif == 0:
        return "hoy"
    if dif == 1:
        return "mañana"
    if dif < 0:
        return "venció el " + d.strftime("%d/%m")
    return DIAS_BONITO[d.weekday()] + " " + d.strftime("%d/%m")


def linea(t, hoy=None):
    from html import escape
    vencida = date.fromisoformat(t["entrega"]) < (hoy or ahora().date())
    texto = ("❗ " if vencida else "") + "<b>#" + str(t["id"]) + "</b> " + escape(t["titulo"])
    if t["materia"] != "General":
        texto += " <i>(" + escape(t["materia"]) + ")</i>"
    texto += " — " + fecha_bonita(t["entrega"], hoy) + ((" " + t["hora"]) if t["hora"] else "")
    return texto


AYUDA = ("Formato: <code>/tarea [materia] descripción fecha [hora]</code>\n"
         "Ejemplos:\n"
         "• <code>/tarea Gráfica Digital III afiche de color 23/10</code>\n"
         "• <code>/tarea Multimedia I video corto viernes 23:59</code>\n"
         "• <code>/tarea comprar pinceles mañana</code>\n"
         "Fechas: 23/10, hoy, mañana, pasado mañana, lunes…domingo.")


def hoy_iso():
    return ahora().date().isoformat()


def manana_iso():
    return (ahora().date() + timedelta(days=1)).isoformat()



def hechas_el(dia):
    """Tareas marcadas como hechas en una fecha local (AAAA-MM-DD)."""
    with closing(_con()) as con:
        return con.execute("SELECT * FROM tareas WHERE estado = 'hecha' AND date(hecha, 'localtime') = ?",
                           (dia,)).fetchall()
