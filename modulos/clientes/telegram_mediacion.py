"""Demo del centro de mediación DENTRO de Jarvis (mismo bot). El proyecto vive en I:\\Clientes\\centro_mediacion.

«modo mediación» (o /mediacion) → los mensajes van primero al asistente del centro; lo que no entienda sigue a Jarvis.
«salir de mediación» / «modo normal» → vuelve a Jarvis. El modo se apaga solo tras 2 h sin usarlo.
Sin entrar al modo: «mediación: agenda de hoy» (una sola frase).
«carga la demo» (en modo mediación) → 5 casos de ejemplo con nombres inventados.
Ruta del proyecto: config/clientes.json → {"mediacion": "I:\\\\Clientes\\\\centro_mediacion"}.
"""
import asyncio
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import Update  # noqa: E402
from telegram.ext import CommandHandler, ContextTypes, filters  # noqa: E402

from modulos.comun.base import CONFIG, USER_ID, registro  # noqa: E402

log = registro("mediacion")
COMANDOS = [("mediacion", "Demo del centro de mediación (entrar/salir)")]
ARCHIVO = CONFIG / "clientes.json"
ESTADO = {"activo": False, "ultimo": 0.0}
VENCE = 2 * 3600
_MOD = {}

ENTRAR = re.compile(r"^\W*(?:jarvis\W+)?(?:modo\s+mediaci[oó]n|entra(?:r)?\s+(?:a|en)\s+(?:modo\s+)?mediaci[oó]n|"
                    r"abre\s+(?:la\s+)?mediaci[oó]n|demo\s+(?:de\s+)?mediaci[oó]n|/?mediacion|mediaci[oó]n)\W*$", re.I)
SALIR = re.compile(r"^\W*(?:sal(?:ir|e|te)?(?:\s+de)?(?:\s+(?:modo\s+)?mediaci[oó]n)?|modo\s+normal|vuelve\s+a\s+jarvis|"
                   r"termina(?:r)?\s+(?:la\s+)?mediaci[oó]n|cierra\s+(?:la\s+)?mediaci[oó]n|listo\s+mediaci[oó]n)\W*$", re.I)
UNA_VEZ = re.compile(r"^\W*mediaci[oó]n\s*[:,\-–]\s*(.+)$", re.I | re.S)
DEMO = re.compile(r"^\W*(?:carga(?:r)?\s+(?:la\s+)?demo|datos\s+de\s+(?:ejemplo|demo)|/demo|casos\s+de\s+ejemplo)\W*$", re.I)


def carpeta():
    try:
        return Path(json.loads(ARCHIVO.read_text(encoding="utf-8-sig"))["mediacion"])
    except FileNotFoundError:
        ARCHIVO.write_text(json.dumps({"mediacion": r"I:\Clientes\centro_mediacion"}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    except Exception as exc:
        log.warning("config/clientes.json: %s", exc)
    return Path(r"I:\Clientes\centro_mediacion")


def modulo():
    """Carga I:\\Clientes\\centro_mediacion\\mediacion.py una sola vez."""
    if "m" not in _MOD:
        ruta = carpeta() / "mediacion.py"
        if not ruta.exists():
            raise FileNotFoundError("No encuentro " + str(ruta))
        spec = importlib.util.spec_from_file_location("mediacion_cliente", ruta)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _MOD["m"] = m
    return _MOD["m"]


def activo():
    if ESTADO["activo"] and time.time() - ESTADO["ultimo"] > VENCE:
        ESTADO["activo"] = False
    return ESTADO["activo"]


def decidir(texto):
    """('entrar'|'salir'|'demo'|'frase'|None, frase). Sin efectos en el modo salvo marcar el uso."""
    t = (texto or "").strip()
    if ENTRAR.match(t):
        return "entrar", ""
    m = UNA_VEZ.match(t)
    if m:
        return "frase", m.group(1).strip()
    if not activo():
        return None, ""
    if SALIR.match(t):
        return "salir", ""
    if DEMO.match(t):
        return "demo", ""
    return "frase", t


DEL_CENTRO = re.compile(r"mediaci|mediador|audiencia|acta\b|acuerdo|invitad|centro|abogad|document|cuesta|costo|tarifa|"
                        r"c[eé]dula|traer|validez|legal|firm|caso", re.I)


def entendido(salida, texto=""):
    if salida["texto"].startswith("No le entendí bien"):
        return False
    return not salida.get("pregunta") or bool(DEL_CENTRO.search(texto))   # «¿qué hora es?» sigue siendo de Jarvis


async def _enviar(msg, salida):
    for i in range(0, len(salida["texto"]), 3900):
        await msg.reply_text(salida["texto"][i:i + 3900])
    for ruta in salida["archivos"]:
        with open(ruta, "rb") as f:
            await msg.reply_document(f, filename=Path(ruta).name)
    for c in salida["copiar"]:
        await msg.reply_text("📋 Para copiar y enviar por WhatsApp:")
        await msg.reply_text(c)


async def intentar(update: Update, texto):
    """Desde bot.atender_texto. True si lo atendió la demo de mediación (entonces Jarvis no responde)."""
    accion, frase = decidir(texto)
    if not accion:
        return False
    msg = update.effective_message
    try:
        m = await asyncio.to_thread(modulo)
    except Exception as exc:
        if accion in ("entrar", "frase") and not activo():
            await msg.reply_text("No pude abrir la demo de mediación (" + str(exc)[:120] + ").")
            return True
        return False
    if accion == "entrar":
        ESTADO.update(activo=True, ultimo=time.time())
        await msg.reply_text("🤝 Modo mediación activo. Lo que escriba va al asistente del centro "
                             "(lo que no entienda lo atiendo yo). «carga la demo» para casos de ejemplo, «ayuda» para ver "
                             "frases y «salir de mediación» para volver.")
        return True
    if accion == "salir":
        ESTADO["activo"] = False
        await msg.reply_text("👍 Salí del modo mediación. Vuelvo a ser Jarvis.")
        return True
    ESTADO["ultimo"] = time.time()
    if accion == "demo":
        n = await asyncio.to_thread(m.cargar_demo)
        await msg.reply_text(("Cargué " + str(n) + " casos de ejemplo con audiencias (nombres inventados). Pruebe «agenda "
                              "de la semana».") if n else "Ya hay casos cargados; no agregué ejemplos.")
        return True
    await update.get_bot().send_chat_action(update.effective_chat.id, "typing")
    try:
        salida = await asyncio.to_thread(m.procesar, frase)
    except m.SinIA:
        salida = {"texto": "La IA no está respondiendo (¿Ollama encendido?). Intente en un momento.", "archivos": [], "copiar": []}
    except Exception as exc:
        log.warning("Mediación falló con «%s»: %s", frase[:60], exc)
        salida = {"texto": "Tuve un problema con eso (" + str(exc)[:100] + ").", "archivos": [], "copiar": []}
    if not entendido(salida, frase) and not UNA_VEZ.match(texto or ""):
        return False                                   # en modo mediación, lo que no entiende el centro lo atiende Jarvis
    await _enviar(msg, salida)
    return True


async def cmd_mediacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if activo():
        ESTADO["activo"] = False
        await update.message.reply_text("👍 Salí del modo mediación. Vuelvo a ser Jarvis.")
    else:
        await intentar(update, "modo mediación")


def registrar(app):
    app.add_handler(CommandHandler("mediacion", cmd_mediacion, filters=filters.User(USER_ID)))
