"""Conexion con Google Calendar (Fase 1, paso 3).

Permisos pedidos (los minimos para lo que necesitamos):
  - calendar.events: crear, cambiar y borrar eventos (el asistente solo escribe en "Asistente")
  - calendar.calendarlist.readonly: ver la lista de calendarios para encontrar "Asistente"
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from google.auth.exceptions import RefreshError  # noqa: E402
from google.auth.transport.requests import Request  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402
from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402

from modulos.comun.base import RAIZ  # noqa: E402

PERMISOS = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]
CREDENCIALES = RAIZ / "credenciales" / "client_secret.json"
TOKEN = RAIZ / "credenciales" / "token.json"
ESTADO = RAIZ / "datos" / "calendario.json"
NOMBRE_CALENDARIO = "Asistente"
ZONA_GOOGLE = "America/Guayaquil"


class NecesitaAutorizar(Exception):
    """El permiso de Google caduco y hay que volver a autorizar en el navegador."""


def _guardar_token(creds):
    TOKEN.parent.mkdir(exist_ok=True)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")


def autorizar():
    """Abre el navegador para que el usuario acepte el permiso. Solo cuando hace falta."""
    if not CREDENCIALES.exists():
        raise FileNotFoundError("Falta credenciales/client_secret.json")
    flujo = InstalledAppFlow.from_client_secrets_file(str(CREDENCIALES), PERMISOS)
    creds = flujo.run_local_server(
        port=0, prompt="consent",
        authorization_prompt_message="Abriendo el navegador para autorizar a Google...",
        success_message="Listo: el asistente ya puede usar tu Google Calendar. Puedes cerrar esta pestaña.")
    _guardar_token(creds)
    return creds


def credenciales(interactivo=False):
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), PERMISOS)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _guardar_token(creds)
            return creds
        except RefreshError:
            pass
    if interactivo:
        return autorizar()
    raise NecesitaAutorizar("Hay que volver a autorizar Google Calendar")


def servicio(interactivo=False):
    return build("calendar", "v3", credentials=credenciales(interactivo), cache_discovery=False)


def id_calendario(srv):
    """Devuelve el ID del calendario 'Asistente' (lo recuerda en datos/calendario.json)."""
    if ESTADO.exists():
        guardado = json.loads(ESTADO.read_text(encoding="utf-8")).get("id")
        if guardado:
            return guardado
    pagina = None
    while True:
        resp = srv.calendarList().list(pageToken=pagina).execute()
        for cal in resp.get("items", []):
            if cal.get("summary", "").strip().lower() == NOMBRE_CALENDARIO.lower():
                ESTADO.parent.mkdir(exist_ok=True)
                ESTADO.write_text(json.dumps({"id": cal["id"], "nombre": cal["summary"]}), encoding="utf-8")
                return cal["id"]
        pagina = resp.get("nextPageToken")
        if not pagina:
            return None


def calendarios(srv):
    return [c.get("summary", "?") for c in srv.calendarList().list().execute().get("items", [])]


# --- PROTECCION_PRUEBAS (10-11) ---
# Si la base no es la real (una prueba), Google queda bloqueado. No tocar.
_servicio_real_sin_proteccion = servicio


def servicio(*args, **kwargs):
    from modulos.comun import modo_prueba
    modo_prueba.bloquear("Google Calendar")
    return _servicio_real_sin_proteccion(*args, **kwargs)
