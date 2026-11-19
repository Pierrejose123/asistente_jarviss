"""Telegram de la vida diaria: hábitos, sueño y el panel del celular.

Comandos: /panel (enlace al panel), /habitos (semana), /sueno (últimas noches).
Trabajos:
- Arranca el panel web (y lo revisa cada 5 min por si Tailscale se conecta después).
- A la hora de config/vida.json → aviso_noche (21:30): UN mensaje con lo pendiente del día (botones) y el
  recordatorio de prepararse para dormir. Si no queda nada pendiente, solo el recordatorio corto.
- Domingo 19:10: informe de sueño de la semana (solo si hay ≥3 noches con datos).
"""
import asyncio
import sys
from datetime import datetime, time as hora
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters  # noqa: E402

from modulos.comun import db  # noqa: E402
from modulos.comun.base import USER_ID, ZONA, ahora, registro  # noqa: E402
from modulos.vida import habitos_vida, servidor, sueno  # noqa: E402

log = registro("vida")
COMANDOS = [("panel", "Su panel de vida en el celular"),
            ("habitos", "Sus hábitos de la semana"),
            ("sueno", "Cómo ha dormido")]


async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = await asyncio.to_thread(servidor.iniciar)
    if not url:
        await update.message.reply_text(
            "No encuentro Tailscale conectado en la PC, señor. Abra Tailscale (ícono junto al reloj) y revise que diga "
            "«Connected»; luego escriba /panel otra vez.")
        return
    await update.message.reply_text(
        "📱 Su panel:\n" + url + "\n\nÁbralo en Safari del iPhone (con Tailscale encendido) y toque Compartir → "
        "«Agregar a pantalla de inicio» para tenerlo como una app.\n\nEl enlace lleva su clave: no lo comparta.",
        disable_web_page_preview=True)


async def cmd_habitos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await asyncio.to_thread(habitos_vida.texto_semana))


async def cmd_sueno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await asyncio.to_thread(sueno.texto_sueno))


def _botones(pendientes):
    filas = []
    for h in pendientes:
        filas.append([InlineKeyboardButton(h["emoji"] + " " + h["nombre"] + " ✅", callback_data="vh:" + h["id"] + ":si"),
                      InlineKeyboardButton("Hoy no", callback_data="vh:" + h["id"] + ":no")])
    if habitos_vida.habito("agua") and habitos_vida.habito("agua").get("activo", True):
        filas.append([InlineKeyboardButton("💧 +1 vaso de agua", callback_data="vh:agua:mas")])
    return InlineKeyboardMarkup(filas) if filas else None


async def aviso_noche(context: ContextTypes.DEFAULT_TYPE):
    clave = ahora().date().isoformat() + "|vida:noche"
    if db.aviso_enviado(clave):
        return
    db.marcar_aviso(clave)
    meta = habitos_vida.ajustes()["hora_dormir"]
    pendientes = await asyncio.to_thread(habitos_vida.pendientes)
    texto = "🌙 En un rato es su hora de dormir (" + meta + "). Vaya bajando luces y pantallas, señor."
    resto = await asyncio.to_thread(habitos_vida.texto_pendientes)
    if resto:
        texto += "\n\n" + resto
    if pendientes:
        texto += "\n\n¿Cómo le fue hoy?"
    await context.bot.send_message(USER_ID, texto, reply_markup=_botones(pendientes))


async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, hid, accion = q.data.split(":")
    await asyncio.to_thread(servidor.accion_habito, hid, accion)
    h = habitos_vida.habito(hid)
    if hid == "agua":
        v = habitos_vida.valor("agua") or 0
        await q.answer("💧 " + ("%g" % v) + " vasos hoy")
        return
    pendientes = await asyncio.to_thread(habitos_vida.pendientes)
    nota = (h["emoji"] + " " + h["nombre"] + (": hecho ✅" if accion == "si" else ": hoy no")) if h else "Listo"
    texto = (q.message.text or "").split("\n\n¿Cómo le fue hoy?")[0]
    texto += "\n\n" + nota + ("\n\n¿Cómo le fue hoy?" if pendientes else "\n\nTodo anotado. Que descanse, señor.")
    try:
        await q.edit_message_text(texto, reply_markup=_botones(pendientes))
    except Exception as exc:
        log.info("No pude editar el aviso de la noche: %s", exc)


async def informe_domingo(context: ContextTypes.DEFAULT_TYPE):
    if ahora().weekday() != 6:
        return
    texto = await asyncio.to_thread(sueno.informe_semanal)
    if texto:
        await context.bot.send_message(USER_ID, texto)


async def revisar_panel(context: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.to_thread(servidor.iniciar)
    except Exception as exc:
        log.warning("No pude arrancar el panel: %s", exc)


def registrar(app):
    solo = filters.User(USER_ID)
    app.add_handler(CommandHandler("panel", cmd_panel, filters=solo))
    app.add_handler(CommandHandler("habitos", cmd_habitos, filters=solo))
    app.add_handler(CommandHandler("sueno", cmd_sueno, filters=solo))
    app.add_handler(CallbackQueryHandler(boton, pattern=r"^vh:[a-z_]+:(?:si|no|mas)$"))


def programar(job_queue):
    job_queue.run_repeating(revisar_panel, interval=300, first=3, name="vida_panel")
    h, m = (int(x) for x in habitos_vida.ajustes()["aviso_noche"].split(":"))
    job_queue.run_daily(aviso_noche, time=hora(h, m, tzinfo=ZONA), name="vida_noche")
    job_queue.run_daily(informe_domingo, time=hora(19, 10, tzinfo=ZONA), name="vida_sueno_domingo")
    if datetime.now(ZONA).time() > hora(h, m) and datetime.now(ZONA).hour < 23:
        job_queue.run_once(aviso_noche, when=40, name="vida_noche_tarde")     # el bot arrancó después de la hora
