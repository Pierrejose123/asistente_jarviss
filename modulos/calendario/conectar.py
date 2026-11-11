"""Fase 1, paso 3 (parte B): autoriza Google Calendar y crea un evento de prueba.

Ejecutar:  .\\.venv\\Scripts\\python.exe modulos\\calendario\\conectar.py
"""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modulos.calendario import google_cal as gc  # noqa: E402
from modulos.comun.base import ahora  # noqa: E402

print("1) Conectando con Google (si hace falta, se abrira el navegador)...")
srv = gc.servicio(interactivo=True)
print("   Conectado.")

print("2) Buscando el calendario 'Asistente'...")
cal_id = gc.id_calendario(srv)
if not cal_id:
    print("   No lo encontre. Calendarios que veo en tu cuenta:")
    for nombre in gc.calendarios(srv):
        print("    - " + nombre)
    sys.exit("   Crea el calendario 'Asistente' en calendar.google.com y vuelve a ejecutar este script.")
print("   Encontrado.")

print("3) Creando un evento de prueba dentro de 10 minutos...")
inicio = (ahora() + timedelta(minutes=10)).replace(second=0, microsecond=0)
srv.events().insert(calendarId=cal_id, body={
    "summary": "Prueba del asistente",
    "description": "Evento de prueba creado por tu asistente. Puedes borrarlo.",
    "start": {"dateTime": inicio.isoformat(), "timeZone": gc.ZONA_GOOGLE},
    "end": {"dateTime": (inicio + timedelta(minutes=15)).isoformat(), "timeZone": gc.ZONA_GOOGLE},
    "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 5}]},
}).execute()
print("   Creado para las " + inicio.strftime("%H:%M") + ". Revisalo en la app de Google Calendar del celular.")
print("   Te debe llegar una notificacion 5 minutos antes (a las "
      + (inicio - timedelta(minutes=5)).strftime("%H:%M") + ").")

print("Listo: Google Calendar conectado. Cuando te llegue el aviso, puedes borrar el evento desde el celular.")