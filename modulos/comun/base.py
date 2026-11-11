"""Utilidades compartidas: rutas, configuracion, secretos, registro y avisos."""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = RAIZ / "config"
load_dotenv(RAIZ / ".env")
ZONA = ZoneInfo((os.getenv("ZONA_HORARIA") or "America/Guayaquil").strip())
NOMBRE = (os.getenv("NOMBRE_USUARIO") or "").strip() or "Usuario"        # cómo se llama el dueño del asistente
PERFIL = (os.getenv("PERFIL_USUARIO") or "").strip()                   # a qué se dedica (para la IA)
TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
USER_ID = int((os.getenv("TELEGRAM_USER_ID") or "0").strip() or 0)

def ruta(clave, defecto):
    """Carpeta de config/rutas.json (absoluta o relativa al proyecto). Si no está, <proyecto>/<defecto>."""
    try:
        valor = json.loads((CONFIG / "rutas.json").read_text(encoding="utf-8-sig")).get(clave)
    except Exception:
        valor = None
    p = Path(valor) if valor else RAIZ / defecto
    return p if p.is_absolute() else RAIZ / p


PESADO = ruta("pesado", "datos_pesados")              # archivos grandes y privados (respaldos, XTB, comprobantes)
INFO_IA = ruta("informacion_ia", "mis_documentos")    # carpeta que leen la biblioteca y el aprendizaje

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DIAS_BONITO = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def ahora():
    return datetime.now(ZONA)


def leer_json(nombre):
    return json.loads((CONFIG / nombre).read_text(encoding="utf-8-sig"))


def registro(nombre):
    """Devuelve un logger que escribe en logs/<nombre>.log y en pantalla."""
    carpeta = RAIZ / "logs"
    carpeta.mkdir(exist_ok=True)
    log = logging.getLogger(nombre)
    if not log.handlers:
        log.setLevel(logging.INFO)
        formato = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
        archivo = logging.FileHandler(carpeta / (nombre + ".log"), encoding="utf-8")
        archivo.setFormatter(formato)
        pantalla = logging.StreamHandler()
        pantalla.setFormatter(formato)
        log.addHandler(archivo)
        log.addHandler(pantalla)
    return log


def enviar_telegram(texto, botones=None):
    """Envia un mensaje al usuario. Lo pueden usar todos los modulos."""
    if not TOKEN or not USER_ID:
        raise RuntimeError("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_USER_ID en .env")
    r = requests.post("https://api.telegram.org/bot" + TOKEN + "/sendMessage", timeout=15,
                      json={"chat_id": USER_ID, "text": texto, "parse_mode": "HTML",
                            "disable_web_page_preview": True,
                            **({"reply_markup": {"inline_keyboard": botones}} if botones else {})})
    r.raise_for_status()
    return True


def clases_del_dia(fecha):
    """Lista de clases (dict) para una fecha, dentro del periodo del horario."""
    horario = leer_json("horario_clases.json")
    dia = fecha.strftime("%Y-%m-%d")
    if not (horario["fecha_inicio"] <= dia <= horario["fecha_fin"]):
        return []
    nombre = DIAS[fecha.weekday()]
    return sorted((c for c in horario["clases"] if c["dia"] == nombre), key=lambda c: c["inicio"])


# --- PROTECCION_PRUEBAS (10-11) ---
# Si la base no es la real (una prueba), Telegram queda bloqueado. No tocar.
_enviar_telegram_sin_proteccion = enviar_telegram


def enviar_telegram(*args, **kwargs):
    from modulos.comun import modo_prueba
    modo_prueba.bloquear("Telegram")
    return _enviar_telegram_sin_proteccion(*args, **kwargs)
