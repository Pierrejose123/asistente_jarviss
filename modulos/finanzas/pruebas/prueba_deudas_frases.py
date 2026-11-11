import sys, itertools, random; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from datetime import datetime
from modulos.comun.base import ZONA
from modulos.finanzas import deudas as D
D.ahora = lambda: datetime(2026, 11, 9, 14, 0, tzinfo=ZONA)
D.abiertas = lambda persona=None, sentido=None: []          # parser puro, sin base
random.seed(7)
PERS = ["Juan", "la empresa", "mi tío", "Ana María", "mi jefe", "Carlos", "el trabajo", "mi hermana", "Pedro", "la oficina",
        "mi primo Luis", "Don Jorge", "Valeria", "mi mamá", "el banco"]
MONTOS = [("500", 500), ("$500", 500), ("500 dólares", 500), ("1.250,50", 1250.5), ("1,250.50", 1250.5), ("12,5", 12.5),
          ("683.05", 683.05), ("683 con 05", 683.05), ("45 usd", 45), ("$ 80", 80), ("2000", 2000), ("7.50", 7.5)]
CONC = ["la laptop", "el celular", "la cena", "el arriendo", "unos zapatos"]
casos = []   # (frase, accion_esperada, persona, monto)
ME = ["{p} me debe {m}", "{p} me debe {m} por {c}", "me debe {m} {p}", "{p} me quedó debiendo {m}", "{p} me adeuda {m}",
      "le presté {m} a {p}", "le preste {m} a {p} para {c}", "anota que {p} me debe {m}", "oye jarvis, {p} me debe {m}",
      "{p} me tiene que pagar {m}", "tengo por cobrar {m} a {p}", "{p} me pidió prestado {m}", "{p} todavía me debe {m}",
      "{P} me debe {m} señor", "apunta que {p} me debe {m} por {c}", "{p} aún me debe {m}", "registra que le presté {m} a {p}",
      "{p} me está debiendo {m}", "Jarvis, le presté {m} a {p}", "{p} me debe {m}."]
YO = ["le debo {m} a {p}", "debo {m} a {p}", "{p} me prestó {m}", "tengo que pagarle {m} a {p}", "le tengo que devolver {m} a {p}",
      "estoy debiendo {m} a {p}", "anota que le debo {m} a {p}", "le debo {m} a {p} por {c}", "{p} me prestó {m} para {c}",
      "oye, le debo {m} a {p}"]
PME = ["{p} me pagó {m}", "{p} me abonó {m}", "{p} ya me pagó {m}", "{p} me devolvió {m}", "{p} me depositó {m}",
       "{p} me transfirió {m}", "recibí {m} de {p}", "{p} me mandó {m}", "anota que {p} me pagó {m}", "{P} me abonó {m} hoy"]
PYO = ["le pagué {m} a {p}", "le aboné {m} a {p}", "le devolví {m} a {p}", "le transferí {m} a {p}", "ya le pagué {m} a {p}",
       "pagué {m} a {p}", "le deposité {m} a {p}"]
PREG_ME = ["cuánto me debe {p}", "¿{p} cuánto me debe?", "qué me debe {p}", "dime cuánto me debe {p}", "cuánto me falta cobrar de {p}",
           "cómo va la deuda de {p}", "saldo de la deuda de {p}", "¿Cuánto me debe {p}?", "cuanto me debe {p} todavía"]
PREG_YO = ["cuánto le debo a {p}", "¿cuánto le debo a {p}?", "qué le debo a {p}", "dime cuánto le debo a {p}"]
for t, (p, (mt, mv)) in itertools.product(ME, itertools.product(PERS, MONTOS)):
    casos.append(((t),t.format(p=p, P=p[:1].upper() + p[1:], m=mt, c=random.choice(CONC)), "deuda_me", p, mv))
for t, (p, (mt, mv)) in itertools.product(YO, itertools.product(PERS, MONTOS[:8])):
    casos.append(((t),t.format(p=p, P=p, m=mt, c=random.choice(CONC)), "deuda_yo", p, mv))
for t, (p, (mt, mv)) in itertools.product(PME, itertools.product(PERS, MONTOS[:6])):
    casos.append(((t),t.format(p=p, P=p[:1].upper() + p[1:], m=mt), "pago_me", p, mv))
for t, (p, (mt, mv)) in itertools.product(PYO, itertools.product(PERS, MONTOS[:6])):
    casos.append(((t),t.format(p=p, m=mt), "pago_yo", p, mv))
for t, p in itertools.product(PREG_ME, PERS):
    casos.append(((t),t.format(p=p), "pregunta_me", p, None))
for t, p in itertools.product(PREG_YO, PERS):
    casos.append(((t),t.format(p=p), "pregunta_yo", p, None))
for t in ["{p} me pagó todo", "{p} ya me pagó todo lo que me debía", "{p} me pagó septiembre", "{p} me pagó lo de octubre",
          "{p} me depositó lo de septiembre"]:
    for p in PERS:
        casos.append(((t),t.format(p=p), "pago_me", p, None))
LISTAS = [("quién me debe", "lista_me"), ("quiénes me deben", "lista_me"), ("cuánto me deben", "lista_me"),
          ("¿quién me debe plata?", "lista_me"), ("cuentas por cobrar", "lista_me"), ("cuánto tengo por cobrar", "lista_me"),
          ("a quién le debo", "lista_yo"), ("cuánto debo", "lista_yo"), ("¿a quiénes les debo?", "lista_yo"),
          ("mis deudas", "lista"), ("deudas", "lista"), ("ver deudas", "lista"), ("qué deudas tengo", "lista"),
          ("muéstrame mis deudas", "lista"), ("dime las deudas", "lista")]
for f, a in LISTAS:
    casos.append(("LISTA", f, a, None, None))
MULTI = ["la empresa me debe 683.05 de septiembre y 725.10 de octubre",
         "{p} me debe septiembre 683.05 y octubre 725.10",
         "{p} me debe 683.05 del mes de septiembre, 725.10 del mes de octubre y cada mes se suman 726.10",
         "{p} me debe 683.05 de sept y 725.10 de oct. Mensualmente se suman 726.10",
         "683.05 eso me deben de septiembre y 725.10 de octubre. {P} me debe eso, cada vez que llegue otro mes , se suma 726.10",
         "anota que {p} me debe 683.05 de septiembre y 725.10 de octubre, y todos los meses se agregan 726.10",
         "{p}: septiembre 683.05, octubre 725.10 me deben"]
for t, p in itertools.product(MULTI, ["la empresa", "el trabajo", "mi jefe", "Juan"]):
    casos.append(((t),t.format(p=p, P=p[:1].upper() + p[1:]), "multi", p if "{p}" in t or "{P}" in t else "la empresa", None))
NO = ["almuerzo 4.50", "gasté 15 en el super", "debo estudiar para el examen", "me pagaron el sueldo 800", "tengo 25 años",
      "la clase es a las 7", "uber 3,20 con diners", "Juan vino a casa", "qué tal el día", "recuérdame pagar la luz el 15",
      "debo entregar la tarea el viernes", "pagué 30 de internet ayer", "sueldo 700", "cuánto gasté este mes", "hola",
      "pon una alarma a las 6", "el examen vale 20 puntos", "nivel 5 completado", "compré pan por 2", "netflix 15.99",
      "recibí el paquete", "mi tío vino de visita", "debo ir al gimnasio", "la empresa abrió una sucursal", "qué hora es"]
for f in NO:
    casos.append(("NO", f, None, None, None))
print("FRASES:", len(casos))
fallos = []
for tpl, f, accion, p, monto in casos:
    try:
        r = D.interpretar(f)
    except Exception as e:
        fallos.append((tpl, f, "EXC " + str(e))); continue
    if accion is None:
        if r: fallos.append((tpl, f, "no era deuda -> " + str(r)))
        continue
    if not r:
        fallos.append((tpl, f, "no entendido")); continue
    if accion == "multi":
        ok = r["accion"] == "deuda_me" and len(r["cargos"]) == 2 and [c["mes"] for c in r["cargos"]] == [9, 10] \
             and D._norm(r["persona"]) == D._norm(p) and (r["recurrente"] == 726.1) == ("726" in f)
        if not ok: fallos.append((tpl, f, r))
        continue
    if r["accion"] != accion:
        fallos.append((tpl, f, "accion " + r["accion"])); continue
    if p and D._norm(r.get("persona") or "") != D._norm(p):
        fallos.append((tpl, f, "persona " + str(r.get("persona")))); continue
    if monto is not None and abs((r.get("monto") or 0) - monto) > 0.001:
        fallos.append((tpl, f, "monto " + str(r.get("monto")))); continue
print("BIEN:", len(casos) - len(fallos), "| MAL:", len(fallos))
import collections
por = collections.defaultdict(list)
for tpl, f, e in fallos: por[tpl].append((f, e))
for tpl, l in sorted(por.items(), key=lambda x: -len(x[1])):
    print("%4d  %-55s | ej: %s => %s" % (len(l), tpl[:55], l[0][0][:70], str(l[0][1])[:110]))
