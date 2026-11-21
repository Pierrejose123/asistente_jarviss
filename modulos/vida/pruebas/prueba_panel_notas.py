"""Pestaña Cerebro del panel: servidor.notas() con una base TEMPORAL (no toca datos reales ni usa internet)."""
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))

from modulos.comun import db  # noqa: E402

db.ARCHIVO = Path(tempfile.mkdtemp()) / "prueba_panel_notas.db"
from modulos.comun import modo_prueba  # noqa: E402

assert modo_prueba.activo(), "La protección de pruebas no está activa: no sigo."
import requests  # noqa: E402


def _sin_red(*a, **k):
    raise RuntimeError("PRUEBA: sin internet ni IA")


requests.get = requests.post = _sin_red
from modulos.segundo_cerebro import segundo_cerebro as SC  # noqa: E402
from modulos.vida import servidor as S  # noqa: E402

fallos, total = [], 0


def ok(cond, que):
    global total
    total += 1
    if not cond:
        fallos.append(que)


v = S.notas()
ok(v["total"] == 0 and v["notas"] == [], "vacío al principio")
SC.guardar("Ofrecer a abogados un asistente que resuma expedientes", tipo="idea", area="negocio", origen="claude")
SC.guardar("Cobrar 30 dólares al mes por el asistente de abogados", tipo="decision", area="negocio", origen="claude")
SC.guardar("Llegar a nivel C1 de inglés", tipo="meta", area="estudios")
v = S.notas()
ok(v["total"] == 3 and len(v["notas"]) == 3, "lista las últimas: %s" % v["total"])
ok(v["por_tipo"] == {"idea": 1, "decision": 1, "meta": 1} and v["por_area"] == {"negocio": 2, "estudios": 1},
   "cuenta por tipo y área: %s %s" % (v["por_tipo"], v["por_area"]))
ok(v["notas"][0]["texto"].startswith("Llegar") and v["notas"][0]["fecha"] and v["notas"][2]["origen"] == "claude",
   "orden y campos")
ok({n["tipo"] for n in S.notas(tipo="decision")["notas"]} == {"decision"}, "filtra por tipo")
ok({n["area"] for n in S.notas(area="estudios")["notas"]} == {"estudios"}, "filtra por área")
b = S.notas(q="abogados")
ok(len(b["notas"]) == 2 and b["buscado"] == "abogados", "busca por palabra (sin IA)")
ok(S.notas(q="zzzz")["notas"] == [], "búsqueda sin resultados")
ok(len(S.notas(tipo="hackeo", area="x")["notas"]) == 3, "ignora filtros inválidos")

if fallos:
    print("FALLOS:\n" + "\n".join("- " + f for f in fallos))
    sys.exit(1)
print("PANEL NOTAS: TODO BIEN %d de %d" % (total, total))
