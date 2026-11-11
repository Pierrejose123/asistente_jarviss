import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from datetime import datetime
from modulos.comun.base import ZONA
from modulos.finanzas import deudas as D
D.ahora = lambda: datetime(2026, 11, 9, 14, 0, tzinfo=ZONA)
D.abiertas = lambda persona=None, sentido=None: []
C = [  # frase, accion, persona, monto
("oye jarvis la empresa me sigue debiendo 725.10 de octubre", "deuda_me", "la empresa", 725.1),
("mi jefe todavia no me paga y me debe 683,05", "deuda_me", "mi jefe", 683.05),
("anotame que el pana kevin me debe 20", "deuda_me", "el pana kevin", 20),
("kevin me debe 20 lucas", "deuda_me", "kevin", 20),
("me deben 50 en la tienda", "deuda_me", "la tienda", 50),
("Le presté 300 dólares a mi prima Sofi para su matrícula", "deuda_me", "mi prima sofi", 300),
("preste 15 a Andres", "deuda_me", "andres", 15),
("le prestamos 100 a la vecina", "deuda_me", "la vecina", 100),
("Andrés me pidió 40 prestados", "deuda_me", "andres", 40),
("la vecina me tiene que devolver 25", "deuda_me", "la vecina", 25),
("tengo que cobrarle 60 a Marco", "deuda_me", "marco", 60),
("mi hermano me debe 1500 del carro", "deuda_me", "mi hermano", 1500),
("Juan me debe $1.000", "deuda_me", "juan", 1000),
("juan me debe mil", None, None, None),
("debo 80 a la tarjeta", "deuda_yo", "la tarjeta", 80),
("le debo a mi tio 200", "deuda_yo", "mi tio", 200),
("a mi tío le debo 200", "deuda_yo", "mi tio", 200),
("mi papá me prestó 500 para el viaje", "deuda_yo", "mi papa", 500),
("me prestaron 100 en el trabajo", "deuda_yo", "el trabajo", 100),
("le quedé debiendo 30 a Pablo", "deuda_yo", "pablo", 30),
("tengo q pagarle 45 a Rosa", "deuda_yo", "rosa", 45),
("kevin ya me pago los 20", "pago_me", "kevin", 20),
("Kevin me pagó 10 de los 20", "pago_me", "kevin", 10),
("la empresa por fin me pagó octubre", "pago_me", "la empresa", None),
("me depositaron 683.05 de la empresa", "pago_me", "la empresa", 683.05),
("la empresa me hizo una transferencia de 725.10", "pago_me", "la empresa", 725.1),
("recibí 300 de mi hermano", "pago_me", "mi hermano", 300),
("ya me pagaron lo de septiembre en la empresa", "pago_me", "la empresa", None),
("Sofi me devolvió todo", "pago_me", "sofi", None),
("le pague 50 a mi tio", "pago_yo", "mi tio", 50),
("ya le devolví los 100 a mi papá", "pago_yo", "mi papa", 100),
("le transferí 30 a Pablo", "pago_yo", "pablo", 30),
("cuanto me debe kevin", "pregunta_me", "kevin", None),
("cuánto es lo que me debe la empresa", "pregunta_me", "la empresa", None),
("la empresa cuánto me debe ya?", "pregunta_me", "la empresa", None),
("cuanto me falta que me pague la empresa", "pregunta_me", "la empresa", None),
("que tanto le debo a mi papa", "pregunta_yo", "mi papa", None),
("cuánto le debo todavía a mi tío", "pregunta_yo", "mi tio", None),
("quien me debe plata", "lista_me", None, None),
("quienes me deben dinero", "lista_me", None, None),
("cuanto me deben en total", "lista_me", None, None),
("cuánto debo en total", "lista_yo", None, None),
("tengo deudas?", "lista", None, None),
("dame un resumen de mis deudas", "lista", None, None),
("borra la deuda de Kevin", "borrar", "kevin", None),
("Jaspharm me debe 3326,22 , me ha hecho 5 abonos", "deuda_me", "jaspharm", 3326.22),
("Juan me debe 300, ya me pagó 3 cuotas", "deuda_me", "juan", 300),
("elimina lo que me debe Jaspharm", "borrar", "jaspharm", None),
("quita la deuda con Jaspharm", "borrar", "jaspharm", None),
("borra la cuenta de la empresa", "borrar", "la empresa", None),
("eliminar todo lo que me debe Jaspharm", "borrar", "jaspharm", None),
("elimina la deuda que tiene Jaspharm", "borrar", "jaspharm", None),
("recupera la deuda de Jaspharm", "recuperar", "jaspharm", None),
("vuelve a poner lo que me debe Kevin", "recuperar", "kevin", None),
("la empresa me debe 726.10 cada mes", "deuda_me", "la empresa", None),
("cada mes la empresa me queda debiendo 726.10", "deuda_me", "la empresa", None),
# no son deudas
("pagué la luz 25", None, None, None), ("debo comprar pan", None, None, None), ("mi tío me visitó ayer", None, None, None),
("la empresa me dio el día libre", None, None, None), ("me pagaron 800 de sueldo", None, None, None),
("debo 3 tareas de animación", None, None, None), ("tengo que pagar el arriendo el 5", None, None, None),
("presta atención a la clase", None, None, None), ("me debes una explicación", None, None, None),
("cuánto cuesta un iphone", None, None, None), ("cuánto gasté en uber", None, None, None),
("almorcé por 6", None, None, None), ("le di like al video", None, None, None),
("me prestó atención la profe", None, None, None), ("debo ir al banco", None, None, None),
]
ok, ia, mal = 0, [], []
for f, a, p, m in C:
    r = D.interpretar(f)
    if a is None:
        if r is None: ok += 1
        else: mal.append((f, "NO era deuda -> " + str({k: r.get(k) for k in ("accion", "persona", "monto")})))
        continue
    if r is None:
        ia.append(f); continue
    bien = r["accion"] == a and (p is None or D._norm(r.get("persona") or "") == D._norm(p)) and (m is None or abs((r.get("monto") or 0) - m) < 0.01)
    if a == "deuda_me" and "cada mes" in f: bien = bien and r.get("recurrente") == 726.1
    if bien: ok += 1
    else: mal.append((f, {k: r.get(k) for k in ("accion", "persona", "monto", "recurrente", "meses")}))
print("TOTAL", len(C), "| bien en código:", ok, "| van a la IA:", len(ia), "| MAL:", len(mal))
for f in ia: print("  IA :", f)
for f, e in mal: print("  MAL:", f, "=>", e)
