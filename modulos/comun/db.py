"""Base de datos local del asistente (SQLite en datos/asistente.db)."""
import sqlite3
from contextlib import closing

from modulos.comun.base import RAIZ

ARCHIVO = RAIZ / "datos" / "asistente.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS eventos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clave       TEXT UNIQUE NOT NULL,   -- identificador propio, ej. clase:DGPA-3-2
    tipo        TEXT NOT NULL,          -- clase, aviso, tarea, recordatorio...
    titulo      TEXT NOT NULL,
    google_id   TEXT,                   -- id del evento en Google Calendar
    huella      TEXT,                   -- resumen del contenido para saber si cambio
    estado      TEXT DEFAULT 'activo',
    actualizado TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS excepciones (
    clave        TEXT NOT NULL,             -- ej. clase:DGPA-3-3
    fecha        TEXT NOT NULL,             -- fecha original de esa ocurrencia (AAAA-MM-DD)
    estado       TEXT NOT NULL,             -- cancelada | movida
    nuevo_inicio TEXT,                      -- si se movio: fecha y hora nuevas (ISO)
    nuevo_fin    TEXT,
    PRIMARY KEY (clave, fecha)
);
CREATE TABLE IF NOT EXISTS avisos_enviados (
    clave  TEXT PRIMARY KEY,                -- ej. 2026-10-16|clase:DGPA-3-3|abrir
    cuando TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def conectar():
    ARCHIVO.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(ARCHIVO)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def obtener_evento(clave):
    with closing(conectar()) as con:
        return con.execute("SELECT * FROM eventos WHERE clave = ?", (clave,)).fetchone()


def guardar_evento(clave, tipo, titulo, google_id, huella):
    with closing(conectar()) as con, con:
        con.execute(
            """INSERT INTO eventos (clave, tipo, titulo, google_id, huella)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(clave) DO UPDATE SET tipo = excluded.tipo, titulo = excluded.titulo,
                 google_id = excluded.google_id, huella = excluded.huella,
                 estado = 'activo', actualizado = CURRENT_TIMESTAMP""",
            (clave, tipo, titulo, google_id, huella))


def aviso_enviado(clave):
    with closing(conectar()) as con:
        return con.execute("SELECT 1 FROM avisos_enviados WHERE clave = ?", (clave,)).fetchone() is not None


def marcar_aviso(clave):
    with closing(conectar()) as con, con:
        con.execute("INSERT OR IGNORE INTO avisos_enviados (clave) VALUES (?)", (clave,))


def evento_por_google_id(google_id):
    with closing(conectar()) as con:
        return con.execute("SELECT * FROM eventos WHERE google_id = ?", (google_id,)).fetchone()


def marcar_estado(clave, estado):
    with closing(conectar()) as con, con:
        con.execute("UPDATE eventos SET estado = ?, actualizado = CURRENT_TIMESTAMP WHERE clave = ?",
                    (estado, clave))


def guardar_excepcion(clave, fecha, estado, nuevo_inicio=None, nuevo_fin=None):
    with closing(conectar()) as con, con:
        con.execute("INSERT OR REPLACE INTO excepciones VALUES (?, ?, ?, ?, ?)",
                    (clave, fecha, estado, nuevo_inicio, nuevo_fin))


def borrar_excepcion(clave, fecha):
    with closing(conectar()) as con, con:
        con.execute("DELETE FROM excepciones WHERE clave = ? AND fecha = ?", (clave, fecha))


def excepcion(clave, fecha):
    with closing(conectar()) as con:
        return con.execute("SELECT * FROM excepciones WHERE clave = ? AND fecha = ?",
                           (clave, fecha)).fetchone()


def movidas_hacia(fecha):
    """Ocurrencias movidas que ahora caen en 'fecha' (AAAA-MM-DD)."""
    with closing(conectar()) as con:
        return con.execute("SELECT * FROM excepciones WHERE estado = 'movida' AND substr(nuevo_inicio, 1, 10) = ?",
                           (fecha,)).fetchall()
