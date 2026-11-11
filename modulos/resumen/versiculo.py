"""Versiculo del dia en Reina-Valera 1960, desde el feed oficial de BibleGateway (uso personal).

El texto se muestra tal cual lo entrega BibleGateway (sin modificarlo), con su referencia,
aviso de copyright y enlace. Se guarda en datos/versiculo.json para no pedirlo dos veces al dia.
"""
import json
import re
from html import escape, unescape

import requests

from modulos.comun.base import RAIZ, ahora, registro

URL = "https://www.biblegateway.com/votd/get/?format=json&version=RVR1960"
CACHE = RAIZ / "datos" / "versiculo.json"
log = registro("versiculo")


def _limpio(texto):
    texto = unescape(re.sub(r"<[^>]+>", "", texto or ""))
    return re.sub(r"\s+", " ", texto).strip().strip("“”\"")


def del_dia():
    """Devuelve dict con texto, referencia, copyright y enlace, o None si no se pudo."""
    hoy = ahora().date().isoformat()
    try:
        if CACHE.exists():
            guardado = json.loads(CACHE.read_text(encoding="utf-8"))
            if guardado.get("fecha") == hoy:
                return guardado
    except Exception:
        pass
    try:
        v = requests.get(URL, timeout=10, headers={"User-Agent": "AsistentePersonal/1.0"}).json()["votd"]
        datos = {
            "fecha": hoy,
            "texto": _limpio(v.get("text") or v.get("content")),
            "referencia": _limpio(v.get("display_ref") or v.get("reference")),
            "copyright": _limpio(v.get("copyright")),
            "enlace": unescape(v.get("permalink") or "").replace("\\/", "/"),
        }
        if not datos["texto"]:
            return None
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        return datos
    except Exception as exc:
        log.warning("No pude obtener el versiculo del dia: %s", exc)
        return None


def bloque(titulo):
    """Texto HTML listo para Telegram, o '' si no hay versiculo."""
    v = del_dia()
    if not v:
        return ""
    texto = "\U0001F4D6 <b>" + titulo + "</b>\n<i>«" + escape(v["texto"]) + "»</i>\n— " + escape(v["referencia"]) + " (RVR1960)"
    if v.get("enlace"):
        texto += '\n<a href="' + escape(v["enlace"]) + '">Ver en BibleGateway</a>'
    if v.get("copyright"):
        texto += "\n<i>" + escape(v["copyright"][:200]) + "</i>"
    return texto
