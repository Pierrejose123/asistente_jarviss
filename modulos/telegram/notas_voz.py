"""Notas de voz por Telegram (Fase 2).

El usuario manda un audio desde el celular -> Whisper lo pasa a texto -> el MISMO cerebro que
los mensajes escritos (tareas, agenda, gastos, memoria...) -> responde por escrito y,
ademas, con una nota de voz (la misma voz de "hey Jarvis").

- Si hay una practica de ingles abierta (/ingles), la nota se entiende en ingles, se
  responde con la voz inglesa y "that's all" la termina con las correcciones.
- Whisper se carga solo cuando llega una nota y se suelta tras unos minutos sin uso.
  En modo juego/diseno usa el procesador (modelo chico) para no tocar la tarjeta grafica.
- El audio se borra apenas se transcribe; solo queda el texto (logs/voz_transcripciones.txt).

Ajustes opcionales en config/voz.json (si no estan, se usan estos valores):
  "telegram_responder_con_voz": true      responder tambien con nota de voz
  "telegram_max_segundos": 300            notas mas largas no se procesan
  "telegram_soltar_tras_min": 5           minutos sin uso para soltar Whisper
"""
import asyncio
import gc
import re
import sys
import tempfile
import threading
import time
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import Update  # noqa: E402
from telegram.ext import ContextTypes, MessageHandler, filters  # noqa: E402

from modulos.comun import modos  # noqa: E402
from modulos.comun.base import enviar_telegram, registro  # noqa: E402
from modulos.ingles import conversacion  # noqa: E402
from modulos.voz import voz as voz_pc  # noqa: E402   (reusa Whisper, limpieza y voz neural)

log = registro("notas_voz")

PREDETERMINADOS = {"telegram_responder_con_voz": True, "telegram_max_segundos": 300,
                   "telegram_soltar_tras_min": 5, "telegram_whisper_gpu": "large-v3-turbo",
                   "telegram_whisper_cpu": "small"}
MAX_LECTURA = 1200          # caracteres que se leen en voz alta; el resto queda por escrito
TASAS_OPUS = (8000, 12000, 16000, 24000, 48000)
EMOJIS = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")

_whisper = {"modelo": None, "donde": "", "uso": 0.0}
_cerrojo = threading.Lock()
_atender = None             # funcion del bot que procesa un texto (se pasa en registrar)


def ajuste(clave):
    return voz_pc.AJUSTES.get(clave, PREDETERMINADOS[clave])


# ------------------------------------------------------------------ Whisper bajo demanda ---
def soltar():
    """Saca Whisper de la memoria (y de la tarjeta grafica)."""
    if _whisper["modelo"] is not None:
        log.info("Suelto Whisper (%s)", _whisper["donde"])
    _whisper["modelo"], _whisper["donde"] = None, ""
    gc.collect()


def _cargar():
    ligero = modos.en_modo_ligero()
    if _whisper["modelo"] is not None and (_whisper["donde"] == "cpu" or not ligero):
        return _whisper["modelo"]
    soltar()                                     # estaba en la tarjeta y se abrio un juego
    import numpy as np
    voz_pc._librerias_cuda()
    from faster_whisper import WhisperModel
    opciones = []
    if not ligero and voz_pc.AJUSTES.get("whisper_dispositivo") != "cpu":
        gpu = ajuste("telegram_whisper_gpu")
        opciones += [("cuda", "int8_float16", gpu), ("cuda", "float16", gpu)]
    opciones.append(("cpu", "int8", ajuste("telegram_whisper_cpu")))
    for dispositivo, tipo, nombre in opciones:
        try:
            extra = {"cpu_threads": 4} if dispositivo == "cpu" else {}
            modelo = WhisperModel(nombre, device=dispositivo, compute_type=tipo,
                                  download_root=voz_pc._carpeta_modelos(), **extra)
            list(modelo.transcribe(np.zeros(16000, dtype=np.float32), language="es")[0])   # prueba real
            _whisper.update(modelo=modelo, donde=dispositivo)
            log.info("Whisper '%s' cargado en %s (%s)", nombre, dispositivo, tipo)
            return modelo
        except Exception as exc:
            log.info("Whisper no pudo cargar en %s/%s: %s", dispositivo, tipo, str(exc)[:120])
    raise RuntimeError("No se pudo cargar Whisper")


def leer_audio(ruta):
    """OGG/Opus, MP3, M4A... -> 16 kHz mono para Whisper, con PyAV (sin ffmpeg).
    No se usa decode_audio de faster-whisper: falla con PyAV 14+ ('metadata_errors')."""
    import av
    import numpy as np
    partes = []
    with av.open(str(ruta)) as contenedor:
        cambio = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for cuadro in contenedor.decode(audio=0):
            partes += [c.to_ndarray().reshape(-1) for c in cambio.resample(cuadro)]
        partes += [c.to_ndarray().reshape(-1) for c in cambio.resample(None)]
    return (np.concatenate(partes).astype(np.float32) / 32768) if partes else np.zeros(0, np.float32)


def transcribir_archivo(ruta, idioma):
    audio = leer_audio(ruta)
    with _cerrojo:
        modelo = _cargar()
        texto = voz_pc.transcribir(modelo, audio, idioma)
        _whisper["uso"] = time.monotonic()
    return texto


async def revisar_inactivo(context: ContextTypes.DEFAULT_TYPE):
    """Cada minuto: si Whisper lleva varios minutos sin uso, lo suelta."""
    if _whisper["modelo"] is None or _cerrojo.locked():
        return
    if time.monotonic() - _whisper["uso"] > ajuste("telegram_soltar_tras_min") * 60:
        await asyncio.to_thread(soltar)


# ------------------------------------------------------------------ respuesta con voz ---
def texto_para_leer(texto):
    texto = EMOJIS.sub("", re.sub(r"<[^>]+>", "", texto))
    texto = voz_pc.limpiar_para_voz(texto)
    if len(texto) > MAX_LECTURA:
        corte = max(texto.rfind(s, 0, MAX_LECTURA) for s in (". ", "? ", "! "))
        texto = texto[:corte + 1 if corte > 200 else MAX_LECTURA] + " El resto se lo dejé por escrito, señor."
    return texto


def audio_de_respuesta(texto, voz=None):
    """Devuelve la respuesta como nota de voz (OGG/Opus, lo que usa Telegram) o None."""
    import soundfile as sf
    limpio = texto_para_leer(texto)
    if not re.search(r"\w", limpio):
        return None
    audio, tasa = voz_pc.sintetizar(limpio, voz)
    if tasa not in TASAS_OPUS:
        import numpy as np
        nuevo = len(audio) * 24000 // tasa
        audio = np.interp(np.linspace(0, len(audio) - 1, nuevo), np.arange(len(audio)), audio).astype("float32")
        tasa = 24000
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "respuesta.ogg"
        sf.write(str(ruta), audio, tasa, format="OGG", subtype="OPUS")
        return ruta.read_bytes()


async def responder_con_voz(mensaje, texto, voz=None):
    if not ajuste("telegram_responder_con_voz") or not texto:
        return
    try:
        await mensaje.chat.send_action("record_voice")
        datos = await asyncio.to_thread(audio_de_respuesta, texto, voz)
        if datos:
            await mensaje.reply_voice(voice=datos)
    except Exception as exc:
        log.info("No pude responder con voz: %s", exc)      # la respuesta escrita ya llego


# ------------------------------------------------------------------ practica de ingles ---
def _practica_abierta():
    try:
        return conversacion.abierta("telegram")
    except Exception as exc:
        log.info("No pude revisar la practica de ingles: %s", exc)
        return None


async def _turno_ingles(mensaje, practica, texto):
    voz_en = conversacion.vocab.ajustes().get("voz_ingles", "en-GB-RyanNeural")
    try:
        if conversacion.es_fin(texto):
            await asyncio.to_thread(conversacion.cerrar, practica["id"])
            html, nuevas = await asyncio.to_thread(conversacion.texto_correcciones, practica["id"])
            await asyncio.to_thread(enviar_telegram, html,
                                    conversacion.botones_expresiones(practica["id"], nuevas) or None)
            await responder_con_voz(mensaje, conversacion.resumen_para_voz(practica["id"]))
            return
        respuesta = await asyncio.to_thread(conversacion.responder, practica["id"], texto)
    except Exception as exc:
        log.warning("Error en la practica de ingles por nota de voz: %s", exc)
        respuesta = "Sorry, sir, I lost my train of thought. Could you say that again?"
    await mensaje.reply_text(respuesta)
    await responder_con_voz(mensaje, respuesta, voz_en)


# ------------------------------------------------------------------ manejador ---
async def nota_de_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = update.message
    medio = mensaje.voice or mensaje.audio
    if medio is None:
        return
    maximo = ajuste("telegram_max_segundos")
    if (medio.duration or 0) > maximo:
        await mensaje.reply_text("La nota dura más de %d minutos, señor. Mándemela en partes más cortas." % (maximo // 60))
        return
    if (medio.file_size or 0) > 20 * 1024 * 1024:
        await mensaje.reply_text("El audio pesa más de 20 MB (límite de Telegram para bots), señor.")
        return
    practica = _practica_abierta()
    await mensaje.chat.send_action("typing")
    t0 = time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "nota"
            archivo = await medio.get_file()
            await archivo.download_to_drive(ruta)
            texto = await asyncio.to_thread(transcribir_archivo, ruta, "en" if practica else "es")
    except Exception as exc:
        log.warning("No pude transcribir la nota: %s", exc)
        await mensaje.reply_text("No pude escuchar la nota de voz, señor. ¿Me la escribe, por favor?")
        return
    log.info("Nota de %ss transcrita en %.1fs (%s): %s", medio.duration, time.monotonic() - t0,
             _whisper["donde"], texto[:80])
    if not texto:
        await mensaje.reply_text("No le entendí la nota, señor. ¿Me la repite o me la escribe?")
        return
    await mensaje.reply_html("\U0001F399 <i>" + escape(texto) + "</i>")
    if practica:
        await _turno_ingles(mensaje, practica, texto)
        return
    respuesta = await _atender(update, context, texto)
    await responder_con_voz(mensaje, respuesta)


def registrar(app, atender, solo_dueno):
    """atender(update, context, texto) es la funcion del bot que responde un texto y devuelve la respuesta."""
    global _atender
    _atender = atender
    app.add_handler(MessageHandler(solo_dueno & (filters.VOICE | filters.AUDIO), nota_de_voz))


def programar(job_queue):
    job_queue.run_repeating(revisar_inactivo, interval=60, first=60, name="whisper_telegram")
