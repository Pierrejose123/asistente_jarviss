"""Une los deberes repetidos de Moodle una sola vez (lo corre el instalador). Después lo hace solo en cada revisión."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import requests  # noqa: E402

from modulos.estudio import moodle  # noqa: E402
from modulos.tareas import tareas  # noqa: E402

eventos = []
try:
    r = requests.get(moodle.url(), timeout=60)
    r.raise_for_status()
    eventos = moodle.leer_calendario(r.text)
except Exception as exc:
    print("No pude leer Moodle ahora (se junta igual lo que es seguro):", exc)
hecho = moodle.reparar_duplicados(eventos)
print("\n== Deberes repetidos ==")
print("\n".join(hecho) if hecho else "No había deberes repetidos.")
print("\n== Deberes pendientes ahora ==")
for t in tareas.pendientes():
    print(re.sub(r"<[^>]+>", "", tareas.linea(t)))
