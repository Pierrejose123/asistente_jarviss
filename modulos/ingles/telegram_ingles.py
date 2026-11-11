"""Comandos y botones de ingles en Telegram (Fase 2, punto 5, paso 1).

/repaso                  repasa las tarjetas que tocan hoy (botones Otra vez / Dificil / Bien / Facil)
/repaso estudio          repasa las tarjetas de ESTUDIO (/repaso animacion: solo esa materia; ver telegram_tarjetas)
/palabra deadline        agrega una palabra (la IA pone significado y ejemplo)
/palabra come up with = ocurrirsele   agrega o corrige con su propio significado
/palabras                cuantas tiene, cuantas domina y las ultimas agregadas
/proponer                el asistente propone palabras nuevas ahora
/borrarpalabra 12        quita una tarjeta (con confirmacion)
/ingles [tema]           practica conversando en ingles (todo lo que escriba va al profesor)
/fin                     termina la practica y envia las correcciones

Aviso automatico: al empezar el bloque de ingles de la agenda (o a la hora de respaldo si ese dia
no hay bloque) llega el repaso y las palabras propuestas del dia.
"""
import asyncio
from datetime import datetime, timedelta
from html import escape

from telegram import InlineKeyboardButton as Boton, InlineKeyboardMarkup as Teclado, Update
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler

from modulos.comun import db
from modulos.comun.base import USER_ID, ZONA, ahora, registro
from modulos.ingles import conversacion, vocab

log = registro("ingles")

COMANDOS = [
    ("repaso", "Repasar inglés (/repaso estudio: tarjetas de clase)"),
    ("palabra", "Agregar palabra: /palabra deadline"),
    ("palabras", "Mis tarjetas de inglés"),
    ("proponer", "Que el asistente proponga palabras"),
    ("borrarpalabra", "Quitar una tarjeta: /borrarpalabra 12"),
    ("ingles", "Practicar conversando en ingl\u00e9s: /ingles [tema]"),
    ("fin", "Terminar la pr\u00e1ctica de ingl\u00e9s y ver correcciones"),
]


# ------------------------------------------------------------------ tarjeta en pantalla ---
def _frente(t, pos, total):
    return "\U0001F1EC\U0001F1E7 <b>" + escape(t["frente"]) + "</b>\n<i>(" + str(pos) + " de " + str(total) + ")</i>"


def _respuesta(t):
    sig = escape(t["significado"]) if t["significado"] else "<i>(sin significado: /palabra " + escape(t["frente"]) + " = ...)</i>"
    texto = "\U0001F1EC\U0001F1E7 <b>" + escape(t["frente"]) + "</b>\n\U0001F1EA\U0001F1F8 " + sig
    if t["ejemplo"]:
        texto += "\n\U0001F4AC <i>" + escape(t["ejemplo"]) + "</i>"
    return texto


def _dias(n):
    return "mañana" if n == 1 else "en " + str(n) + " días"


async def _siguiente(context, chat_id):
    s = context.bot_data.get("voc")
    if not s or not s["cola"]:
        await _fin(context, chat_id)
        return
    tid = s["cola"][0]
    t = vocab.obtener(tid)
    s["pos"] += 1
    await context.bot.send_message(chat_id, _frente(t, s["pos"], s["pos"] + len(s["cola"]) - 1), parse_mode="HTML",
                                   reply_markup=Teclado([[Boton("\U0001F441 Ver respuesta", callback_data="voc:ver:" + str(tid))]]))


async def _fin(context, chat_id):
    context.bot_data.pop("voc", None)
    r = vocab.resumen_hoy()
    hechas = sum(r.values())
    if not hechas:
        await context.bot.send_message(chat_id, "No hay tarjetas para hoy, señor. Agregue palabras con /palabra o pida /proponer.")
        return
    detalle = ", ".join(vocab.NOTAS[k] + " " + str(v) for k, v in sorted(r.items()))
    e = vocab.estadisticas()
    await context.bot.send_message(chat_id, "✅ Repaso terminado, señor.\n\n• Hoy: " + str(hechas) + " repasos ("
                                   + detalle + ")\n• Tarjetas activas: " + str(e["total"]) + " (dominadas: "
                                   + str(e["aprendidas"]) + ")\n• Sin estrenar: " + str(e["sin_ver"]))


async def empezar_repaso(context, chat_id):
    tarjetas = await asyncio.to_thread(vocab.para_repasar)
    if not tarjetas:
        await _fin(context, chat_id)
        return
    context.bot_data["voc"] = {"cola": [t["id"] for t in tarjetas], "pos": 0, "otra_vez": {}}
    await _siguiente(context, chat_id)


# ------------------------------------------------------------------ propuestas ---
def _texto_propuestas(lista):
    lineas = ["\U0001F4A1 <b>Palabras propuestas para hoy</b>", "Toque ✅ para aprenderla o ❌ si ya la sabe.\n"]
    for t in lista:
        lineas.append("• <b>" + escape(t["frente"]) + "</b> – " + escape(t["significado"]))
        if t["ejemplo"]:
            lineas.append("   <i>" + escape(t["ejemplo"]) + "</i>")
    return "\n".join(lineas)


def _teclado_propuestas(lista):
    return Teclado([[Boton("✅ " + t["frente"], callback_data="voc:si:" + str(t["id"])),
                     Boton("❌", callback_data="voc:no:" + str(t["id"]))] for t in lista]) if lista else None


async def enviar_propuestas(context, chat_id, generar=True):
    """Envia las propuestas pendientes; si no hay, pide nuevas a la IA. Devuelve True si se enviaron."""
    lista = await asyncio.to_thread(vocab.propuestas_pendientes)
    if not lista and generar:
        try:
            await asyncio.to_thread(vocab.proponer)
        except Exception as exc:
            log.info("No pude proponer palabras ahora: %s", exc)
            return False
        lista = await asyncio.to_thread(vocab.propuestas_pendientes)
    if not lista:
        return False
    await context.bot.send_message(chat_id, _texto_propuestas(lista), parse_mode="HTML",
                                   reply_markup=_teclado_propuestas(lista))
    return True


# ------------------------------------------------------------------ comandos ---
async def cmd_repaso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].lower() not in ("ingles", "inglés", "english"):
        from modulos.estudio import telegram_tarjetas          # mazo de estudio, aparte del de inglés
        await telegram_tarjetas.repaso(context, update.effective_chat.id, " ".join(context.args))
        return
    await empezar_repaso(context, update.effective_chat.id)


async def cmd_palabra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = " ".join(context.args).strip()
    if not texto:
        await update.message.reply_html("Ejemplos:\n/palabra deadline\n/palabra come up with = ocurrírsele\n\n"
                                        "Con <b>=</b> pone usted el significado; sin él lo pongo yo con un ejemplo.")
        return
    frente, _, significado = (x.strip() for x in texto.partition("="))
    existente = await asyncio.to_thread(vocab.buscar, frente)
    if existente and not significado:
        await update.message.reply_html("Ya la tiene (#" + str(existente["id"]) + "):\n\n" + _respuesta(existente)
                                        + "\n\nPara corregir el significado: /palabra " + escape(existente["frente"]) + " = ...")
        return
    if existente:
        vocab.actualizar(existente["id"], significado=significado, estado="activa")
        await update.message.reply_html("✏️ Corregida:\n\n" + _respuesta(vocab.obtener(existente["id"])))
        return
    ejemplo = ""
    if not significado:
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        try:
            frente, significado, ejemplo = await asyncio.to_thread(vocab.completar, frente)
        except Exception as exc:
            log.info("No pude completar '%s': %s", frente, exc)
            await update.message.reply_text("Ahora no puedo buscar el significado (¿modo juego/diseño?). "
                                            "Escríbala así: /palabra " + frente + " = significado")
            return
    tid = await asyncio.to_thread(vocab.crear, frente, significado, ejemplo)
    await update.message.reply_html("✅ Tarjeta #" + str(tid) + " agregada:\n\n" + _respuesta(vocab.obtener(tid))
                                    + "\n\nAparecerá en su próximo /repaso. Si el significado no le convence: "
                                    "/palabra " + escape(frente) + " = ...")


async def cmd_palabras(update: Update, context: ContextTypes.DEFAULT_TYPE):
    e = await asyncio.to_thread(vocab.estadisticas)
    ultimas = (await asyncio.to_thread(vocab.activas))[:12]
    texto = ("<b>Su vocabulario</b>\n• Tarjetas activas: " + str(e["total"]) + "\n• Dominadas (3+ semanas): "
             + str(e["aprendidas"]) + "\n• Sin estrenar: " + str(e["sin_ver"]) + "\n• Para repasar hoy: "
             + str(e["para_hoy"]) + "\n• Repasos esta semana: " + str(e["repasos_semana"]))
    if ultimas:
        texto += "\n\n<b>Últimas</b>\n" + "\n".join("#" + str(t["id"]) + " " + escape(t["frente"]) + " – "
                                                       + escape(t["significado"]) for t in ultimas)
    await update.message.reply_html(texto)


async def cmd_proponer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    if not await enviar_propuestas(context, update.effective_chat.id):
        await update.message.reply_text("Ahora no pude proponer palabras (¿modo juego/diseño u Ollama apagado?). "
                                        "Inténtelo más tarde, señor.")


async def cmd_borrarpalabra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    num = context.args[0].lstrip("#") if context.args else ""
    t = vocab.obtener(int(num)) if num.isdigit() else None
    if not t or t["estado"] == "borrada":
        await update.message.reply_text("Indíqueme el número de la tarjeta, por ejemplo /borrarpalabra 12 (vea /palabras).")
        return
    await update.message.reply_html("¿Quito esta tarjeta?\n\n" + _respuesta(t), reply_markup=Teclado(
        [[Boton("Sí, quitar", callback_data="voc:del:" + str(t["id"])), Boton("No", callback_data="voc:nada:0")]]))


# ------------------------------------------------------------------ conversacion ---
async def enviar_correcciones(bot, sid):
    texto, nuevas = await asyncio.to_thread(conversacion.texto_correcciones, sid)
    filas = conversacion.botones_expresiones(sid, nuevas)
    teclado = Teclado([[Boton(b["text"], callback_data=b["callback_data"]) for b in fila] for fila in filas]) if filas else None
    await bot.send_message(USER_ID, texto, parse_mode="HTML", reply_markup=teclado)


async def cmd_ingles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from modulos.comun import modos
    if modos.en_modo_ligero():
        await update.message.reply_text("En modo juego/dise\u00f1o la IA chica no sirve de profesora, se\u00f1or. "
                                        "Practiquemos cuando cierre el programa.")
        return
    previa = conversacion.abierta("telegram")
    if previa:
        await update.message.reply_text("Ya estamos practicando, sir. Siga escribiendo en ingl\u00e9s o termine con /fin.")
        return
    sid = conversacion.abrir("telegram", " ".join(context.args))
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        primera = await asyncio.to_thread(conversacion.saludo, sid)
    except Exception as exc:
        log.warning("No pude empezar la practica: %s", exc)
        await asyncio.to_thread(conversacion.cerrar, sid)
        await update.message.reply_text("No pude empezar la pr\u00e1ctica ahora (\u00bfOllama apagado?).")
        return
    await update.message.reply_html("\U0001F1EC\U0001F1E7 <b>English practice</b> \u2013 escriba en ingl\u00e9s; "
                                    "las correcciones llegan al final con /fin.\n\n" + escape(primera))


async def cmd_fin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = conversacion.abierta("telegram")
    if not s:
        await update.message.reply_text("No hay una pr\u00e1ctica abierta. Empiece una con /ingles.")
        return
    await update.message.reply_text("Great job, sir. Preparing your corrections... \u23F3")
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    await asyncio.to_thread(conversacion.cerrar, s["id"])
    await enviar_correcciones(context.bot, s["id"])


async def mensaje_en_practica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Grupo -1: si hay practica abierta, el mensaje va al profesor y no al asistente normal."""
    s = conversacion.abierta("telegram")
    if not s:
        return                                           # sigue al manejador normal (IA del asistente)
    texto = update.message.text.strip()
    if conversacion.es_fin(texto):
        await cmd_fin(update, context)
        raise ApplicationHandlerStop
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        respuesta = await asyncio.to_thread(conversacion.responder, s["id"], texto)
    except Exception as exc:
        log.warning("Error en la practica: %s", exc)
        respuesta = "Sorry, sir, I lost my train of thought. Could you say that again? (o /fin para terminar)"
    await update.message.reply_text(respuesta)
    raise ApplicationHandlerStop


async def cerrar_olvidadas(context: ContextTypes.DEFAULT_TYPE):
    """Cada minuto: cierra las practicas (Telegram o voz) sin mensajes hace 10 min y envia las correcciones."""
    for s in await asyncio.to_thread(conversacion.vencidas, 10):
        await asyncio.to_thread(conversacion.cerrar, s["id"])
        await enviar_correcciones(context.bot, s["id"])


# ------------------------------------------------------------------ botones ---
async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q.from_user or q.from_user.id != USER_ID:
        return
    await q.answer()
    partes = q.data.split(":")
    accion, tid = partes[1], int(partes[2]) if len(partes) > 2 and partes[2].isdigit() else 0
    chat = q.message.chat_id
    if accion == "empezar":
        await q.edit_message_reply_markup(None)
        await empezar_repaso(context, chat)
    elif accion == "ver":
        t = vocab.obtener(tid)
        await q.edit_message_text(_respuesta(t), parse_mode="HTML", reply_markup=Teclado([[
            Boton(vocab.NOTAS[n], callback_data="voc:n:" + str(tid) + ":" + str(n)) for n in (1, 2, 3, 4)]]))
    elif accion == "n":
        s = context.bot_data.get("voc")
        if not s or not s["cola"] or s["cola"][0] != tid:
            await q.edit_message_reply_markup(None)        # boton viejo (repaso anterior)
            return
        nota = int(partes[3])
        dias = await asyncio.to_thread(vocab.calificar, tid, nota)
        s["cola"].pop(0)
        if nota == 1 and s["otra_vez"].get(tid, 0) < 2:   # vuelve al final del repaso de hoy
            s["otra_vez"][tid] = s["otra_vez"].get(tid, 0) + 1
            s["cola"].append(tid)
        t = vocab.obtener(tid)
        await q.edit_message_text(_respuesta(t) + "\n\n→ " + vocab.NOTAS[nota] + " · vuelve " + _dias(dias),
                                  parse_mode="HTML")
        await _siguiente(context, chat)
    elif accion in ("si", "no"):
        t = vocab.obtener(tid)
        if t and t["estado"] == "propuesta":
            vocab.actualizar(tid, estado="activa" if accion == "si" else "descartada")
        quedan = vocab.propuestas_pendientes()
        if quedan:
            await q.edit_message_reply_markup(_teclado_propuestas(quedan))
        else:
            await q.edit_message_reply_markup(None)
            await context.bot.send_message(chat, "Listo, señor. Las palabras aceptadas entran en su /repaso.")
    elif accion == "exp":
        c = conversacion.correcciones(tid) or {}
        i = int(partes[3])
        x = c.get("expresiones", [])[i] if i < len(c.get("expresiones", [])) else None
        if x and not vocab.buscar(x["frente"]):
            nuevo = vocab.crear(x["frente"], x.get("significado", ""), x.get("ejemplo", ""), "asistente")
            await context.bot.send_message(chat, "\u2705 \u00ab" + x["frente"] + "\u00bb guardada como tarjeta #" + str(nuevo) + ".")
        _, nuevas = conversacion.texto_correcciones(tid)
        filas = conversacion.botones_expresiones(tid, nuevas)
        await q.edit_message_reply_markup(Teclado([[Boton(b["text"], callback_data=b["callback_data"]) for b in f]
                                                   for f in filas]) if filas else None)
    elif accion == "del":
        vocab.actualizar(tid, estado="borrada")
        await q.edit_message_text("\U0001F5D1 Tarjeta #" + str(tid) + " quitada.")
    else:
        await q.edit_message_text("Cancelado.")


# ------------------------------------------------------------------ aviso automatico ---
def momento_de_ingles(fecha=None):
    """Hora del aviso de hoy: inicio del primer bloque de ingles de la agenda, o la hora de respaldo."""
    from modulos.agenda import eventos
    fecha = fecha or ahora()
    bloques = [e for e in eventos.del_dia(fecha) if "ingl" in e["titulo"].lower()]
    hora = bloques[0]["inicio"] if bloques else vocab.ajustes()["hora_respaldo"]
    return datetime.combine(fecha.date(), datetime.strptime(hora, "%H:%M").time(), tzinfo=ZONA), bool(bloques)


async def revisar_ingles(context: ContextTypes.DEFAULT_TYPE):
    """Cada minuto: si ya es la hora de ingles, avisa una vez al dia; luego manda las propuestas."""
    try:
        momento, es_bloque = await asyncio.to_thread(momento_de_ingles)
    except Exception as exc:
        log.warning("No pude revisar la hora de ingles: %s", exc)
        return
    f = ahora()
    if f < momento or f.hour >= 23:
        return
    dia = f.date().isoformat()
    if not db.aviso_enviado(dia + "|ingles"):
        db.marcar_aviso(dia + "|ingles")
        n = len(await asyncio.to_thread(vocab.para_repasar))
        from modulos.clases import avisos
        avisos.notificar_windows("Hora de inglés", (str(n) + " tarjetas para repasar") if n else "Practique un rato")
        texto = ("\U0001F1EC\U0001F1E7 <b>Hora de inglés</b>, señor" + ("" if es_bloque else " (hoy no tiene bloque; le aviso igual)")
                 + ".\n\n" + ("Tiene <b>" + str(n) + "</b> tarjetas para repasar." if n else
                              "No tiene tarjetas pendientes. Agregue palabras con /palabra o acepte las propuestas."))
        await context.bot.send_message(USER_ID, texto, parse_mode="HTML", reply_markup=Teclado(
            [[Boton("▶️ Empezar repaso", callback_data="voc:empezar:0")]]) if n else None)
        log.info("Aviso de ingles enviado (%d tarjetas)", n)
    espera = context.bot_data.get("ingles_reintento", 0)
    if not db.aviso_enviado(dia + "|ingles_propuestas") and f.timestamp() >= espera:
        context.bot_data["ingles_reintento"] = f.timestamp() + 15 * 60      # si falla, otra vez en 15 min
        if await enviar_propuestas(context, USER_ID):
            db.marcar_aviso(dia + "|ingles_propuestas")       # si fallo (modo juego), reintenta al minuto siguiente


def registrar(app):
    """Conecta los comandos y botones de ingles al bot (llamar ANTES del manejador general de botones)."""
    from telegram.ext import filters
    solo = filters.User(user_id=USER_ID)
    for nombre, funcion in (("repaso", cmd_repaso), ("palabra", cmd_palabra), ("palabras", cmd_palabras),
                            ("proponer", cmd_proponer), ("borrarpalabra", cmd_borrarpalabra),
                            ("ingles", cmd_ingles), ("fin", cmd_fin)):
        app.add_handler(CommandHandler(nombre, funcion, filters=solo))
    app.add_handler(MessageHandler(solo & filters.TEXT & ~filters.COMMAND, mensaje_en_practica), group=-1)
    app.add_handler(CallbackQueryHandler(boton, pattern=r"^voc:"))


def programar(job_queue):
    job_queue.run_repeating(revisar_ingles, interval=60, first=40, name="ingles")
    job_queue.run_repeating(cerrar_olvidadas, interval=60, first=50, name="ingles_olvidadas")
