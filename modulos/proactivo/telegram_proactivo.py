"""Telegram: plan semanal que se agenda solo (con botón Quitar), revisión del domingo y avisos que conectan."""
import asyncio
import sys
from datetime import time as hora, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters  # noqa: E402

from modulos.comun import db  # noqa: E402
from modulos.comun.base import USER_ID, ZONA, ahora, registro  # noqa: E402
from modulos.proactivo import proactivo  # noqa: E402

log = registro("proactivo")
COMANDOS = [("planificar", "Plan de la semana: agenda solo cuándo hacer cada deber"),
            ("revision", "Revisión de la semana: qué cumplió")]


def _botones(creados):
    """Un botón 'Quitar' por bloque nuevo (máx. 8), de dos en dos."""
    filas, fila = [], []
    for c in creados[:8]:
        fila.append(InlineKeyboardButton("❌ Quitar " + proactivo._dia_corto(c["dia"]) + " " + c["ini"],
                                         callback_data="planq:" + str(c["id"])))
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    return InlineKeyboardMarkup(filas) if filas else None


def _reprogramar_avisos(context):
    """Que los avisos de hoy en la PC incluyan los bloques nuevos."""
    try:
        from modulos.clases import avisos
        avisos.programar_dia(context.job_queue, USER_ID)
    except Exception:
        pass


async def _plan(context, chat_id, desde=None, adelanto=None):
    plan, creados, sin_google = await asyncio.to_thread(proactivo.sincronizar, desde, adelanto)
    texto = proactivo.texto_plan(plan, creados, sin_google)
    await context.bot.send_message(chat_id, texto, parse_mode="HTML", reply_markup=_botones(creados))
    if creados:
        _reprogramar_avisos(context)


async def cmd_planificar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    try:
        todo = bool(context.args) and context.args[0].lower() in ("todo", "todos", "adelantar", "adelanta")
        await _plan(context, update.effective_chat.id, adelanto=90 if todo else None)
    except Exception as exc:
        log.warning("Error en /planificar: %s", exc)
        await update.message.reply_text("No pude armar el plan ahora: " + str(exc)[:120])


async def cmd_revision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    await update.message.reply_html(await asyncio.to_thread(proactivo.revision_semana))


async def boton_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botones 'Agendar' de mensajes viejos (antes de que se agendara solo)."""
    q = update.callback_query
    if not q.from_user or q.from_user.id != USER_ID:
        return
    await q.answer()
    await q.edit_message_reply_markup(None)
    if q.data == "plan:no":
        return
    await q.message.reply_text(await asyncio.to_thread(proactivo.agendar_plan, int(q.data.split(":")[1])))
    _reprogramar_avisos(context)


async def boton_quitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q.from_user or q.from_user.id != USER_ID:
        return
    await q.answer("Quitando…")
    bid = int(q.data.split(":")[1])
    try:
        texto = await asyncio.to_thread(proactivo.quitar_bloque, bid)
    except Exception as exc:
        log.warning("No pude quitar el bloque %s: %s", bid, exc)
        await q.message.reply_text("No pude quitarlo ahora: " + str(exc)[:120])
        return
    teclado = q.message.reply_markup.inline_keyboard if q.message.reply_markup else []
    resto = [[b for b in fila if b.callback_data != q.data] for fila in teclado]
    resto = [fila for fila in resto if fila]
    try:
        await q.edit_message_reply_markup(InlineKeyboardMarkup(resto) if resto else None)
    except Exception:
        pass
    await q.message.reply_text(texto)
    await revisar_y_agendar(context)              # le busca otro hueco enseguida
    _reprogramar_avisos(context)


async def revisar_y_agendar(context: ContextTypes.DEFAULT_TYPE):
    """Cada 30 min: reintenta Google, borra bloques que sobran y agenda los deberes nuevos (Moodle o a mano).
    Solo escribe si agendó algo."""
    try:
        _, creados, sin_google = await asyncio.to_thread(proactivo.sincronizar)
    except Exception as exc:
        log.info("Agendado automático falló: %s", exc)
        return
    if creados:
        await context.bot.send_message(USER_ID, proactivo.texto_creados(creados, sin_google), parse_mode="HTML",
                                       reply_markup=_botones(creados))
        _reprogramar_avisos(context)


async def domingo(context: ContextTypes.DEFAULT_TYPE):
    """Domingo 18:00: revisión de la semana y plan de la siguiente (una vez)."""
    hoy = ahora()
    clave = hoy.date().isoformat() + "|domingo"
    if hoy.weekday() != 6 or hoy.hour < 18 or db.aviso_enviado(clave):
        return
    db.marcar_aviso(clave)
    try:
        await context.bot.send_message(USER_ID, await asyncio.to_thread(proactivo.revision_semana), parse_mode="HTML")
        await _plan(context, USER_ID, hoy.date() + timedelta(days=1))
    except Exception as exc:
        log.warning("Falló el domingo: %s", exc)


async def _enviar(context, funcion):
    try:
        for m in await asyncio.to_thread(funcion):
            await context.bot.send_message(USER_ID, m, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as exc:
        log.info("Falló %s: %s", funcion.__name__, exc)


async def cada_5_min(context: ContextTypes.DEFAULT_TYPE):
    await _enviar(context, proactivo.aviso_clase_con_deber)


async def miercoles(context: ContextTypes.DEFAULT_TYPE):
    if ahora().weekday() == 2:
        await _enviar(context, proactivo.aviso_ritmo_gasto)


async def noche(context: ContextTypes.DEFAULT_TYPE):
    await _enviar(context, proactivo.aviso_manana_cargado)


def registrar(app):
    solo = filters.User(user_id=USER_ID)
    app.add_handler(CommandHandler("planificar", cmd_planificar, filters=solo))
    app.add_handler(CommandHandler("revision", cmd_revision, filters=solo))
    app.add_handler(CallbackQueryHandler(boton_quitar, pattern=r"^planq:\d+$"))
    app.add_handler(CallbackQueryHandler(boton_plan, pattern=r"^plan:"))


def programar(job_queue):
    job_queue.run_daily(domingo, time=hora(18, 0, tzinfo=ZONA), name="domingo")     # la función revisa que sea domingo
    job_queue.run_once(domingo, when=260, name="domingo_tarde")          # si el domingo la PC se encendió tarde
    job_queue.run_repeating(revisar_y_agendar, interval=1800, first=150, name="agendar_estudio")
    job_queue.run_repeating(cada_5_min, interval=300, first=45, name="deber_clase")
    job_queue.run_daily(miercoles, time=hora(20, 0, tzinfo=ZONA), name="ritmo_gasto")
    job_queue.run_daily(noche, time=hora(20, 30, tzinfo=ZONA), name="manana_cargado")
