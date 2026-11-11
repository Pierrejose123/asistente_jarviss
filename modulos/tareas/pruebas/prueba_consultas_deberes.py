"""Prueba (base TEMPORAL, no toca sus datos): preguntas de deberes y deberes repetidos de Moodle."""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")   # la consola de Windows no muestra emojis sin esto
except Exception:
    pass
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from modulos.comun import db  # noqa: E402

db.ARCHIVO = Path(tempfile.mkdtemp()) / "prueba.db"

# SEGURIDAD: una prueba NUNCA toca Google Calendar (si lo intenta, falla aquí y no sale nada de la PC)
from modulos.calendario import google_cal as _gc  # noqa: E402


def _sin_google(*a, **k):
    raise RuntimeError("prueba: Google Calendar desactivado")


_gc.servicio = _sin_google
from modulos.comun.base import leer_json  # noqa: E402
from modulos.tareas import consultas, tareas  # noqa: E402
from modulos.estudio import moodle  # noqa: E402

HOY = date(2026, 11, 9)
clases = [c["materia"] for c in leer_json("horario_clases.json")["clases"]]
MULTI = next((m for m in clases if "multimedia" in tareas._sin_tildes(m)), clases[0])
OTRA = next((m for m in clases if m != MULTI), "General")
iso = lambda n: (HOY + timedelta(days=n)).isoformat()

ens1 = tareas.crear(MULTI, "S3-Ensayo Bibliográfico_TAU.", iso(6), "23:59")       # entrega
ens2 = tareas.crear(MULTI, "S3-Ensayo Bibliográfico_TAU.", iso(11), "23:59")      # cierre (copia)
ens3 = tareas.crear(MULTI, "S3-Ensayo Bibliográfico_TAU.", iso(11), "23:59")      # copia exacta
foro1 = tareas.crear(OTRA, "Foro semanal", iso(3), "23:59")
foro2 = tareas.crear(OTRA, "Foro semanal", iso(10), "23:59")                       # foro de otra semana: NO se junta
inf = tareas.crear(OTRA, "Informe de color", iso(2), None)

fallos = []
def ver(frase, debe, *contiene):
    r = consultas.procesar(frase, hoy=HOY)
    ok = (r is not None) == debe and all(c in (r or "") for c in contiene)
    if not ok:
        fallos.append((frase, r))
    print(("OK   " if ok else "FALLA"), frase, "->", (r or "None").replace("\n", " | ")[:150])

# --- preguntas que SÍ debe responder
ver("Puedes decirme si tienes registrado el deber que tengo en 6 días de multimedia", True, "Ensayo", "15/11")
ver("Para cuando es el deber del ensayo", True, "Ensayo", "15/11")
ver("para cuándo es el ensayo?", True, "Ensayo")
ver("cuándo entrego el ensayo", True, "Ensayo")
ver("¿Qué deberes tengo de multimedia?", True, "Ensayo")
ver("que tareas tengo esta semana", True, "Informe")
ver("qué entregas tengo mañana", True)
ver("tienes anotado el informe de color?", True, "Informe", "registrado")
ver("hasta cuándo tengo para el informe", True, "Informe")
ver("mis deberes", True, "Ensayo", "Informe")
ver("qué deber tengo pasado mañana", True, "Informe")
ver("está registrado el foro?", True, "Foro")
ver("tengo algún deber de multimedia en 3 días?", True, "Ensayo")   # no exacto: muestra el más cercano
ver("cuando es la maqueta?", True, "No tengo")
# --- cosas que NO son consultas de deberes
for f in ["anota el deber de multimedia para el viernes", "ya entregué el ensayo", "marca el ensayo como hecho",
          "planifica la semana", "cuánto gasté este mes", "Juan me debe 300", "qué tengo hoy", "hola",
          "recuérdame el deber de animación el lunes", "borra la tarea 3", "agéndame el ensayo el sábado",
          "cambia el ensayo al viernes", "la empresa donde trabajo me debe 683", "mueve el bloque del ensayo",
          "qué dice Pepe del video de Nvidia?", "resúmeme el video de Cava", "cuándo sale el video de Cava?",
          "cuáles son mis deudas pendientes?", "qué actividades tengo mañana?", "qué es un ensayo?",
          "cómo hago un buen informe?", "cuánto me falta pagar a Juan?"]:
    ver(f, False)

# --- deberes repetidos de Moodle
with moodle._con() as con:
    con.execute("INSERT INTO moodle_eventos (uid,tipo,titulo,curso,materia,vence,tarea_id) VALUES "
                "('u1','deber','S3-Ensayo Bibliográfico_TAU.','X','',?,?)", (iso(6), ens1))
    con.execute("INSERT INTO moodle_eventos (uid,tipo,titulo,curso,materia,vence,tarea_id) VALUES "
                "('u2','deber','S3-Ensayo Bibliográfico_TAU.','X','',?,?)", (iso(11), ens2))
    con.execute("INSERT INTO moodle_eventos (uid,tipo,titulo,curso,materia,vence,tarea_id) VALUES "
                "('f1','deber','Foro semanal','Y','',?,?)", (iso(3), foro1))
    con.execute("INSERT INTO moodle_eventos (uid,tipo,titulo,curso,materia,vence,tarea_id) VALUES "
                "('f2','deber','Foro semanal','Y','',?,?)", (iso(10), foro2))
    con.commit()
eventos = [{"uid": "u1", "resumen": "S3-Ensayo Bibliográfico_TAU. vence"},
           {"uid": "u2", "resumen": "S3-Ensayo Bibliográfico_TAU. se cierra"},
           {"uid": "f1", "resumen": "Foro semanal vence"}, {"uid": "f2", "resumen": "Foro semanal vence"}]
hecho = moodle.reparar_duplicados(eventos)
print("\n".join(hecho))
estados = {t: tareas.obtener(t)["estado"] for t in (ens1, ens2, ens3, foro1, foro2, inf)}
esperado = {ens1: "pendiente", ens2: "borrada", ens3: "borrada", foro1: "pendiente", foro2: "pendiente", inf: "pendiente"}
print("estados:", estados)
if estados != esperado:
    fallos.append(("repetidos", estados))
if moodle.reparar_duplicados(eventos):
    fallos.append(("repetir no debe hacer nada", ""))
# Moodle nuevo: el cierre no crea tarea si existe la entrega
ev = [{"uid": "a", "resumen": "Mapa mental vence", "curso": "X"}, {"uid": "b", "resumen": "Mapa mental se cierra", "curso": "X"}]
print("clasificar cierre:", [bool(moodle.CIERRE.search(e["resumen"])) for e in ev])
if [bool(moodle.CIERRE.search(e["resumen"])) for e in ev] != [False, True]:
    fallos.append(("cierre", ""))

total = 14 + 22 + 3
print("\nRESULTADO:", total - len(fallos), "/", total, "bien")
sys.exit(1 if fallos else 0)
