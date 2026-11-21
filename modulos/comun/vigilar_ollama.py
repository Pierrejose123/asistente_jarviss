"""Vigila que Ollama (la IA local de Jarvis) esté encendido y lo abre solo si no responde (19-11).

Lo llama el bot cada 2 minutos (telegram_salud.programar). Sin avisos normales: solo escribe en logs/ollama.log.
- Si Ollama no responde 2 veces seguidas, abre la app de Ollama (máx. 1 intento cada 10 min).
- Si el proceso está abierto pero colgado (~8 min sin responder), lo cierra y lo abre de nuevo.
- Solo avisa por Telegram si falla 3 veces en una hora (una vez por día).
- Para apagar la vigilancia: "vigilar_ollama": false en config/ia.json.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modulos.comun.base import RAIZ, registro  # noqa: E402

log = registro("ollama")
URL = "http://127.0.0.1:11434/api/version"
NOMBRES = ("ollama.exe", "ollama app.exe")
ESPERA_INTENTO = 600            # s entre intentos de abrirlo
COLGADO = 4                     # revisiones seguidas sin responder con el proceso abierto = colgado
ESTADO = {"fallos": 0, "ultimo": 0.0, "intentos": [], "aviso_dia": ""}


def activado():
    try:
        datos = json.loads((RAIZ / "config" / "ia.json").read_text(encoding="utf-8-sig"))
        return bool(datos.get("vigilar_ollama", True))
    except Exception:
        return True


def responde(timeout=3):
    try:
        abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # local: sin proxy
        with abridor.open(URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def procesos():
    try:
        import psutil
        return [p for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() in NOMBRES]
    except Exception:
        return []


def ruta_app():
    base = os.getenv("LOCALAPPDATA")
    if base:
        r = Path(base) / "Programs" / "Ollama" / "ollama app.exe"
        if r.exists():
            return r
    return None


def abrir(ruta):
    banderas = (0x00000008 | 0x00000200 | 0x08000000) if os.name == "nt" else 0
    subprocess.Popen([str(ruta)], cwd=str(Path(ruta).parent), creationflags=banderas, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def cerrar(lista):
    for p in lista:
        try:
            p.terminate()
        except Exception:
            pass
    time.sleep(3)


def revisar(ts=None):
    """Una revisión. Devuelve un texto para avisar por Telegram (raro) o None."""
    ts = time.time() if ts is None else ts
    if not activado():
        return None
    if responde():
        if ESTADO["fallos"] >= 2:
            log.info("Ollama responde de nuevo")
        ESTADO["fallos"] = 0
        return None
    ESTADO["fallos"] += 1
    if ESTADO["fallos"] < 2 or ts - ESTADO["ultimo"] < ESPERA_INTENTO:
        return None
    ruta = ruta_app()
    if not ruta:
        log.warning("Ollama no responde y no encuentro la app (LOCALAPPDATA\\Programs\\Ollama)")
        return _aviso(ts, "⚠️ La IA local (Ollama) está apagada y no encuentro la app para abrirla. ¿Se desinstaló?")
    abiertos = procesos()
    if abiertos and ESTADO["fallos"] < COLGADO:
        return None                                  # quizá está arrancando: esperar un poco más
    if abiertos:
        log.warning("Ollama abierto pero sin responder: lo cierro y lo abro de nuevo")
        cerrar(abiertos)
    try:
        abrir(ruta)
        log.info("Ollama no respondía: lo abrí (%d revisiones sin respuesta)", ESTADO["fallos"])
    except Exception as exc:
        log.warning("No pude abrir Ollama: %s", exc)
    ESTADO["ultimo"] = ts
    ESTADO["intentos"] = [t for t in ESTADO["intentos"] if ts - t < 3600] + [ts]
    if len(ESTADO["intentos"]) >= 3:
        return _aviso(ts, "⚠️ La IA local (Ollama) se apagó 3 veces en una hora; la abrí cada vez, pero algo la "
                          "está cerrando. Revise logs\\ollama.log.")
    return None


def _aviso(ts, texto):
    dia = time.strftime("%Y-%m-%d", time.localtime(ts))
    if ESTADO["aviso_dia"] == dia:
        return None
    ESTADO["aviso_dia"] = dia
    return texto
