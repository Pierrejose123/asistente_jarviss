"""Borra de Google Calendar los recordatorios «🔔 …» que creó la PRUEBA del 09-11 (comprar pan, llamar a mamá…).

Solo toca eventos que: empiezan con 🔔, se crearon o cambiaron desde el 09-11 en la noche, y NO están en la base
del asistente (los recordatorios reales que usted pidió por Telegram sí están en la base y no se tocan).
Antes de borrar muestra la lista y pide confirmación.
"""
import sys
from contextlib import closing
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from modulos.calendario import google_cal as gc  # noqa: E402
from modulos.comun import db  # noqa: E402

srv = gc.servicio(interactivo=False)
cal = gc.id_calendario(srv)
with closing(db.conectar()) as con:
    reales = {f["google_id"] for f in con.execute("SELECT google_id FROM eventos WHERE google_id IS NOT NULL")}

basura, pagina = [], None
while True:
    res = srv.events().list(calendarId=cal, updatedMin="2026-11-10T02:30:00Z", maxResults=250,
                            showDeleted=False, pageToken=pagina).execute()
    for e in res.get("items", []):
        if (e.get("summary") or "").startswith("\U0001F514") and e["id"] not in reales:
            basura.append(e)
    pagina = res.get("nextPageToken")
    if not pagina:
        break

if not basura:
    print("No encontré recordatorios de la prueba en Google Calendar. No hay nada que borrar.")
    sys.exit(0)
print("Recordatorios creados por la prueba (", len(basura), "):")
for e in basura:
    inicio = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", ""))[:16].replace("T", " ")
    print("  -", e.get("summary"), "|", inicio, "| se repite" if e.get("recurrence") else "")
if input("\n¿Los borro de Google Calendar? Escriba s y Enter para borrar: ").strip().lower() not in ("s", "si", "sí"):
    print("No borré nada.")
    sys.exit(0)
borrados = 0
for e in basura:
    try:
        srv.events().delete(calendarId=cal, eventId=e["id"]).execute()
        borrados += 1
    except Exception as exc:
        print("  No pude borrar", e.get("summary"), ":", exc)
print("Listo: borré", borrados, "de", len(basura), "recordatorios de prueba.")
