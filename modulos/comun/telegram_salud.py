"""Chequeo de salud por Telegram.

- Asistente: cada mañana (06:50) SOLO si algo falla (o siempre, con "chequeo_diario_solo_si_falla": false en
  config/pc.json) y con /salud.
- PC: revisión semanal (domingo 17:00 o al encender si se saltó), avisos inmediatos solo si es grave y /pc.
- /ejecutar_claude: corre claude_ejecutar.cmd (lo prepara Claude cuando no puede ejecutar en la PC por sí mismo:
  pruebas, reinicios). Muestra qué hará y pide confirmar con un botón; nunca ejecuta texto libre.
- /reiniciar: reinicia el asistente (bot y voz) para cargar las últimas actualizaciones; avisa al volver.
- /pruebas [nombre]: corre las pruebas del asistente (base temporal, sin tocar sus datos) y manda el resumen.
"""
import asyncio
import subprocess
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
            ("pc", "Revisión de la PC: seguridad, discos, tarjeta gráfica"),
            ("ejecutar_claude", "Corre lo que Claude dejó preparado (pruebas, reinicio) y le avisa al terminar"),
            ("reiniciar", "Reinicia el asistente para cargar las últimas actualizaciones"),
            ("pruebas", "Corre las pruebas del asistente: /pruebas o /pruebas mercado")]
RAIZ = Path(__file__).resolve().parents[2]
EJECUTABLE = RAIZ / "claude_ejecutar.cmd"
SALIDA = RAIZ / "para_claude_salida.txt"
PYTHON = RAIZ / ".venv" / "Scripts" / "python.exe"
PYTHONW = RAIZ / ".venv" / "Scripts" / "pythonw.exe"
MARCA_REINICIO = RAIZ / "datos" / "reinicio_pedido.txt"
LENTAS = ("prueba_propuesta_real",)          # usan la IA y tardan: solo si las pide por nombre
BOTON_REINICIAR = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Reiniciar", callback_data="pc:reinicio_si"),
                                         InlineKeyboardButton("Cancelar", callback_data="pc:reinicio_no")]])
BOTON_EJECUTAR = InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Ejecutar", callback_data="pc:claude_si"),
                                        InlineKeyboardButton("Cancelar", callback_data="pc:claude_no")]])
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


def tarea_claude():
    """Qué hará el archivo, según sus líneas «REM CLAUDE:». None si no hay nada preparado."""
    if not EJECUTABLE.exists():
        return None
    lineas = [l.split(":", 1)[1].strip() for l in EJECUTABLE.read_text(encoding="utf-8", errors="ignore").splitlines()
              if l.strip().upper().startswith("REM CLAUDE:")]
    return lineas or ["(sin descripción)"]


async def cmd_ejecutar_claude(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tarea = tarea_claude()
    if not tarea:
        await update.message.reply_text("No hay nada preparado por Claude para ejecutar.")
        return
    ya = SALIDA.exists() and SALIDA.stat().st_mtime > EJECUTABLE.stat().st_mtime
    await update.message.reply_text("Claude dejó preparado esto:\n• " + "\n• ".join(tarea) +
                                    ("\n\n⚠️ Ya se ejecutó una vez. ¿Otra vez?" if ya else "\n\n¿Lo ejecuto?"),
                                    reply_markup=BOTON_EJECUTAR)


def lanzar_claude():
    """Proceso aparte (sobrevive si el archivo reinicia el bot), sin ventana."""
    _aparte(["cmd", "/c", str(EJECUTABLE), "auto"])


def _aparte(args):
    banderas = 0x00000200 | 0x08000000   # NEW_PROCESS_GROUP | NO_WINDOW (consola oculta: las redirecciones > archivo funcionan)
    subprocess.Popen(args, cwd=str(RAIZ), creationflags=banderas, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


async def cmd_reiniciar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¿Reinicio el asistente (bot y voz)? Tarda unos 30 segundos y carga las últimas "
                                    "actualizaciones.", reply_markup=BOTON_REINICIAR)


async def avisar_reinicio(context: ContextTypes.DEFAULT_TYPE):
    """Al arrancar: si el reinicio se pidió por Telegram, confirma que volvió."""
    if MARCA_REINICIO.exists():
        try:
            MARCA_REINICIO.unlink()
        except Exception:
            pass
        await context.bot.send_message(USER_ID, "✅ Asistente reiniciado: ya tiene las últimas actualizaciones.")


def lista_pruebas(filtro=""):
    todas = sorted((RAIZ / "modulos").glob("*/pruebas/prueba_*.py"))
    f = filtro.lower().strip()
    if f:
        return [p for p in todas if f in p.stem.lower() or f in p.parts[-3].lower()]
    return [p for p in todas if p.stem not in LENTAS]


def correr_prueba(ruta):
    """(bien, resumen). Cada prueba usa su base temporal y bloquea internet/Telegram."""
    import os
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run([str(PYTHON), str(ruta)], cwd=str(RAIZ), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300, env=env, creationflags=0x08000000)
    except subprocess.TimeoutExpired:
        return False, "tardó más de 5 minutos"
    lineas = [l.strip() for l in (r.stdout + "\n" + r.stderr).splitlines() if l.strip() and " INFO " not in l]
    clave = [l for l in lineas if "TODO BIEN" in l.upper() or "FALLOS" in l.upper()]
    resumen = clave[-1] if clave else (lineas[-1] if lineas else "sin salida")
    fallos = [l for l in lineas if l.startswith("- ")][:3] if r.returncode else []
    return r.returncode == 0, resumen[:150] + ("".join("\n   " + f[:120] for f in fallos))


async def cmd_pruebas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    filtro = " ".join(context.args or [])
    pruebas = lista_pruebas(filtro)
    if not pruebas:
        await update.message.reply_text("No encontré pruebas" + (" con «" + filtro + "»" if filtro else "") + ".")
        return
    await update.message.reply_text("🧪 Corro %d prueba(s)%s… (puede tardar unos minutos; no tocan sus datos)"
                                    % (len(pruebas), " de «" + filtro + "»" if filtro else ""))
    lineas, bien = [], 0
    for p in pruebas:
        await update.message.chat.send_action("typing")
        ok, resumen = await asyncio.to_thread(correr_prueba, p)
        bien += ok
        lineas.append(("✅ " if ok else "❌ ") + p.parts[-3] + "/" + p.stem.replace("prueba_", "") + ": " + resumen)
    log.info("Pruebas por Telegram: %d de %d bien", bien, len(pruebas))
    texto = ("🧪 <b>%d de %d pruebas bien</b>\n" % (bien, len(pruebas))) + "\n".join(
        l.replace("&", "&amp;").replace("<", "&lt;") for l in lineas)
    for i in range(0, len(texto), 3900):
        await update.message.reply_html(texto[i:i + 3900])


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
    if q.data in ("pc:reinicio_si", "pc:reinicio_no"):
        await q.edit_message_reply_markup(None)
        if q.data == "pc:reinicio_no":
            await q.answer("Cancelado")
            return
        await q.answer("Reiniciando…")
        try:
            MARCA_REINICIO.parent.mkdir(exist_ok=True)
            MARCA_REINICIO.write_text(ahora().isoformat(timespec="seconds"), encoding="utf-8")
            await context.bot.send_message(USER_ID, "🔄 Reiniciando… le aviso cuando vuelva (unos 30 segundos).")
            log.info("Reinicio pedido por Telegram")
            _aparte([str(PYTHONW if PYTHONW.exists() else PYTHON), str(RAIZ / "modulos" / "comun" / "control.py"),
                     "reiniciar"])
        except Exception as exc:
            await context.bot.send_message(USER_ID, "No pude reiniciar: " + str(exc)[:200])
        return
    if q.data in ("pc:claude_si", "pc:claude_no"):
        await q.edit_message_reply_markup(None)
        if q.data == "pc:claude_no":
            await q.answer("Cancelado")
            return
        await q.answer("Ejecutando…")
        try:
            lanzar_claude()
            log.info("Ejecutando claude_ejecutar.cmd: %s", "; ".join(tarea_claude() or []))
            await context.bot.send_message(USER_ID, "▶️ Ejecutando. Le aviso aquí cuando termine "
                                                    "(si incluye reinicio, el bot se apaga unos segundos).")
        except Exception as exc:
            await context.bot.send_message(USER_ID, "No pude ejecutarlo: " + str(exc)[:200])
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
    app.add_handler(CommandHandler("ejecutar_claude", cmd_ejecutar_claude, filters=solo))
    app.add_handler(CommandHandler("reiniciar", cmd_reiniciar, filters=solo))
    app.add_handler(CommandHandler("pruebas", cmd_pruebas, filters=solo))
    app.add_handler(CallbackQueryHandler(boton, pattern=r"^pc:(limpiar|claude_si|claude_no|reinicio_si|reinicio_no)$"))


def programar(job_queue):
    job_queue.run_daily(chequeo_manana, time=hora(6, 50, tzinfo=ZONA), name="salud")
    job_queue.run_once(chequeo_manana, when=200, name="salud_inicio")
    job_queue.run_once(avisar_reinicio, when=15, name="aviso_reinicio")      # si la PC se encendió tarde
    job_queue.run_repeating(revision_semanal, interval=1800, first=600, name="pc_semanal")
    job_queue.run_repeating(vigilar_grave, interval=600, first=180, name="pc_grave")
