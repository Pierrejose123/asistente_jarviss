"""Prueba del bloque «Dinero» del resumen matutino (19-11). Datos INVENTADOS, base temporal.
    .\\.venv\\Scripts\\python.exe modulos\\resumen\\pruebas\\prueba_dinero_resumen.py
"""
import sys
import tempfile
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
CONSOLA = sys.__stdout__

from modulos.comun import db  # noqa: E402

db.ARCHIVO = Path(tempfile.mkdtemp()) / "prueba_dinero_resumen.db"
from modulos.comun import modo_prueba  # noqa: E402

assert modo_prueba.activo(), "La protección de pruebas no está activa: no sigo."
from modulos.resumen import resumen as R  # noqa: E402

fallos, total = [], 0


def ok(cond, que):
    global total
    total += 1
    if not cond:
        fallos.append(que)


HOY = date(2026, 11, 20)
T = [{"tarjeta": "Tarjeta A", "fecha_max": "2026-11-22", "falta": 150.5, "minimo": 20.0, "pagada": False},
     {"tarjeta": "Tarjeta B", "fecha_max": "2026-11-30", "falta": 80.0, "minimo": None, "pagada": False},
     {"tarjeta": "Tarjeta C", "fecha_max": "2026-11-21", "falta": 0, "minimo": None, "pagada": True},
     {"tarjeta": "Tarjeta D", "fecha_max": "2026-11-18", "falta": 297.52, "minimo": 433.46, "pagado": 400.0,
      "pagada": False},
     {"tarjeta": "Tarjeta F", "fecha_max": "2026-11-16", "falta": 32.25, "minimo": 20.25, "pagado": 370.0,
      "pagada": False},
     {"tarjeta": "Tarjeta G", "fecha_max": "2026-10-01", "falta": 50.0, "minimo": 100.0, "pagado": 0, "pagada": False},
     {"tarjeta": "Tarjeta E", "fecha_max": None, "falta": 0, "minimo": None, "pagada": False}]
l = R.lineas_dinero(HOY, T, 450.0, 1000.0)
txt = "\n".join(l)
ok(l and l[0].startswith("💰"), "tiene título")
ok("Tarjeta A" in txt and "$150,50" in txt and "22/11" in txt and "en 2 días" in txt and "mínimo $20,00" in txt,
   "tarjeta que vence en 2 días: " + txt)
ok("Tarjeta B" not in txt, "la que vence en 10 días no sale")
ok("Tarjeta C" not in txt, "la pagada no sale")
ok("Tarjeta D" in txt and "no cubrió el mínimo" in txt and "$33,46" in txt, "vencida sin cubrir el mínimo: avisa lo que falta")
ok("Tarjeta F" not in txt, "vencida pero con el mínimo pagado: no sale (el resto pasa a crédito)")
ok("Tarjeta G" not in txt, "vencida hace más de 15 días: ya no se repite")
ok("Tarjeta E" not in txt, "sin estado de cuenta no sale")
ok("$450,00 de $1.000,00 (45 %)" in txt and "⚠️" not in txt.split("Gastado")[1], "gasto del mes")
ok("⚠️" in "\n".join(R.lineas_dinero(HOY, [], 950.0, 1000.0)), "aviso si ya gastó 90 % o más")
ok(R.lineas_dinero(HOY, [], 0.0, 0.0) == [], "sin datos no muestra nada")
ok("mañana" in "\n".join(R.lineas_dinero(HOY, [dict(T[0], fecha_max="2026-11-21")], 0, 0)), "vence mañana")
ok("hoy" in "\n".join(R.lineas_dinero(HOY, [dict(T[0], fecha_max="2026-11-20")], 0, 0)), "vence hoy")
ok("&lt;" in "\n".join(R.lineas_dinero(HOY, [dict(T[0], tarjeta="<x>")], 0, 0)), "escapa el HTML")

if fallos:
    CONSOLA.write("DINERO RESUMEN: FALLOS %d\n" % len(fallos) + "".join(" - %s\n" % f for f in fallos))
    sys.exit(1)
CONSOLA.write("DINERO RESUMEN: TODO BIEN %d de %d\n" % (total, total))
