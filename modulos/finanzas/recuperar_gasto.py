"""Hecho por Claude (19/11/2026): recupera el gasto #76 (Atimasa Ruben $8.97) borrado sin querer
y descarta la pregunta falsa «recupera el gasto $76» que se creó al probar."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contextlib import closing
from modulos.finanzas import gastos

g = gastos.recuperar(76)
print("Recuperado:", gastos.linea(g) if g else "ya estaba activo")
with closing(gastos._con()) as con, con:
    n = con.execute("UPDATE gastos_pendientes SET estado = 'descartado' WHERE estado = 'pendiente' "
                    "AND descripcion LIKE 'recupera el gasto%'").rowcount
print("Preguntas falsas descartadas:", n)
