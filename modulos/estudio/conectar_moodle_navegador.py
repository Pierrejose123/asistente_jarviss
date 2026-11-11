"""Conecta el asistente con Moodle iniciando sesion en el NAVEGADOR (sirve con Microsoft / Office 365).

Es el mismo metodo que usa la app oficial de Moodle:
 1. Se registra (solo para su usuario de Windows y solo durante la conexion) el enlace "moodlemobile://".
 2. Se abre <su Moodle>/admin/tool/mobile/launch.php en su navegador.
 3. Usted inicia sesion como siempre. Moodle responde con moodlemobile://token=... y Windows se lo
    entrega a este programa, que verifica la firma, guarda SOLO la clave de servicio en .env y
    borra el registro temporal.
El asistente nunca ve su contrasena: la escribe usted en la pagina oficial (Moodle o Microsoft).

Ejecutar:  .\\.venv\\Scripts\\python.exe modulos\\estudio\\conectar_moodle_navegador.py
"""
import base64
import hashlib
import random
import sys
import time
import webbrowser
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
TEMP = RAIZ / "datos" / "moodle_conexion.tmp"          # pasaporte y luego la clave, por unos segundos
CLAVE_REG = r"Software\Classes\moodlemobile"


def guardar_en_env(clave, valor):
    lineas = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    lineas = [l for l in lineas if not l.startswith(clave + "=")]
    lineas.append(clave + "=" + valor)
    ENV.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def registrar_enlace():
    import winreg
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    comando = '"' + str(pythonw) + '" "' + str(Path(__file__).resolve()) + '" recibir "%1"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CLAVE_REG) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:moodlemobile")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CLAVE_REG + r"\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, comando)


def quitar_enlace():
    import winreg
    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, CLAVE_REG + sub)
        except OSError:
            pass


def recibir(enlace):
    """Lo llama Windows con moodlemobile://token=BASE64. Verifica y deja la clave en el archivo temporal."""
    try:
        pasaporte = TEMP.read_text(encoding="utf-8").strip().split("|")[0]
        datos = enlace.split("token=", 1)[1].strip().strip("/").strip('"')
        datos += "=" * (-len(datos) % 4)
        partes = base64.b64decode(datos).decode("utf-8").split(":::")
        firma, token = partes[0], partes[1]
        esperada = hashlib.md5((SITIO + pasaporte).encode()).hexdigest()
        if firma != esperada:
            TEMP.write_text(pasaporte + "|ERROR firma", encoding="utf-8")
            return
        TEMP.write_text(pasaporte + "|OK|" + token, encoding="utf-8")
    except Exception as exc:
        try:
            TEMP.write_text("0|ERROR " + str(exc)[:80], encoding="utf-8")
        except Exception:
            pass


def main():
    global SITIO
    SITIO = _pedir_sitio()
    if sys.platform != "win32":
        sys.exit("Este programa es para Windows.")
    pasaporte = str(random.randint(10 ** 8, 10 ** 9 - 1))
    TEMP.parent.mkdir(exist_ok=True)
    TEMP.write_text(pasaporte, encoding="utf-8")
    registrar_enlace()
    url = (SITIO + "/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=" + pasaporte
           + "&urlscheme=moodlemobile")
    print("Abriendo Moodle en su navegador...")
    print(" 1. Inicie sesion si se lo pide (Microsoft o usuario y clave, como siempre).")
    print(" 2. Si el navegador pregunta si desea abrir 'pythonw' / la aplicacion, pulse ABRIR.\n")
    webbrowser.open(url)
    token = None
    try:
        for _ in range(300):                                    # hasta 5 minutos
            time.sleep(1)
            contenido = TEMP.read_text(encoding="utf-8") if TEMP.exists() else ""
            if "|OK|" in contenido:
                token = contenido.split("|OK|", 1)[1].strip()
                break
            if "|ERROR" in contenido:
                sys.exit("No se pudo verificar la respuesta de Moodle: " + contenido.split("|ERROR", 1)[1])
        if not token:
            sys.exit("No llego la respuesta de Moodle en 5 minutos. Si el navegador no pregunto nada, avise a Claude.")
        info = requests.post(SITIO + "/webservice/rest/server.php", timeout=30,
                             data={"wstoken": token, "wsfunction": "core_webservice_get_site_info",
                                   "moodlewsrestformat": "json"}).json()
        if "userid" not in info:
            sys.exit("La clave de servicio no funciono: " + str(info.get("message", info))[:120])
        guardar_en_env("MOODLE_TOKEN", token)
        nombre = (info.get("firstname") or "").split(" ")[0]
        print("Conectado" + (" como " + nombre if nombre else "") + ". Clave de servicio guardada en .env.")
        print("Ya puede cerrar la pestana del navegador.")
        print("\nReinicie el asistente:  .\\.venv\\Scripts\\python.exe modulos\\comun\\control.py reiniciar")
    finally:
        quitar_enlace()
        try:
            TEMP.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "recibir":
        recibir(sys.argv[2])
    else:
        main()
