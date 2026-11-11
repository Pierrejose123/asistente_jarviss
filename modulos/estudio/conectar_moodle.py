"""Conecta el asistente con Moodle UNA vez, sin guardar la contrasena.

Pide usuario y clave EN ESTA VENTANA (la clave no se ve al escribir), los envia SOLO a Moodle
(<su Moodle>/login/token.php, el mismo metodo que usa la app oficial de Moodle)
y recibe una "clave de servicio". Solo esa clave se guarda en .env (MOODLE_TOKEN).
La contrasena no se escribe en ningun archivo ni registro y se borra de la memoria al terminar.

Para anularla: Moodle -> Preferencias -> Claves de seguridad -> Restablecer, o cambie su contrasena.

Ejecutar:  .\\.venv\\Scripts\\python.exe modulos\\estudio\\conectar_moodle.py
"""
import getpass
import re
import sys
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parents[2]
SITIO = ""
ENV = RAIZ / ".env"


def _pedir_sitio():
    """El sitio de Moodle sale de MOODLE_SITIO en el .env; si no está, se pregunta y se guarda."""
    from dotenv import dotenv_values, set_key
    sitio = (dotenv_values(ENV).get("MOODLE_SITIO") or "").strip().rstrip("/")
    if not sitio:
        sitio = input("Dirección de su Moodle (ej. https://campus.su-instituto.edu): ").strip().rstrip("/")
        if not sitio.startswith("https://"):
            raise SystemExit("La dirección debe empezar con https://")
        set_key(str(ENV), "MOODLE_SITIO", sitio)
    return sitio


def guardar_en_env(clave, valor):
    lineas = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    lineas = [l for l in lineas if not l.startswith(clave + "=")]
    lineas.append(clave + "=" + valor)
    ENV.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main():
    global SITIO
    SITIO = _pedir_sitio()
    print("Conectar el asistente con Moodle (" + SITIO + ")")
    print("Su clave NO se guarda: solo se usa ahora para pedirle a Moodle una clave de servicio.\n")
    usuario = input("Usuario de Moodle: ").strip()
    clave = getpass.getpass("Clave de Moodle (no se ve al escribir): ")
    try:
        r = requests.post(SITIO + "/login/token.php", timeout=30,
                          data={"username": usuario, "password": clave, "service": "moodle_mobile_app"})
    finally:
        clave = None                                          # se olvida la clave
    try:
        datos = r.json()
    except ValueError:
        sys.exit("Moodle respondio algo inesperado (codigo " + str(r.status_code) + ").")
    if "token" not in datos:
        error = datos.get("errorcode") or datos.get("error") or "desconocido"
        print("\nMoodle no dio la clave de servicio: " + str(error))
        if error in ("invalidlogin",):
            print("Usuario o clave incorrectos. Si en Moodle entra con 'Office 365', este metodo no sirve: avise a Claude.")
        elif error in ("enablewsdescription", "servicenotavailable"):
            print("El instituto no tiene activado el acceso para apps. Avise a Claude para usar otro camino.")
        sys.exit(1)
    token = datos["token"]
    info = requests.post(SITIO + "/webservice/rest/server.php", timeout=30,
                         data={"wstoken": token, "wsfunction": "core_webservice_get_site_info",
                               "moodlewsrestformat": "json"}).json()
    if "userid" not in info:
        sys.exit("La clave de servicio no funciono: " + str(info.get("message", info))[:120])
    guardar_en_env("MOODLE_TOKEN", token)
    nombre = (info.get("firstname") or "").split(" ")[0]
    print("\nConectado" + (" como " + nombre if nombre else "") + ". Clave de servicio guardada en .env.")
    funciones = {f["name"] for f in info.get("functions", [])}
    necesarias = ["message_popup_get_popup_notifications", "mod_forum_get_forums_by_courses",
                  "mod_forum_get_forum_discussions", "core_enrol_get_users_courses",
                  "core_calendar_get_calendar_event_by_id", "mod_assign_get_submission_status"]
    for f in necesarias:
        print("  " + ("OK " if not funciones or f in funciones else "NO ") + re.sub(r"_", " ", f))
    print("\nReinicie el asistente:  .\\.venv\\Scripts\\python.exe modulos\\comun\\control.py reiniciar")


if __name__ == "__main__":
    main()
