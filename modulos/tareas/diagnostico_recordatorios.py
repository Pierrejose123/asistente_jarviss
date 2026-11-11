"""Muestra de dónde salieron los recordatorios falsos: la prueba del 09-11 dejó su rastro en logs/recordatorios.log,
y ninguno de ellos está en la base del asistente (el bot no los creó)."""
import sys
from contextlib import closing
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from modulos.comun import db  # noqa: E402

log = RAIZ / "logs" / "recordatorios.log"
lineas = [x for x in log.read_text(encoding="utf-8", errors="replace").splitlines() if "Recordatorio #" in x] if log.exists() else []
with closing(db.conectar()) as con:
    try:
        reales = con.execute("SELECT id, titulo, fecha, inicio FROM agenda WHERE nota = 'Recordatorio'").fetchall()
    except Exception:
        reales = []
print("== Registro (logs/recordatorios.log) ==")
por_minuto = {}
for x in lineas:
    por_minuto.setdefault(x[:16], []).append(x)
for minuto, grupo in por_minuto.items():
    print(minuto, "->", len(grupo), "recordatorio(s):", "; ".join(g.split(": ", 1)[-1].split(" | ")[0] for g in grupo[:6]),
          "..." if len(grupo) > 6 else "")
print("\nMuchos en el mismo minuto = la prueba (una persona no crea 30 en un minuto).")
print("\n== Recordatorios guardados de verdad en el asistente ==")
print("\n".join("#%s %s — %s %s" % (r["id"], r["titulo"], r["fecha"], r["inicio"]) for r in reales) or "Ninguno.")
