"""Telegram: alertas de precio, diario de decisiones y calendario de resultados.

Las frases normales ("avísame si V sube 35 % desde mi compra", "decisión: compro V porque …",
"mis alertas") las resuelve alertas.procesar() desde el cerebro: funcionan igual por escrito,
nota de voz y "hey Jarvis". Aquí van los comandos y las revisiones programadas.
"""
import asyncio
import sys
from datetime import time as hora
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import Update  # noqa: E402
from telegram.ext import CommandHandler, ContextTypes, filters  # noqa: E402

from modulos.alertas import alertas  # noqa: E402
from modulos.comun.base import USER_ID, ZONA, registro  # noqa: E402

log = registro("alertas")
COMANDOS = [("alertas", "Alertas de precio: /alerta NVDA < 120"),
            ("alerta", "Crear alerta: /alerta V sube 35% desde mi compra"),
            ("diario", "Diario de decisiones de inversión"),
            ("calendario", "Resultados y dividendos de sus acciones")]

AYUDA = ("\n\nEjemplos (también por voz o nota de voz):\n"
         "• avísame si V sube 35 % desde mi compra\n• avísame si NVDA baja de 120\n"
         "• avísame si AMZN cae 5 % en un día\n• avísame si GOOG cae 15 % desde su máximo\n"
         "• borra la alerta 3")


async def _enviar(context, textos):
    for t in textos:
        await context.bot.send_message(USER_ID, t, parse_mode="HTML", disable_web_page_preview=True)


async def cmd_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) == 2 and args[0].lower() in ("borrar", "borra") and args[1].lstrip("#").isdigit():
        texto = await asyncio.to_thread(alertas.procesar, "borra la alerta " + args[1].lstrip("#"))
    else:
        await update.message.chat.send_action("typing")
        texto = await asyncio.to_thread(alertas.texto_lista)
        texto += AYUDA if "No tiene" not in texto else ""
    await update.message.reply_text(texto)


async def cmd_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Dígame la regla, por ejemplo: /alerta NVDA < 120" + AYUDA)
        return
    frase = " ".join(context.args).replace("<", " baja de ").replace(">", " supera ")
    await update.message.chat.send_action("typing")
    texto = await asyncio.to_thread(alertas.procesar, "avísame si " + frase)
    await update.message.reply_text(texto or "No entendí la regla." + AYUDA)


async def cmd_diario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    await update.message.reply_text(await asyncio.to_thread(alertas.texto_diario))


async def cmd_calendario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    await update.message.reply_text(await asyncio.to_thread(alertas.texto_calendario))


async def vigilar_precios(context: ContextTypes.DEFAULT_TYPE):
    try:
        await _enviar(context, await asyncio.to_thread(alertas.revisar_alertas))
    except Exception as exc:
        log.info("No pude revisar alertas: %s", exc)


async def revisiones_diarias(context: ContextTypes.DEFAULT_TYPE):
    """Cada mañana: calendario, revisiones del diario y compras nuevas sin motivo."""
    for funcion in (alertas.avisos_calendario, alertas.calendario_a_google, alertas.revisar_decisiones,
                    alertas.compras_sin_motivo):
        try:
            await _enviar(context, await asyncio.to_thread(funcion))
        except Exception as exc:
            log.info("Falló %s: %s", funcion.__name__, exc)


async def vigilar_compras(context: ContextTypes.DEFAULT_TYPE):
    try:
        await _enviar(context, await asyncio.to_thread(alertas.compras_sin_motivo))
    except Exception as exc:
        log.info("No pude revisar compras nuevas: %s", exc)


def registrar(app):
    solo = filters.User(user_id=USER_ID)
    app.add_handler(CommandHandler("alertas", cmd_alertas, filters=solo))
    app.add_handler(CommandHandler("alerta", cmd_alerta, filters=solo))
    app.add_handler(CommandHandler("diario", cmd_diario, filters=solo))
    app.add_handler(CommandHandler("calendario", cmd_calendario, filters=solo))


def programar(job_queue):
    job_queue.run_repeating(vigilar_precios, interval=600, first=120, name="alertas_precio")
    job_queue.run_daily(revisiones_diarias, time=hora(8, 15, tzinfo=ZONA), name="alertas_diarias")
    job_queue.run_once(revisiones_diarias, when=240, name="alertas_diarias_inicio")   # por si la PC se enciende tarde
    job_queue.run_repeating(vigilar_compras, interval=3600, first=900, name="alertas_compras")
