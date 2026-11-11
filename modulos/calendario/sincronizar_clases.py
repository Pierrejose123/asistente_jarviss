"""Fase 1, paso 3 (parte C1): sube las clases a Google Calendar como eventos semanales.

- Sin duplicados: cada evento lleva una "clave" propia guardada en la base local
  y tambien dentro del evento de Google (propiedad privada).
- Si cambias el horario en config/horario_clases.json y lo vuelves a ejecutar,
  actualiza los eventos en vez de crear otros.

- Si borraste una clase completa desde el celular, NO la vuelve a crear
  (salvo que lo ejecutes con --restaurar).

Ejecutar:  .\\.venv\\Scripts\\python.exe modulos\\calendario\\sincronizar_clases.py
"""
import hashlib
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from googleapiclient.errors import HttpError  # noqa: E402

from modulos.calendario import google_cal as gc  # noqa: E402
from modulos.comun import db  # noqa: E402
from modulos.comun.base import DIAS, leer_json, registro  # noqa: E402

log = registro("calendario")
COLOR_CLASE = "9"   # azul
COLOR_AVISO = "6"   # naranja


def primera_fecha(desde, dia):
    """Primer dia de la semana 'dia' a partir de la fecha 'desde'."""
    objetivo = DIAS.index(dia)
    return desde + timedelta(days=(objetivo - desde.weekday()) % 7)


def cuerpo_evento(clave, titulo, descripcion, inicio, fin, hasta, avisos, color, ubicacion="", dias=None):
    # UNTIL va en UTC: 04:59 UTC del dia siguiente = 23:59 en Ecuador del ultimo dia
    fin_periodo = (hasta + timedelta(days=1)).strftime("%Y%m%d") + "T045959Z"
    return {
        "summary": titulo,
        "description": descripcion,
        "location": ubicacion,
        "start": {"dateTime": inicio.isoformat(), "timeZone": gc.ZONA_GOOGLE},
        "end": {"dateTime": fin.isoformat(), "timeZone": gc.ZONA_GOOGLE},
        "recurrence": ["RRULE:FREQ=WEEKLY;" + ("BYDAY=" + ",".join(dias) + ";" if dias else "") + "UNTIL=" + fin_periodo],
        "reminders": {"useDefault": False,
                      "overrides": [{"method": "popup", "minutes": m} for m in avisos]},
        "colorId": color,
        "extendedProperties": {"private": {"asistente_clave": clave}},
    }


def eventos_deseados():
    horario = leer_json("horario_clases.json")
    desde = date.fromisoformat(horario["fecha_inicio"])
    hasta = date.fromisoformat(horario["fecha_fin"])
    avisos = horario.get("avisos_minutos_antes", [15, 5])
    lista = []
    for c in horario["clases"]:
        dia = primera_fecha(desde, c["dia"])
        ini = datetime.combine(dia, datetime.strptime(c["inicio"], "%H:%M").time())
        fin = datetime.combine(dia, datetime.strptime(c["fin"], "%H:%M").time())
        desc = "Docente: " + c.get("docente", "") + "\nModalidad: Teams"
        if c.get("enlace"):
            desc += "\nUnirse: " + c["enlace"]
        lista.append(("clase:" + c["codigo"], "clase",
                      cuerpo_evento("clase:" + c["codigo"], "Clase: " + c["materia"], desc,
                                    ini, fin, hasta, avisos, COLOR_CLASE, "Microsoft Teams")))
    for i, a in enumerate(horario.get("avisos_extra", [])):
        dia = primera_fecha(desde, a["dia"])
        ini = datetime.combine(dia, datetime.strptime(a["hora"], "%H:%M").time())
        clave = "aviso:" + a["dia"] + ":" + a["hora"]
        lista.append((clave, "aviso",
                      cuerpo_evento(clave, a.get("titulo") or "Aviso: " + a["texto"].split(":")[0], a["texto"],
                                    ini, ini + timedelta(minutes=10), hasta, [0], COLOR_AVISO)))
    return lista


CODIGO_DIA = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def eventos_habitos():
    """Recordatorio de entrenamiento (config/habitos.json), si existe."""
    from modulos.comun.base import CONFIG
    if not (CONFIG / "habitos.json").exists():
        return []
    e = leer_json("habitos.json").get("entrenamiento")
    if not e or not e.get("dias"):
        return []
    desde = date.fromisoformat(leer_json("horario_clases.json")["fecha_inicio"])   # fecha fija: sin cambios diarios
    inicio_dia = min(primera_fecha(desde, d) for d in e["dias"])
    ini = datetime.combine(inicio_dia, datetime.strptime(e["hora"], "%H:%M").time())
    dias = [CODIGO_DIA[DIAS.index(d)] for d in e["dias"]]
    return [("habito:entrenamiento", "habito",
             cuerpo_evento("habito:entrenamiento", e.get("nombre") or "Entrenamiento", e.get("texto", ""),
                           ini, ini + timedelta(minutes=45), desde + timedelta(days=365), [0], "10",
                           dias=dias))]


def huella(cuerpo):
    return hashlib.sha256(json.dumps(cuerpo, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def buscar_en_google(srv, cal_id, clave):
    resp = srv.events().list(calendarId=cal_id, privateExtendedProperty="asistente_clave=" + clave,
                             showDeleted=False, maxResults=5).execute()
    items = [e for e in resp.get("items", []) if e.get("status") != "cancelled"]
    return items[0]["id"] if items else None


def existe_en_google(srv, cal_id, google_id):
    try:
        ev = srv.events().get(calendarId=cal_id, eventId=google_id).execute()
        return ev.get("status") != "cancelled"
    except HttpError as err:
        if err.resp.status in (404, 410):
            return False
        raise


def sincronizar(restaurar=False):
    srv = gc.servicio(interactivo=True)
    cal_id = gc.id_calendario(srv)
    if not cal_id:
        raise SystemExit("No encuentro el calendario 'Asistente'.")
    cuenta = {"creados": 0, "actualizados": 0, "sin cambios": 0, "omitidos (borrados por ti)": 0}
    for clave, tipo, cuerpo in eventos_deseados() + eventos_habitos():
        h = huella(cuerpo)
        fila = db.obtener_evento(clave)
        if fila and fila["estado"] == "borrado" and not restaurar:
            cuenta["omitidos (borrados por ti)"] += 1
            continue
        google_id = fila["google_id"] if fila else None
        if google_id and not existe_en_google(srv, cal_id, google_id):
            google_id = None                      # lo borraron desde Google: se vuelve a crear
        if not google_id:
            google_id = buscar_en_google(srv, cal_id, clave)   # por si se perdio la base local
            if google_id:
                fila = None                       # forzar actualizacion
        if google_id and fila and fila["huella"] == h:
            cuenta["sin cambios"] += 1
        elif google_id:
            srv.events().update(calendarId=cal_id, eventId=google_id, body=cuerpo).execute()
            cuenta["actualizados"] += 1
            log.info("Actualizado %s", clave)
        else:
            google_id = srv.events().insert(calendarId=cal_id, body=cuerpo).execute()["id"]
            cuenta["creados"] += 1
            log.info("Creado %s", clave)
        db.guardar_evento(clave, tipo, cuerpo["summary"], google_id, h)
    return cuenta


if __name__ == "__main__":
    resultado = sincronizar(restaurar="--restaurar" in sys.argv)
    print("Listo: " + ", ".join(str(v) + " " + k for k, v in resultado.items()))
