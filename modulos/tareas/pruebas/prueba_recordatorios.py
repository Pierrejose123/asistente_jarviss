"""Prueba (base TEMPORAL, no toca sus datos): cientos de formas de pedir un recordatorio."""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import tempfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from modulos.comun import db  # noqa: E402

db.ARCHIVO = Path(tempfile.mkdtemp()) / "prueba.db"

# SEGURIDAD: una prueba NUNCA toca Google Calendar (si lo intenta, falla aquí y no sale nada de la PC)
from modulos.calendario import google_cal as _gc  # noqa: E402


def _sin_google(*a, **k):
    raise RuntimeError("prueba: Google Calendar desactivado")


_gc.servicio = _sin_google
from modulos.comun.base import ZONA  # noqa: E402
from modulos.tareas import recordatorios as rc  # noqa: E402

rc._pregunta_anterior = lambda: None
AHORA = datetime(2026, 11, 9, 10, 0, tzinfo=ZONA)          # lunes 09/11 10:00
LUN, MAR, MIE, JUE, VIE, SAB, DOM = (date(2026, 11, d) for d in range(9, 16))
TODOS = "lunes,martes,miercoles,jueves,viernes,sabado,domingo"
LV = "lunes,martes,miercoles,jueves,viernes"
fallos, total = [], 0


def ver(frase, desc=None, fecha=None, hora=None, dias="", hasta=None):
    global total
    total += 1
    r = rc.interpretar(frase, AHORA)
    malo = []
    if desc is not None and r["desc"].lower() != desc.lower():
        malo.append("desc=" + repr(r["desc"]))
    if r["fecha"] != fecha:
        malo.append("fecha=" + str(r["fecha"]))
    if r["hora"] != hora:
        malo.append("hora=" + str(r["hora"]))
    if r["dias"] != dias:
        malo.append("dias=" + r["dias"])
    if r["hasta"] != hasta:
        malo.append("hasta=" + str(r["hasta"]))
    if malo:
        fallos.append(frase)
        print("FALLA", frase, "->", ", ".join(malo))


# --- un día, distintas formas de pedirlo
for pide in ["recuérdame", "Recuerdame", "recordarme", "me recuerdas", "puedes recordarme", "podrías recordarme",
             "quiero que me recuerdes", "necesito que me recuerdes", "acuérdame", "hazme acordar",
             "no me dejes olvidar", "pon un recordatorio para", "ponme una alarma para", "crea un recordatorio de",
             "que no se me olvide", "oye recuérdame por favor", "recuérdame porfa"]:
    ver(pide + " comprar pinceles el viernes", "comprar pinceles", VIE)
    ver(pide + " llamar a María mañana a las 5", "llamar a María", MAR, "17:00")
for cuando, f, h in [("este viernes", VIE, None), ("para este viernes", VIE, None), ("el viernes", VIE, None),
                     ("el próximo viernes", VIE, None), ("el viernes que viene", VIE, None),
                     ("para el viernes", VIE, None), ("mañana", MAR, None), ("pasado mañana", MIE, None),
                     ("hoy a las 8 de la noche", LUN, "20:00"), ("esta noche", LUN, "20:00"),
                     ("esta tarde", LUN, "15:00"), ("mañana en la mañana", MAR, "09:00"),
                     ("mañana por la tarde", MAR, "15:00"), ("mañana temprano", MAR, "08:00"),
                     ("el jueves a las 7:30", JUE, "07:30"), ("el jueves a las 7:30 pm", JUE, "19:30"),
                     ("el 13", VIE, None), ("el 13/11", VIE, None), ("el 13 de noviembre", VIE, None),
                     ("13/11 a las 15:00", VIE, "15:00"), ("en 3 días", JUE, None), ("dentro de 2 días", MIE, None),
                     ("el sábado al mediodía", SAB, "12:00"), ("el fin de semana", SAB, None),
                     ("la próxima semana", date(2026, 11, 16), None), ("el lunes de la próxima semana", date(2026, 11, 16), None),
                     ("el domingo a las 10 de la mañana", DOM, "10:00"), ("el miércoles a las 3 y media", MIE, "15:30"),
                     ("el martes a las 6 menos cuarto", MAR, "17:45"), ("mañana a las 9am", MAR, "09:00"),
                     ("mañana a las 12", MAR, "12:00"), ("el 20", date(2026, 11, 20), None),
                     ("el 2", date(2026, 12, 2), None), ("a fin de mes", date(2026, 11, 30), None)]:
    ver("recuérdame pagar la luz " + cuando, "pagar la luz", f, h)
    ver("recuérdame " + cuando + " pagar la luz", "pagar la luz", f, h)
ver("recuérdame en 2 horas sacar la ropa", "sacar la ropa", LUN, "12:00")
ver("recuérdame en 30 minutos apagar el horno", "apagar el horno", LUN, "10:30")
ver("avísame en media hora que salga", "salga", LUN, "10:30")
ver("recuérdame dentro de una hora tomar agua", "tomar agua", LUN, "11:00")
ver("recuérdame a las 5 llamar al banco", "llamar al banco", None, "17:00")
ver("recuérdame a las 11 la reunión", "reunión", None, "11:00")
# --- repetidos
ver("recuérdame tomar agua todos los días", "tomar agua", None, None, TODOS)
ver("recuérdame tomar agua todos los días a las 10", "tomar agua", None, "10:00", TODOS)
ver("recuérdame cada día a las 8 de la noche estudiar inglés", "estudiar inglés", None, "20:00", TODOS)
ver("recuérdame estudiar inglés a diario", "estudiar inglés", None, None, TODOS)
ver("recuérdame de lunes a viernes a las 7 hacer ejercicio", "hacer ejercicio", None, "07:00", LV)
ver("recuérdame entre semana hacer ejercicio", "hacer ejercicio", None, None, LV)
ver("recuérdame los fines de semana regar las plantas", "regar las plantas", None, None, "sabado,domingo")
ver("recuérdame los martes y jueves sacar la basura", "sacar la basura", None, None, "martes,jueves")
ver("recuérdame cada lunes revisar el presupuesto", "revisar el presupuesto", None, None, "lunes")
ver("recuérdame todos los lunes, miércoles y viernes ir al gym", "ir al gym", None, None, "lunes,miercoles,viernes")
ver("recuérdame toda la semana tomar la pastilla", "tomar la pastilla", None, None, TODOS, DOM)
ver("recuérdame tomar la pastilla durante esta semana", "tomar la pastilla", None, None, TODOS, DOM)
ver("recuérdame toda la semana para este viernes entregar el ensayo", "entregar el ensayo", None, None, TODOS, VIE)
ver("recuérdame el ensayo para el viernes toda la semana", "ensayo", None, None, TODOS, VIE)
ver("recuérdame todos los días hasta el viernes entregar el ensayo", "entregar el ensayo", None, None, TODOS, VIE)
ver("recuérdame entregar el ensayo hasta el viernes", "entregar el ensayo", None, None, TODOS, VIE)
ver("recuérdame tomar el antibiótico por 5 días", "tomar el antibiótico", None, None, TODOS, date(2026, 11, 13))
ver("recuérdame durante 3 días hacer los estiramientos", "hacer los estiramientos", None, None, TODOS, MIE)
ver("recuérdame todas las noches lavarme los dientes", "lavarme los dientes", None, "20:00", TODOS)
ver("recuérdame todas las mañanas tomar vitaminas", "tomar vitaminas", None, "09:00", TODOS)
ver("recuérdame cada semana el viernes pagar la renta", "pagar la renta", None, None, "viernes")
ver("recuérdame hasta el 20/11 practicar", "practicar", None, None, TODOS, date(2026, 11, 20))

# --- conversaciones (la respuesta llega en otro mensaje)
def charla(*mensajes, contiene=(), no_contiene=()):
    global total
    total += 1
    rc.PENDIENTE.clear()
    rc.ULTIMO.clear()
    r = None
    for m in mensajes:
        r = rc.procesar(m, AHORA)
    ok = r is not None and all(c in r for c in contiene) and not any(c in r for c in no_contiene)
    if not ok:
        fallos.append(" / ".join(mensajes))
        print("FALLA", " / ".join(mensajes), "->", r)

charla("recuérdame comprar pan", "el viernes", contiene=("Le recordaré «Comprar pan» el viernes 13/11 a las 09:00",))
charla("recuérdame comprar pan", "toda la semana", contiene=("todos los días", "hasta el domingo 15/11"))
charla("recuérdame entregar el ensayo para este viernes", contiene=("viernes 13/11",))
charla("recuérdame algo para el viernes", "comprar pinceles", contiene=("«Comprar pinceles» el viernes 13/11",))
charla("recuérdame algo", "llamar a mamá", "mañana a las 6", contiene=("«Llamar a mamá» mañana a las 18:00",))
charla("recuérdame comprar pan hoy", "5", contiene=("hoy a las 17:00",))
charla("recuérdame comprar pan hoy", "a las 7 de la noche", contiene=("hoy a las 19:00",))
charla("recuérdame comprar pan", "de lunes a viernes a las 7", contiene=("de lunes a viernes a las 07:00",))
charla("recuérdame hoy a las 8 de la mañana sacar la basura", contiene=("ya pasó",))
charla("pon un recordatorio cada hora para tomar agua", contiene=("no cada hora",))
charla("qué recordatorios tengo", contiene=("«", ) if False else ("recordatorios",))
charla("recuérdame comprar pan", "no", contiene=("no lo anoto",))
charla("recuérdame entregar el ensayo el viernes", "no, mejor toda la semana", contiene=("lo cambié", "todos los días", "hasta el viernes 13/11"))
charla("recuérdame entregar el ensayo el viernes", "mejor a las 7 de la noche", contiene=("lo cambié", "viernes 13/11 a las 19:00"))
charla("recuérdame pagar la luz mañana a las 5", "mejor el jueves", contiene=("lo cambié", "jueves 12/11 a las 17:00"))

# --- lo que NO es un recordatorio
for f in ["hola", "qué tengo hoy", "Juan me debe 300", "gasté 20 en comida", "¿para cuándo es el ensayo?",
          "avísame cuando AMZN baje a 180", "anota el deber de multimedia para el viernes", "¿te acuerdas de mi PC?",
          "recuerdo que tenía clase", "no me acuerdo de la contraseña", "recuérdame que Juan me debe 300",
          "recuerda que prefiero estudiar de noche"]:
    total += 1
    rc.PENDIENTE.clear()
    rc.ULTIMO.clear()
    if rc.procesar(f, AHORA) is not None:
        fallos.append(f)
        print("FALLA (no debía responder)", f)

for m in ["recuérdame comprar pan", "toda la semana"]:
    print("  ", m, "->", rc.procesar(m, AHORA))
rc.ULTIMO.clear()
print("\nRESULTADO:", total - len(fallos), "/", total, "bien")
sys.exit(1 if fallos else 0)
