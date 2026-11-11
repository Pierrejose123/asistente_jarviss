"""Telegram del lector de transcripciones: vigila la carpeta, pregunta el autor, lee con la IA local y avisa.

Se registra desde telegram_cava (así no hay que tocar bot.py).
Comandos: /aprender (leer ya), /videos (cola y lo leído), /ficha META, /reglas cava.
Las frases ("¿qué dice Pepe de META?", "autor 3 Pepe", "fecha video 3 28/10/2026") las resuelve
aprendizaje.procesar() desde el cerebro: funcionan por escrito, nota de voz y "hey Jarvis".
"""
import asyncio
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters  # noqa: E402

from modulos.aprendizaje import aprendizaje  # noqa: E402
from modulos.biblioteca import telegram_biblioteca  # noqa: E402
from modulos.comun.base import USER_ID, registro  # noqa: E402

log = registro("aprendizaje")
COMANDOS = [("aprender", "Leer ya las transcripciones nuevas"),
            ("videos", "Transcripciones leídas y en cola"),
            ("ficha", "Lo aprendido de una acción: /ficha META"),
            ("reglas", "Reglas del método aprendidas: /reglas cava")] + telegram_biblioteca.COMANDOS
OCUPADO = threading.Lock()


def _botones_autor(fid):
    autores = aprendizaje.ajustes()["autores"]
    fila, filas = [], []
    for clave, a in autores.items():
        fila.append(InlineKeyboardButton(a["nombre"], callback_data="aprend:" + str(fid) + ":" + clave))
        if len(fila) == 3:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    return InlineKeyboardMarkup(filas)


async def _preguntar_autores(bot):
    for f in await asyncio.to_thread(aprendizaje.por_preguntar):
        await bot.send_message(USER_ID, "📥 Transcripción nueva #" + str(f["id"]) + ":\n«" + f["titulo"] + "»\n\n"
                               "¿De quién es el video? Si no está en los botones, escriba «autor " + str(f["id"]) +
                               " Nombre».", reply_markup=_botones_autor(f["id"]))


async def ciclo(context: ContextTypes.DEFAULT_TYPE, forzado=False, chat_id=None):
    """Cada 5 min: busca archivos nuevos, pregunta autores y lee UNA transcripción (si la IA está libre)."""
    bot = context.bot
    try:
        await asyncio.to_thread(aprendizaje.escanear)
    except FileNotFoundError as exc:
        if forzado:
            await bot.send_message(chat_id or USER_ID, "⚠️ " + str(exc) + ". Cambie la ruta en config\\aprendizaje.json.")
        return
    except Exception as exc:
        log.info("No pude revisar la carpeta: %s", exc)
    await _preguntar_autores(bot)
    if not aprendizaje.permitido_ahora(forzado) or not OCUPADO.acquire(blocking=False):
        return
    loop = asyncio.get_running_loop()

    def aviso_inicio(f, n):
        minutos = max(1, round(n * 9 / 60))
        asyncio.run_coroutine_threadsafe(bot.send_message(
            USER_ID, "📖 Empecé a leer «" + f["titulo"] + "» (" + str(n) + " partes, unos " + str(minutos) +
            " min). Le aviso al terminar; si abre un juego, pauso y sigo después."), loop)

    try:
        while True:
            try:
                res = await asyncio.to_thread(aprendizaje.procesar_siguiente, aviso_inicio)
            except aprendizaje.Pausa as exc:
                log.info("Lectura en pausa: %s", exc)
                if forzado is True:
                    await bot.send_message(chat_id or USER_ID, "⏸ Pausé la lectura (" + str(exc) + "). Sigo sola más tarde.")
                return
            if not res:
                if forzado is True:
                    await bot.send_message(chat_id or USER_ID, "No hay transcripciones pendientes. " +
                                           "Déjelas en:\n" + str(aprendizaje.carpeta()))
                return
            await bot.send_message(USER_ID, aprendizaje.texto_resultado(res)[:4000])
            if not forzado:                          # en automático: una por vuelta, para no acaparar la IA
                return
            forzado = "seguido"                      # /aprender: sigue con la cola, sin repetir avisos de vacío
            chat_id = None
    except Exception as exc:
        log.warning("Falló la lectura de transcripciones: %s", exc)
        await bot.send_message(USER_ID, "⚠️ No pude terminar de leer una transcripción: " + str(exc)[:200])
    finally:
        OCUPADO.release()


async def _vuelta(context: ContextTypes.DEFAULT_TYPE):
    await ciclo(context)


async def cmd_aprender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if OCUPADO.locked():
        await update.message.reply_text("Ya estoy leyendo una transcripción, señor. Vea el avance con /videos.")
        return
    await update.message.reply_text("Reviso la carpeta de transcripciones…")
    context.application.create_task(ciclo(context, forzado=True, chat_id=update.effective_chat.id))


async def cmd_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.to_thread(aprendizaje.escanear)
    except Exception:
        pass
    await update.message.reply_text(await asyncio.to_thread(aprendizaje.texto_videos))
    await _preguntar_autores(context.bot)


async def cmd_ficha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Escriba la acción: /ficha META  ·  /ficha Visa")
        return
    tema = " ".join(context.args)
    texto = await asyncio.to_thread(aprendizaje.ficha, tema)
    await update.message.reply_text(texto or "Aún no aprendí nada de «" + tema + "» en los videos.")


async def cmd_reglas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    autor = aprendizaje.autor_de_texto(" ".join(context.args)) if context.args else None
    await update.message.reply_text(await asyncio.to_thread(aprendizaje.texto_reglas, autor))


async def boton_autor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q.from_user or q.from_user.id != USER_ID:
        return
    await q.answer()
    _, fid, clave = q.data.split(":", 2)
    await q.edit_message_reply_markup(None)
    await q.message.reply_text(await asyncio.to_thread(aprendizaje.asignar_autor, int(fid), clave))


async def documento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Un .txt con el nombre de un autor o «aprende» en el pie: va a la carpeta y a la cola."""
    doc = update.message.document
    if (doc.file_size or 0) > 5 * 1024 * 1024:
        await update.message.reply_text("El archivo pesa más de 5 MB; mándeme solo la transcripción en .txt.")
        return
    archivo = await doc.get_file()
    datos = bytes(await archivo.download_as_bytearray())
    try:
        destino, autor = await asyncio.to_thread(aprendizaje.recibir_texto, datos, doc.file_name or "transcripcion.txt",
                                                 update.message.caption or "")
    except Exception as exc:
        await update.message.reply_text("No pude guardarla: " + str(exc)[:150])
        return
    await update.message.reply_text("📥 Guardada en su carpeta de transcripciones:\n" + destino.name + "\n\n" +
                                     ("La leo en unos minutos y le aviso lo que aprendí." if autor else
                                      "En unos minutos le pregunto de quién es y la leo."))


def registrar(app):
    solo = filters.User(user_id=USER_ID)
    app.add_handler(CommandHandler("aprender", cmd_aprender, filters=solo))
    app.add_handler(CommandHandler("videos", cmd_videos, filters=solo))
    app.add_handler(CommandHandler("ficha", cmd_ficha, filters=solo))
    app.add_handler(CommandHandler("reglas", cmd_reglas, filters=solo))
    app.add_handler(CallbackQueryHandler(boton_autor, pattern=r"^aprend:\d+:"))
    app.add_handler(MessageHandler(solo & filters.Document.MimeType("text/plain") &
                                   filters.CaptionRegex(r"(?i)aprend|pepe|pablo|transcrip"), documento))
    telegram_biblioteca.registrar(app)                # biblioteca general (todo «Informacion IA»)


def programar(job_queue):
    job_queue.run_repeating(_vuelta, interval=300, first=200, name="aprender_videos")
    telegram_biblioteca.programar(job_queue)
