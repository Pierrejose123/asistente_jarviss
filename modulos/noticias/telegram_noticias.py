"""Noticias en Telegram: resumen de la mañana, alertas de sus empresas y /noticias."""
import asyncio
import sys
from datetime import datetime, time as hora
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import Update  # noqa: E402
from telegram.ext import CommandHandler, ContextTypes, filters  # noqa: E402

from modulos.comun import db  # noqa: E402
from modulos.comun.base import USER_ID, ZONA, ahora, registro  # noqa: E402
from modulos.noticias import noticias  # noqa: E402

log = registro("noticias")
COMANDOS = [("noticias", "Noticias del mundo y de sus acciones: /noticias NVDA"),
            ("noticia", "Explicar a fondo una noticia del resumen: /noticia 3")]


async def _enviar(context, texto):
    await context.bot.send_message(USER_ID, texto, parse_mode="HTML", disable_web_page_preview=True)


async def recoger_y_alertar(context: ContextTypes.DEFAULT_TYPE):
    """Cada 30 min: trae noticias nuevas y avisa de las fuertes sobre sus empresas."""
    try:
        await asyncio.to_thread(noticias.recoger)
        for m in await asyncio.to_thread(noticias.alertas_eventos):
            await _enviar(context, m)
    except Exception as exc:
        log.info("No pude recoger noticias: %s", exc)


async def vigilar_movimientos(context: ContextTypes.DEFAULT_TYPE):
    try:
        for m in await asyncio.to_thread(noticias.alertas_movimiento):
            await _enviar(context, m)
    except Exception as exc:
        log.info("No pude revisar movimientos: %s", exc)


async def resumen_manana(context: ContextTypes.DEFAULT_TYPE):
    """A la hora de config/noticias.json (o al encender la PC, hasta las 12:00), una vez al día."""
    f = ahora()
    a = noticias.ajustes()
    toca = a["hora_fin_de_semana"] if f.weekday() >= 5 else a["hora_entre_semana"]
    if f.strftime("%H:%M") < toca or f.hour >= 12:
        return
    clave = f.date().isoformat() + "|noticias_manana"
    if db.aviso_enviado(clave):
        return
    db.marcar_aviso(clave)
    try:
        await asyncio.to_thread(noticias.recoger)
        mensajes = await asyncio.to_thread(noticias.resumen_manana)
    except Exception as exc:
        log.warning("No pude armar el resumen de noticias: %s", exc)
        return
    for texto in mensajes:
        await _enviar(context, texto)
    log.info("Resumen de noticias enviado")


async def cmd_noticias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    if context.args:
        texto = await asyncio.to_thread(noticias.texto_consulta, " ".join(context.args))
        await update.message.reply_text(texto, disable_web_page_preview=True)
        return
    await update.message.reply_text("Reviso las noticias y preparo mi lectura, señor… (un momento)")
    try:
        await asyncio.to_thread(noticias.recoger)
        mensajes = await asyncio.to_thread(noticias.resumen_manana)
    except Exception as exc:
        log.warning("Error en /noticias: %s", exc)
        await update.message.reply_text("No pude traer las noticias ahora: " + str(exc)[:120])
        return
    for texto in mensajes:
        await update.message.reply_html(texto.replace("Noticias de la mañana", "Noticias ahora"),
                                        disable_web_page_preview=True)


async def cmd_noticia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Dígame el número del resumen, por ejemplo /noticia 3. "
                                        "También puede preguntarme normal: «cuéntame más de la 3».")
        return
    await update.message.reply_text("Leo la noticia completa, señor… (unos segundos)")
    await update.message.chat.send_action("typing")
    texto = await asyncio.to_thread(noticias.procesar, "/noticia " + context.args[0])
    try:                                          # para poder seguir preguntando con naturalidad
        from modulos.ia import cerebro
        cerebro.memoria.guardar_turno("Explícame a fondo la noticia " + context.args[0], texto or "")
    except Exception:
        pass
    await update.message.reply_text(texto or "No encontré esa noticia.", disable_web_page_preview=True)


def registrar(app):
    solo = filters.User(user_id=USER_ID)
    app.add_handler(CommandHandler("noticias", cmd_noticias, filters=solo))
    app.add_handler(CommandHandler("noticia", cmd_noticia, filters=solo))


def programar(job_queue):
    a = noticias.ajustes()
    for h in {a["hora_entre_semana"], a["hora_fin_de_semana"]}:
        t = datetime.strptime(h, "%H:%M").time()
        job_queue.run_daily(resumen_manana, time=hora(t.hour, t.minute, tzinfo=ZONA), name="noticias_" + h)
    job_queue.run_once(resumen_manana, when=150, name="noticias_tarde")       # si la PC se encendió tarde
    job_queue.run_repeating(recoger_y_alertar, interval=1800, first=60, name="noticias_recoger")
    job_queue.run_repeating(vigilar_movimientos, interval=1800, first=300, name="noticias_movimientos")
