"""Control del asistente:  python control.py estado | detener | iniciar | reiniciar"""
import subprocess
import sys
import time
from pathlib import Path

import psutil

RAIZ = Path(__file__).resolve().parents[2]
PYTHONW = RAIZ / ".venv" / "Scripts" / "pythonw.exe"
SUPERVISOR = RAIZ / "modulos" / "comun" / "supervisor.py"
MARCAS = ("supervisor.py", "telegram\\bot.py", "telegram/bot.py", "voz\\voz.py", "voz/voz.py")


def _cmd(p):
    return " ".join(p.info["cmdline"] or [])


def procesos():
    lista = []
    for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            cmd = _cmd(p)
        except Exception:
            continue
        if "python" in cmd.lower() and any(m in cmd for m in MARCAS):
            lista.append(p)
    return lista


def estado():
    ps = procesos()
    if not ps:
        print("El asistente esta APAGADO.")
        return
    tiene = lambda marca: any(marca in _cmd(p) for p in ps)  # noqa: E731
    print("Supervisor: " + ("ENCENDIDO" if tiene("supervisor.py") else "apagado"))
    print("Bot:        " + ("ENCENDIDO" if tiene("bot.py") else "apagado"))
    print("Voz:        " + ("ENCENDIDA" if tiene("voz.py") else "apagada"))


def detener():
    ps = procesos()
    for p in sorted(ps, key=lambda p: "supervisor.py" not in _cmd(p)):   # primero el supervisor
        try:
            p.terminate()
        except Exception:
            pass
    psutil.wait_procs(ps, timeout=10)
    print("Asistente detenido (bot y voz)." if ps else "No estaba encendido.")


def iniciar():
    if procesos():
        print("Ya esta encendido.")
        return
    subprocess.Popen([str(PYTHONW), str(SUPERVISOR)], cwd=str(RAIZ), creationflags=0x08000000)
    print("Asistente iniciado en segundo plano (bot y voz).")
    print("En unos segundos le llegara 'Asistente en linea' por Telegram; la voz tarda ~30 s en estar lista.")


def reiniciar():
    detener()
    time.sleep(2)
    iniciar()


if __name__ == "__main__":
    {"estado": estado, "detener": detener, "iniciar": iniciar, "reiniciar": reiniciar}.get(
        (sys.argv[1:] or ["estado"])[0], estado)()
