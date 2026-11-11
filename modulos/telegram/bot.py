"""Bot de Telegram del asistente (Fase 1, pasos 2 y 3).

Solo responde al usuario (TELEGRAM_USER_ID del .env); cualquier otra persona es ignorada
y queda registrada en logs/bot.log.

Ejecutar:  .\\.venv\\Scripts\\python.exe modulos\\telegram\\bot.py
"""
import asyncio
import sys
import time
from datetime import timedelta
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psutil  # noqa: E402
import requests  # noqa: E402
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,  # noqa: E402
                          ContextTypes, MessageHandler, filters)

from modulos.agenda import eventos  # noqa: E402
from modulos.calendario import google_cal, sync_cambios  # noqa: E402
from modulos.clases import avisos  # noqa: E402
from modulos.clases.agenda import clases_efectivas  # noqa: E402
from modulos.comun import db, modos  # noqa: E402
from modulos.habitos import habitos  # noqa: E402
from modulos.ia import cerebro  # noqa: E402
from modulos.ingles import telegram_ingles  # noqa: E402
from modulos.portafolio import telegram_portafolio  # noqa: E402
from modulos.estudio import telegram_moodle  # noqa: E402
from modulos.finanzas import telegram_finanzas  # noqa: E402
from modulos.resumen import resumen  # noqa: E402
from modulos.tareas import tareas  # noqa: E402
from modulos.telegram import notas_voz  # noqa: E402
from modulos.cava import telegram_cava  # noqa: E402
from modulos.noticias import telegram_noticias  # noqa: E402
from modulos.alertas import telegram_alertas  # noqa: E402
from modulos.comun import telegram_salud  # noqa: E402
from modulos.proactivo import telegram_proactivo  # noqa: E402
from modulos.comun.base import (DIAS, DIAS_BONITO, TOKEN, USER_ID, ZONA, ahora,  # noqa: E402
                                leer_json, registro)

log = registro("bot")
SOLO_DUENO = filters.User(user_id=USER_ID)
INICIO = time.time()
_ultimos = {}

COMANDOS = [
    ("hoy", "Tu plan de hoy"),
    ("tarea", "Anotar tarea: /tarea materia descripci\u00f3n fecha"),
    ("tareas", "Tareas pendientes"),
    ("hecho", "Marcar tarea hecha: /hecho 3"),
    ("borrar", "Borrar tarea: /borrar 3"),
    ("entreno", "Resumen de ejercicios de la semana"),
    ("resumen", "Resumen matutino ahora"),
    ("cierre", "Cierre del d\u00eda ahora"),
    ("manana", "Tu plan de ma\u00f1ana"),
    ("semana", "Clases de la semana"),
    ("avisos", "Avisos que quedan hoy"),
    ("sincronizar", "Revisar ya los cambios de Google Calendar"),
    ("probar", "Probar notificaci\u00f3n de Windows + Telegram"),
    ("estado", "Estado de la PC y del asistente"),
    ("modo", "Modo juego/diseño: qué está usando la tarjeta gráfica"),
    ("memoria", "Lo que el asistente sabe de usted"),
    ("olvidar", "Reiniciar el hilo de la conversaci\u00f3n"),
    ("ayuda", "Lista de comandos"),
]
COMANDOS[-1:-1] = telegram_alertas.COMANDOS + telegram_salud.COMANDOS + telegram_proactivo.COMANDOS + telegram_noticias.COMANDOS + telegram_cava.COMANDOS + telegram_finanzas.COMANDOS + telegram_moodle.COMANDOS + telegram_ingles.COMANDOS + telegram_portafolio.COMANDOS      # antes de /ayuda


MARCA = {"": "", "movida": " <i>(movida)</i>", "cancelada": " <s>cancelada</s>"}


def texto_dia(fecha, titulo):
    clases = clases_efectivas(fecha)
    lineas = ["<b>" + titulo + " (" + DIAS_BONITO[fecha.weekday()] + " " + fecha.strftime("%d/%m") + ")</b>"]
    if clases:
        lineas.append("\n\U0001F4DA <b>Clases</b> (Teams)")
        for c in clases:
            lineas.append("\u2022 " + c["inicio"] + "\u2013" + c["fin"] + "  " + escape(c["materia"]) + MARCA[c["nota"]])
    else:
        lineas.append("\n\U0001F4DA Sin clases.")
    actividades = eventos.del_dia(fecha)
    if actividades:
        lineas.append("\n\U0001F5D3 <b>Actividades</b>")
        lineas += ["\u2022 " + e["inicio"] + "\u2013" + e["fin"] + "  " + escape(e["titulo"]) for e in actividades]
    if habitos.toca_hoy(fecha):
        lineas.append("\n\U0001F3CB\uFE0F " + habitos.nombre() + " " + habitos.config()["hora"])
    for extra in leer_json("horario_clases.json").get("avisos_extra", []):
        if extra["dia"] == DIAS[fecha.weekday()]:
            lineas.append("\n\u26A0\uFE0F " + extra["hora"] + " \u2013 " + escape(extra["texto"]))
    dia = fecha.date().isoformat()
    lista = tareas.pendientes(hasta=dia) if dia == ahora().date().isoformat() else tareas.para_fecha(dia)
    if lista:
        lineas.append("\n\U0001F4DD <b>Tareas</b>")
        lineas += ["\u2022 " + tareas.linea(t) for t in lista]
    else:
        lineas.append("\n\U0001F4DD Sin entregas.")
    return "\n".join(lineas)


def limite(update):
    """Evita bucles: como maximo 1 comando por segundo."""
    t = time.time()
    if t - _ultimos.get("t", 0) < 1:
        return True
    _ultimos["t"] = t
    return False


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = "<b>A sus \u00f3rdenes, se\u00f1or.</b> Comandos disponibles:\n\n"
    texto += "\n".join("/" + c + " \u2013 " + d for c, d in COMANDOS)
    texto += "\n\n\U0001F399 Tambi\u00e9n puede mandarme <b>notas de voz</b>: le respondo por escrito y con voz."
    await update.message.reply_html(texto)


async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    await update.message.reply_html(texto_dia(ahora(), "Plan de hoy"))


async def cmd_manana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    await update.message.reply_html(texto_dia(ahora() + timedelta(days=1), "Plan de ma\u00f1ana"))


async def cmd_semana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    hoy = ahora()
    lunes = hoy - timedelta(days=hoy.weekday())
    lineas = ["<b>Clases de la semana</b>"]
    for i in range(7):
        dia = lunes + timedelta(days=i)
        clases = clases_efectivas(dia)
        if clases:
            marca = " \u2190 hoy" if i == hoy.weekday() else ""
            lineas.append("\n<b>" + DIAS_BONITO[i].capitalize() + marca + "</b>")
            for c in clases:
                lineas.append("\u2022 " + c["inicio"] + "  " + escape(c["materia"]) + MARCA[c["nota"]])
    await update.message.reply_html("\n".join(lineas))


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    disco_c = psutil.disk_usage("C:\\") if Path("C:\\").exists() else psutil.disk_usage("/")
    try:
        ollama = "activo" if requests.get("http://127.0.0.1:11434/api/tags", timeout=3).ok else "sin respuesta"
    except Exception:
        ollama = "apagado"
    minutos = int((time.time() - INICIO) // 60)
    texto = (
        "<b>Estado</b>\n"
        "\u2022 CPU: " + str(round(psutil.cpu_percent(interval=0.5))) + " %\n"
        "\u2022 RAM: " + str(round(psutil.virtual_memory().percent)) + " % en uso\n"
        "\u2022 Disco C: " + str(round(disco_c.free / 1e9)) + " GB libres\n"
        "\u2022 Ollama: " + ollama + "\n"
        "\u2022 Modo: " + _texto_modo_corto() + "\n"
        "\u2022 Bot encendido hace " + str(minutos) + " min"
    )
    await update.message.reply_html(texto)


# ------------------------------------------------------------------ modo juego / diseno ---
def _texto_modo_corto():
    modo, programa = modos.modo_actual()
    return escape(modos.texto_modo(modo, programa)) if modo else "normal"


def _uso_tarjeta():
    try:
        cargados = requests.get(modos.OLLAMA + "/api/ps", timeout=3).json().get("models", [])
    except Exception:
        return "Ollama no responde."
    if not cargados:
        return "Ning\u00fan modelo cargado."
    return "\n".join("\u2022 " + m["name"] + (": %.1f GB en tarjeta gr\u00e1fica" % (m["size_vram"] / 1e9)
                                              if m.get("size_vram") else ": solo procesador") for m in cargados)


async def vigilar_modo(context: ContextTypes.DEFAULT_TYPE):
    """Cada 10 s: si se abrio un juego o app de diseno, libera la tarjeta grafica y avisa (una vez)."""
    modo, programa = await asyncio.to_thread(modos.modo_actual)
    anterior = context.bot_data.get("modo")
    if modo == anterior:
        return
    context.bot_data["modo"] = modo
    if modo:
        await asyncio.to_thread(notas_voz.soltar)          # Whisper de las notas de voz tambien
        sacados = await asyncio.to_thread(modos.liberar_tarjeta)
        log.info("Entrando en %s (%s); saque de la tarjeta: %s", modo, programa, sacados)
        texto = (modos.texto_modo(modo, programa) + ": tarjeta gr\u00e1fica libre.\n\n"
                 "\u2022 La voz est\u00e1 en pausa.\n\u2022 Por aqu\u00ed le respondo con la IA chica en el procesador "
                 "(algo m\u00e1s lenta y sencilla).\n\u2022 Avisos y comandos siguen igual.")
    else:
        log.info("Vuelta al modo normal")
        texto = "\u2705 Modo normal: vuelven la voz y la IA completa, se\u00f1or."
    if modos.ajustes().get("avisar_por_telegram", True):
        await context.bot.send_message(USER_ID, texto)


async def cmd_modo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    modo, programa = await asyncio.to_thread(modos.modo_actual, 0)
    if modo:
        cabeza = escape(modos.texto_modo(modo, programa)) + "\nVoz en pausa; IA chica (" + \
                 escape(modos.ajustes()["modelo_liviano"]) + ") en el procesador."
    else:
        cabeza = "Modo normal: voz activa e IA completa."
    await update.message.reply_html("<b>Modo</b>\n" + cabeza + "\n\n<b>Ollama ahora</b>\n"
                                    + escape(await asyncio.to_thread(_uso_tarjeta))
                                    + "\n\nLa lista de juegos y apps est\u00e1 en config\\modos.json")


async def cmd_avisos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    await update.message.reply_html("<b>Avisos de hoy</b>\n" + avisos.pendientes(context.job_queue))


async def revisar_calendario(context: ContextTypes.DEFAULT_TYPE):
    """Cada 5 minutos: trae los cambios hechos en Google Calendar."""
    try:
        mensajes = await asyncio.to_thread(sync_cambios.sincronizar_cambios)
    except google_cal.NecesitaAutorizar:
        hoy = ahora().date().isoformat()
        if context.bot_data.get("aviso_google") != hoy:
            context.bot_data["aviso_google"] = hoy
            await context.bot.send_message(
                USER_ID, "\U0001F511 Google Calendar pide volver a autorizar (pasa cada 7 d\u00edas). "
                "En la PC ejecute:\n.\\.venv\\Scripts\\python.exe modulos\\calendario\\conectar.py")
        return []
    except Exception as exc:
        log.warning("No pude revisar Google Calendar: %s", exc)
        return None
    for m in mensajes:
        await context.bot.send_message(USER_ID, m, parse_mode="HTML")
    avisos.programar_dia(context.job_queue, USER_ID)      # tambien recoge lo agendado por voz
    return mensajes


async def cmd_sincronizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    mensajes = await revisar_calendario(context)
    if mensajes is None:
        await update.message.reply_text("No pude conectar con Google Calendar ahora. Lo intento de nuevo en 5 minutos.")
    elif not mensajes:
        await update.message.reply_text("Revisado: no hay cambios nuevos en su calendario, se\u00f1or.")


async def _subir(tid, hecha=False):
    """Replica en Google Calendar sin bloquear el bot. Devuelve texto de estado."""
    try:
        await asyncio.to_thread(tareas.subir, tid, hecha)
        return "\U0001F4C5 Tambi\u00e9n en Google Calendar."
    except google_cal.NecesitaAutorizar:
        return "\u26A0\uFE0F No la pude subir a Google: hay que volver a autorizar (conectar.py)."
    except Exception as exc:
        log.warning("No se pudo subir la tarea %s: %s", tid, exc)
        return "\u26A0\uFE0F No la pude subir a Google ahora; queda guardada en la PC."


async def cmd_tarea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    datos = tareas.interpretar(" ".join(context.args))
    if isinstance(datos, str):
        await update.message.reply_html(tareas.AYUDA)
        return
    tid = tareas.crear(**datos)
    estado = await _subir(tid)
    await update.message.reply_html("\u2705 Anotada:\n" + tareas.linea(tareas.obtener(tid)) + "\n" + estado)


async def cmd_tareas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    lista = tareas.pendientes()
    if not lista:
        await update.message.reply_text("No tiene tareas pendientes, se\u00f1or. \U0001F389")
        return
    texto = "<b>Tareas pendientes</b>\n" + "\n".join("\u2022 " + tareas.linea(t) for t in lista)
    texto += "\n\nPara marcar una: /hecho n\u00famero"
    await update.message.reply_html(texto)


def _numero(context):
    if context.args and context.args[0].lstrip("#").isdigit():
        t = tareas.obtener(int(context.args[0].lstrip("#")))
        if t and t["estado"] == "pendiente":
            return t
    return None


async def cmd_hecho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    t = _numero(context)
    if not t:
        await update.message.reply_text("Ind\u00edqueme el n\u00famero de una tarea pendiente, por ejemplo: /hecho 3. Use /tareas para verlas.")
        return
    tareas.cambiar_estado(t["id"], "hecha")
    estado = await _subir(t["id"], hecha=True)
    quedan = len(tareas.pendientes())
    await update.message.reply_html("\U0001F44F Bien hecho, se\u00f1or. Marqu\u00e9 <b>#" + str(t["id"]) + " " + escape(t["titulo"])
                                    + "</b> como terminada.\n" + estado.replace("Tambi\u00e9n en", "Actualizada en")
                                    + "\nQuedan " + str(quedan) + " pendientes.")


async def cmd_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    t = _numero(context)
    if not t:
        await update.message.reply_text("Ind\u00edqueme el n\u00famero de la tarea, por ejemplo: /borrar 3.")
        return
    botones = InlineKeyboardMarkup([[InlineKeyboardButton("S\u00ed, borrar", callback_data="borrar:" + str(t["id"])),
                                     InlineKeyboardButton("No", callback_data="cancelar")]])
    await update.message.reply_html("\u00bfBorro la tarea?\n" + tareas.linea(t), reply_markup=botones)


async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q.from_user or q.from_user.id != USER_ID:
        return
    await q.answer()
    if q.data.startswith("borrarev:"):
        eid = int(q.data.split(":")[1])
        e = eventos.obtener(eid)
        if e and e["estado"] == "activo":
            await asyncio.to_thread(eventos.borrar, eid)
            avisos.programar_dia(context.job_queue, USER_ID)
            await q.edit_message_text("\U0001F5D1 Actividad #" + str(eid) + " borrada (tambi\u00e9n de Google Calendar).")
        else:
            await q.edit_message_text("Esa actividad ya no existe.")
        return
    if q.data.startswith("hab:"):
        valor = q.data.split(":")[1]
        habitos.registrar(valor)
        await q.edit_message_text("\U0001F4AA Anotado, se\u00f1or. Buen trabajo." if valor == "si"
                                  else "Anotado. Ma\u00f1ana ser\u00e1, se\u00f1or.")
    elif q.data.startswith("borrar:"):
        tid = int(q.data.split(":")[1])
        t = tareas.obtener(tid)
        if t and t["estado"] == "pendiente":
            tareas.cambiar_estado(tid, "borrada")
            try:
                await asyncio.to_thread(tareas.quitar_de_google, tid)
            except Exception as exc:
                log.warning("No se pudo quitar de Google: %s", exc)
            await q.edit_message_text("\U0001F5D1 Tarea #" + str(tid) + " borrada.")
        else:
            await q.edit_message_text("Esa tarea ya no est\u00e1 pendiente.")
    else:
        await q.edit_message_text("Cancelado. No borr\u00e9 nada.")


async def aviso_tareas(context: ContextTypes.DEFAULT_TYPE):
    """19:00 entregas de manana; 18:15 entregas de hoy. Sin repetir."""
    cual = context.job.data
    dia = tareas.manana_iso() if cual == "manana" else tareas.hoy_iso()
    clave = tareas.hoy_iso() + "|tareas_" + cual
    lista = tareas.para_fecha(dia)
    if not lista or db.aviso_enviado(clave):
        return
    db.marcar_aviso(clave)
    titulo = "Entregas para ma\u00f1ana" if cual == "manana" else "Entregas de hoy"
    avisos.notificar_windows(titulo, ", ".join(t["titulo"] for t in lista)[:200])
    texto = "\U0001F4DD <b>" + titulo + "</b>\n" + "\n".join("\u2022 " + tareas.linea(t) for t in lista)
    await context.bot.send_message(USER_ID, texto, parse_mode="HTML")


async def aviso_entreno(context: ContextTypes.DEFAULT_TYPE):
    clave = tareas.hoy_iso() + "|entrenamiento"
    if not habitos.toca_hoy() or db.aviso_enviado(clave):
        return
    db.marcar_aviso(clave)
    texto = habitos.config().get("texto") or "Hora de entrenar."
    avisos.notificar_windows(habitos.nombre(), texto)
    botones = InlineKeyboardMarkup([[InlineKeyboardButton("\u2705 Lo hice", callback_data="hab:si"),
                                     InlineKeyboardButton("Hoy no", callback_data="hab:no")]])
    await context.bot.send_message(USER_ID, "\U0001F3CB\uFE0F " + escape(texto) + "\nCuando termine, marque:",
                                   reply_markup=botones)


async def cmd_entreno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    await update.message.reply_html(habitos.resumen_semana())


def programar_entreno(job_queue):
    from datetime import datetime as dt, time as hora
    e = habitos.config()
    if not e:
        return
    h = dt.strptime(e["hora"], "%H:%M").time()
    job_queue.run_daily(aviso_entreno, time=hora(h.hour, h.minute, tzinfo=ZONA), name="entreno")
    ahora_ = ahora()
    if h.hour * 60 + h.minute <= ahora_.hour * 60 + ahora_.minute < 23 * 60 + 30:
        job_queue.run_once(aviso_entreno, when=25, name="entreno_tarde")


def _horas_resumen():
    conf = leer_json("resumenes.json") if (Path(__file__).resolve().parents[2] / "config" / "resumenes.json").exists() else {}
    m = conf.get("matutino", {})
    return (m.get("entre_semana", "07:00"), m.get("fin_de_semana", "09:00"),
            conf.get("nocturno", {}).get("hora", "22:00"))


async def enviar_resumen(context: ContextTypes.DEFAULT_TYPE):
    """Se ejecuta cada minuto clave; envia el resumen que toque (una vez al dia)."""
    cual = context.job.data
    f = ahora()
    entre, finde, noche = _horas_resumen()
    if cual == "matutino":
        hora_ok = finde if f.weekday() >= 5 else entre
        if f.strftime("%H:%M") < hora_ok or f.hour >= 12:
            return
        texto = resumen.matutino(f)
    else:
        if f.strftime("%H:%M") < noche:
            return
        texto = resumen.nocturno(f)
    clave = f.date().isoformat() + "|resumen_" + cual
    if db.aviso_enviado(clave):
        return
    db.marcar_aviso(clave)
    await context.bot.send_message(USER_ID, texto, parse_mode="HTML")
    log.info("Resumen %s enviado", cual)


def programar_resumenes(job_queue):
    from datetime import datetime as dt, time as hora
    entre, finde, noche = _horas_resumen()
    for h, cual in ((entre, "matutino"), (finde, "matutino"), (noche, "nocturno")):
        t = dt.strptime(h, "%H:%M").time()
        job_queue.run_daily(enviar_resumen, time=hora(t.hour, t.minute, tzinfo=ZONA), data=cual, name="resumen_" + cual)
    # Si la PC se encendio tarde: envia el matutino (hasta las 12:00) o el nocturno pendiente
    job_queue.run_once(enviar_resumen, when=30, data="matutino", name="resumen_tarde_m")
    job_queue.run_once(enviar_resumen, when=35, data="nocturno", name="resumen_tarde_n")


async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    await update.message.reply_html(resumen.matutino(ahora()))


async def cmd_cierre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    await update.message.reply_html(resumen.nocturno(ahora()))


def programar_tareas(job_queue):
    from datetime import time as hora
    for cual, h, m in (("hoy", 18, 15), ("manana", 19, 0)):
        job_queue.run_daily(aviso_tareas, time=hora(h, m, tzinfo=ZONA), data=cual, name="tareas_" + cual)
        ahora_ = ahora()
        if ahora_.hour * 60 + ahora_.minute >= h * 60 + m and ahora_.hour < 23:
            job_queue.run_once(aviso_tareas, when=20, data=cual, name="tareas_" + cual + "_tarde")


async def cmd_probar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if limite(update):
        return
    avisos.notificar_windows("Prueba del asistente", "Si ves esto, las notificaciones de Windows funcionan.")
    await update.message.reply_text("Envi\u00e9 una notificaci\u00f3n de prueba a la PC: deber\u00eda verla en la esquina de la pantalla, se\u00f1or.")


CONFIRMACIONES = {"si", "s\u00ed", "ok", "okay", "listo", "vale", "perfecto", "gracias", "dale", "bien"}


async def texto_libre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await atender_texto(update, context, update.message.text.strip())


async def atender_texto(update: Update, context: ContextTypes.DEFAULT_TYPE, texto):
    """Responde un texto (escrito o de una nota de voz). Devuelve la respuesta, o None si no hubo."""
    if texto.lower().strip(".!\u00a1 ") in CONFIRMACIONES and not cerebro.memoria.historial(1):
        await update.message.reply_text("Perfecto, se\u00f1or. Quedo atento.")
        return None
    if not await asyncio.to_thread(cerebro.modelo_listo):
        await update.message.reply_text(
            "Mi cerebro (Ollama) no est\u00e1 disponible ahora, se\u00f1or. Los comandos con / siguen funcionando: /ayuda")
        return None
    await context.bot.send_chat_action(USER_ID, "typing")
    try:
        respuesta, pendientes = await asyncio.to_thread(cerebro.responder, texto, None, texto_dia)
    except Exception as exc:
        log.warning("Error de la IA: %s", exc)
        await update.message.reply_text("Disculpe, se\u00f1or, tuve un problema pensando la respuesta. Intente de nuevo.")
        return None
    await update.message.reply_text(respuesta)
    avisos.programar_dia(context.job_queue, USER_ID)       # por si se agendo algo para hoy
    for accion, tid in pendientes:
        if accion == "borrar_evento":
            e = eventos.obtener(tid)
            if e:
                botones = InlineKeyboardMarkup([[InlineKeyboardButton("S\u00ed, borrar", callback_data="borrarev:" + str(tid)),
                                                 InlineKeyboardButton("No", callback_data="cancelar")]])
                await update.message.reply_text("\u00bfBorro la actividad?\n" + eventos.descripcion(e), reply_markup=botones)
            continue
        t = tareas.obtener(tid)
        if accion == "borrar" and t:
            botones = InlineKeyboardMarkup([[InlineKeyboardButton("S\u00ed, borrar", callback_data="borrar:" + str(tid)),
                                             InlineKeyboardButton("No", callback_data="cancelar")]])
            await update.message.reply_html("\u00bfBorro la tarea?\n" + tareas.linea(t), reply_markup=botones)
    return respuesta


async def cmd_olvidar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cerebro.memoria.borrar_conversacion()
    await update.message.reply_text("Borr\u00e9 el hilo de esta conversaci\u00f3n, se\u00f1or. "
                                    "Lo que s\u00e9 de usted (/memoria) sigue intacto.")


async def cmd_memoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lista = cerebro.memoria.recuerdos()
    texto = "<b>Lo que s\u00e9 de usted</b>\n\n" + "\n".join("\u2022 <b>#" + str(r["id"]) + "</b> " + escape(r["dato"]) for r in lista)
    texto += "\n\nPara corregir algo, d\u00edgamelo normal (ej. \u00abya no entreno a las 17:10\u00bb) o escriba /olvido n\u00famero."
    await update.message.reply_html(texto)


async def cmd_olvido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].lstrip("#").isdigit() and cerebro.memoria.olvidar(int(context.args[0].lstrip("#"))):
        await update.message.reply_text("Listo, lo borr\u00e9 de mi memoria.")
    else:
        await update.message.reply_text("Ind\u00edqueme el n\u00famero del recuerdo, por ejemplo /olvido 3. Vea la lista con /memoria.")


async def intruso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    log.warning("Mensaje ignorado de user_id=%s nombre=%s", u.id if u else "?", u.full_name if u else "?")


async def al_iniciar(app: Application):
    await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMANDOS])
    avisos.iniciar(app.job_queue, USER_ID)
    programar_tareas(app.job_queue)
    programar_entreno(app.job_queue)
    programar_resumenes(app.job_queue)
    app.job_queue.run_repeating(revisar_calendario, interval=300, first=15, name="calendario")
    app.job_queue.run_repeating(vigilar_modo, interval=10, first=5, name="modo")
    telegram_ingles.programar(app.job_queue)
    telegram_portafolio.programar(app.job_queue)
    telegram_moodle.programar(app.job_queue)
    telegram_finanzas.programar(app.job_queue)
    notas_voz.programar(app.job_queue)
    telegram_cava.programar(app.job_queue)
    telegram_noticias.programar(app.job_queue)
    telegram_alertas.programar(app.job_queue)
    telegram_salud.programar(app.job_queue)
    telegram_proactivo.programar(app.job_queue)
    await app.bot.send_message(USER_ID, "\U0001F7E2 Asistente en l\u00ednea, se\u00f1or. Escriba /ayuda.")
    log.info("Bot iniciado")


async def al_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("Error: %s", context.error)


def main():
    if not TOKEN or not USER_ID:
        sys.exit("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_USER_ID en .env")
    app = Application.builder().token(TOKEN).post_init(al_iniciar).build()
    app.add_handler(CommandHandler(["start", "ayuda", "help"], cmd_ayuda, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("hoy", cmd_hoy, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("manana", cmd_manana, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("semana", cmd_semana, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("estado", cmd_estado, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("avisos", cmd_avisos, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("modo", cmd_modo, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("probar", cmd_probar, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("sincronizar", cmd_sincronizar, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("tarea", cmd_tarea, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("tareas", cmd_tareas, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("hecho", cmd_hecho, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("borrar", cmd_borrar, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("entreno", cmd_entreno, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("resumen", cmd_resumen, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("cierre", cmd_cierre, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("olvidar", cmd_olvidar, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("memoria", cmd_memoria, filters=SOLO_DUENO))
    app.add_handler(CommandHandler("olvido", cmd_olvido, filters=SOLO_DUENO))
    notas_voz.registrar(app, atender_texto, SOLO_DUENO)
    telegram_cava.registrar(app)
    telegram_noticias.registrar(app)
    telegram_alertas.registrar(app)
    telegram_salud.registrar(app)
    telegram_proactivo.registrar(app)
    telegram_ingles.registrar(app)                 # antes del manejador general de botones
    telegram_portafolio.registrar(app)
    telegram_moodle.registrar(app)
    telegram_finanzas.registrar(app)
    app.add_handler(CallbackQueryHandler(boton))
    app.add_handler(MessageHandler(SOLO_DUENO & filters.TEXT & ~filters.COMMAND, texto_libre))
    app.add_handler(MessageHandler(~SOLO_DUENO, intruso))
    app.add_error_handler(al_error)
    log.info("Arrancando bot (Ctrl + C para detener)...")
    # drop_pending_updates=False: lo que el usuario escribio con la PC apagada (hasta ~24 h) se procesa al encender
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
