"""Telegram de las tarjetas de estudio (se registra desde telegram_moodle; no hace falta tocar bot.py).

/tarjetas clase 5        propone tarjetas de ese documento o tema (✅/❌)
/tarjetas                cuántas tiene por materia
/repaso estudio          repasa las de estudio (/repaso animación: solo esa materia); /repaso solo = inglés
/borrartarjeta 7         quita una tarjeta
Aviso: al empezar su primer bloque de «Estudio» del día, si hay tarjetas para repasar.
"""
import asyncio
from datetime import datetime
from html import escape

from telegram import InlineKeyboardButton as Boton, InlineKeyboardMarkup as Teclado, Update
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes

from modulos.comun import db
from modulos.comun.base import USER_ID, ZONA, ahora, registro
from modulos.estudio import tarjetas

log = registro("tarjetas")


def _teclado(filas):
    return Teclado([[Boton(b["text"], callback_data=b["callback_data"]) for b in f] for f in filas]) if filas else None


def _dias(n):
    return "mañana" if n == 1 else "en " + str(n) + " días"


def _respuesta(t):
    return ("📝 <b>" + escape(t["pregunta"]) + "</b>\n\n✅ " + escape(t["respuesta"])
            + ("\n<i>📄 " + escape(t["fuente"]) + "</i>" if t["fuente"] else ""))


# ------------------------------------------------------------------ crear ---
async def cmd_tarjetas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pedido = " ".join(context.args).strip()
    if not pedido:
        await update.message.reply_text(await asyncio.to_thread(tarjetas.estado_texto))
        return
    await update.message.reply_text("Leyendo el material para preparar las tarjetas… (unos segundos)")
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    from modulos.biblioteca import biblioteca
    try:
        que, materia, filas = await asyncio.to_thread(tarjetas.crear_desde, pedido)
    except tarjetas.SinMaterial as exc:
        await update.message.reply_text(str(exc) + "\nGuarde el PDF o PowerPoint en «Informacion IA\\Moodle\\<Materia>» "
                                        "(o vea qué tiene con /biblioteca).")
        return
    except biblioteca.Pausa as exc:
        await update.message.reply_text("Ahora no puedo preparar tarjetas (" + str(exc) + "). Pídamelas al cerrar el juego.")
        return
    except Exception as exc:
        log.warning("No pude crear tarjetas: %s", exc)
        await update.message.reply_text("No pude preparar las tarjetas: " + str(exc)[:120])
        return
    if not filas:
        await update.message.reply_text("Leí " + que + " pero no saqué tarjetas nuevas (quizá ya las tiene).")
        return
    await update.message.reply_html(tarjetas.texto_propuesta(que, filas),
                                    reply_markup=_teclado(tarjetas.botones_propuesta(filas)))


async def cmd_borrartarjeta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    num = context.args[0].lstrip("#") if context.args else ""
    t = tarjetas.obtener(int(num)) if num.isdigit() else None
    if not t or t["estado"] == "borrada":
        await update.message.reply_text("Indíqueme el número: /borrartarjeta 7 (sale al repasar).")
        return
    await update.message.reply_html("¿Quito esta tarjeta?\n\n" + _respuesta(t), reply_markup=Teclado(
        [[Boton("Sí, quitar", callback_data="tje:del:" + str(t["id"])), Boton("No", callback_data="tje:nada:0")]]))


# ------------------------------------------------------------------ repaso ---
async def repaso(context, chat_id, texto=""):
    """Empieza el repaso de estudio. texto: '' / 'estudio' = todas, o el nombre de una materia."""
    materia = tarjetas.materia_de_texto(texto)
    if materia is None:
        await context.bot.send_message(chat_id, "No tengo tarjetas de «" + texto + "». Materias con tarjetas: "
                                       + (", ".join(tarjetas.materias()) or "ninguna todavía") + ".")
        return
    lista = await asyncio.to_thread(tarjetas.para_repasar, materia)
    if not lista:
        await context.bot.send_message(chat_id, "No hay tarjetas de estudio para hoy" + (" de " + materia if materia else "")
                                       + ", señor. 👍\n" + (await asyncio.to_thread(tarjetas.estado_texto)))
        return
    context.bot_data["est"] = {"cola": [t["id"] for t in lista], "pos": 0, "otra_vez": {}}
    await _siguiente(context, chat_id)


async def _siguiente(context, chat_id):
    s = context.bot_data.get("est")
    if not s or not s["cola"]:
        context.bot_data.pop("est", None)
        r = tarjetas.resumen_hoy()
        detalle = ", ".join(tarjetas.NOTAS[k] + " " + str(v) for k, v in sorted(r.items()))
        await context.bot.send_message(chat_id, "✅ Repaso de estudio terminado.\n• Hoy: " + str(sum(r.values()))
                                       + " repasos (" + detalle + ")\n\n" + tarjetas.estado_texto())
        return
    tid = s["cola"][0]
    t = tarjetas.obtener(tid)
    s["pos"] += 1
    await context.bot.send_message(
        chat_id, "📝 <b>" + escape(t["pregunta"]) + "</b>\n<i>" + escape(t["materia"]) + " · " + str(s["pos"]) + " de "
        + str(s["pos"] + len(s["cola"]) - 1) + "</i>\n\nPiense la respuesta y tóquela para ver si acertó.",
        parse_mode="HTML", reply_markup=Teclado([[Boton("👁 Ver respuesta", callback_data="tje:ver:" + str(tid))]]))


# ------------------------------------------------------------------ botones ---
async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q.from_user or q.from_user.id != USER_ID:
        raise ApplicationHandlerStop
    await q.answer()
    partes = q.data.split(":")
    accion = partes[1]
    num = int(partes[2]) if len(partes) > 2 and partes[2].isdigit() else 0
    chat = q.message.chat_id
    try:
        if accion in ("si", "no"):
            t = tarjetas.obtener(num)
            if t and t["estado"] == "propuesta":
                tarjetas.cambiar(num, "activa" if accion == "si" else "descartada")
            await _actualizar_propuesta(q, context, t["lote"] if t else 0)
        elif accion in ("todas", "ninguna"):
            for t in tarjetas.del_lote(num):
                tarjetas.cambiar(t["id"], "activa" if accion == "todas" else "descartada")
            await _actualizar_propuesta(q, context, num)
        elif accion == "empezar":
            await q.edit_message_reply_markup(None)
            await repaso(context, chat)
        elif accion == "ver":
            t = tarjetas.obtener(num)
            await q.edit_message_text(_respuesta(t), parse_mode="HTML", reply_markup=Teclado([[
                Boton(tarjetas.NOTAS[n], callback_data="tje:n:" + str(num) + ":" + str(n)) for n in (1, 2, 3, 4)]]))
        elif accion == "n":
            s = context.bot_data.get("est")
            if not s or not s["cola"] or s["cola"][0] != num:
                await q.edit_message_reply_markup(None)          # botón de un repaso anterior
                raise ApplicationHandlerStop
            nota = int(partes[3])
            dias = await asyncio.to_thread(tarjetas.calificar, num, nota)
            s["cola"].pop(0)
            if nota == 1 and s["otra_vez"].get(num, 0) < 2:
                s["otra_vez"][num] = s["otra_vez"].get(num, 0) + 1
                s["cola"].append(num)
            await q.edit_message_text(_respuesta(tarjetas.obtener(num)) + "\n\n→ " + tarjetas.NOTAS[nota]
                                      + " · vuelve " + _dias(dias) + "  <i>#" + str(num) + "</i>", parse_mode="HTML")
            await _siguiente(context, chat)
        elif accion == "del":
            tarjetas.cambiar(num, "borrada")
            await q.edit_message_text("🗑 Tarjeta #" + str(num) + " quitada.")
        else:
            await q.edit_message_text("Cancelado.")
    except ApplicationHandlerStop:
        raise
    except Exception as exc:
        log.warning("Botón de tarjetas: %s", exc)
    raise ApplicationHandlerStop                                   # que no lo procese otro manejador


async def _actualizar_propuesta(q, context, lote):
    quedan = tarjetas.del_lote(lote)
    if quedan:
        filas = tarjetas.botones_propuesta(quedan)
        await q.edit_message_reply_markup(_teclado(filas))
        return
    await q.edit_message_reply_markup(None)
    activas = len(tarjetas.del_lote(lote, "activa"))
    await context.bot.send_message(q.message.chat_id, ("Listo: " + str(activas) + " tarjeta(s) al mazo de estudio. "
                                                       "Repáselas con /repaso estudio.") if activas else
                                   "Listo, no guardé ninguna.")


# ------------------------------------------------------------------ aviso en el bloque de estudio ---
async def revisar_aviso(context: ContextTypes.DEFAULT_TYPE):
    if not tarjetas.ajustes().get("aviso_en_bloque_de_estudio", True):
        return
    f = ahora()
    dia = f.date().isoformat()
    if db.aviso_enviado(dia + "|tarjetas_estudio") or f.hour >= 23:
        return
    try:
        from modulos.agenda import eventos
        bloques = [e for e in eventos.del_dia(f) if "estudio" in e["titulo"].lower()]
    except Exception as exc:
        log.info("No pude ver la agenda para las tarjetas: %s", exc)
        return
    if not bloques:
        return
    inicio = min(datetime.combine(f.date(), datetime.strptime(b["inicio"], "%H:%M").time(), tzinfo=ZONA) for b in bloques)
    if f < inicio:
        return
    db.marcar_aviso(dia + "|tarjetas_estudio")
    n = len(await asyncio.to_thread(tarjetas.para_repasar))
    if not n:
        return
    await context.bot.send_message(USER_ID, "📝 Empieza su bloque de estudio: tiene <b>" + str(n) + "</b> tarjetas para "
                                   "repasar (unos " + str(max(2, n // 2)) + " min).", parse_mode="HTML",
                                   reply_markup=Teclado([[Boton("▶️ Repasar", callback_data="tje:empezar:0")]]))


COMANDOS = [("tarjetas", "Tarjetas de estudio: /tarjetas clase 5"),
            ("borrartarjeta", "Quitar una tarjeta de estudio: /borrartarjeta 7")]


def registrar(app):
    from telegram.ext import filters
    solo = filters.User(user_id=USER_ID)
    app.add_handler(CommandHandler("tarjetas", cmd_tarjetas, filters=solo))
    app.add_handler(CommandHandler("borrartarjeta", cmd_borrartarjeta, filters=solo))
    app.add_handler(CallbackQueryHandler(boton, pattern=r"^tje:"), group=-2)     # antes que el manejador general


def programar(job_queue):
    job_queue.run_repeating(revisar_aviso, interval=300, first=120, name="tarjetas_estudio")
