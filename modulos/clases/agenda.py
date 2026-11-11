"""Clases reales de un dia, teniendo en cuenta lo que el usuario cambio desde Google Calendar."""
from datetime import datetime

from modulos.comun import db
from modulos.comun.base import clases_del_dia, leer_json


def clases_efectivas(fecha):
    """Lista de clases (dict) del dia con 'inicio'/'fin' ya ajustados.

    Cada clase lleva 'nota': '' | 'movida' | 'cancelada'.
    Las canceladas se incluyen (para mostrarlas en /hoy) pero los avisos las saltan.
    """
    dia = fecha.strftime("%Y-%m-%d")
    resultado = []
    for c in clases_del_dia(fecha):
        fila = db.obtener_evento("clase:" + c["codigo"])
        if fila and fila["estado"] == "borrado":
            continue                           # El usuario borro la serie completa
        c = dict(c, nota="")
        exc = db.excepcion("clase:" + c["codigo"], dia)
        if exc and exc["estado"] == "cancelada":
            c["nota"] = "cancelada"
        elif exc and exc["estado"] == "movida":
            if exc["nuevo_inicio"][:10] != dia:
                continue                       # se movio a otro dia
            c.update(inicio=exc["nuevo_inicio"][11:16], fin=(exc["nuevo_fin"] or "")[11:16] or c["fin"],
                     nota="movida")
        resultado.append(c)
    codigos = {c["codigo"]: c for c in leer_json("horario_clases.json")["clases"]}
    for exc in db.movidas_hacia(dia):
        codigo = exc["clave"].split(":", 1)[1]
        if exc["fecha"] != dia and codigo in codigos:
            resultado.append(dict(codigos[codigo], inicio=exc["nuevo_inicio"][11:16],
                                  fin=(exc["nuevo_fin"] or "")[11:16], nota="movida"))
    return sorted(resultado, key=lambda c: c["inicio"])


def hora(texto):
    return datetime.strptime(texto, "%H:%M").time()
