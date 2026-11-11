"""Protección: si el programa NO está usando la base real (datos/asistente.db) es una PRUEBA, y una prueba
nunca puede tocar Google Calendar ni mandar Telegram. Lo usan google_cal.servicio y base.enviar_telegram.

Origen (10-11): una prueba con base temporal subió ~30 recordatorios falsos a Google («Comprar pan»…).
"""
from pathlib import Path


def activo():
    from modulos.comun import db
    from modulos.comun.base import RAIZ
    try:
        return Path(db.ARCHIVO).resolve() != (RAIZ / "datos" / "asistente.db").resolve()
    except Exception:
        return True                     # ante la duda, se bloquea


def bloquear(que="Google Calendar"):
    if activo():
        raise RuntimeError("Bloqueado: esto es una prueba (base temporal) y no puede usar " + que + ".")
