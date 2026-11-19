"""Telegram del segundo cerebro.

Comandos: /notas (las últimas), /ideas (solo ideas), /cerebro (estado).
Las frases («idea: …», «decidí …», «qué ideas tengo del negocio») las resuelve segundo_cerebro.procesar()
desde cerebro.responder, así que también funcionan por nota de voz y «hey Jarvis».
Trabajos: cada 10 min ordena lo nuevo (si la IA está libre); domingo 19:00 la revisión semanal (un solo mensaje,
y solo si guardó algo esa semana).
"""
import asyncio
import sys
from datetime import time as hora
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters  # noqa: E402

from modulos.comun.base import USER_ID, ZONA, registro  # noqa: E402
from modulos.segundo_cerebro import segundo_cerebro as sc  # noqa: E402

log = registro("segundo_cerebro")
COMANDOS = [("notas", "Segundo cerebro: sus últimas notas"),
            ("ideas", "Segundo cerebro: sus ideas"),
            ("cerebro", "Segundo cerebro: qué hay guardado")]


def _cortar(texto):
    return texto if len(texto) <= 4000 else texto[:3990].rsplit("\n", 1)[0] + "\n…"


def _lock():
    """La misma cerradura que la biblioteca y el aprendizaje: una sola tarea de IA en segundo plano a la vez."""
    try:
        from modulos.aprendizaje import telegram_aprendizaje
        return telegram_aprendizaje.OCUPADO
    except Exception:
        return None


async def ordenar(context: ContextTypes.DEFAULT_TYPE):
    candado = _lock()
    if candado is not None and not candado.acquire(blocking=False):
        return
    try:
        n = await asyncio.to_thread(sc.ordenar_pendientes)
        if n:
            log.info("Segundo cerebro: %d notas ordenadas", n)
    except Exception as exc:                        # Pausa (modo juego, Ollama apagado) u otro: se reintenta luego
        log.info("Segundo cerebro en pausa: %s", exc)
    finally:
        if candado is not None:
            candado.release()


async def revision(context: ContextTypes.DEFAULT_TYPE):
    from modulos.comun.base import ahora
    if ahora().weekday() != 6:                      # solo domingo (se programa diario para no depender de «days»)
        return
    try:
        r = await asyncio.to_thread(sc.preparar_revision)
    except Exception as exc:
        log.info("Revisión semanal pospuesta: %s", exc)
        return
    if not r:
        return
    await context.bot.send_message(USER_ID, r["texto"])
    for rid, dato in r["propuestas"]:
        botones = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Sí", callback_data="sc:si:" + str(rid)),
                                         InlineKeyboardButton("❌ No", callback_data="sc:no:" + str(rid))]])
        await context.bot.send_message(USER_ID, "• " + dato, reply_markup=botones)


async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, que, rid = q.data.split(":")
    texto = await asyncio.to_thread(sc.responder_propuesta, int(rid), que == "si")
    await q.edit_message_text(texto)


async def cmd_notas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notas = await asyncio.to_thread(sc.ultimas, 15)
    await update.message.reply_html(escape(_cortar(sc.texto_lista(notas, "🧠 Sus últimas notas:")))
                                    + "\n\n<i>Borrar: «borra la nota 3»</i>")


async def cmd_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notas = await asyncio.to_thread(sc.ultimas, 15, "idea")
    await update.message.reply_text(_cortar(sc.texto_lista(notas, "💡 Sus ideas:")))


async def cmd_cerebro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await asyncio.to_thread(sc.estado))


def registrar(app):
    solo = filters.User(USER_ID)
    app.add_handler(CommandHandler("notas", cmd_notas, filters=solo))
    app.add_handler(CommandHandler("ideas", cmd_ideas, filters=solo))
    app.add_handler(CommandHandler("cerebro", cmd_cerebro, filters=solo))
    app.add_handler(CallbackQueryHandler(boton, pattern=r"^sc:(?:si|no):\d+$"))


def programar(job_queue):
    job_queue.run_repeating(ordenar, interval=600, first=120, name="cerebro_ordenar")
    job_queue.run_daily(revision, time=hora(19, 0, tzinfo=ZONA), name="cerebro_revision")
