"""Fase 1, paso 3 (parte C3): detecta lo que el usuario cambia en Google Calendar desde el celular.

Usa la sincronizacion incremental de Google (syncToken): cada vez solo pide lo que cambio.
Casos que entiende, para los eventos creados por el asistente:
  - Borraste UNA clase (solo esa fecha)      -> no te avisa ni abre Teams ese dia.
  - Moviste UNA clase a otra hora/dia        -> los avisos siguen la nueva hora.
  - Borraste la serie completa               -> el asistente no la vuelve a crear.
  - Cambiaste la hora de la serie completa   -> actualiza config/horario_clases.json.
Devuelve una lista de mensajes para avisarte por Telegram.
"""
import json
import sys
from html import escape
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from googleapiclient.errors import HttpError  # noqa: E402

from modulos.calendario import google_cal as gc  # noqa: E402
from modulos.comun import db  # noqa: E402
from modulos.comun.base import CONFIG, DIAS, DIAS_BONITO, ZONA, registro  # noqa: E402

log = registro("calendario")


def _estado():
    return json.loads(gc.ESTADO.read_text(encoding="utf-8")) if gc.ESTADO.exists() else {}


def _guardar_token(token):
    estado = _estado()
    estado["sync_token"] = token
    gc.ESTADO.write_text(json.dumps(estado), encoding="utf-8")


def _local(fecha_hora):
    """'2026-10-16T19:00:00-05:00' -> datetime en hora de Ecuador."""
    return datetime.fromisoformat(fecha_hora.replace("Z", "+00:00")).astimezone(ZONA)


def _nombre(fila):
    return fila["titulo"].replace("Clase: ", "").replace("Aviso: ", "")


def _bonito(dt):
    return DIAS_BONITO[dt.weekday()] + " " + dt.strftime("%d/%m %H:%M")


def _actualizar_horario(codigo, inicio, fin):
    """La serie entera cambio de hora o de dia: se ajusta el horario local."""
    archivo = CONFIG / "horario_clases.json"
    horario = json.loads(archivo.read_text(encoding="utf-8-sig"))
    for c in horario["clases"]:
        if c["codigo"] == codigo:
            nuevo = {"dia": DIAS[inicio.weekday()], "inicio": inicio.strftime("%H:%M"), "fin": fin.strftime("%H:%M")}
            if all(c[k] == v for k, v in nuevo.items()):
                return False
            c.update(nuevo)
            archivo.write_text(json.dumps(horario, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return True
    return False


def _procesar(ev):
    """Interpreta un cambio. Devuelve un mensaje para el usuario o None."""
    padre = ev.get("recurringEventId")
    fila = db.evento_por_google_id(padre or ev["id"])
    if not fila:
        return None                                   # no es un evento del asistente
    clave = fila["clave"]

    if padre:                                         # cambio en UNA ocurrencia de la serie
        original = ev.get("originalStartTime", {}).get("dateTime")
        if not original:
            return None
        orig = _local(original)
        fecha = orig.date().isoformat()
        if ev.get("status") == "cancelled":
            db.guardar_excepcion(clave, fecha, "cancelada")
            extra = " ni abrir\u00e9 Teams" if clave.startswith("clase:") else ""
            return "\U0001F5D1 Quitaste <b>" + _nombre(fila) + "</b> del " + _bonito(orig) + ". Ese d\u00eda no te avisar\u00e9" + extra + "."
        inicio, fin = _local(ev["start"]["dateTime"]), _local(ev["end"]["dateTime"])
        if inicio == orig:
            habia = db.excepcion(clave, fecha)
            db.borrar_excepcion(clave, fecha)
            if habia:
                return "\u21A9\uFE0F <b>" + _nombre(fila) + "</b> del " + _bonito(orig) + " volvi\u00f3 a su horario normal. Ajust\u00e9 los avisos."
            return None
        db.guardar_excepcion(clave, fecha, "movida", inicio.isoformat(), fin.isoformat())
        return "\U0001F4C5 Moviste <b>" + _nombre(fila) + "</b> del " + _bonito(orig) + " al " + _bonito(inicio) + ". Ajusté los avisos."

    if clave.startswith("tarea:"):                    # tareas (eventos de dia completo)
        from modulos.tareas import tareas as T
        tid = int(clave.split(":", 1)[1])
        t = T.obtener(tid)
        if not t:
            return None
        if ev.get("status") == "cancelled":
            db.marcar_estado(clave, "borrado")
            if t["estado"] == "pendiente":
                T.cambiar_estado(tid, "borrada")
                return "\U0001F5D1 Borraste la tarea <b>#" + str(tid) + " " + escape(t["titulo"]) + "</b> desde el calendario. La quit\u00e9 de tu lista."
            return None
        nueva = ev.get("start", {}).get("date")
        if nueva and nueva != t["entrega"] and t["estado"] == "pendiente":
            T.cambiar_entrega(tid, nueva)
            return ("\U0001F4C5 Moviste la entrega de <b>#" + str(tid) + " " + escape(t["titulo"]) + "</b> al "
                    + T.fecha_bonita(nueva) + ". Ajust\u00e9 los avisos.")
        return None

    if clave.startswith("evento:"):                   # actividades con hora creadas por el asistente
        from modulos.agenda import eventos
        eid = int(clave.split(":", 1)[1])
        e = eventos.obtener(eid)
        if not e or e["estado"] != "activo":
            return None
        if ev.get("status") == "cancelled":
            eventos.actualizar(eid, estado="borrado")
            db.marcar_estado(clave, "borrado")
            return "\U0001F5D1 Borraste la actividad <b>" + escape(e["titulo"]) + "</b> desde el calendario. Ya no te avisar\u00e9."
        if "dateTime" in ev.get("start", {}):
            inicio, fin = _local(ev["start"]["dateTime"]), _local(ev["end"]["dateTime"])
            cambios = {}
            if inicio.strftime("%H:%M") != e["inicio"] or fin.strftime("%H:%M") != e["fin"]:
                cambios.update(inicio=inicio.strftime("%H:%M"), fin=fin.strftime("%H:%M"))
            if not e["dias"] and inicio.date().isoformat() != e["fecha"]:
                cambios["fecha"] = inicio.date().isoformat()
            if ev.get("summary") and ev["summary"] != e["titulo"]:
                cambios["titulo"] = ev["summary"]
            if cambios:
                eventos.actualizar(eid, **cambios)
                return ("\U0001F4C5 Cambiaste <b>" + escape(cambios.get("titulo", e["titulo"])) + "</b>: ahora "
                        + _bonito(inicio) + "\u2013" + fin.strftime("%H:%M") + ". Ajust\u00e9 los avisos.")
        return None

    if clave.startswith(("mercado:", "moodle:")):      # resultados/dividendos y eventos de Moodle
        if ev.get("status") == "cancelled" and fila["estado"] == "activo":
            db.marcar_estado(clave, "borrado")
            return "\U0001F5D1 Quitaste <b>" + escape(fila["titulo"]) + "</b> del calendario. No lo vuelvo a poner."
        return None                                   # lo quitó el asistente o lo moviste: nada que hacer

    if ev.get("status") == "cancelled":               # borraron la serie completa
        if fila["estado"] == "borrado":
            return None
        db.marcar_estado(clave, "borrado")
        return ("\U0001F5D1 Borraste <b>" + _nombre(fila) + "</b> completa del calendario. "
                "No la volveré a crear. Si fue un error, avísale a Claude para restaurarla.")

    if clave.startswith("clase:") and "dateTime" in ev.get("start", {}):
        inicio, fin = _local(ev["start"]["dateTime"]), _local(ev["end"]["dateTime"])
        if _actualizar_horario(clave.split(":", 1)[1], inicio, fin):
            return ("\U0001F4C5 Cambiaste el horario de <b>" + _nombre(fila) + "</b>: ahora es los "
                    + DIAS_BONITO[inicio.weekday()] + " de " + inicio.strftime("%H:%M") + " a " + fin.strftime("%H:%M") + ".")
    return None


def sincronizar_cambios(srv=None):
    """Devuelve la lista de mensajes con los cambios encontrados."""
    srv = srv or gc.servicio(interactivo=False)
    cal_id = gc.id_calendario(srv)
    token = _estado().get("sync_token")
    primera_vez = not token
    mensajes = []
    pagina = None
    while True:
        try:
            if token:
                resp = srv.events().list(calendarId=cal_id, syncToken=token, pageToken=pagina,
                                         showDeleted=True).execute()
            else:
                resp = srv.events().list(calendarId=cal_id, pageToken=pagina, showDeleted=True).execute()
        except HttpError as err:
            if err.resp.status == 410:                # token vencido: empezar de cero sin avisar
                log.info("syncToken vencido, sincronizacion completa")
                token, pagina, primera_vez = None, None, True
                continue
            raise
        if not primera_vez:
            for ev in resp.get("items", []):
                msg = _procesar(ev)
                if msg:
                    mensajes.append(msg)
                    log.info("Cambio desde Google: %s", msg)
        pagina = resp.get("nextPageToken")
        if not pagina:
            _guardar_token(resp.get("nextSyncToken"))
            break
    return mensajes


if __name__ == "__main__":
    msgs = sincronizar_cambios(gc.servicio(interactivo=True))
    print("\n".join(m.replace("<b>", "").replace("</b>", "") for m in msgs) or "Sin cambios desde el celular.")
