"""Finanzas en Telegram: gastos (/gastos, /mes, botones), /deudas, fotos de comprobantes y avisos.

- Foto con texto ("Juan me pago 100"): se guarda y se adjunta a ese pago.
- Foto sin texto: se guarda y se adjunta a lo proximo que anote en los siguientes 15 minutos.
- Avisos a las 09:00: cuotas del dia, atrasos (3 dias) y fechas limite. Sin repetir.
"""
import asyncio
import tempfile
from datetime import time as hora
from pathlib import Path

from telegram import InlineKeyboardButton as Boton, InlineKeyboardMarkup as Teclado, Update
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from modulos.comun import db
from modulos.comun.base import USER_ID, ZONA, ahora, registro
from modulos.finanzas import ahorros, deudas, gastos, perfil, presupuesto

log = registro("finanzas")

COMANDOS = [("gastos", "Mis gastos de este mes"), ("mes", "Resumen completo del mes pasado"),
            ("movimientos", "Últimos gastos e ingresos (para borrar)"), ("borrargasto", "Borrar un gasto: /borrargasto 12"),
            ("correos", "Revisar ya los correos de consumo del banco"),
            ("presupuesto", "Sueldo, cuánto me queda y presupuestos"),
            ("historial", "Mi dinero mes a mes"), ("ahorros", "Mis ahorros programados"),
            ("deudas", "Quién me debe y a quién le debo")]


def _teclado_crudo(filas):
    return Teclado([[Boton(b["text"], callback_data=b["callback_data"]) for b in fila] for fila in filas])


async def _procesar_correos(context, dias):
    """Revisa Gmail y avisa. Devuelve el numero de novedades."""
    from modulos.finanzas import correos
    eventos = await asyncio.to_thread(correos.revisar, dias)
    importacion = dias > 3
    nuevos = [mid for tipo, mid in eventos if tipo == "nuevo"] + [d[0] for tipo, d in eventos if tipo == "nuevo_con_cargo"]
    if importacion:
        total = sum(gastos.obtener(m)["monto"] for m in nuevos)
        texto = ("💳 Conecté sus correos del banco. " + ("Importé " + str(len(nuevos)) + " consumos de los últimos "
                 + str(dias) + " días (" + deudas.fmt(total) + "). Véalos con /movimientos o /gastos." if nuevos else
                 "En los últimos " + str(dias) + " días no encontré correos de consumo que pueda leer."))
        texto += "\n(Correos encontrados: " + str(correos.ULTIMA["encontrados"]) + ", ya procesados: " + str(correos.ULTIMA["vistos"]) + ")"
        if correos.IGNORADOS:
            texto += "\nIgnoré correos de dominios desconocidos: " + ", ".join(correos.IGNORADOS[-5:])
        await context.bot.send_message(USER_ID, texto)
    for tipo, dato in eventos:
        if tipo == "nuevo" and not importacion:
            await context.bot.send_message(USER_ID, correos.texto_nuevo(dato), reply_markup=_botones_gasto(dato))
            motivo = await asyncio.to_thread(perfil.revisar_consumo, dato)
            if motivo:                                   # algo no cuadra con sus habitos: preguntar
                await context.bot.send_message(USER_ID, perfil.texto_pregunta(dato, motivo), reply_markup=Teclado(
                    [[Boton("✅ Fui yo", callback_data="rev:si:" + str(dato)),
                      Boton("🚫 No lo reconozco", callback_data="rev:no:" + str(dato))]]))
        elif tipo == "unido" and not importacion:
            await context.bot.send_message(USER_ID, correos.texto_unido(dato))
        elif tipo == "avance":
            texto, filas = correos.texto_avance(dato)
            await context.bot.send_message(USER_ID, texto, reply_markup=_teclado_crudo(filas))
        elif tipo == "reverso":
            await context.bot.send_message(USER_ID, correos.texto_reverso(dato))
        elif tipo == "inversion":
            await context.bot.send_message(USER_ID, correos.texto_inversion(*dato))
        elif tipo == "nuevo_con_cargo" and not importacion:
            await context.bot.send_message(USER_ID, correos.texto_nuevo(dato[0]), reply_markup=_botones_gasto(dato[0]))
            await context.bot.send_message(USER_ID, correos.texto_cargo(dato[1]))
        elif tipo == "moneda":
            await context.bot.send_message(USER_ID, "💱 " + dato)
        elif tipo == "ilegible":
            await context.bot.send_message(USER_ID, "⚠️ No pude leer un correo de consumo (" + dato
                                           + "). Quizá el banco cambió el formato: anótelo a mano y avise a Claude.")
    return len(eventos)


async def revisar_correos(context: ContextTypes.DEFAULT_TYPE):
    from modulos.finanzas import correos
    if not correos.TOKEN.exists():
        return
    correos.reintentar_ilegibles()                    # si mejoro un lector, repite la importacion (sin duplicar)
    primera = not db.aviso_enviado("correos|importacion")
    try:
        await _procesar_correos(context, 45 if primera else 3)
        if primera:
            db.marcar_aviso("correos|importacion")
        arreglo = correos.texto_reparacion(await asyncio.to_thread(correos.corregir_reversos_pasados))   # una sola vez
        if arreglo:
            await context.bot.send_message(USER_ID, arreglo)
    except correos.SinPermiso:
        clave = ahora().date().isoformat() + "|gmail_permiso"
        if not db.aviso_enviado(clave):
            db.marcar_aviso(clave)
            await context.bot.send_message(USER_ID, "🔑 Gmail pide volver a autorizar (pasa cada 7 días). En la PC ejecute:\n"
                                           ".\\.venv\\Scripts\\python.exe modulos\\finanzas\\conectar_gmail.py")
    except Exception as exc:
        log.warning("No pude revisar los correos: %s", exc)
        motivo = explicar_error(exc)
        clave = ahora().date().isoformat() + "|gmail_error|" + motivo[:20]
        if not db.aviso_enviado(clave):                     # una vez al dia por tipo de error
            db.marcar_aviso(clave)
            await context.bot.send_message(USER_ID, "⚠️ No pude revisar sus correos del banco.\n\n" + motivo)


def explicar_error(exc):
    """Traduce el error de Google a algo que el usuario pueda resolver."""
    t = str(exc)
    if "accessNotConfigured" in t or "has not been used" in t or "is disabled" in t or "SERVICE_DISABLED" in t:
        return ("La API de Gmail está DESACTIVADA en su proyecto de Google Cloud. Actívela (1 minuto):\n"
                "1. Abra https://console.cloud.google.com/apis/library/gmail.googleapis.com\n"
                "2. Arriba elija el proyecto «Asistente personal»\n3. Pulse «Habilitar»\n"
                "Luego escriba /correos (no hace falta reiniciar).")
    if "insufficient" in t.lower() or "PERMISSION_DENIED" in t or "403" in t:
        return ("Google negó el permiso de lectura. En la PC vuelva a ejecutar:\n"
                ".\\.venv\\Scripts\\python.exe modulos\\finanzas\\conectar_gmail.py\n"
                "y marque la casilla de «Ver sus mensajes de correo» si aparece.")
    if "invalid_grant" in t or "expired" in t.lower() or "revoked" in t.lower():
        return "El permiso de Gmail venció (pasa cada 7 días). En la PC ejecute conectar_gmail.py de nuevo."
    if "Unable to find the server" in t or "Max retries" in t or "timed out" in t or "NameResolution" in t:
        return "No hay conexión a internet o Google no responde. Lo intento de nuevo en 10 minutos."
    return "Error técnico: " + t[:200] + "\nCópielo a Claude para revisarlo."


async def cmd_correos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from modulos.finanzas import correos
    if not correos.TOKEN.exists():
        await update.message.reply_text("Gmail aún no está conectado. En la PC ejecute: modulos\\finanzas\\conectar_gmail.py")
        return
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        n = await _procesar_correos(context, 7)
    except correos.SinPermiso:
        await update.message.reply_text("Gmail pide volver a autorizar: ejecute conectar_gmail.py en la PC.")
        return
    except Exception as exc:
        log.warning("No pude revisar los correos (/correos): %s", exc)
        await update.message.reply_text("⚠️ No pude revisar Gmail.\n\n" + explicar_error(exc), disable_web_page_preview=True)
        return
    texto = ("Revisé los correos de los últimos 7 días: " + ("sin consumos nuevos." if not n else str(n) + " novedad(es).")
             + "\n(Correos encontrados: " + str(correos.ULTIMA["encontrados"]) + ", ya procesados: " + str(correos.ULTIMA["vistos"]) + ")")
    if correos.IGNORADOS:
        texto += ("\nIgnoré correos que parecen del banco pero vienen de dominios desconocidos: " + ", ".join(correos.IGNORADOS[-5:])
                  + ". Si alguno es legítimo, agréguelo en config\\finanzas.json (remitentes_bancos).")
    await update.message.reply_text(texto)


def _confirmar_borrado(g):
    return ("¿Borro este " + ("ingreso" if g["tipo"] == "ingreso" else "gasto") + "?\n" + gastos.linea(g)
            + " (" + g["categoria"] + ")", Teclado([[Boton("🗑 Sí, borrar", callback_data="gas:del:" + str(g["id"])),
                                                    Boton("No", callback_data="gas:no:" + str(g["id"]))]]))


async def cmd_movimientos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lista = await asyncio.to_thread(gastos.recientes, 10)
    if not lista:
        await update.message.reply_text("No hay gastos ni ingresos registrados.")
        return
    filas = [[Boton("🗑 " + gastos.linea(g)[:60], callback_data="gas:pre:" + str(g["id"]))] for g in lista]
    await update.message.reply_text("Últimos movimientos. Toque uno para borrarlo (le pido confirmación):",
                                    reply_markup=Teclado(filas))


async def cmd_borrargasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    num = (context.args[0].lstrip("#") if context.args else "")
    g = gastos.obtener(int(num)) if num.isdigit() else None
    if not g or g["estado"] != "activo":
        await update.message.reply_text("Indíqueme el número del gasto, por ejemplo /borrargasto 12 (véalos con /movimientos).")
        return
    texto, teclado = _confirmar_borrado(g)
    await update.message.reply_text(texto, reply_markup=teclado)


def _botones_gasto(mid):
    return Teclado([[Boton("🏷 Cambiar categoría", callback_data="gas:cat:" + str(mid)),
                     Boton("↩️ Deshacer", callback_data="gas:del:" + str(mid))]])


async def texto_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Grupo -2: los gastos e ingresos claros se anotan aqui mismo, con botones (sin pasar por la IA)."""
    try:
        from modulos.ingles import conversacion
        if conversacion.abierta("telegram"):
            return                                         # en practica de ingles no se interpreta como gasto
    except Exception:
        pass
    texto = update.message.text or ""
    if deudas.interpretar(texto) or deudas.parece_deuda(texto):
        return                                             # las deudas las resuelve el cerebro (código o IA)
    a = ahorros.interpretar(texto)
    if a:
        await update.message.reply_text(await asyncio.to_thread(ahorros.ejecutar, a))
        raise ApplicationHandlerStop
    p = presupuesto.interpretar(texto)
    if p:
        respuesta = await asyncio.to_thread(presupuesto.ejecutar, p)
        teclado = None
        if p["accion"] == "sugerir":
            propuesta, _ = await asyncio.to_thread(presupuesto.sugerir)
            if propuesta:
                context.bot_data["propuesta_presupuesto"] = propuesta
                teclado = Teclado([[Boton("✅ Aplicar estos presupuestos", callback_data="pre:aplicar:0")]])
        await update.message.reply_text(respuesta, reply_markup=teclado)
        raise ApplicationHandlerStop
    d = gastos.interpretar(texto)
    if d and d["accion"] == "borrar_desc":
        lista = await asyncio.to_thread(gastos.buscar, d["texto"], "ingreso" if d.get("tipo") == "ingreso" else "gasto")
        if not lista:
            await update.message.reply_text("No encontré un " + d.get("tipo", "gasto") + " reciente de «" + d["texto"] + "».")
        else:
            texto, teclado = _confirmar_borrado(lista[0])
            if len(lista) > 1:
                texto += "\n\n(Hay otros parecidos: use /movimientos para elegir otro.)"
            await update.message.reply_text(texto, reply_markup=teclado)
        raise ApplicationHandlerStop
    if d and d["accion"] == "dudoso":
        pid = await asyncio.to_thread(gastos.crear_pendiente, d)
        texto, filas = gastos.pregunta_pendiente(pid)
        await update.message.reply_text(texto, reply_markup=Teclado(
            [[Boton(b["text"], callback_data=b["callback_data"]) for b in fila] for fila in filas]))
        raise ApplicationHandlerStop
    if not d or d["accion"] not in ("gasto", "ingreso"):
        return
    respuesta = await asyncio.to_thread(gastos.ejecutar, d)
    mid = gastos.ULTIMO_ANOTADO[0] if gastos.ULTIMO_ANOTADO else None
    await update.message.reply_text(respuesta, reply_markup=_botones_gasto(mid) if mid else None)
    raise ApplicationHandlerStop


async def boton_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q.from_user or q.from_user.id != USER_ID:
        return
    await q.answer()
    partes = q.data.split(":")
    accion, mid = partes[1], int(partes[2])
    if accion == "pend":
        cat = gastos.categorias()[int(partes[3])]
        nuevo = await asyncio.to_thread(gastos.resolver_pendiente, mid, cat)
        if not nuevo:
            await q.edit_message_text("Esa pregunta ya se respondió.")
            return
        await q.edit_message_text(gastos.confirmacion(nuevo) + " Aprendido para la próxima.",
                                  reply_markup=_botones_gasto(nuevo))
        return
    if accion == "pendno":
        gastos.descartar_pendiente(mid)
        await q.edit_message_text("Entendido, no lo anoté.")
        return
    g = gastos.obtener(mid)
    if not g or g["estado"] != "activo":
        await q.edit_message_reply_markup(None)
        return
    if accion == "pre":
        texto, teclado = _confirmar_borrado(g)
        await context.bot.send_message(q.message.chat_id, texto, reply_markup=teclado)
        return
    if accion == "no":
        await q.edit_message_text("Cancelado. No borré nada.")
        return
    if accion == "cat":
        cats = gastos.categorias()
        botones = [Boton(c, callback_data="gas:set:" + str(mid) + ":" + str(i)) for i, c in enumerate(cats)]
        await q.edit_message_reply_markup(Teclado([botones[j:j + 2] for j in range(0, len(botones), 2)]))
    elif accion == "set":
        cat = gastos.categorias()[int(partes[3])]
        gastos.cambiar(mid, categoria=cat)
        gastos.aprender(g["descripcion"], cat)
        await q.edit_message_text("💸 " + deudas.fmt(g["monto"]) + " en " + cat + " (" + g["descripcion"] + ")"
                                  + (" · " + g["medio"] if g["medio"] else "") + ". Aprendido: «" + g["descripcion"]
                                  + "» irá a " + cat + " de ahora en adelante.")
    elif accion == "del":
        gastos.cambiar(mid, estado="borrado")
        await q.edit_message_text("🗑 Borrado: " + gastos.linea(g) + ".")


async def cmd_gastos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = await asyncio.to_thread(gastos.consulta, " ".join(context.args) or "este mes")
    await update.message.reply_text(texto + "\n\nAnote así: «almuerzo 4.50», «uber 3,20 con diners», «sueldo 800». "
                                    "Consulte: «¿cuánto gasté en comida?», «gastos de la semana».")


async def cmd_presupuesto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = await asyncio.to_thread(presupuesto.estado)
    await update.message.reply_text(texto + "\n\nEjemplos: «mi sueldo es 800 y me pagan el 30», «presupuesto comida 150», "
                                    "«me pagaron movilidad 40», «¿cuánto me queda en comida?»",
                                    reply_markup=Teclado([[Boton("💡 Sugerirme presupuestos", callback_data="pre:sugerir:0")]]))


async def boton_presupuesto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q.from_user or q.from_user.id != USER_ID:
        return
    await q.answer()
    accion = q.data.split(":")[1]
    if accion == "sugerir":
        propuesta, nota = await asyncio.to_thread(presupuesto.sugerir)
        if not propuesta:
            await context.bot.send_message(q.message.chat_id, nota)
            return
        context.bot_data["propuesta_presupuesto"] = propuesta
        await context.bot.send_message(q.message.chat_id, presupuesto.texto_sugerencia(propuesta, nota), reply_markup=Teclado(
            [[Boton("✅ Aplicar estos presupuestos", callback_data="pre:aplicar:0")]]))
    elif accion == "aplicar":
        propuesta = context.bot_data.pop("propuesta_presupuesto", None)
        if not propuesta:
            await q.edit_message_reply_markup(None)
            return
        for cat, monto in propuesta.items():
            presupuesto.poner_presupuesto(cat, monto)
        await q.edit_message_reply_markup(None)
        await context.bot.send_message(q.message.chat_id, "✅ Presupuestos aplicados.\n\n" + presupuesto.estado())
    elif accion == "sueldo_si":
        monto = presupuesto.sueldo()
        mid = gastos.anotar("ingreso", monto, "Sueldo", "Sueldo", "", None, "telegram", usar_foto=False)
        await q.edit_message_text("💼 Registré su sueldo de " + deudas.fmt(monto) + ". ¡Buen mes, señor!")
    elif accion == "sueldo_no":
        await q.edit_message_text("Entendido. Cuando llegue escriba «sueldo " + ("%g" % presupuesto.sueldo())
                                  + "» (o el monto que le llegó).")


async def preguntar_sueldo(context: ContextTypes.DEFAULT_TYPE):
    hoy = ahora().date()
    clave = hoy.isoformat() + "|pregunta_sueldo"
    if not presupuesto.toca_preguntar_sueldo(hoy) or db.aviso_enviado(clave):
        return
    db.marcar_aviso(clave)
    await context.bot.send_message(USER_ID, "💼 Hoy es su día de pago: ¿le llegó el sueldo de " + deudas.fmt(presupuesto.sueldo())
                                   + "?\nSi llegó otro monto, escríbalo así: «sueldo 820».", reply_markup=Teclado(
        [[Boton("✅ Sí, llegó", callback_data="pre:sueldo_si:0"), Boton("Aún no", callback_data="pre:sueldo_no:0")]]))


async def cmd_historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await asyncio.to_thread(perfil.historial))


async def cmd_ahorros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await asyncio.to_thread(ahorros.resumen))


async def boton_revision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q.from_user or q.from_user.id != USER_ID:
        return
    await q.answer()
    _, accion, mid = q.data.split(":")
    mid = int(mid)
    if accion == "si":
        await q.edit_message_text(q.message.text + "\n\n✅ Confirmado: fue usted. Lo tendré en cuenta.")
    else:
        gastos.cambiar(mid, estado="sospechoso")
        await q.edit_message_text(q.message.text + "\n\n🚫 Marcado como no reconocido.")
        await context.bot.send_message(USER_ID, perfil.texto_no_reconocido(mid))


async def aportes_y_semana(context: ContextTypes.DEFAULT_TYPE):
    for texto in await asyncio.to_thread(ahorros.aportes_de_hoy):
        await context.bot.send_message(USER_ID, texto)


async def resumen_semanal(context: ContextTypes.DEFAULT_TYPE):
    hoy = ahora().date()
    clave = hoy.isoformat() + "|semana_financiera"
    if hoy.weekday() != 6 or db.aviso_enviado(clave):
        return
    db.marcar_aviso(clave)
    await context.bot.send_message(USER_ID, await asyncio.to_thread(perfil.semana))


async def cmd_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await asyncio.to_thread(gastos.resumen_mes_anterior))


async def resumen_mensual(context: ContextTypes.DEFAULT_TYPE):
    f = ahora()
    if f.day != 1:
        return
    clave = f.date().isoformat() + "|resumen_gastos"
    if db.aviso_enviado(clave):
        return
    db.marcar_aviso(clave)
    await context.bot.send_message(USER_ID, await asyncio.to_thread(gastos.resumen_mes_anterior))


def _botones_lista():
    filas = []
    for d in deudas.abiertas():
        etiqueta = ("\U0001F4B0 " if d["sentido"] == "me_debe" else "\U0001F4B8 ") + d["persona"] + " " + deudas.fmt(deudas.saldo(d["id"]))
        filas.append([Boton(etiqueta, callback_data="fin:ver:" + str(d["id"]))])
    return Teclado(filas) if filas else None


async def cmd_deudas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = await asyncio.to_thread(deudas.resumen)
    ayuda = ("\n\nPara anotar, escríbame normal:\n• Juan me debe 500 por la laptop\n• Juan me pagó 100\n"
             "• Juan paga 100 cada 15\n• Le debo 200 a mi tío\n• Mande una foto para guardar la captura")
    await update.message.reply_text(texto + ayuda, reply_markup=_botones_lista())


async def foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    archivo = msg.photo[-1] if msg.photo else msg.document
    sufijo = ".jpg" if msg.photo else (Path(msg.document.file_name or "x.jpg").suffix or ".jpg")
    tmp = Path(tempfile.gettempdir()) / ("asistente_" + str(msg.message_id) + sufijo)
    f = await context.bot.get_file(archivo.file_id)
    await f.download_to_drive(str(tmp))
    destino = await asyncio.to_thread(deudas.guardar_comprobante, tmp)
    log.info("Comprobante guardado: %s", destino.name)
    if msg.caption:
        r = await asyncio.to_thread(deudas.procesar, msg.caption)
        if r:
            await msg.reply_text(r)
            return
        d = gastos.interpretar(msg.caption)
        if d and d["accion"] in ("gasto", "ingreso"):
            r = await asyncio.to_thread(gastos.ejecutar, d)
            mid = gastos.ULTIMO_ANOTADO[0] if gastos.ULTIMO_ANOTADO else None
            await msg.reply_text(r, reply_markup=_botones_gasto(mid) if mid else None)
            return
    await msg.reply_text("\U0001F4CE Guardé la imagen en la PC. ¿De qué es? Escríbame en los próximos 15 minutos, "
                         "por ejemplo «Juan me pagó 100» o «farmacia 12.40», y la adjunto.")


async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q.from_user or q.from_user.id != USER_ID:
        return
    await q.answer()
    _, accion, num = q.data.split(":")[:3]
    d = deudas.obtener(int(num))
    if not d:
        await q.edit_message_text("Esa deuda ya no existe.")
        return
    if accion == "ver":
        filas = [[Boton("\U0001F4CE Capturas", callback_data="fin:img:" + num)]]
        if d["sentido"] == "me_debe":
            filas[0].append(Boton("✉️ Mensaje de cobro", callback_data="fin:cobro:" + num))
        await context.bot.send_message(q.message.chat_id, deudas.detalle(d), reply_markup=Teclado(filas))
    elif accion == "img":
        fotos = [m for m in deudas.movimientos(d["id"]) if m["comprobante"] and Path(m["comprobante"]).exists()]
        if not fotos:
            await context.bot.send_message(q.message.chat_id, "No hay capturas guardadas de " + d["persona"] + ".")
        for m in fotos[-10:]:
            with open(m["comprobante"], "rb") as fh:
                await context.bot.send_photo(q.message.chat_id, fh, caption=m["fecha"] + "  "
                                             + ("+" if m["tipo"] == "cargo" else "−") + deudas.fmt(m["monto"]))
    elif accion == "cobro":
        await context.bot.send_message(q.message.chat_id, "Borrador para que usted se lo envíe a " + d["persona"]
                                       + " (cópielo y edítelo):\n\n" + deudas.mensaje_cobro(d["id"]))


async def avisos(context: ContextTypes.DEFAULT_TYPE):
    hoy = ahora().date().isoformat()
    for tipo, did, texto in await asyncio.to_thread(deudas.avisos_de_hoy):
        clave = hoy + "|deuda:" + str(did) + "|" + tipo
        if db.aviso_enviado(clave):
            continue
        db.marcar_aviso(clave)
        d = deudas.obtener(did)
        teclado = None
        if d and d["sentido"] == "me_debe":
            teclado = Teclado([[Boton("✉️ Mensaje de cobro", callback_data="fin:cobro:" + str(did)),
                                Boton("Ver detalle", callback_data="fin:ver:" + str(did))]])
        await context.bot.send_message(USER_ID, texto, reply_markup=teclado)


def registrar(app):
    solo = filters.User(user_id=USER_ID)
    app.add_handler(CommandHandler("deudas", cmd_deudas, filters=solo))
    app.add_handler(CommandHandler("gastos", cmd_gastos, filters=solo))
    app.add_handler(CommandHandler("mes", cmd_mes, filters=solo))
    app.add_handler(CommandHandler("correos", cmd_correos, filters=solo))
    app.add_handler(CommandHandler("presupuesto", cmd_presupuesto, filters=solo))
    app.add_handler(CommandHandler("historial", cmd_historial, filters=solo))
    app.add_handler(CommandHandler("ahorros", cmd_ahorros, filters=solo))
    app.add_handler(CallbackQueryHandler(boton_revision, pattern=r"^rev:"))
    app.add_handler(CallbackQueryHandler(boton_presupuesto, pattern=r"^pre:"))
    app.add_handler(CommandHandler("movimientos", cmd_movimientos, filters=solo))
    app.add_handler(CommandHandler("borrargasto", cmd_borrargasto, filters=solo))
    app.add_handler(CallbackQueryHandler(boton_gasto, pattern=r"^gas:"))
    app.add_handler(MessageHandler(solo & filters.TEXT & ~filters.COMMAND, texto_gasto), group=-2)
    app.add_handler(MessageHandler(solo & (filters.PHOTO | filters.Document.IMAGE), foto))
    app.add_handler(CallbackQueryHandler(boton, pattern=r"^fin:"))


def programar(job_queue):
    job_queue.run_daily(avisos, time=hora(9, 0, tzinfo=ZONA), name="deudas_avisos")
    job_queue.run_daily(resumen_mensual, time=hora(9, 5, tzinfo=ZONA), name="resumen_gastos")
    job_queue.run_repeating(revisar_correos, interval=10 * 60, first=120, name="correos_banco")
    job_queue.run_daily(preguntar_sueldo, time=hora(10, 0, tzinfo=ZONA), name="pregunta_sueldo")
    job_queue.run_daily(aportes_y_semana, time=hora(8, 30, tzinfo=ZONA), name="aportes_ahorro")
    job_queue.run_once(aportes_y_semana, when=80, name="aportes_ahorro_tarde")
    job_queue.run_daily(resumen_semanal, time=hora(20, 0, tzinfo=ZONA), name="semana_financiera")
    if 10 <= ahora().hour < 22:
        job_queue.run_once(preguntar_sueldo, when=75, name="pregunta_sueldo_tarde")
    job_queue.run_once(resumen_mensual, when=60, name="resumen_gastos_tarde")
    f = ahora()
    if 9 <= f.hour < 22:                          # si la PC se encendio despues de las 9
        job_queue.run_once(avisos, when=45, name="deudas_avisos_tarde")
