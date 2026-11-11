"""Telegram de la biblioteca personal (se registra desde telegram_aprendizaje; no hace falta tocar bot.py).

Comandos: /biblioteca (estado), /preguntar <pregunta>, /buscar <palabras>, /resumir <nombre del archivo>.
Frases (también por nota de voz y "hey Jarvis"): «según mis videos, …», «resúmeme el video de …»,
«¿qué sé sobre …?» — las resuelve biblioteca.procesar() desde el cerebro.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import Update  # noqa: E402
from telegram.ext import CommandHandler, ContextTypes, filters  # noqa: E402

from modulos.biblioteca import biblioteca  # noqa: E402
from modulos.comun.base import USER_ID, registro  # noqa: E402

log = registro("biblioteca")
COMANDOS = [("biblioteca", "Su biblioteca: archivos leídos y en cola"),
            ("preguntar", "Preguntar a su biblioteca: /preguntar qué es el PER"),
            ("buscar", "Buscar en sus archivos: /buscar iluminación"),
            ("resumir", "Resumen de un archivo: /resumir masterclass")]


def _silencioso(ruta):
    """Lo que llegó en la primera descarga de Moodle se lee sin avisar uno por uno."""
    try:
        from modulos.estudio import moodle_materiales
        return moodle_materiales.silencioso(ruta)
    except Exception:
        return False


def _cortar(texto):
    return texto if len(texto) <= 4000 else texto[:3990].rsplit("\n", 1)[0] + "\n…"


async def vuelta(context: ContextTypes.DEFAULT_TYPE):
    """Cada 5 min: indexa lo nuevo (segundos) y, si la IA está libre, resume UN documento."""
    from modulos.aprendizaje import telegram_aprendizaje
    try:
        await asyncio.to_thread(biblioteca.actualizar)
    except FileNotFoundError:
        return
    except Exception as exc:
        log.info("No pude revisar la biblioteca: %s", exc)
        return
    if not telegram_aprendizaje.OCUPADO.acquire(blocking=False):     # una sola lectura con IA a la vez
        return
    loop = asyncio.get_running_loop()

    def aviso_inicio(doc, n):
        if _silencioso(doc["ruta"]):
            return
        asyncio.run_coroutine_threadsafe(context.bot.send_message(
            USER_ID, "📖 Leyendo «" + doc["titulo"] + "» (" + str(n) + " partes). Le aviso al terminar."), loop)

    try:
        res = await asyncio.to_thread(biblioteca.leer_siguiente, aviso_inicio)
        if res and not res["silencioso"] and not _silencioso(res["doc"]["ruta"]):
            await context.bot.send_message(USER_ID, _cortar(biblioteca.texto_resultado(res)))
    except biblioteca.Pausa as exc:
        log.info("Biblioteca en pausa: %s", exc)
    except Exception as exc:
        log.warning("Falló la lectura de la biblioteca: %s", exc)
    finally:
        telegram_aprendizaje.OCUPADO.release()


async def cmd_biblioteca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.to_thread(biblioteca.actualizar)
    except Exception as exc:
        log.info("No pude revisar la carpeta: %s", exc)
    await update.message.reply_text(_cortar(await asyncio.to_thread(biblioteca.estado)))


async def cmd_preguntar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Escriba la pregunta: /preguntar cómo valorar una empresa")
        return
    await update.message.chat.send_action("typing")
    texto = await asyncio.to_thread(biblioteca.responder, " ".join(context.args))
    await update.message.reply_text(_cortar(texto))


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Escriba qué buscar: /buscar ventaja competitiva")
        return
    resultados = await asyncio.to_thread(biblioteca.buscar, " ".join(context.args), 8)
    if not resultados:
        await update.message.reply_text("No encontré nada sobre eso en su biblioteca.")
        return
    lineas = ["🔎 Encontré:"] + ["• " + biblioteca.fuente_txt(r) + "\n   " + biblioteca._corto(r["texto"], 180)
                                 for r in resultados]
    await update.message.reply_text(_cortar("\n".join(lineas)))


async def cmd_resumir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = " ".join(context.args) if context.args else "último"
    doc = await asyncio.to_thread(biblioteca.buscar_documento, nombre)
    await update.message.reply_text(_cortar(biblioteca.texto_resumen(doc)))


def registrar(app):
    solo = filters.User(user_id=USER_ID)
    app.add_handler(CommandHandler("biblioteca", cmd_biblioteca, filters=solo))
    app.add_handler(CommandHandler("preguntar", cmd_preguntar, filters=solo))
    app.add_handler(CommandHandler("buscar", cmd_buscar, filters=solo))
    app.add_handler(CommandHandler("resumir", cmd_resumir, filters=solo))


def programar(job_queue):
    job_queue.run_repeating(vuelta, interval=300, first=260, name="biblioteca")
