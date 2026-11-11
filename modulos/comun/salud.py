"""Chequeo de salud del asistente: revisa que cada pieza funcione y lo cuenta en un mensaje corto.

Cada mañana (06:50, o al encender la PC hasta las 12:00) y con /salud.
Solo lectura: no cambia nada. Si algo falla, dice qué hacer.

Desde la PC:  .\\.venv\\Scripts\\python.exe modulos\\comun\\salud.py
"""
import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modulos.comun.base import PESADO, RAIZ, ahora, registro  # noqa: E402

log = registro("salud")
OK, AVISO, MAL = "✅", "⚠️", "❌"


def _prueba(nombre, funcion):
    t0 = time.monotonic()
    try:
        estado, detalle = funcion()
    except Exception as exc:
        estado, detalle = MAL, str(exc)[:120]
    return {"nombre": nombre, "estado": estado, "detalle": detalle, "segundos": time.monotonic() - t0}


# ------------------------------------------------------------------ cada pieza ---
def ollama():
    from modulos.ia import cerebro
    if cerebro.modelo_listo():
        return OK, "modelo " + cerebro.config()["modelo"]
    return MAL, "no responde o falta el modelo: abra la app de Ollama"


def calendario():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    token = RAIZ / "credenciales" / "token.json"
    if not token.exists():
        return MAL, "sin permiso: ejecute modulos\\calendario\\conectar.py"
    cred = Credentials.from_authorized_user_file(str(token))
    if cred.expired and cred.refresh_token:
        try:
            cred.refresh(Request())
            token.write_text(cred.to_json(), encoding="utf-8")
        except Exception:
            return MAL, "el permiso venció: ejecute modulos\\calendario\\conectar.py"
    build("calendar", "v3", credentials=cred, cache_discovery=False).calendarList().list(maxResults=1).execute()
    return OK, "conectado"


def gmail():
    from modulos.finanzas import correos
    try:
        srv = correos.servicio()
    except correos.SinPermiso:
        return MAL, "el permiso venció: ejecute modulos\\finanzas\\conectar_gmail.py"
    srv.users().getProfile(userId="me").execute()
    return OK, "solo lectura"


def moodle():
    import requests
    from dotenv import dotenv_values
    env = dotenv_values(RAIZ / ".env")
    token, ical = env.get("MOODLE_TOKEN"), env.get("MOODLE_ICAL_URL")
    partes = []
    if ical:
        r = requests.get(ical, timeout=20)
        partes.append("calendario " + ("OK" if r.ok and "BEGIN:VCALENDAR" in r.text[:300] else "falla"))
    if token:
        base = re.match(r"https?://[^/]+", ical or env.get("MOODLE_SITIO") or "https://moodle.invalid").group()
        r = requests.get(base + "/webservice/rest/server.php", timeout=20,
                         params={"wstoken": token, "wsfunction": "core_webservice_get_site_info",
                                 "moodlewsrestformat": "json"})
        datos = r.json() if r.ok else {}
        partes.append("avisos " + ("OK" if datos.get("userid") else "falla (" + str(datos.get("errorcode", r.status_code)) + ")"))
    if not partes:
        return AVISO, "no configurado"
    return (OK if all("OK" in p for p in partes) else AVISO), ", ".join(partes)


def voz():
    import psutil
    for p in psutil.process_iter(["cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if ("voz\\voz.py" in cmd or "voz/voz.py" in cmd) and "python" in cmd.lower():
            return OK, "escuchando"
    try:
        from modulos.comun.base import leer_json
        if leer_json("voz.json").get("arrancar_con_windows") is False:
            return OK, "apagada a propósito"
    except Exception:
        pass
    return AVISO, "no está corriendo: control.py reiniciar"


def precios():
    from modulos.alertas import alertas
    c = alertas.cotizacion("SPY")
    return (OK, "Yahoo responde") if c else (AVISO, "Yahoo no responde (alertas en pausa hasta que vuelva)")


def noticias_():
    from modulos.noticias import noticias
    with noticias._con() as con:
        fila = con.execute("SELECT MAX(guardada) AS u, COUNT(*) AS n FROM noticias").fetchone()
    if not fila["u"]:
        return AVISO, "aún no hay noticias guardadas"
    horas = (ahora() - datetime.fromisoformat(fila["u"])).total_seconds() / 3600
    estado = OK if horas < 6 else AVISO
    return estado, "última hace " + ("%.0f h" % horas if horas >= 1 else "menos de 1 h") + " · " + str(fila["n"]) + " guardadas"


def busqueda_web():
    from modulos.noticias import noticias
    try:
        import ddgs  # noqa: F401
    except ImportError:
        try:
            import duckduckgo_search  # noqa: F401
        except ImportError:
            return AVISO, "no instalada: pip install ddgs"
    return (OK, "DuckDuckGo responde") if noticias.buscar_web("bolsa hoy", 1) else (AVISO, "DuckDuckGo no respondió ahora")


def respaldo():
    carpeta = PESADO / "respaldos"
    if not carpeta.exists():
        return MAL, "no hay carpeta de respaldos (¿disco " + carpeta.anchor + " conectado?)"
    lista = sorted(carpeta.glob("respaldo_*.zip"))
    if not lista:
        return MAL, "no hay respaldos"
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{4})", lista[-1].name)
    fecha = datetime.strptime(m.group(1) + m.group(2), "%Y-%m-%d%H%M") if m else datetime.fromtimestamp(lista[-1].stat().st_mtime)
    dias = (datetime.now() - fecha).days
    return (OK if dias <= 1 else AVISO if dias <= 3 else MAL), "último " + fecha.strftime("%d/%m %H:%M") + " · " + str(len(lista)) + " guardados"


def discos():
    partes, peor = [], OK
    letras = [("C:\\", 15)] + ([(PESADO.anchor, 20)] if PESADO.anchor and PESADO.anchor.upper() != "C:\\" else [])
    for letra, minimo in letras:
        if not Path(letra).exists():
            if letra != "C:\\":
                partes.append(letra[:2] + " no conectado")
                peor = MAL
            continue
        libre = shutil.disk_usage(letra).free / 1e9
        partes.append(letra[0] + ": " + ("%.0f" % libre) + " GB libres")
        if libre < minimo:
            peor = AVISO if peor == OK else peor
    return peor, " · ".join(partes)


# Fallos de red pasajeros (Telegram, Google, Yahoo): se reintentan solos, no son errores del asistente
PASAJEROS = re.compile(r"Bad Gateway|Gateway Time-?out|Service Unavailable|Timed? ?out|NetworkError|ReadError|ConnectError|"
                       r"Connection (?:reset|aborted|refused)|RemoteDisconnected|Temporary failure|Max retries|50[234]\b", re.I)


def errores_recientes():
    """Cuenta errores de las últimas 24 h en los registros (logs/*.log)."""
    limite = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    cuenta, ejemplo, pasajeros = {}, {}, 0
    for archivo in (RAIZ / "logs").glob("*.log"):
        try:
            with open(archivo, encoding="utf-8", errors="ignore") as f:
                f.seek(max(0, os.path.getsize(archivo) - 400_000))      # solo el final
                for linea in f:
                    if linea[:19] >= limite and " ERROR " in linea:
                        if PASAJEROS.search(linea):
                            pasajeros += 1
                            continue
                        cuenta[archivo.stem] = cuenta.get(archivo.stem, 0) + 1
                        ejemplo[archivo.stem] = re.sub(r"^\S+\s+", "", linea[20:].strip())[:90]
        except Exception:
            continue
    nota = (" (+" + str(pasajeros) + " cortes de red que se arreglaron solos)") if pasajeros else ""
    if not cuenta:
        return OK, "ninguno en 24 h" + nota
    total = sum(cuenta.values())
    peor = max(cuenta, key=cuenta.get)
    return (AVISO if total < 20 else MAL), (str(total) + " en 24 h (más en " + peor + ".log: " + ejemplo[peor] + ")" + nota)


PRUEBAS = [("Cerebro (Ollama)", ollama), ("Google Calendar", calendario), ("Gmail", gmail), ("Moodle", moodle),
           ("Voz", voz), ("Precios", precios), ("Noticias", noticias_), ("Búsqueda web", busqueda_web),
           ("Respaldo", respaldo), ("Discos", discos), ("Errores", errores_recientes)]


def revisar():
    return [_prueba(n, f) for n, f in PRUEBAS]


def texto(resultados, completo=False):
    malos = [r for r in resultados if r["estado"] != OK]
    if not malos and not completo:
        return "🩺 Chequeo de la mañana: todo en orden (" + str(len(resultados)) + "/" + str(len(resultados)) + ") ✅"
    cabeza = "🩺 <b>Chequeo del asistente</b>" + ("" if malos else " — todo en orden ✅")
    lineas = [cabeza]
    for r in (resultados if completo else malos):
        lineas.append(r["estado"] + " <b>" + r["nombre"] + "</b>: " + _html(r["detalle"]))
    if not completo:
        lineas.append("\n" + str(len(resultados) - len(malos)) + " piezas más funcionan bien. Detalle: /salud")
    return "\n".join(lineas)


def _html(t):
    from html import escape
    return escape(t or "")


if __name__ == "__main__":
    for r in revisar():
        print(r["estado"], r["nombre"].ljust(18), r["detalle"], "(%.1f s)" % r["segundos"])
