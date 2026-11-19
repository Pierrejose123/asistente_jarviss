"""Telegram del equipo de agentes.

/equipo [pedido]  sin texto: trabajos recientes; con texto: le encarga el trabajo al equipo.
Los pedidos por frase («equipo: …», «que el equipo …») llegan desde cerebro.responder → lanzar().
Avisa el avance en UN mensaje que se va editando, al final manda el resumen + el .md, y las tareas propuestas
con botones ✅/❌ (nada se agenda sin su visto). Revisa trabajos programados cada 10 minutos.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters  # noqa: E402

from modulos.comun.base import USER_ID, registro  # noqa: E402
from modulos.equipo import equipo  # noqa: E402

log = registro("equipo")
COMANDOS = [("equipo", "Equipo de agentes: /equipo <pedido>")]
_APP = {}


def _lock():
    try:
        from modulos.aprendizaje import telegram_aprendizaje
        return telegram_aprendizaje.OCUPADO
    except Exception:
        return None


def _cortar(t, n=4000):
    return t if len(t) <= n else t[:n - 10].rsplit("\n", 1)[0] + "\n…"


def lanzar(pedido, chat_id=USER_ID):
    """Desde cerebro.responder (otro hilo). pedido = {'tarea': id}. Devuelve el texto inicial."""
    app, bucle = _APP.get("app"), _APP.get("bucle")
    if not app or not bucle:
        return "El equipo todavía está arrancando; pruebe en un minuto (el pedido quedó guardado como #" + \
            str(pedido["tarea"]) + ")."
    asyncio.run_coroutine_threadsafe(trabajar(app.bot, pedido["tarea"], chat_id), bucle)
    return ("🤖 Encargado al equipo (trabajo #" + str(pedido["tarea"]) + "). El CEO arma el plan y los agentes se "
            "ponen a trabajar; le voy contando aquí. Con la IA local tarda unos 5–15 minutos.")


async def _guardar_bucle(context: ContextTypes.DEFAULT_TYPE):
    _APP["bucle"] = asyncio.get_running_loop()


async def trabajar(bot, tid, chat_id=USER_ID):
    cola = _APP.setdefault("cola", asyncio.Lock())       # un trabajo del equipo a la vez
    async with cola:
        bucle = asyncio.get_running_loop()
        estado = {"lineas": [], "msg": None}
        estado["msg"] = await bot.send_message(chat_id, "🤖 Trabajo #" + str(tid) + " en marcha…")

        async def _editar():
            try:
                await estado["msg"].edit_text(_cortar("🤖 Trabajo #" + str(tid) + "\n" + "\n".join(estado["lineas"][-12:])))
            except Exception:
                pass

        def aviso(texto):                                 # se llama desde el hilo de trabajo
            estado["lineas"].append(texto)
            asyncio.run_coroutine_threadsafe(_editar(), bucle)

        candado = _lock()
        try:
            if candado is not None:
                for _ in range(180):
                    if candado.acquire(blocking=False):
                        break
                    await asyncio.sleep(5)
                else:
                    raise RuntimeError("la IA estuvo ocupada demasiado tiempo")
            try:
                t = await asyncio.to_thread(equipo.ejecutar, tid, aviso)
            finally:
                if candado is not None:
                    candado.release()
        except Exception as exc:
            await bot.send_message(chat_id, "⚠️ El equipo no pudo terminar el trabajo #" + str(tid) + " ("
                                   + str(exc)[:120] + "). Pídamelo de nuevo cuando quiera.")
            return
        await entregar(bot, t, chat_id)


def resumen_corto(t):
    """Una línea con el objetivo + las secciones del documento (sin el texto completo)."""
    import json
    try:
        plan = json.loads(t.get("plan") or "{}")
        objetivo = plan.get("titulo") or plan.get("objetivo") or t["pedido"]
    except Exception:
        objetivo = t["pedido"]
    resultado = (t.get("resultado") or "").split("\n## Fuentes")[0]
    secciones = [x.strip("# ").strip() for x in resultado.splitlines() if x.startswith("## ")][:8]
    fuentes = (t.get("resultado") or "").split("\n## Fuentes")[-1].count("\n[") if "## Fuentes" in (t.get("resultado") or "") else 0
    return ("✅ Trabajo #" + str(t["id"]) + " listo: " + objetivo[:200]
            + ("\nIncluye: " + " · ".join(secciones) if secciones else "")
            + ("\n📚 " + str(fuentes) + " fuentes" if fuentes else ""))


async def entregar(bot, t, chat_id=USER_ID):
    """Manda SOLO el documento con un resumen corto; el texto completo va por mensaje solo si no hay archivo."""
    resumen = resumen_corto(t)
    if t.get("archivo") and Path(t["archivo"]).exists():
        try:
            with open(t["archivo"], "rb") as f:
                await bot.send_document(chat_id, f, filename=Path(t["archivo"]).name, caption=_cortar(resumen, 1000))
            enviado = True
        except Exception as exc:
            log.info("No pude mandar el archivo: %s", exc)
            enviado = False
    else:
        enviado = False
    if not enviado:
        cuerpo = (t.get("resultado") or "").split("\n## Fuentes")[0]
        await bot.send_message(chat_id, _cortar(resumen + "\n\n" + cuerpo, 3900), disable_web_page_preview=True)
    for p in t.get("pendientes") or []:
        botones = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Agendar", callback_data="eq:ok:" + str(p["id"])),
                                         InlineKeyboardButton("❌ No", callback_data="eq:no:" + str(p["id"]))]])
        await bot.send_message(chat_id, "🗓️ El organizador propone: " + p["texto"] + "\n(para el " + p["fecha"] + ")",
                               reply_markup=botones)


async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, que, aid = q.data.split(":")
    await q.edit_message_text(await asyncio.to_thread(equipo.aprobar, int(aid), que == "ok"))


async def cmd_equipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pedido = " ".join(context.args or []).strip()
    if len(pedido) >= 8:
        tid = await asyncio.to_thread(equipo.crear, pedido)
        await update.message.reply_text(lanzar({"tarea": tid}, update.effective_chat.id))
        return
    await update.message.reply_text(equipo.procesar("estado del equipo") + "\n\nPara encargar algo: «equipo: …» o "
                                    "/equipo <pedido>.")


async def revisar_programadas(context: ContextTypes.DEFAULT_TYPE):
    try:
        for p in await asyncio.to_thread(equipo.toca_programadas):
            tid = await asyncio.to_thread(equipo.crear, p["pedido"], "programado")
            context.application.create_task(trabajar(context.bot, tid))
    except Exception as exc:
        log.info("Programadas del equipo: %s", exc)


async def fallos_semana(context: ContextTypes.DEFAULT_TYPE):
    from modulos.comun.base import ahora
    if ahora().weekday() != 6:
        return
    if equipo.fallos(7):
        await context.bot.send_message(USER_ID, _cortar(equipo.texto_fallos(7)))


def registrar(app):
    app.add_handler(CommandHandler("equipo", cmd_equipo, filters=filters.User(USER_ID)))
    app.add_handler(CallbackQueryHandler(boton, pattern=r"^eq:(?:ok|no):\d+$"))
    _APP["app"] = app


def programar(job_queue):
    from datetime import time as hora
    from modulos.comun.base import ZONA
    job_queue.run_once(_guardar_bucle, when=1, name="equipo_bucle")
    job_queue.run_repeating(revisar_programadas, interval=600, first=120, name="equipo_programadas")
    job_queue.run_daily(fallos_semana, time=hora(19, 20, tzinfo=ZONA), name="equipo_fallos")
