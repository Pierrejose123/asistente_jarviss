"""Fase 2, paso 2: actividades con hora (reuniones, estudio, gimnasio...), unicas o semanales.

- Se guardan en la base local (tabla 'agenda') y en Google Calendar (clave 'evento:ID').
- Avisos: Google en el celular y, en la PC, Windows + Telegram 'aviso_min' minutos antes.
- Antes de crear, revisa choques con clases y otras actividades.
"""
from contextlib import closing
from datetime import date, datetime, timedelta

from modulos.comun import db
from modulos.comun.base import DIAS, DIAS_BONITO, ZONA, registro

log = registro("agenda")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS agenda (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo    TEXT NOT NULL,
    fecha     TEXT NOT NULL,            -- primera fecha (AAAA-MM-DD)
    inicio    TEXT NOT NULL,            -- HH:MM
    fin       TEXT NOT NULL,            -- HH:MM
    dias      TEXT DEFAULT '',          -- 'lunes,martes' si se repite cada semana; vacio = una sola vez
    hasta     TEXT,                     -- ultima fecha si se repite
    aviso_min INTEGER DEFAULT 15,
    nota      TEXT DEFAULT '',
    estado    TEXT DEFAULT 'activo',    -- activo | borrado
    creado    TEXT DEFAULT CURRENT_TIMESTAMP
);
"""
CODIGO_DIA = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def obtener(eid):
    with closing(_con()) as con:
        return con.execute("SELECT * FROM agenda WHERE id = ?", (eid,)).fetchone()


def activos():
    with closing(_con()) as con:
        return con.execute("SELECT * FROM agenda WHERE estado = 'activo' ORDER BY fecha, inicio").fetchall()


def actualizar(eid, **campos):
    if not campos:
        return
    with closing(_con()) as con, con:
        con.execute("UPDATE agenda SET " + ", ".join(k + " = ?" for k in campos) + " WHERE id = ?",
                    (*campos.values(), eid))


def _ocurre(ev, dia):
    """True si el evento cae en 'dia' (date) segun su fecha / repeticion."""
    if dia.isoformat() < ev["fecha"]:
        return False
    if not ev["dias"]:
        return dia.isoformat() == ev["fecha"]
    if ev["hasta"] and dia.isoformat() > ev["hasta"]:
        return False
    return DIAS[dia.weekday()] in ev["dias"].split(",")


def del_dia(fecha):
    """Actividades efectivas de un dia, con cambios hechos desde el celular aplicados."""
    dia = fecha.date() if isinstance(fecha, datetime) else fecha
    iso = dia.isoformat()
    lista = []
    for ev in activos():
        clave = "evento:" + str(ev["id"])
        if _ocurre(ev, dia):
            exc = db.excepcion(clave, iso)
            if exc and exc["estado"] == "cancelada":
                continue
            item = dict(ev)
            if exc and exc["estado"] == "movida":
                if exc["nuevo_inicio"][:10] != iso:
                    continue
                item.update(inicio=exc["nuevo_inicio"][11:16], fin=(exc["nuevo_fin"] or "")[11:16] or ev["fin"])
            lista.append(item)
    for exc in db.movidas_hacia(iso):
        if exc["clave"].startswith("evento:") and exc["fecha"] != iso:
            ev = obtener(int(exc["clave"].split(":")[1]))
            if ev and ev["estado"] == "activo":
                lista.append(dict(ev, inicio=exc["nuevo_inicio"][11:16], fin=(exc["nuevo_fin"] or "")[11:16]))
    return sorted(lista, key=lambda e: e["inicio"])


def _cruza(a_ini, a_fin, b_ini, b_fin):
    return a_ini < b_fin and b_ini < a_fin


def choques(dia, inicio, fin, dias="", hasta=None, ignorar_id=None):
    """Lista de textos con lo que se cruza (revisa 4 semanas si se repite)."""
    from modulos.clases.agenda import clases_efectivas
    fechas = [dia]
    if dias:
        fin_rango = min(date.fromisoformat(hasta) if hasta else dia + timedelta(days=27), dia + timedelta(days=27))
        fechas = [dia + timedelta(days=i) for i in range((fin_rango - dia).days + 1)
                  if DIAS[(dia + timedelta(days=i)).weekday()] in dias.split(",")]
    encontrados = []
    for d in fechas:
        momento = datetime.combine(d, datetime.min.time(), tzinfo=ZONA)
        for c in clases_efectivas(momento):
            if c["nota"] != "cancelada" and _cruza(inicio, fin, c["inicio"], c["fin"]):
                encontrados.append(DIAS_BONITO[d.weekday()] + " " + d.strftime("%d/%m") + " " + c["inicio"] + "-" + c["fin"] + " clase " + c["materia"])
        for e in del_dia(d):
            if e["id"] != ignorar_id and _cruza(inicio, fin, e["inicio"], e["fin"]):
                encontrados.append(DIAS_BONITO[d.weekday()] + " " + d.strftime("%d/%m") + " " + e["inicio"] + "-" + e["fin"] + " " + e["titulo"])
    vistos = []
    for x in encontrados:
        if x not in vistos:
            vistos.append(x)
    return vistos[:6]


def crear(titulo, dia, inicio, fin, dias="", hasta=None, aviso_min=15, nota=""):
    if dias and not hasta:
        hasta = (dia + timedelta(days=182)).isoformat()      # seis meses por defecto
    with closing(_con()) as con, con:
        cur = con.execute("INSERT INTO agenda (titulo, fecha, inicio, fin, dias, hasta, aviso_min, nota) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (titulo, dia.isoformat(), inicio, fin, dias, hasta, aviso_min, nota))
        return cur.lastrowid


# ------------------------------------------------------------------ Google Calendar ---
def _cuerpo(ev):
    from modulos.calendario import google_cal as gc
    dia = date.fromisoformat(ev["fecha"])
    if ev["dias"]:      # primera ocurrencia real
        while DIAS[dia.weekday()] not in ev["dias"].split(","):
            dia += timedelta(days=1)
    ini = datetime.combine(dia, datetime.strptime(ev["inicio"], "%H:%M").time())
    fin = datetime.combine(dia, datetime.strptime(ev["fin"], "%H:%M").time())
    if fin <= ini:
        fin += timedelta(days=1)
    cuerpo = {
        "summary": ev["titulo"],
        "description": ((ev["nota"] + "\n") if ev["nota"] else "") + "Actividad #" + str(ev["id"]) + " del asistente.",
        "start": {"dateTime": ini.isoformat(), "timeZone": gc.ZONA_GOOGLE},
        "end": {"dateTime": fin.isoformat(), "timeZone": gc.ZONA_GOOGLE},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": int(ev["aviso_min"])}]},
        "colorId": "7",
        "extendedProperties": {"private": {"asistente_clave": "evento:" + str(ev["id"])}},
    }
    if ev["dias"]:
        hasta = date.fromisoformat(ev["hasta"]) + timedelta(days=1)
        cuerpo["recurrence"] = ["RRULE:FREQ=WEEKLY;BYDAY=" + ",".join(CODIGO_DIA[DIAS.index(d)] for d in ev["dias"].split(","))
                                + ";UNTIL=" + hasta.strftime("%Y%m%d") + "T045959Z"]
    return cuerpo


def subir(eid):
    from modulos.calendario import google_cal as gc
    ev = obtener(eid)
    srv = gc.servicio(interactivo=False)
    cal_id = gc.id_calendario(srv)
    clave = "evento:" + str(eid)
    fila = db.obtener_evento(clave)
    cuerpo = _cuerpo(ev)
    if fila and fila["google_id"] and fila["estado"] != "borrado":
        srv.events().update(calendarId=cal_id, eventId=fila["google_id"], body=cuerpo).execute()
        google_id = fila["google_id"]
    else:
        google_id = srv.events().insert(calendarId=cal_id, body=cuerpo).execute()["id"]
    db.guardar_evento(clave, "evento", ev["titulo"], google_id, "")


def borrar(eid):
    actualizar(eid, estado="borrado")
    fila = db.obtener_evento("evento:" + str(eid))
    if fila and fila["google_id"]:
        try:
            from modulos.calendario import google_cal as gc
            srv = gc.servicio(interactivo=False)
            srv.events().delete(calendarId=gc.id_calendario(srv), eventId=fila["google_id"]).execute()
        except Exception as exc:
            log.info("No se pudo borrar en Google: %s", exc)
    db.marcar_estado("evento:" + str(eid), "borrado")


# ------------------------------------------------------------------ textos ---
def descripcion(ev):
    texto = "#" + str(ev["id"]) + " " + ev["titulo"] + " " + ev["inicio"] + "-" + ev["fin"]
    if ev["dias"]:
        dias = ev["dias"].split(",")
        nombres = [DIAS_BONITO[DIAS.index(d)] for d in dias]
        texto += ", cada " + (", ".join(nombres[:-1]) + " y " + nombres[-1] if len(nombres) > 1 else nombres[0])
        texto += " hasta el " + date.fromisoformat(ev["hasta"]).strftime("%d/%m/%Y")
    else:
        d = date.fromisoformat(ev["fecha"])
        texto += ", " + DIAS_BONITO[d.weekday()] + " " + d.strftime("%d/%m")
    return texto
