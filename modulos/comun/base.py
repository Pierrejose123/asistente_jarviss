"""Utilidades compartidas: rutas, configuracion, secretos, registro y avisos."""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:                       # usar los certificados de Windows: funciona aunque un antivirus (Avast) revise el HTTPS
    import truststore
    truststore.inject_into_ssl()
except Exception:          # sin truststore se usa la lista propia de Python (certifi), como antes
    pass

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


def _ca_windows():
    """yfinance usa curl_cffi, que NO ve los certificados de Windows (truststore solo arregla requests/ssl). Con Avast
    revisando el HTTPS, Yahoo falla con «unable to get local issuer certificate». Se arma un archivo con los
    certificados de Windows + certifi y curl_cffi lo usa por defecto. Se rehace una vez al día."""
    import ssl
    import time
    if not hasattr(ssl, "enum_certificates"):              # solo Windows
        return None
    destino = RAIZ / "datos" / "ca_windows.pem"
    try:
        if destino.exists() and time.time() - destino.stat().st_mtime < 86400:
            return str(destino)
        pems = []
        for tienda in ("ROOT", "CA"):
            for cert, codificacion, _uso in ssl.enum_certificates(tienda):
                if codificacion == "x509_asn":
                    pems.append(ssl.DER_cert_to_PEM_cert(cert))
        try:
            import certifi
            pems.append(Path(certifi.where()).read_text(encoding="utf-8"))
        except Exception:
            pass
        destino.parent.mkdir(exist_ok=True)
        tmp = destino.with_suffix(".tmp%d" % os.getpid())
        tmp.write_text("".join(pems), encoding="utf-8")
        os.replace(tmp, destino)
        return str(destino)
    except Exception:
        return str(destino) if destino.exists() else None


try:                       # curl_cffi (yfinance: precios, calendario de resultados) con los certificados de Windows
    _CA = _ca_windows()
    if _CA:
        from curl_cffi import requests as _curl_requests
        _sesion_original = _curl_requests.Session.__init__

        def _sesion_con_ca(self, *a, **k):
            k.setdefault("verify", _CA)
            _sesion_original(self, *a, **k)

        if not getattr(_curl_requests.Session, "_ca_windows", False):
            _curl_requests.Session.__init__ = _sesion_con_ca
            _curl_requests.Session._ca_windows = True
except Exception:          # sin curl_cffi o sin certificados: todo sigue como antes
    pass


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
        if not _es_prueba():
            archivo = logging.FileHandler(carpeta / (nombre + ".log"), encoding="utf-8")
            archivo.setFormatter(formato)
            log.addHandler(archivo)
        pantalla = logging.StreamHandler()
        pantalla.setFormatter(formato)
        log.addHandler(pantalla)
    return log


def _es_prueba():
    """21-11: las pruebas (base temporal) ya no escriben en logs/ reales. Antes la prueba del equipo dejaba
    «El equipo falló en la tarea 9: Ollama apagado / sin red» en logs/equipo.log y parecía una falla real."""
    try:
        from modulos.comun import modo_prueba
        return modo_prueba.activo()
    except Exception:
        return False                    # ante la duda, se escribe el registro como siempre


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
