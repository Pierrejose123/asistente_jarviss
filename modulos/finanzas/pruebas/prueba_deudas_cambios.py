"""Prueba de CAMBIOS a deudas existentes (saldo, subir, bajar, mes, suma mensual, motivo, fecha, al revés, pagos, nombre).
Usa una base TEMPORAL: nunca toca sus datos reales.   python modulos\\finanzas\\pruebas\\prueba_deudas_cambios.py"""
import sys, tempfile, itertools
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from datetime import datetime
from modulos.comun import db
db.ARCHIVO = Path(tempfile.mkdtemp()) / "prueba.db"            # base temporal
from modulos.comun.base import ZONA
from modulos.finanzas import deudas as D
D.ahora = lambda: datetime(2026, 11, 9, 17, 30, tzinfo=ZONA)
D.interpretar_con_ia = lambda t: None
D.subir_google = D.quitar_google = lambda *a, **k: None

def preparar():
    with D._con() as con:
        con.execute("DELETE FROM deuda_movimientos"); con.execute("DELETE FROM deudas")
    D._ULTIMA.clear()
    D.procesar("Juan me debe 500")
    D.procesar("le debo 200 a mi tío")
    D.procesar("la empresa me debe 683.05 de septiembre y 725.10 de octubre y cada mes se suman 726.10")
    D.procesar("Juan me abonó 100")
    D._ULTIMA.clear()

def saldo(nombre):
    ds = D._todas(nombre)
    return round(sum(D.saldo(x["id"]) for x in ds), 2) if ds else None

C = []   # (frase, comprobación)
for f in ["cambia la deuda de Juan a 350", "corrige lo que me debe Juan a 350", "pon el saldo de Juan en 350", "ajusta la cuenta de Juan a 350",
          "Juan en realidad me debe 350", "Juan ahora me debe 350", "en realidad Juan me debe 350", "Juan me debe 350, no 400",
          "Juan no me debe 400, me debe 350", "el saldo de Juan es 350", "lo que me debe Juan es de 350", "deja la deuda de Juan en 350",
          "modifica lo que me debe Juan a 350 dólares", "cambia a Juan a 350", "actualiza la deuda de juan en $350", "corrijo: Juan me debe 350",
          "pon la deuda en 350 a Juan", "la deuda de Juan debería ser 350", "Juan al final me debe 350", "me equivoqué, Juan me debe 350"]:
    C.append((f, lambda: saldo("Juan") == 350))
for f in ["súbele 50 a Juan", "súmale 50 a la deuda de Juan", "aumenta la deuda de Juan en 50", "agrégale 50 a Juan", "Juan me debe 50 más",
          "sube 50 a Juan", "aumenta lo que me debe Juan en 50", "cárgale 50 a Juan", "Juan me debe otros 50", "añádele 50 más a Juan"]:
    C.append((f, lambda: saldo("Juan") == 450))
for f in ["bájale 50 a Juan", "réstale 50 a Juan", "descuéntale 50 a Juan", "quítale 50 a la deuda de Juan", "Juan me debe 50 menos",
          "reduce la deuda de Juan en 50", "rebaja 50 de lo que me debe Juan", "disminuye lo que me debe Juan en 50", "baja 50 a Juan", "resta 50 a Juan"]:
    C.append((f, lambda: saldo("Juan") == 350))
for f in ["septiembre fue 700", "corrige septiembre a 700", "cambia septiembre de la empresa a 700", "septiembre era 700 no 683.05",
          "el mes de septiembre fue de 700", "lo de septiembre son 700", "cambia la empresa septiembre a 700", "septiembre no fue 683.05, fue 700",
          "septiembre de la empresa fue 700", "corrige el mes de septiembre en 700"]:
    C.append((f, lambda: saldo("la empresa") == 1425.10))
for f in ["cambia la suma mensual de la empresa a 750", "pon la suma mensual en 750", "ahora se suman 750 cada mes", "cambia lo que se suma cada mes a 750",
          "corrige el monto mensual de la empresa a 750", "que se sumen 750 cada mes a la empresa", "ajusta la cuota mensual a 750"]:
    C.append((f, lambda: D._todas("la empresa")[0]["recurrente"] == 750))
for f in ["ya no sumes nada cada mes", "deja de sumar cada mes a la empresa", "quita la suma mensual de la empresa", "que no se sume nada más",
          "para la suma mensual", "ya no se suma nada cada mes", "elimina la suma mensual"]:
    C.append((f, lambda: not D._todas("la empresa")[0]["recurrente"]))
for f in ["que se sume el 10", "que se sumen el 10 de cada mes", "cambia el día de la suma al 10", "sumalo el 10 de cada mes"]:
    C.append((f, lambda: D._todas("la empresa")[0]["dia_recurrente"] == 10))
for f in ["la deuda de Juan es por la laptop", "lo que me debe Juan es por la laptop", "cambia el motivo de Juan a la laptop", "Juan me debe por la laptop"]:
    C.append((f, lambda: "laptop" in D._todas("Juan")[0]["concepto"]))
for f in ["la fecha límite de Juan es el 30/11", "cambia la fecha de Juan al 30/11", "Juan me paga hasta el 30/11", "el plazo de Juan es el 30/11",
          "Juan tiene hasta el 30/11"]:
    C.append((f, lambda: (D._todas("Juan")[0]["limite"] or "").endswith("11-30")))
for f in ["no, yo le debo a Juan", "al revés, yo le debo a Juan", "soy yo el que le debe a Juan", "es al revés, yo le debo a Juan"]:
    C.append((f, lambda: D._todas("Juan")[0]["sentido"] == "le_debo"))
for f in ["no, mi tío me debe a mí", "al revés, mi tío me debe a mi"]:
    C.append((f, lambda: D._todas("mi tío")[0]["sentido"] == "me_debe"))
for f in ["el último pago de Juan fue 150", "el abono de Juan fue de 150", "corrige el pago de Juan a 150", "Juan me pagó 150, no 100", "cambia el último abono de Juan a 150"]:
    C.append((f, lambda: saldo("Juan") == 350))
for f in ["borra el último pago de Juan", "elimina el abono de Juan"]:
    C.append((f, lambda: saldo("Juan") == 500))
for f in ["cambia Juan por Juan Pérez", "Juan ahora se llama Juan Pérez", "renombra a Juan como Juan Pérez", "no es Juan, es Juan Pérez"]:
    C.append((f, lambda: bool(D._todas("Juan Pérez"))))
NO = ["cambia la clase por la tarde", "pon una alarma a las 10", "sube el volumen", "agrega el 15 a la lista", "baja 2 kilos", "octubre son 30 días",
      "cambia el fondo de pantalla", "que se sume Pedro a la reunión", "ajusta el brillo", "la fecha del examen es el 30/11"]
fallos = []
for f, ok in C:
    preparar()
    r = D.procesar(f)
    try:
        bien = ok()
    except Exception as e:
        bien = False
    if not bien:
        fallos.append((f, r))
for f in NO:
    preparar()
    if D.interpretar(f):
        fallos.append((f, "NO era un cambio de deuda -> " + str(D.interpretar(f).get("accion"))))
print("CAMBIOS:", len(C) + len(NO), "| BIEN:", len(C) + len(NO) - len(fallos), "| MAL:", len(fallos))
for f, r in fallos: print("  MAL:", f, "=>", str(r)[:150].replace("\n", " | "))
