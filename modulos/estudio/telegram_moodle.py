"""Moodle en Telegram: deberes (calendario, cada 30 min), notificaciones y avisos (clave de servicio, cada
15 min) y el comando /moodle."""
import asyncio
from html import escape

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from modulos.comun.base import USER_ID, registro
from modulos.estudio import moodle, moodle_avisos

log = registro("moodle")

COMANDOS = [("moodle", "Deberes de Moodle (revisa ahora)"),
            ("materiales", "Materiales de Moodle en su biblioteca (revisa ahora)")]
try:
    from modulos.estudio import telegram_tarjetas as _tarjetas
    COMANDOS += _tarjetas.COMANDOS
except Exception as _exc:                       # si algo falla, Moodle sigue funcionando
    _tarjetas = None
    log.warning("Tarjetas de estudio no disponibles: %s", _exc)


async def revisar_moodle(context: ContextTypes.DEFAULT_TYPE):
    if not moodle.url():
        return
    try:
        mensajes, _ = await asyncio.to_thread(moodle.revisar)
        context.bot_data["moodle_fallos"] = 0
    except Exception as exc:
        fallos = context.bot_data.get("moodle_fallos", 0) + 1
        context.bot_data["moodle_fallos"] = fallos
        log.warning("No pude revisar Moodle (%d): %s", fallos, exc)
        if fallos == 6:                       # ~3 horas seguidas sin poder: avisar una vez
            await context.bot.send_message(USER_ID, "⚠️ Hace unas 3 horas que no puedo revisar Moodle ("
                                           + str(exc)[:80] + "). Si cambió el enlace del calendario, vuelva a exportarlo.")
        return
    for m in mensajes:
        await context.bot.send_message(USER_ID, m, parse_mode="HTML")
    if mensajes:
        from modulos.clases import avisos
        avisos.notificar_windows("Moodle", "Hay novedades en sus deberes")
        avisos.programar_dia(context.job_queue, USER_ID)


async def cmd_moodle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not moodle.url():
        await update.message.reply_text("Falta conectar Moodle: guarde el enlace del calendario en .env (MOODLE_ICAL_URL).")
        return
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        mensajes, n = await asyncio.to_thread(moodle.revisar)
    except Exception as exc:
        await update.message.reply_text("No pude revisar Moodle ahora: " + str(exc)[:120])
        return
    for m in mensajes:
        await update.message.reply_html(m)
    if moodle_avisos.token():
        try:
            for m in await asyncio.to_thread(moodle_avisos.revisar):
                await update.message.reply_html(m, disable_web_page_preview=True)
        except Exception as exc:
            await update.message.reply_text("No pude revisar las notificaciones: " + str(exc)[:100])
    lista = await asyncio.to_thread(moodle.proximos)
    if not lista:
        await update.message.reply_text("Revisé Moodle: no hay deberes en las próximas 3 semanas, señor.")
        return
    lineas = ["\U0001F393 <b>Deberes de Moodle (próximas 3 semanas)</b>", ""]
    for d in lista:
        lineas.append(("✅ " if d["hecha"] else "• ") + "<b>" + escape(d["titulo"]) + "</b>"
                      + (" – " + escape(d["materia"]) if d["materia"] else "") + "\n   " + moodle._cuando(d["vence"])
                      + ("  <i>#" + str(d["tarea"]) + "</i>" if d["tarea"] else ""))
    lineas += ["", "<i>Moodle no me dice si ya lo entregó: márquelo con /hecho número.</i>"]
    await update.message.reply_html("\n".join(lineas))


async def revisar_avisos(context: ContextTypes.DEFAULT_TYPE):
    if not moodle_avisos.token():
        return
    try:
        mensajes = await asyncio.to_thread(moodle_avisos.revisar)
        context.bot_data["avisos_fallos"] = 0
    except moodle_avisos.SinConexion as exc:
        if not context.bot_data.get("avisos_token_avisado"):
            context.bot_data["avisos_token_avisado"] = True
            await context.bot.send_message(USER_ID, "\U0001F511 Moodle ya no acepta la clave de servicio (" + str(exc)[:60]
                                           + "). Si cambi\u00f3 su contrase\u00f1a, en la PC ejecute:\n"
                                           ".\\.venv\\Scripts\\python.exe modulos\\estudio\\conectar_moodle.py")
        return
    except Exception as exc:
        fallos = context.bot_data.get("avisos_fallos", 0) + 1
        context.bot_data["avisos_fallos"] = fallos
        log.warning("No pude revisar avisos de Moodle (%d): %s", fallos, exc)
        return
    context.bot_data["avisos_token_avisado"] = False
    for m in mensajes:
        await context.bot.send_message(USER_ID, m, parse_mode="HTML", disable_web_page_preview=True)
    if mensajes:
        from modulos.clases import avisos
        avisos.notificar_windows("Moodle", "Tiene " + str(len(mensajes)) + " novedad(es) de Moodle")


# ------------------------------------------------------------------ materiales -> biblioteca ---
async def revisar_materiales(context: ContextTypes.DEFAULT_TYPE):
    """Cada 30 min mira si ya tocan las 6 h (y no hay modo juego); entonces baja lo nuevo."""
    from modulos.estudio import moodle_materiales as mm
    try:
        res = await asyncio.to_thread(mm.revisar)
        context.bot_data["materiales_fallos"] = 0
    except mm.SinPermisoDescarga as exc:
        if not context.bot_data.get("materiales_permiso_avisado"):
            context.bot_data["materiales_permiso_avisado"] = True
            await context.bot.send_message(USER_ID, "⚠️ Moodle no me deja descargar los materiales ("
                                           + str(exc)[:80] + "). Los deberes y avisos siguen funcionando.")
        return
    except moodle_avisos.SinConexion:
        return                                  # ya lo avisa revisar_avisos
    except Exception as exc:
        fallos = context.bot_data.get("materiales_fallos", 0) + 1
        context.bot_data["materiales_fallos"] = fallos
        log.warning("No pude revisar materiales de Moodle (%d): %s", fallos, exc)
        return
    context.bot_data["materiales_permiso_avisado"] = False
    for m in mm.mensajes(res):
        await context.bot.send_message(USER_ID, m, parse_mode="HTML", disable_web_page_preview=True)


async def cmd_materiales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from modulos.estudio import moodle_materiales as mm
    if not moodle_avisos.token():
        await update.message.reply_text("Falta la clave de servicio de Moodle (MOODLE_TOKEN en .env).")
        return
    await update.message.reply_text("Revisando los materiales de sus cursos en Moodle…")
    try:
        res = await asyncio.to_thread(mm.revisar, True)
    except mm.SinPermisoDescarga as exc:
        await update.message.reply_text("Moodle no me deja descargar los archivos: " + str(exc)[:150])
        return
    except Exception as exc:
        await update.message.reply_text("No pude revisar los materiales ahora: " + str(exc)[:150])
        return
    for m in mm.mensajes(res):
        await update.message.reply_html(m, disable_web_page_preview=True)
    if res and res.get("ocupado"):
        await update.message.reply_text("Moodle me pidió esperar un poco (demasiadas consultas seguidas). "
                                        "Sigo solo en unos 30 minutos.")
    elif res and not (res["nuevos"] or res["actualizados"] or res["primera"]):
        await update.message.reply_text("No hay material nuevo, señor.")
    await update.message.reply_text(await asyncio.to_thread(mm.estado_texto))


def registrar(app):
    from telegram.ext import filters
    app.add_handler(CommandHandler("moodle", cmd_moodle, filters=filters.User(user_id=USER_ID)))
    app.add_handler(CommandHandler("materiales", cmd_materiales, filters=filters.User(user_id=USER_ID)))
    if _tarjetas:
        _tarjetas.registrar(app)


def programar(job_queue):
    job_queue.run_repeating(revisar_moodle, interval=30 * 60, first=90, name="moodle")
    job_queue.run_repeating(revisar_avisos, interval=15 * 60, first=150, name="moodle_avisos")
    job_queue.run_repeating(revisar_materiales, interval=30 * 60, first=600, name="moodle_materiales")
    if _tarjetas:
        _tarjetas.programar(job_queue)
