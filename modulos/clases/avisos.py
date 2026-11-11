"""Fase 1, paso 3 (parte C2): avisos de clases en la PC (Windows + Telegram) y apertura de Teams.

El bot programa cada dia:
  - 15 min antes: aviso por Telegram y notificacion de Windows.
  - 5 min antes: abre la clase (vinculo de Teams -> app de Teams -> RuEdge) y avisa.
  - Avisos extra (ej. miercoles 17:40).
No repite avisos ya enviados (se guardan en la base de datos).
"""
import os
from datetime import datetime, time, timedelta
from html import escape

from modulos.clases.agenda import clases_efectivas
from modulos.comun import db
from modulos.comun.base import DIAS, ZONA, ahora, leer_json, registro

log = registro("avisos")


def notificar_windows(titulo, mensaje, enlace=None):
    """Notificacion de Windows (si falla, no detiene nada)."""
    try:
        from winotify import Notification, audio
        n = Notification(app_id="Asistente", title=titulo, msg=mensaje, duration="long")
        n.set_audio(audio.Reminder, loop=False)
        if enlace:
            n.add_actions(label="Unirse", launch=enlace)
        n.show()
    except Exception as exc:
        log.warning("No se pudo mostrar la notificacion de Windows: %s", exc)


def abrir_clase(clase):
    """Abre la clase segun el orden configurado. Devuelve como se abrio."""
    conf = leer_json("horario_clases.json").get("apertura_clase", {})
    orden = conf.get("orden", ["enlace_teams", "calendario_teams", "ruedge"])
    for metodo in orden:
        try:
            if metodo == "enlace_teams" and clase.get("enlace"):
                os.startfile(clase["enlace"])
                return "vínculo de la clase"
            if metodo == "calendario_teams":
                os.startfile("msteams:")
                return "Teams (entra al Calendario y pulsa Unirse)"
            if metodo == "ruedge" and conf.get("url_ruedge_horario"):
                os.startfile(conf["url_ruedge_horario"])
                return "RuEdge"
        except Exception as exc:
            log.warning("No se pudo abrir con %s: %s", metodo, exc)
    return None


def avisos_del_dia(fecha):
    """Lista de (momento, clave, tipo, clase_o_texto) para una fecha."""
    lista = []
    dia = fecha.date() if isinstance(fecha, datetime) else fecha
    horario = leer_json("horario_clases.json")
    minutos = horario.get("apertura_clase", {}).get("minutos_antes", 5)
    for c in clases_efectivas(fecha):
        if c["nota"] == "cancelada":
            continue
        inicio = datetime.combine(dia, datetime.strptime(c["inicio"], "%H:%M").time(), tzinfo=ZONA)
        base = dia.isoformat() + "|clase:" + c["codigo"]
        lista.append((inicio - timedelta(minutes=15), base + "|previo", "previo", c))
        lista.append((inicio - timedelta(minutes=minutos), base + "|abrir", "abrir", c))
    from modulos.agenda import eventos
    for e in eventos.del_dia(dia):
        inicio = datetime.combine(dia, datetime.strptime(e["inicio"], "%H:%M").time(), tzinfo=ZONA)
        lista.append((inicio - timedelta(minutes=int(e["aviso_min"] or 0)),
                      dia.isoformat() + "|evento:" + str(e["id"]) + "|" + e["inicio"], "evento", e))
    for a in horario.get("avisos_extra", []):
        if a["dia"] == DIAS[dia.weekday()]:
            momento = datetime.combine(dia, datetime.strptime(a["hora"], "%H:%M").time(), tzinfo=ZONA)
            lista.append((momento, dia.isoformat() + "|aviso:" + a["hora"], "extra", a))
    return sorted(lista, key=lambda x: x[0])


async def ejecutar_aviso(context):
    momento, clave, tipo, dato = context.job.data
    if db.aviso_enviado(clave):
        return
    db.marcar_aviso(clave)
    if tipo == "evento":
        cuando = "ahora" if not dato["aviso_min"] else "en " + str(dato["aviso_min"]) + " minutos"
        notificar_windows(dato["titulo"], dato["inicio"] + " \u2013 " + cuando)
        await context.bot.send_message(context.job.chat_id, "\U0001F5D3 " + escape(dato["titulo"]) + " a las "
                                       + dato["inicio"] + " (" + cuando + ")." + ((" " + escape(dato["nota"])) if dato["nota"] else ""))
    elif tipo == "extra":
        notificar_windows("Aviso", dato["texto"])
        await context.bot.send_message(context.job.chat_id, "⚠️ " + dato["texto"])
    elif tipo == "previo":
        texto = "En 15 minutos: " + dato["materia"] + " (" + dato["inicio"] + ")"
        notificar_windows("Clase en 15 minutos", dato["materia"] + " a las " + dato["inicio"], dato.get("enlace"))
        msg = "\U0001F4DA " + escape(texto)
        if dato.get("enlace"):
            msg += '\n<a href="' + escape(dato["enlace"]) + '">Unirse desde el celular</a>'
        await context.bot.send_message(context.job.chat_id, msg, parse_mode="HTML")
    elif tipo == "abrir":
        como = abrir_clase(dato)
        if como:
            notificar_windows("Tu clase empieza en 5 minutos", dato["materia"] + ": abrí " + como)
            texto = "\U0001F7E2 " + escape(dato["materia"]) + " empieza a las " + dato["inicio"] + ". En la PC abrí: " + escape(como) + "."
        else:
            notificar_windows("Tu clase empieza en 5 minutos", dato["materia"] + ": entra por Teams")
            texto = "\U0001F7E1 " + escape(dato["materia"]) + " empieza a las " + dato["inicio"] + ". No pude abrir Teams en la PC; entra manualmente."
        if dato.get("enlace"):
            texto += '\n<a href="' + escape(dato["enlace"]) + '">Unirse desde el celular</a>'
        await context.bot.send_message(context.job.chat_id, texto, parse_mode="HTML")
    log.info("Aviso enviado: %s", clave)


def programar_dia(job_queue, chat_id, fecha=None):
    """Programa los avisos de hoy. Si el bot arranca tarde, abre la clase igual si aun no empezo."""
    fecha = fecha or ahora()
    for job in job_queue.get_jobs_by_name("aviso"):
        job.schedule_removal()
    programados = 0
    for momento, clave, tipo, dato in avisos_del_dia(fecha):
        if db.aviso_enviado(clave):
            continue
        datos = (momento, clave, tipo, dato)
        if momento > ahora():
            job_queue.run_once(ejecutar_aviso, when=momento, data=datos, chat_id=chat_id, name="aviso")
            programados += 1
        elif tipo == "abrir":
            inicio = datetime.combine(momento.date(), datetime.strptime(dato["inicio"], "%H:%M").time(), tzinfo=ZONA)
            if ahora() < inicio:
                job_queue.run_once(ejecutar_aviso, when=1, data=datos, chat_id=chat_id, name="aviso")
                programados += 1
    log.info("Avisos programados para hoy: %d", programados)
    return programados


async def reprogramar(context):
    programar_dia(context.job_queue, context.job.chat_id)


def iniciar(job_queue, chat_id):
    programar_dia(job_queue, chat_id)
    job_queue.run_daily(reprogramar, time=time(0, 1, tzinfo=ZONA), chat_id=chat_id, name="diario")


def pendientes(job_queue):
    """Texto con los avisos que quedan hoy."""
    filas = []
    for job in sorted(job_queue.get_jobs_by_name("aviso"), key=lambda j: j.data[0]):
        momento, clave, tipo, dato = job.data
        nombre = dato.get("materia") or dato.get("titulo") or dato.get("texto", "")
        accion = {"previo": "aviso 15 min", "abrir": "abrir Teams", "extra": "aviso", "evento": "actividad"}[tipo]
        filas.append("• " + momento.strftime("%H:%M") + "  " + escape(nombre) + " (" + accion + ")")
    return "\n".join(filas) if filas else "No quedan avisos para hoy."
