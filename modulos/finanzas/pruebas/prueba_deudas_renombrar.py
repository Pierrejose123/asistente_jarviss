"""Prueba de CAMBIAR EL NOMBRE de un deudor con frases libres (v2.4, 11-11).
Usa una base TEMPORAL y nunca toca Google ni Telegram.   python modulos\\finanzas\\pruebas\\prueba_deudas_renombrar.py"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from datetime import datetime
from modulos.comun import db
db.ARCHIVO = Path(tempfile.mkdtemp()) / "prueba.db"            # base temporal
from modulos.comun.base import ZONA
from modulos.finanzas import deudas as D
D.ahora = lambda: datetime(2026, 11, 11, 15, 0, tzinfo=ZONA)
D.interpretar_con_ia = lambda t: None
D.subir_google = D.quitar_google = lambda *a, **k: None       # regla: ninguna prueba toca Google


def preparar():
    with D._con() as con:
        con.execute("DELETE FROM deuda_movimientos"); con.execute("DELETE FROM deudas")
    D._ULTIMA.clear()
    D.procesar("Juan me debe 500")
    D.procesar("le debo 200 a mi tío")
    D.procesar("la empresa me debe 683.05 de septiembre y 725.10 de octubre y cada mes se suman 726.10")
    D.procesar("la empresa me pagó 228.10")
    D._ULTIMA.clear()


def nombres():
    return sorted(x["persona"] for x in D.abiertas())


def renombrado(viejo, nuevo, saldo=None):
    def ok():
        ns = nombres()
        if viejo in ns or nuevo not in ns:
            return False
        if saldo is not None:
            d = [x for x in D.abiertas() if x["persona"] == nuevo][0]
            return abs(D.saldo(d["id"]) - saldo) < 0.01
        return True
    return ok


NADA = ["Juan", "la empresa", "mi tío"]
sin_cambios = lambda: nombres() == sorted(NADA)

C = []   # (frase, comprobación, preparación extra)
EMPRESA = [
    "la deuda de la empresa cambia el nombre por Meraki",          # una frase real del usuario (11-11)
    "la deuda de la empresa cambia el nombre por meraki",
    "La deuda de la empresa cámbiale el nombre a Meraki",
    "la deuda de la empresa, cambia el nombre por Meraki",
    "oye Jarvis, la deuda de la empresa cambia el nombre por Meraki porfa",
    "a la deuda de la empresa ponle Meraki",
    "a la empresa ponle de nombre Meraki",
    "ponle Meraki a la empresa",
    "ponle Meraki a la deuda de la empresa",
    "ponle de nombre Meraki a la deuda de la empresa",
    "pon el nombre Meraki a la empresa",
    "cambia el nombre de la empresa por Meraki",
    "cambia el nombre de la empresa a Meraki",
    "cambia el nombre de la empresa como Meraki",
    "cámbiale el nombre a la empresa por Meraki",
    "cambiale el nombre de la deuda de la empresa a Meraki",
    "cambia el nombre de la deuda de la empresa a Meraki",
    "la empresa cámbiale el nombre a Meraki",
    "la empresa cambia de nombre a Meraki",
    "empresa cambia el nombre a Meraki",
    "de la empresa cambia el nombre a Meraki",
    "el nombre de la empresa ahora es Meraki",
    "el nombre de la empresa es Meraki",
    "que la empresa se llame Meraki",
    "quiero que la empresa se llame Meraki",
    "la empresa pasa a llamarse Meraki",
    "la empresa se va a llamar Meraki",
    "la empresa ahora se llama Meraki",
    "la empresa en realidad se llama Meraki",
    "la empresa se llama Meraki",
    "llama Meraki a la empresa",
    "renombra la empresa a Meraki",
    "renombra la deuda de la empresa como Meraki",
    "bautiza a la empresa como Meraki",
    "cambia la empresa por Meraki",
    "cambia el nombre de la empresa a Meraki ahora",
    "cambia el nombre de la empresa a Meraki por favor",
    "¿puedes cambiarle el nombre a la empresa por Meraki?",
    "Jarvis, a la empresa cámbiale el nombre, ponle Meraki",
    "la deuda de la empresa cambiale el nombre a Meraki gracias",
]
for f in EMPRESA:
    C.append((f, renombrado("la empresa", "Meraki", 1180.05), None))
for f in ["cambia el nombre de la deuda de la empresa a Meraki S.A.", "la deuda de la empresa cambia el nombre por Meraki S.A."]:
    C.append((f, renombrado("la empresa", "Meraki S.A.", 1180.05), None))
for f in ["la empresa ahora se llama Banco del Pacífico", "cambia el nombre de la empresa a Banco del Pacífico"]:
    C.append((f, renombrado("la empresa", "Banco del Pacífico"), None))
for f in ["Juan ahora se llama Juan Pérez", "cambia el nombre de Juan a Juan Pérez", "a Juan ponle Juan Pérez",
          "la deuda de Juan cambia el nombre por Juan Pérez", "ponle Juan Pérez a Juan", "que Juan se llame Juan Pérez"]:
    C.append((f, renombrado("Juan", "Juan Pérez", 500), None))
for f in ["cambia el nombre de mi tío a tío Carlos", "la deuda de mi tío cambia el nombre por tío Carlos", "mi tío se llama tío Carlos"]:
    C.append((f, renombrado("mi tío", "Tío Carlos", 200), None))
# sin decir de quién: usa la última deuda que tocó (aquí, la empresa)
tocar_empresa = lambda: D.procesar("la empresa me pagó 1")
for f in ["cámbiale el nombre a Meraki", "cambia el nombre a Meraki", "ponle de nombre a esa deuda Meraki".replace(" a esa deuda", ""),
          "cambia el nombre de esa deuda a Meraki", "a esa deuda cámbiale el nombre a Meraki"]:
    C.append((f, renombrado("la empresa", "Meraki", 1179.05), tocar_empresa))
# sin decir de quién y con varias deudas: pregunta, no cambia nada
C.append(("cámbiale el nombre a Meraki", sin_cambios, None))
# falta el nombre nuevo: no cambia nada (pide el nombre)
for f in ["cambiale el nombre a la empresa", "la deuda de la empresa cambia el nombre", "cambia el nombre de la deuda"]:
    C.append((f, sin_cambios, None))
# ya existe OTRA deuda abierta con ese nombre: no mezcla
C.append(("cambia el nombre de la empresa a Juan", sin_cambios, None))

# --- frases que NO son cambiar nombre: nada debe renombrarse ---
NO = ["Juan me debe 50", "mis deudas", "¿cuánto me debe la empresa?", "la empresa me pagó 100", "cambia la deuda de Juan a 350",
      "¿cómo se llama la empresa?", "¿cuál es el nombre de la deuda de Juan?", "recuérdame llamar a Juan", "llama a Juan",
      "llama a Juan para cobrarle", "llama a Juan mañana", "ponle una alerta a Juan", "ponle una nota a la empresa",
      "ponle fecha límite a Juan", "le debo 100 a mi tío", "Juan me abonó 50", "borra la deuda de Juan",
      "súbele 50 a Juan", "septiembre fue 700", "cambia la fecha de Juan al 30/11", "cambia el motivo de Juan a la laptop",
      "cambia el nombre del archivo a foto", "el nombre de mi perro es Max", "cómo se llama mi tío",
      "dile a Juan que me pague", "ponle Juan a la tarea", "Juan se llama así por su abuelo"]


def no_renombra(f):
    def ok():
        d = D.interpretar(f)
        return not d or d.get("accion") not in ("renombrar",)
    return ok


bien, mal = 0, []
for frase, comprobar, extra in C:
    preparar()
    if extra:
        extra()
    r = D.procesar(frase)
    try:
        ok = comprobar()
    except Exception as exc:
        ok, r = False, "ERROR " + str(exc)
    if ok:
        bien += 1
    else:
        mal.append((frase, r, nombres()))
for frase in NO:
    preparar()
    if no_renombra(frase)():
        bien += 1
    else:
        mal.append((frase, "lo tomó como cambio de nombre: " + str(D.interpretar(frase)), nombres()))

total = len(C) + len(NO)
print("RENOMBRAR:", total, "| BIEN:", bien, "| MAL:", len(mal))
for frase, r, ns in mal:
    print("  MAL:", frase, "=>", r, "| deudas:", ns)
