"""Fase 1, paso 5 (version simple): recordatorio de entrenamiento y registro de si se hizo.

El usuario tiene un hábito diario (p. ej. ejercicios); el asistente NO indica ejercicios,
solo recuerda y anota "lo hice" / "hoy no".
"""
from contextlib import closing
from datetime import timedelta

from modulos.comun import db
from modulos.comun.base import DIAS, DIAS_BONITO, CONFIG, ahora, leer_json

ESQUEMA = """
CREATE TABLE IF NOT EXISTS habitos (
    fecha   TEXT NOT NULL,
    habito  TEXT NOT NULL,
    valor   TEXT NOT NULL,          -- si | no
    momento TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fecha, habito)
);
"""


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def config():
    if not (CONFIG / "habitos.json").exists():
        return None
    return leer_json("habitos.json").get("entrenamiento")


def nombre():
    """Cómo se llama el hábito («Entrenamiento», «Estiramientos»…): config/habitos.json → entrenamiento.nombre."""
    return ((config() or {}).get("nombre") or "Entrenamiento").strip()


def toca_hoy(fecha=None):
    e = config()
    fecha = fecha or ahora()
    if not e or DIAS[fecha.weekday()] not in e.get("dias", []):
        return False
    exc = db.excepcion("habito:entrenamiento", fecha.date().isoformat())
    return not (exc and exc["estado"] == "cancelada")


def registrar(valor, fecha=None):
    dia = (fecha or ahora()).date().isoformat()
    with closing(_con()) as con, con:
        con.execute("INSERT OR REPLACE INTO habitos (fecha, habito, valor) VALUES (?, 'entrenamiento', ?)",
                    (dia, valor))


def resumen_semana():
    hoy = ahora()
    lineas, hechos, tocaban = [], 0, 0
    with closing(_con()) as con:
        for i in range(6, -1, -1):
            d = hoy - timedelta(days=i)
            fila = con.execute("SELECT valor FROM habitos WHERE fecha = ? AND habito = 'entrenamiento'",
                               (d.date().isoformat(),)).fetchone()
            toca = toca_hoy(d)
            if toca:
                tocaban += 1
            if fila and fila["valor"] == "si":
                hechos += 1
                marca = "✅"
            elif fila:
                marca = "➖"
            else:
                marca = "❔" if toca else "·"
            lineas.append(marca + " " + DIAS_BONITO[d.weekday()][:3].capitalize() + " " + d.strftime("%d/%m"))
    return ("<b>" + nombre() + " – últimos 7 días</b>\n" + "\n".join(lineas)
            + "\n\n" + str(hechos) + " de " + str(tocaban) + " días previstos.\n"
            "✅ hecho  ➖ hoy no  ❔ sin registrar")


def registro_de(fecha):
    """'si', 'no' o None para el dia indicado."""
    with closing(_con()) as con:
        fila = con.execute("SELECT valor FROM habitos WHERE fecha = ? AND habito = 'entrenamiento'",
                           (fecha.date().isoformat(),)).fetchone()
    return fila["valor"] if fila else None
