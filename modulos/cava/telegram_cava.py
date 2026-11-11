"""Comandos de Telegram del cuaderno Cava y del diario de práctica.

Las frases normales ("nota cava: ...", "trade NVDA compra 140 ...", "¿qué dijo Cava de NVDA?")
las resuelve cava.procesar() desde el cerebro, así funcionan igual por escrito, por nota de voz
y con "hey Jarvis". Aquí van los comandos, los .txt de transcripciones y los avisos programados.
"""
import asyncio
import re
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import Update  # noqa: E402
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters  # noqa: E402

from modulos.aprendizaje import telegram_aprendizaje  # noqa: E402
from modulos.cava import cava, newsletter  # noqa: E402
from modulos.comun.base import USER_ID, registro  # noqa: E402

log = registro("cava")

COMANDOS = [
    ("cava", "Cuaderno de Cava: /cava NVDA o /cava stop"),
    ("cavaresumen", "Resumir una transcripción pegada de un video"),
    ("cavavideos", "Últimos videos de BolsaCava"),
    ("trade", "Anotar trade de práctica: /trade NVDA compra 140 stop 132"),
    ("practica", "Diario de trading y estadísticas"),
    ("pablogil", "Lo que guardé de los newsletters de Pablo Gil"),
    ("newsletter", "Revisar ya si llegó un newsletter nuevo"),
] + telegram_aprendizaje.COMANDOS

AYUDA_CAVA = (
    "\n\n<b>Cómo usarlo</b>\n"
    "• Anotar: «nota cava: NVDA rompió 140, busca 160» (escrito o nota de voz)\n"
    "• Buscar: «¿qué dijo Cava de Nvidia?» o /cava stop\n"
    "• Video largo: déjelo en su carpeta de transcripciones o mande el .txt con «cava» en el pie (/videos)\n"
    "• Borrar una nota: /cava borrar 12"
)


async def cmd_cava(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) == 2 and args[0].lower() == "borrar" and args[1].lstrip("#").isdigit():
        hecho = await asyncio.to_thread(cava.borrar_nota, int(args[1].lstrip("#")))
        await update.message.reply_text("Nota borrada." if hecho else "No encuentro esa nota.")
        return
    texto = await asyncio.to_thread(cava.texto_busqueda, " ".join(args))
    await update.message.reply_html(escape(texto) + (AYUDA_CAVA if not args else ""))


async def _resumir(update, texto, fuente):
    await update.message.reply_text("Leyendo la transcripción, señor. Tardo un poco según lo largo del video…")
    await update.message.chat.send_action("typing")
    try:
        nid, resumen = await asyncio.to_thread(cava.resumir_transcripcion, texto, fuente)
    except Exception as exc:
        log.warning("No pude resumir la transcripción: %s", exc)
        await update.message.reply_text("No pude resumirla: " + str(exc))
        return
    await update.message.reply_text("📺 Resumen guardado en su cuaderno Cava (#" + str(nid) + "):\n\n" + resumen[:3500]
                                     + "\n\nEl texto original no se guarda, solo este resumen.")


async def cmd_cavaresumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    partes = (update.message.text or "").split(maxsplit=1)
    if len(partes) < 2 or len(partes[1]) < 200:
        await update.message.reply_text(
            "Pegue la transcripción después del comando: /cavaresumen <texto>.\n"
            "Si es muy larga para un mensaje (más de ~4000 letras), guárdela en un .txt y mándemela como archivo "
            "con la palabra «cava» en el pie (puede añadir el título del video).\n\n"
            "En YouTube: debajo del video → … más → Mostrar transcripción → seleccione y copie.")
        return
    await _resumir(update, partes[1], "")


async def documento_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Un .txt con «cava» en el pie: va a la carpeta de transcripciones y el lector lo aprende entero."""
    await telegram_aprendizaje.documento(update, context)


async def cmd_cavavideos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not cava.ajustes()["canal_id"]:
        await update.message.reply_text("Aún no conecto el canal. En la PC ejecute:\n"
                                        ".\\.venv\\Scripts\\python.exe modulos\\cava\\conectar_youtube.py")
        return
    try:
        await asyncio.to_thread(cava.revisar_videos)
    except Exception as exc:
        log.info("No pude revisar YouTube: %s", exc)
    videos = await asyncio.to_thread(cava.ultimos_videos, 5)
    if not videos:
        await update.message.reply_text("No encontré videos todavía.")
        return
    lineas = ["📺 <b>Últimos videos de " + escape(cava.ajustes()["canal_youtube"]) + "</b>"]
    for v in videos:
        lineas.append("• " + v["publicado"][:10] + " <a href=\"" + escape(v["url"]) + "\">" + escape(v["titulo"]) + "</a>")
    lineas.append("\nCuando vea uno, mándeme lo importante con «nota cava: …».")
    await update.message.reply_html("\n".join(lineas), disable_web_page_preview=True)


async def cmd_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Anote una operación de práctica así:\n"
            "/trade NVDA compra 140 stop 132 objetivo 160 motivo ruptura de resistencia\n\n"
            "• Va a la cuenta demo; agregue «real» si es con dinero real.\n"
            "• Cambiar: «stop trade 3 135» · Cerrar: «cerrar trade 3 a 155»\n"
            "• Lo aprendido: «nota trade 3: …» · Ver todo: /practica")
        return
    await update.message.reply_text(await asyncio.to_thread(cava.procesar, "trade " + " ".join(context.args)))


async def cmd_practica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    await update.message.reply_text(await asyncio.to_thread(cava.estadisticas))


async def vigilar_videos(context: ContextTypes.DEFAULT_TYPE):
    try:
        nuevos = await asyncio.to_thread(cava.revisar_videos)
    except Exception as exc:
        log.info("No pude revisar YouTube: %s", exc)
        return
    for titulo, url in nuevos:
        await context.bot.send_message(USER_ID, "📺 <b>Nuevo video de " + escape(cava.ajustes()["canal_youtube"]) +
                                       "</b>\n<a href=\"" + escape(url) + "\">" + escape(titulo) + "</a>\n\n"
                                       "Cuando lo vea, mándeme lo importante con «nota cava: …».", parse_mode="HTML")


async def vigilar_trades(context: ContextTypes.DEFAULT_TYPE):
    try:
        mensajes = await asyncio.to_thread(cava.revisar_trades)
    except Exception as exc:
        log.info("No pude revisar los trades: %s", exc)
        return
    for m in mensajes:
        await context.bot.send_message(USER_ID, m)


async def cmd_pablogil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = await asyncio.to_thread(cava.texto_busqueda, " ".join(context.args or []), "pablo")
    await update.message.reply_text(texto)


def _texto_newsletter(autor, asunto, resumen, nota_id, enlace):
    cuerpo = escape(resumen[:2500]) if resumen else "(No traía texto para resumir.)"
    return ("📰 <b>Nuevo newsletter de " + escape(autor) + "</b>\n«" + escape(asunto) + "»\n\n" + cuerpo +
            ("\n\nGuardado en su cuaderno (#" + str(nota_id) + "). " if nota_id else "\n\n") +
            "<a href=\"" + escape(enlace) + "\">Abrir en Gmail</a>")


async def revisar_newsletters(context, manual=False):
    from modulos.finanzas import correos
    try:
        nuevos, primera = await asyncio.to_thread(newsletter.revisar)
    except correos.SinPermiso:
        return "Gmail pide volver a autorizar: ejecute modulos\\finanzas\\conectar_gmail.py en la PC."
    except Exception as exc:
        log.info("No pude revisar los newsletters: %s", exc)
        return "No pude revisar el correo ahora: " + str(exc)[:150]
    if primera and nuevos:
        lista = "\n".join("• " + escape(a) + " (#" + str(n) + ")" for _, a, _, n, _ in nuevos)
        await context.bot.send_message(USER_ID, "📰 <b>Conecté los newsletters de Pablo Gil</b>\nGuardé los "
                                       + str(len(nuevos)) + " más recientes en su cuaderno:\n" + lista +
                                       "\n\nDesde ahora le aviso de cada uno nuevo. Véalos con /pablogil.",
                                       parse_mode="HTML")
    else:
        for datos in nuevos:
            await context.bot.send_message(USER_ID, _texto_newsletter(*datos), parse_mode="HTML",
                                           disable_web_page_preview=True)
    if manual and not nuevos:
        return "Revisado: no hay newsletters nuevos, señor."
    return None


async def vigilar_newsletters(context: ContextTypes.DEFAULT_TYPE):
    await revisar_newsletters(context)


async def cmd_newsletter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Revisando su correo… (resumir puede tardar un poco)")
    texto = await revisar_newsletters(context, manual=True)
    if texto:
        await update.message.reply_text(texto)


def registrar(app):
    solo = filters.User(user_id=USER_ID)
    app.add_handler(CommandHandler("cava", cmd_cava, filters=solo))
    app.add_handler(CommandHandler("cavaresumen", cmd_cavaresumen, filters=solo))
    app.add_handler(CommandHandler("cavavideos", cmd_cavavideos, filters=solo))
    app.add_handler(CommandHandler("trade", cmd_trade, filters=solo))
    app.add_handler(CommandHandler("practica", cmd_practica, filters=solo))
    app.add_handler(CommandHandler("pablogil", cmd_pablogil, filters=solo))
    app.add_handler(CommandHandler("newsletter", cmd_newsletter, filters=solo))
    app.add_handler(MessageHandler(solo & filters.Document.MimeType("text/plain") &
                                   filters.CaptionRegex(r"(?i)[ck]a[vb]a"), documento_txt))
    telegram_aprendizaje.registrar(app)               # lector de transcripciones (videos de Cava, Pepe…)


def programar(job_queue):
    job_queue.run_repeating(vigilar_videos, interval=3600, first=120, name="cava_videos")
    job_queue.run_repeating(vigilar_trades, interval=900, first=90, name="cava_trades")
    job_queue.run_repeating(vigilar_newsletters, interval=1200, first=180, name="newsletters")
    telegram_aprendizaje.programar(job_queue)
