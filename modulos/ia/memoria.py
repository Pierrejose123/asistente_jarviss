"""Memoria del asistente (Fase 2): todo queda en la base local de la PC.

- 'recuerdos': datos permanentes sobre el usuario (preferencias, correcciones, datos estables).
  La IA los guarda sola cuando el usuario dice algo que vale la pena recordar, y se le muestran en cada mensaje.
- 'conversacion': los ultimos mensajes, para que la charla siga aunque el bot se reinicie.
"""
from contextlib import closing

from modulos.comun import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS recuerdos (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    dato   TEXT NOT NULL,
    creado TEXT DEFAULT CURRENT_TIMESTAMP,
    activo INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS conversacion (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    rol       TEXT NOT NULL,
    contenido TEXT NOT NULL,
    momento   TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

INICIALES_EJEMPLO = [   # se usan solo si no existe config/memoria_inicial.json (lista de frases)
    "Prefiere que lo llamen solo 'senor' y que lo traten de usted.",
]


def _iniciales():
    try:
        import json
        from modulos.comun.base import CONFIG
        return json.loads((CONFIG / "memoria_inicial.json").read_text(encoding="utf-8-sig"))
    except Exception:
        return INICIALES_EJEMPLO


INICIALES = _iniciales()


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def _sembrar(con):
    if con.execute("SELECT COUNT(*) FROM recuerdos").fetchone()[0] == 0:
        con.executemany("INSERT INTO recuerdos (dato) VALUES (?)",
                        [(d.replace("senor", "señor").replace("diseno", "diseño").replace("Diseno", "Diseño"),)
                         for d in INICIALES])


def recuerdos():
    with closing(_con()) as con, con:
        _sembrar(con)
        return con.execute("SELECT * FROM recuerdos WHERE activo = 1 ORDER BY id").fetchall()


def recordar(dato):
    dato = " ".join(dato.split())[:300]
    with closing(_con()) as con, con:
        repetido = con.execute("SELECT id FROM recuerdos WHERE activo = 1 AND lower(dato) = lower(?)", (dato,)).fetchone()
        if repetido:
            return repetido["id"]
        return con.execute("INSERT INTO recuerdos (dato) VALUES (?)", (dato,)).lastrowid


def olvidar(rid):
    with closing(_con()) as con, con:
        return con.execute("UPDATE recuerdos SET activo = 0 WHERE id = ? AND activo = 1", (rid,)).rowcount > 0


def actualizar(rid, dato):
    """Reescribe un recuerdo existente (para completar o corregir un dato sin crear otro)."""
    dato = " ".join(dato.split())[:300]
    if not dato:
        return False
    with closing(_con()) as con, con:
        return con.execute("UPDATE recuerdos SET dato = ? WHERE id = ? AND activo = 1", (dato, rid)).rowcount > 0


def historial(n):
    with closing(_con()) as con:
        filas = con.execute("SELECT rol, contenido FROM conversacion ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    return [{"role": f["rol"], "content": f["contenido"]} for f in reversed(filas)]


def guardar_turno(usuario, asistente):
    with closing(_con()) as con, con:
        con.executemany("INSERT INTO conversacion (rol, contenido) VALUES (?, ?)",
                        [("user", usuario), ("assistant", asistente)])
        con.execute("DELETE FROM conversacion WHERE id NOT IN (SELECT id FROM conversacion ORDER BY id DESC LIMIT 200)")


def borrar_conversacion():
    with closing(_con()) as con, con:
        con.execute("DELETE FROM conversacion")
