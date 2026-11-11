"""Eventos sueltos del asistente en Google Calendar (resultados y dividendos, eventos de Moodle...).

- Cada evento tiene una clave propia ("mercado:AMZN|resultados|2026-11-20", "moodle:<uid>") guardada en la
  tabla 'eventos': no se duplica y se puede actualizar o borrar.
- Si el usuario lo borra desde el celular, sync_cambios lo marca 'borrado' y el asistente NO lo vuelve a crear.
- Solo títulos genéricos (ticker, nombre del deber): nunca montos ni datos de cuentas.
"""
from datetime import timedelta

from modulos.comun import db
from modulos.comun.base import registro

log = registro("calendario")


def _guardar(clave, tipo, cuerpo):
    from modulos.calendario import google_cal as gc
    srv = gc.servicio(interactivo=False)
    cal_id = gc.id_calendario(srv)
    cuerpo.setdefault("extendedProperties", {"private": {"asistente_clave": clave}})
    fila = db.obtener_evento(clave)
    if fila and fila["google_id"] and fila["estado"] == "activo":
        srv.events().update(calendarId=cal_id, eventId=fila["google_id"], body=cuerpo).execute()
        gid = fila["google_id"]
    else:
        gid = srv.events().insert(calendarId=cal_id, body=cuerpo).execute()["id"]
    db.guardar_evento(clave, tipo, cuerpo["summary"], gid, "")
    return gid


def borrado_por_usuario(clave):
    fila = db.obtener_evento(clave)
    return bool(fila and fila["estado"] == "borrado")


def dia_completo(clave, tipo, titulo, fecha, descripcion="", avisos_min=(300,), color="5"):
    """Evento de todo el día. avisos_min: minutos antes de las 00:00 (300 = 19:00 del día anterior)."""
    return _guardar(clave, tipo, {
        "summary": titulo, "description": descripcion + "\nDel asistente.",
        "start": {"date": fecha.isoformat()}, "end": {"date": (fecha + timedelta(days=1)).isoformat()},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": m} for m in avisos_min]},
        "colorId": color, "transparency": "transparent"})


def con_hora(clave, tipo, titulo, inicio, minutos=60, descripcion="", avisos_min=(60,), color="9"):
    """Evento con hora. inicio: datetime con zona."""
    from modulos.calendario import google_cal as gc
    fin = inicio + timedelta(minutes=minutos)
    return _guardar(clave, tipo, {
        "summary": titulo, "description": descripcion + "\nDel asistente.",
        "start": {"dateTime": inicio.replace(tzinfo=None).isoformat(timespec="seconds"), "timeZone": gc.ZONA_GOOGLE},
        "end": {"dateTime": fin.replace(tzinfo=None).isoformat(timespec="seconds"), "timeZone": gc.ZONA_GOOGLE},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": m} for m in avisos_min]},
        "colorId": color})


def quitar(clave, estado="reemplazado"):
    """Lo quita el asistente (fecha cambiada, ya no aplica). 'reemplazado' ≠ 'borrado' (eso lo decide el usuario)."""
    fila = db.obtener_evento(clave)
    if not fila or not fila["google_id"] or fila["estado"] != "activo":
        return
    try:
        from modulos.calendario import google_cal as gc
        srv = gc.servicio(interactivo=False)
        srv.events().delete(calendarId=gc.id_calendario(srv), eventId=fila["google_id"]).execute()
    except Exception as exc:
        log.info("No se pudo quitar %s de Google: %s", clave, exc)
    db.marcar_estado(clave, estado)


def activos(prefijo):
    from contextlib import closing
    with closing(db.conectar()) as con:
        return con.execute("SELECT * FROM eventos WHERE clave LIKE ? AND estado='activo'", (prefijo + "%",)).fetchall()
