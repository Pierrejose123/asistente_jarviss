"""Chequeo de salud por Telegram.

- Asistente: cada mañana (06:50) SOLO si algo falla (o siempre, con "chequeo_diario_solo_si_falla": false en
  config/pc.json) y con /salud.
- PC: revisión semanal (domingo 17:00 o al encender si se saltó), avisos inmediatos solo si es grave y /pc.
"""
import asyncio
import sys
from datetime import time as hora
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters  # noqa: E402

from modulos.comun import db, pc_salud, salud  # noqa: E402
from modulos.comun.base import USER_ID, ZONA, ahora, registro  # noqa: E402

log = registro("salud")
COMANDOS = [("salud", "Chequeo: qué partes del asistente funcionan"),
            ("pc", "Revisión de la PC: seguridad, discos, tarjeta gráfica")]
BOTON_LIMPIAR = InlineKeyboardMarkup([[InlineKeyboardButton("🧹 Limpiar temporales viejos", callback_data="pc:limpiar")]])


def _en_juego():
    try:
        from modulos.comun import modos
        return modos.en_modo_ligero()
    except Exception:
        return False


async def chequeo_manana(context: ContextTypes.DEFAULT_TYPE):
    f = ahora()
    if f.strftime("%H:%M") < "06:50" or f.hour >= 12:
        return
    clave = f.date().isoformat() + "|salud"
    if db.aviso_enviado(clave):
        return
    db.marcar_aviso(clave)
    resultados = await asyncio.to_thread(salud.revisar)
    log.info("Chequeo: %s", ", ".join(r["nombre"] + "=" + r["estado"] for r in resultados))
    if pc_salud.chequeo_diario_silencioso() and all(r["estado"] == salud.OK for r in resultados):
        return                                             # todo bien: sin mensaje (menos ruido)
    await context.bot.send_message(USER_ID, salud.texto(resultados), parse_mode="HTML")


async def cmd_salud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Revisando cada parte del asistente… (unos segundos)")
    await update.message.chat.send_action("typing")
    resultados = await asyncio.to_thread(salud.revisar)
    await update.message.reply_html(salud.texto(resultados, completo=True))


async def cmd_pc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Reviso su PC: seguridad, Windows, discos y tarjeta gráfica… (1 o 2 minutos)")
    await update.message.chat.send_action("typing")
    res = await asyncio.to_thread(pc_salud.revisar)
    await update.message.reply_html(pc_salud.texto(res, completo=True),
                                    reply_markup=BOTON_LIMPIAR if pc_salud.hay_temporales(res) else None)


async def revision_semanal(context: ContextTypes.DEFAULT_TYPE):
    """Cada 30 min mira si toca (domingo 17:00 o semana saltada). Espera si hay juego o diseño abierto."""
    if _en_juego() or not await asyncio.to_thread(pc_salud.toca_semanal):
        return
    pc_salud.marcar_semanal()
    try:
        res = await asyncio.to_thread(pc_salud.revisar)
    except Exception as exc:
        log.warning("Revisión semanal de la PC falló: %s", exc)
        return
    await context.bot.send_message(USER_ID, pc_salud.texto(res), parse_mode="HTML",
                                   reply_markup=BOTON_LIMPIAR if pc_salud.hay_temporales(res) else None)


async def vigilar_grave(context: ContextTypes.DEFAULT_TYPE):
    try:
        for texto in await asyncio.to_thread(pc_salud.vigilar_grave):
            await context.bot.send_message(USER_ID, texto)
    except Exception as exc:
        log.info("Vigilancia de la PC: %s", exc)


async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != USER_ID:
        return
    await q.answer("Limpiando…")
    gb = await asyncio.to_thread(pc_salud.limpiar_temporales)
    await q.edit_message_reply_markup(None)
    await context.bot.send_message(USER_ID, "🧹 Listo: liberé %.1f GB de temporales viejos (los que estaban en uso los dejé)."
                                   % gb)


def registrar(app):
    solo = filters.User(user_id=USER_ID)
    app.add_handler(CommandHandler("salud", cmd_salud, filters=solo))
    app.add_handler(CommandHandler("pc", cmd_pc, filters=solo))
    app.add_handler(CallbackQueryHandler(boton, pattern=r"^pc:limpiar$"))


def programar(job_queue):
    job_queue.run_daily(chequeo_manana, time=hora(6, 50, tzinfo=ZONA), name="salud")
    job_queue.run_once(chequeo_manana, when=200, name="salud_inicio")      # si la PC se encendió tarde
    job_queue.run_repeating(revision_semanal, interval=1800, first=600, name="pc_semanal")
    job_queue.run_repeating(vigilar_grave, interval=600, first=180, name="pc_grave")
