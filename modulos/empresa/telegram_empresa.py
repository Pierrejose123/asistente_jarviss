"""Telegram del agente de la empresa.

Comandos: /empresa (último informe), /competidores.
Las frases las atiende cerebro.responder → empresa.procesar(); lo que necesita la IA (informe, borrador, ideas,
buscar competidores) se hace aquí en segundo plano y se responde al terminar.
Trabajos: recoger cada 6 h (silencioso) + aviso de competidor (máx. 1/día); buscar competidores el miércoles 15:00
(propone con botones); informe el día/hora de config/empresa.json (viernes 17:30).
"""
import asyncio
import sys
from datetime import time as hora
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters  # noqa: E402

from modulos.comun.base import DIAS, USER_ID, ZONA, ahora, registro  # noqa: E402
from modulos.empresa import empresa  # noqa: E402

log = registro("empresa")
COMANDOS = [("empresa", "Informe de su empresa de IA"), ("competidores", "Competidores que sigue")]


def _lock():
    try:
        from modulos.aprendizaje import telegram_aprendizaje
        return telegram_aprendizaje.OCUPADO
    except Exception:
        return None


def _cortar(t):
    return t if len(t) <= 4000 else t[:3990].rsplit("\n", 1)[0] + "\n…"


async def _con_ia(funcion, *args):
    """Corre una tarea de IA respetando la cerradura compartida (espera hasta 10 min)."""
    candado = _lock()
    if candado is not None:
        for _ in range(120):
            if candado.acquire(blocking=False):
                break
            await asyncio.sleep(5)
        else:
            raise RuntimeError("la IA está ocupada")
    try:
        return await asyncio.to_thread(funcion, *args)
    finally:
        if candado is not None:
            candado.release()


async def mandar_informe(bot, d):
    await bot.send_message(USER_ID, _cortar(empresa.texto_informe(d)), disable_web_page_preview=True)
    for b in d.get("borradores", []):
        await bot.send_message(USER_ID, _cortar("✍️ Borrador " + b["red"] + " – " + b["tema"] + "\n\n" + b["texto"]))


_APP = {}


def lanzar(pedido, chat_id=USER_ID):
    """Desde cerebro.responder (otro hilo): arranca la tarea en el bucle del bot. Devuelve el texto inicial."""
    app, bucle = _APP.get("app"), _APP.get("bucle")
    if not app or not bucle:
        return "El agente de la empresa todavía está arrancando; pruebe en un minuto."
    asyncio.run_coroutine_threadsafe(tarea(app.bot, pedido, chat_id), bucle)
    return respuesta_inicial(pedido)


async def _guardar_bucle(context: ContextTypes.DEFAULT_TYPE):
    _APP["bucle"] = asyncio.get_running_loop()


async def tarea(bot, pedido, chat_id):
    """Atiende en segundo plano lo que empresa.procesar devolvió como {'tarea': ...}."""
    try:
        if pedido["tarea"] == "informe":
            await asyncio.to_thread(empresa.recoger)
            d = await _con_ia(empresa.generar_informe, True)
            if d:
                await mandar_informe(bot, d)
            else:
                await bot.send_message(chat_id, "Todavía no hay suficientes noticias guardadas para un informe. "
                                                "Pruebe en unas horas.")
        elif pedido["tarea"] == "borrador":
            texto = await _con_ia(empresa.borrador, pedido["tema"], pedido["red"])
            await bot.send_message(chat_id, _cortar("✍️ " + pedido["red"] + " – " + pedido["tema"] + "\n\n"
                                                    + (texto or "No me salió el borrador; pruebe otra vez.")))
        elif pedido["tarea"] == "ideas":
            await bot.send_message(chat_id, _cortar(await _con_ia(empresa.ideas)))
        elif pedido["tarea"] == "descubrir":
            nuevos = await _con_ia(empresa.descubrir_competidores)
            await proponer(bot, nuevos, chat_id)
    except Exception as exc:
        log.warning("Tarea de empresa %s falló: %s", pedido.get("tarea"), exc)
        await bot.send_message(chat_id, "No pude terminar eso ahora (" + str(exc)[:80] + "). Lo intento luego si me lo "
                                        "vuelve a pedir.")


def respuesta_inicial(pedido):
    return {"informe": "📊 Armando el informe de su empresa con lo investigado… tarda unos minutos, se lo mando aquí.",
            "borrador": "✍️ Escribiendo el borrador, un momento…",
            "ideas": "💡 Pensando ideas con sus notas y lo investigado…",
            "descubrir": "🔎 Buscando competidores en internet… le aviso lo que encuentre."}[pedido["tarea"]]


async def proponer(bot, nuevos, chat_id=USER_ID, silencioso=False):
    if not nuevos:
        if not silencioso:
            await bot.send_message(chat_id, "No encontré competidores nuevos esta vez.")
        return
    await bot.send_message(chat_id, "🔎 Encontré " + str(len(nuevos)) + " posibles competidores. ¿Los sigo?")
    for cid, nombre, web, que in nuevos[:6]:
        botones = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Seguir", callback_data="emp:seguir:" + str(cid)),
                                         InlineKeyboardButton("❌ No", callback_data="emp:no:" + str(cid))]])
        await bot.send_message(chat_id, "🏁 " + nombre + ("\n" + que if que else "") + ("\n" + web if web else ""),
                               reply_markup=botones, disable_web_page_preview=True)


async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, que, cid = q.data.split(":")
    nombre = await asyncio.to_thread(empresa.cambiar_competidor, int(cid), "seguido" if que == "seguir" else "descartado")
    await q.edit_message_text(("✅ Sigo a " if que == "seguir" else "❌ Descartado: ") + (nombre or "?"))


async def recoger(context: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.to_thread(empresa.recoger)
        aviso = await asyncio.to_thread(empresa.aviso_competidor)
        if aviso:
            await context.bot.send_message(USER_ID, aviso, disable_web_page_preview=True)
    except Exception as exc:
        log.info("Recoger empresa falló: %s", exc)


async def informe_programado(context: ContextTypes.DEFAULT_TYPE):
    cuando = empresa.ajustes()["informe"]
    if DIAS[ahora().weekday()] != empresa._sin_tildes(cuando.get("dia", "viernes")):
        return
    try:
        await asyncio.to_thread(empresa.recoger)
        d = await _con_ia(empresa.generar_informe)
        if d:
            await mandar_informe(context.bot, d)
    except Exception as exc:
        log.warning("Informe de la empresa pospuesto: %s", exc)


async def descubrir_programado(context: ContextTypes.DEFAULT_TYPE):
    if ahora().weekday() != 2:                       # miércoles
        return
    try:
        nuevos = await _con_ia(empresa.descubrir_competidores)
        await proponer(context.bot, nuevos, silencioso=True)
    except Exception as exc:
        log.info("Buscar competidores pospuesto: %s", exc)


async def cmd_empresa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = await asyncio.to_thread(empresa.ultimo_informe)
    await update.message.reply_text(_cortar(empresa.texto_informe(d)), disable_web_page_preview=True)


async def cmd_competidores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await asyncio.to_thread(empresa.texto_competidores), disable_web_page_preview=True)


def registrar(app):
    solo = filters.User(USER_ID)
    app.add_handler(CommandHandler("empresa", cmd_empresa, filters=solo))
    app.add_handler(CommandHandler("competidores", cmd_competidores, filters=solo))
    app.add_handler(CallbackQueryHandler(boton, pattern=r"^emp:(?:seguir|no):\d+$"))
    _APP["app"] = app


def programar(job_queue):
    job_queue.run_once(_guardar_bucle, when=1, name="empresa_bucle")
    job_queue.run_repeating(recoger, interval=6 * 3600, first=300, name="empresa_recoger")
    h, m = (int(x) for x in empresa.ajustes()["informe"].get("hora", "17:30").split(":"))
    job_queue.run_daily(informe_programado, time=hora(h, m, tzinfo=ZONA), name="empresa_informe")
    job_queue.run_daily(descubrir_programado, time=hora(15, 0, tzinfo=ZONA), name="empresa_descubrir")
