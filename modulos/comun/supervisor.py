"""Mantiene el asistente encendido: arranca el bot y la voz sin ventana y los reinicia si se caen.

Se ejecuta con pythonw.exe al iniciar sesion en Windows (acceso directo en la carpeta Inicio).
- Una sola copia: si ya hay un supervisor corriendo, sale.
- Cuida dos servicios por separado: el bot de Telegram y la voz ("hey Jarvis").
  Si uno se cae, solo ese se reinicia (15 s, 30 s, 1 min... hasta 5 min).
- Si uno se cae 5 veces en 10 minutos, avisa por Telegram (una vez).
- Si alguien abrio el bot o la voz a mano (bot.py / jarvis-voz.cmd), espera a que lo cierre.
- La voz se puede apagar del arranque con "arrancar_con_windows": false en config/voz.json.
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

import psutil  # noqa: E402

PYTHON = RAIZ / ".venv" / "Scripts" / "python.exe"
LOGS = RAIZ / "logs"
SIN_VENTANA = 0x08000000  # CREATE_NO_WINDOW

SERVICIOS = {
    "bot": {"script": RAIZ / "modulos" / "telegram" / "bot.py", "marca": "bot.py",
            "salida": LOGS / "bot_salida.log", "nombre": "El asistente (bot)"},
    "voz": {"script": RAIZ / "modulos" / "voz" / "voz.py", "marca": "voz.py",
            "salida": LOGS / "voz_salida.log", "nombre": "La voz (hey Jarvis)"},
}


def _cmd(p):
    try:
        return " ".join(p.info["cmdline"] or [])
    except Exception:
        return ""


def ya_corriendo():
    """True si hay OTRO supervisor. En Windows el python del .venv es un lanzador que abre
    un segundo proceso con el mismo comando, asi que se ignoran el propio, sus padres e hijos."""
    yo = psutil.Process()
    propios = {yo.pid} | {p.pid for p in yo.parents()} | {p.pid for p in yo.children(recursive=True)}
    for p in psutil.process_iter(["pid", "cmdline"]):
        cmd = _cmd(p)
        if p.info["pid"] not in propios and "supervisor.py" in cmd and "python" in cmd.lower():
            return True
    return False


def suelto_corriendo(marca):
    """True si el servicio esta abierto a mano (no es hijo de este supervisor)."""
    hijos = {p.pid for p in psutil.Process().children(recursive=True)}
    for p in psutil.process_iter(["pid", "cmdline"]):
        cmd = _cmd(p)
        if p.info["pid"] not in hijos and marca in cmd and "python" in cmd.lower() \
                and "probar" not in cmd:
            return True
    return False


def voz_activada():
    try:
        datos = json.loads((RAIZ / "config" / "voz.json").read_text(encoding="utf-8-sig"))
        return bool(datos.get("arrancar_con_windows", True))
    except Exception:
        return True


def avisar(texto):
    try:
        from modulos.comun.base import enviar_telegram
        enviar_telegram(texto)
    except Exception:
        pass


def cuidar(clave):
    """Bucle de un servicio: lo abre, espera a que termine y lo vuelve a abrir."""
    s = SERVICIOS[clave]
    entorno = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    caidas, espera, avisado = [], 15, False
    while True:
        if clave == "voz" and not voz_activada():
            time.sleep(60)
            continue
        while suelto_corriendo(s["marca"]):       # abierto a mano: esperar a que lo cierre
            time.sleep(60)
        inicio = time.time()
        with open(s["salida"], "a", encoding="utf-8") as salida:
            salida.write("\n=== Arranque %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
            salida.flush()
            proc = subprocess.Popen([str(PYTHON), str(s["script"])], cwd=str(RAIZ), stdout=salida,
                                    stderr=subprocess.STDOUT, creationflags=SIN_VENTANA, env=entorno)
            proc.wait()
        if time.time() - inicio > 600:            # funciono mas de 10 min: reiniciar contadores
            caidas, espera, avisado = [], 15, False
        caidas = [t for t in caidas if time.time() - t < 600] + [time.time()]
        if len(caidas) >= 5 and not avisado:
            avisar("⚠️ " + s["nombre"] + " se ha caído varias veces seguidas. Revise logs\\"
                   + s["salida"].name + " en la PC.")
            avisado = True
        time.sleep(espera)
        espera = min(espera * 2, 300)


def main():
    if ya_corriendo():
        return
    LOGS.mkdir(exist_ok=True)
    hilos = [threading.Thread(target=cuidar, args=(c,), daemon=True) for c in SERVICIOS]
    for h in hilos:
        h.start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
