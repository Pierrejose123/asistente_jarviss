"""Fase 1, paso 6: resumen matutino y nocturno (sin IA, solo datos reales)."""
from datetime import date, timedelta
from html import escape

from modulos.clases.agenda import clases_efectivas
from modulos.comun.base import DIAS, DIAS_BONITO, leer_json
from modulos.habitos import habitos
from modulos.resumen import versiculo
from modulos.tareas import tareas

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha_larga(f):
    return DIAS_BONITO[f.weekday()] + " " + str(f.day) + " de " + MESES[f.month - 1]


def _clases(f):
    lista = [c for c in clases_efectivas(f) if c["nota"] != "cancelada"]
    if not lista:
        return ["\U0001F4DA Sin clases."]
    lineas = ["\U0001F4DA <b>Clases</b> (Teams se abrirá 5 min antes)"]
    for c in lista:
        lineas.append("• " + c["inicio"] + "  " + escape(c["materia"]) + (" <i>(movida)</i>" if c["nota"] else ""))
    return lineas


def _actividades(f):
    from modulos.agenda import eventos
    lista = eventos.del_dia(f)
    if not lista:
        return []
    return ["\U0001F5D3 <b>Actividades</b>"] + ["\u2022 " + e["inicio"] + "  " + escape(e["titulo"]) for e in lista]


def _extras(f):
    lineas = []
    for a in leer_json("horario_clases.json").get("avisos_extra", []):
        if a["dia"] == DIAS[f.weekday()]:
            lineas.append("⚠️ " + a["hora"] + " – " + escape(a["texto"]))
    if habitos.toca_hoy(f):
        lineas.append("\U0001F9B5 " + habitos.config()["hora"] + " – " + habitos.nombre().lower())
    return lineas


def matutino(f):
    hoy = f.date().isoformat()
    vencidas = [t for t in tareas.pendientes(hasta=hoy) if t["entrega"] < hoy]
    de_hoy = tareas.para_fecha(hoy)
    limite = (f.date() + timedelta(days=3)).isoformat()
    proximas = [t for t in tareas.pendientes(hasta=limite) if t["entrega"] > hoy]

    lineas = ["☀️ <b>Buenos días, señor.</b>", "Hoy es " + _fecha_larga(f) + ".", ""]
    lineas += _clases(f)
    act = _actividades(f)
    if act:
        lineas += [""] + act
    extras = _extras(f)
    if extras:
        lineas += [""] + extras
    lineas.append("")
    if de_hoy or vencidas:
        lineas.append("\U0001F4DD <b>Entregas</b>")
        lineas += ["• " + tareas.linea(t) for t in vencidas + de_hoy]
    else:
        lineas.append("\U0001F4DD Nada que entregar hoy.")
    if proximas:
        lineas += ["", "\U0001F51C <b>Próximos 3 días</b>"] + ["• " + tareas.linea(t) for t in proximas]
    if not (de_hoy or vencidas or proximas) and not [c for c in clases_efectivas(f) if c["nota"] != "cancelada"]:
        lineas += ["", "Un día tranquilo. Que lo disfrute."]
    v = versiculo.bloque("Para empezar el día")
    if v:
        lineas += ["", v]
    return "\n".join(lineas)


def nocturno(f):
    hoy = f.date().isoformat()
    manana = f + timedelta(days=1)
    hechas = tareas.hechas_el(hoy)
    lineas = ["\U0001F319 <b>Cierre del día</b> – " + _fecha_larga(f), ""]
    if hechas:
        lineas.append("✅ <b>Completadas hoy</b>")
        lineas += ["• " + escape(t["titulo"]) for t in hechas]
    else:
        lineas.append("✅ Hoy no marcó tareas como hechas.")
    if habitos.toca_hoy(f):
        r = habitos.registro_de(f)
        lineas.append("\U0001F9B5 " + habitos.nombre() + ": " + {"si": "hechos \U0001F4AA", "no": "hoy no"}.get(r, "sin registrar"))
    lineas += ["", "<b>Mañana, " + _fecha_larga(manana) + "</b>"]
    lineas += _clases(manana)
    lineas += _actividades(manana)
    entregas = tareas.para_fecha(manana.date().isoformat())
    if entregas:
        lineas.append("\U0001F4DD <b>Entregas</b>")
        lineas += ["• " + tareas.linea(t) for t in entregas]
    pendientes = len(tareas.pendientes())
    lineas += ["", "Tareas pendientes en total: " + str(pendientes) + "."]
    v = versiculo.bloque("Para cerrar el día")
    if v:
        lineas += ["", v]
    lineas += ["", "Que descanse, señor."]
    return "\n".join(lineas)
