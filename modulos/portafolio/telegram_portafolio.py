"""Portafolio en Telegram: /portafolio (solo porcentajes) y recogida automatica de informes de XTB.

Cuando exporta un informe en xStation 5, el Excel queda en Descargas con un nombre como
USD_12345678_2006-01-01_2026-10-29.xlsx. El bot lo detecta (cada 2 min), lo mueve a la carpeta
privada (rutas.json → pesado\\xtb) y le avisa. Nunca envia el archivo ni montos por Telegram.
"""
import asyncio

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from modulos.comun.base import USER_ID, registro
from modulos.portafolio import portafolio

log = registro("portafolio")

COMANDOS = [("portafolio", "Mi portafolio de XTB (en porcentajes)"),
            ("acciones", "Qué acciones tengo (informe de XTB + lo que me contó)")]


async def cmd_portafolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        r = await asyncio.to_thread(portafolio.calcular, None, not (context.args and context.args[0] == "ya"))
    except FileNotFoundError:
        await update.message.reply_text("No tengo ning\u00fan informe de XTB todav\u00eda. Exp\u00f3rtelo en xStation 5 "
                                        "(Historial \u2192 Exportar) y lo recojo solo de Descargas.")
        return
    except Exception as exc:
        log.warning("Error al calcular el portafolio: %s", exc)
        await update.message.reply_text("No pude calcular el portafolio ahora: " + str(exc)[:120])
        return
    await update.message.reply_html(portafolio.texto_telegram(r))


async def vigilar_informes(context: ContextTypes.DEFAULT_TYPE):
    try:
        nuevo = await asyncio.to_thread(portafolio.recoger_informes)
    except Exception as exc:
        log.warning("No pude revisar Descargas: %s", exc)
        return
    if nuevo:
        texto = ("\U0001F4E5 Recib\u00ed su informe nuevo de XTB y lo guard\u00e9 en la carpeta privada de la PC. "
                 "Escriba /portafolio para verlo.")
        try:
            from modulos.portafolio import cambios
            n = await asyncio.to_thread(cambios.conciliar_con_ultimo)
            if n:
                texto += ("\n\u270D\uFE0F " + str(n) + (" cambio que me cont\u00f3 ya viene" if n == 1 else
                                                     " cambios que me cont\u00f3 ya vienen") + " en el informe: ahora manda el informe.")
        except Exception as exc:
            log.info("No pude conciliar los cambios: %s", exc)
        await context.bot.send_message(USER_ID, texto)


async def cmd_acciones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from modulos.portafolio import cambios
    texto = await asyncio.to_thread(cambios.texto_lista)
    texto += ("\n\nPara contarme un cambio, escr\u00edbalo normal: \u00abcompr\u00e9 Nvidia\u00bb, \u00abvend\u00ed la mitad de "
              "Amazon\u00bb, \u00abya no tengo Visa\u00bb. Si me equivoco: \u00abdeshaz lo \u00faltimo\u00bb.")
    await update.message.reply_text(texto)


def registrar(app):
    from telegram.ext import filters
    app.add_handler(CommandHandler("portafolio", cmd_portafolio, filters=filters.User(user_id=USER_ID)))
    app.add_handler(CommandHandler("acciones", cmd_acciones, filters=filters.User(user_id=USER_ID)))


def programar(job_queue):
    job_queue.run_repeating(vigilar_informes, interval=120, first=60, name="xtb_informes")
