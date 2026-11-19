"""Prueba de CUENTAS del banco (paso 7, 13-11): lectores de correos de Produbanco y Pichincha, decisiones, botones,
saldo estimado, ajuste del día 1 y frases. Base TEMPORAL; Gmail, Google, Telegram e internet NO se usan.
Los correos son copias del formato real con nombres y números INVENTADOS.
python modulos\\finanzas\\pruebas\\prueba_cuentas.py"""
import json
from contextlib import closing
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from modulos.comun import db  # noqa: E402
TMP = Path(tempfile.mkdtemp())
db.ARCHIVO = TMP / "prueba.db"
from modulos.comun import base  # noqa: E402
from modulos.comun.base import ZONA  # noqa: E402
base.enviar_telegram = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Telegram bloqueado en la prueba"))
try:
    from modulos.calendario import google_cal
    google_cal.servicio = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Google bloqueado en la prueba"))
except Exception:
    pass
from modulos.finanzas import ahorros, cuentas as C, deudas, gastos  # noqa: E402

AHORA = [datetime(2026, 11, 13, 12, 0, tzinfo=ZONA)]
for mod in (C, gastos, deudas, ahorros):
    mod.ahora = lambda: AHORA[0]
gastos.ajustes = lambda: {"medios": {}, "categorias": {"Comida": ["almuerzo"], "Hogar y servicios": ["claro", "internet"],
                                                        "Regalos": [], "Otros": []}}
C.gastos.ajustes = gastos.ajustes

BIEN, MAL = 0, 0


def ver(nombre, cond):
    global BIEN, MAL
    if cond:
        BIEN += 1
    else:
        MAL += 1
        print("MAL:", nombre)


TIT = "MORA PAREDES ANA LUCIA"
P_ENVIADA = ("Estimado/a " + TIT + " Fecha y Hora: 12/11/2026 18:10:05 Transacción: Transferencia Enviada Produbanco Detalle "
             "Beneficiario: Carla Beatriz Torres Vega Banco Beneficiario: Produbanco Cuenta Beneficiario: XXXXXX12345 Monto: $140.00 "
             "Descripción: Transferencia Local Canal: Página Web Referencia: 123456789 Si no realizaste esta transacción por favor "
             "comunícate de manera urgente con nosotros.")
P_PAGO_TC = ("Produbanco enlínea notificacion nuevo formato Estimado/a " + TIT + " Fecha y Hora: 11/Noviembre/2026 22:50 "
             "Transacción: Pago Tarjeta de Crédito Produbanco Registramos el pago de la tarjeta MASTERCARD SUPERMAXI GOLD "
             "XXXXXXXXXXXX4321 por el monto de USD 100.00 a través del canal Página Web, debitado de la cuenta XXXXXX12345. Atentamente")
P_PAGO_TC_OTRO = ("Estimado/a " + TIT + " Fecha y Hora: 10/Noviembre/2026 09:15 Transacción: Pago de Tarjeta Enviada Exitosamente "
                  "desde Produbanco Detalle Contacto: ANA LUCIA MORA PAREDES Banco Contacto: BANCO PICHINCHA Tarjeta Contacto: "
                  "XXXXXXXXXXX55555 Monto: $250.00 Descripción: Pago de tarjeta de crédito Canal: Página Web Referencia: 99887766 "
                  "Esta transacción tiene un costo de $0.41 por motivo de Transferencia Interbancaria. Si no realizaste")
P_PAGO_RECIBIDO = ("Estimado/a ANA LUCIA MORA PAREDES Te confirmamos que " + TIT + " ha realizado un pago a tu tarjeta en BANCO "
                   "PICHINCHA , enviada desde Produbanco. Fecha y Hora: 10/Noviembre/2026 09:15 Transacción: Pago de tarjeta recibido "
                   "exitosamente desde Produbanco Detalle Banco Destino : BANCO PICHINCHA Monto: $250.00")
P_SUELDO = ("Estimado/a " + TIT + " Fecha y Hora: 09/noviembre/2026 17:10 Transacción: Transferencia Recibida Produbanco Detalle "
            "Enviada por: FARMAEJEMPLO CIA LTDA Banco Origen: BANCO BOLIVARIANO Beneficiario: " + TIT + " Cuenta Beneficiario: "
            "XXXXXX12345 Monto: $700.00 Descripción: ABONO SUELDOS Referencia: 555666777 Atentamente")
P_RECIBIDA_AMIGO = ("Estimado/a " + TIT + " Fecha y Hora: 11/noviembre/2026 13:20 Transacción: Transferencia Recibida Produbanco "
                    "Detalle Enviada por: LUIS ALBERTO ROMERO DIAZ Banco Origen: BANCO GUAYAQUIL Beneficiario: " + TIT
                    + " Cuenta Beneficiario: XXXXXX12345 Monto: $1,250.50 Descripción: diseño logo Referencia: 1 Atentamente")
I_SERVICIO = ("Banco Pichincha Fecha: VIERNES, 13 DE NOVIEMBRE DE 2026 08:12 Pago de servicios " + TIT + " El pago se realizó con "
              "éxito. Detalle Empresa: CONECEL CLARO PLANES Y RECARGAS Contrapartida: 0991234567 Valor: USD 25.00 Comisión: USD 0.45 "
              "Valor total: USD 25.45 Cuenta: XXXXXX9876 Si no has solicitado este servicio")
I_TRANSF_1 = ("Mora Paredes Ana Lucia Tu cédula termina en: ******* 1234 TRANSFERENCIA La transferencia solicitada será debitada "
              "de su cuenta, y acreditada en la cuenta destino en 1 hora. Detalle Cuenta de origen: ******9876 Banco destino: BANCO "
              "BOLIVARIANO Cuenta acreditada: ******4444 Fecha: 12/11/2026 Nombre del beneficiario: Rosa Elena Quispe Tapia "
              "Identificación beneficiario: 1712345678 Monto: USD 80.00 Descripción: Número de documento: 12345678 Si no has")
I_TRANSF_DEUNA = ("Ana Lucia Mora Paredes Tu cédula termina en: ******* 1234 TRANSFERENCIA Pago realizado correctamente Detalle "
                  "Cuenta de origen: ******9876 Banco destino: DE UNA Cuenta acreditada: ******3333 Fecha: 12/11/2026 Nombre del "
                  "beneficiario: Jorge Andres Paz Lima Identificación beneficiario: 1799999999 Monto: USD 3.50 Descripción: Número")
I_TRANSF_PROPIA = (TIT + " Tu cédula termina en: ******* 1234 ¡Transferencia exitosa! Hola, " + TIT + ", Realizaste una "
                   "transferencia. Detalle de la transacción Monto: Concepto 50.00 Cuenta de origen Número de cuenta: ******9876 "
                   "Cuenta destino Nombre: Número de cuenta: " + TIT + " ******2222 Documento: Fecha: 123456 12/11/2026 Si no has")
I_TRANSF_A_PRODU = ("Mora Paredes Ana Lucia Tu cédula termina en: ******* 1234 TRANSFERENCIA La transferencia solicitada será "
                    "debitada. Detalle Cuenta de origen: ******9876 Banco destino: PRODUBANCO Cuenta acreditada: ******12345 Fecha: "
                    "13/11/2026 Nombre del beneficiario: ANA LUCIA MORA PAREDES Identificación beneficiario: 1700000000 Monto: USD "
                    "200.00 Descripción: Número de documento: 1")
P_RECIBIDA_PROPIA = ("Estimado/a " + TIT + " Fecha y Hora: 13/noviembre/2026 15:00 Transacción: Transferencia Recibida Produbanco "
                     "Detalle Enviada por: ANA LUCIA MORA PAREDES Banco Origen: BANCO PICHINCHA Beneficiario: " + TIT
                     + " Cuenta Beneficiario: XXXXXX12345 Monto: $200.00 Descripción: ahorro Referencia: 2 Atentamente")
I_PAGO_TC = ("Banco Pichincha MIÉRCOLES, 11 DE NOVIEMBRE DE 2026 10:00 Pago tarjeta de crédito Estimado/a: " + TIT + " Reciba un "
             "cordial saludo del Asesor Virtual del Banco Pichincha Su transacción fue realizada con éxito. Detalle de transacción "
             "Concepto: Pago de la tarjeta de crédito No. 4111XXXXXXXX1111 Cuenta de débito: XXXXXX9876 Monto: $ 310.20 Fecha: 11/11/2026")
I_REMESA = ("ANA MORA LUCIA Tu identificación termina en:*******1234 REMESAS PICHINCHA ¡Recibiste dinero del exterior! PEDRO PABLO "
            "MORA El dinero se acreditó exitosamente, con el siguiente detalle. Transacción Fecha Referencia del envío 2026-11-10 "
            "WU1234567890 Remitente Nombre País PEDRO PABLO MORA Estados Unidos Receptor Nombre Cuenta Total al receptor ANA MORA "
            "LUCIA XXXXXX9876 1,500.00 USD ¿Necesitas ayuda?")
I_EMPRESAS = ("MORA PAREDES ANA LUCIA Tu RUC termina en: xxxxxx0001 Pichincha Empresas Notificación Estimado MORA PAREDES ANA "
              "LUCIA: El 9 de noviembre de 2026 a la(s) 10:11:12 , se ha realizado la acreditación del Pago a Terceros por el valor "
              "de USD 450 de la empresa CONSULTORA EJEMPLO S A S con la referencia: PAGO FACTURA 015. . Gracias por utilizar")
I_LOGIN = ("Ana Lucia Mora Paredes Tu cédula termina en: ******* 1234 Inicio de sesión exitoso en Banca Web el 12/11/2026. "
           "Si no fuiste tú, comunícate.")

# --- lectores ---------------------------------------------------------------------------------------------------
d = C.leer_produbanco(P_ENVIADA)
ver("produ enviada", d and d["sentido"] == "salida" and d["monto"] == 140 and d["contraparte"] == "Carla Beatriz Torres Vega")
d = C.leer_produbanco(P_PAGO_TC)
ver("produ pago tc", d and d["clase"] == "pago_tarjeta" and d["monto"] == 100)
d = C.leer_produbanco(P_PAGO_TC_OTRO)
ver("produ pago tc otro banco + comisión", d and d["clase"] == "pago_tarjeta" and d["monto"] == 250 and d["comision"] == 0.41)
ver("produ pago recibido se ignora", C.leer_produbanco(P_PAGO_RECIBIDO).get("ignorar"))
d = C.leer_produbanco(P_SUELDO)
ver("produ sueldo", d and d["sentido"] == "entrada" and d["monto"] == 700 and d["descripcion"] == "ABONO SUELDOS"
    and d["contraparte"] == "FARMAEJEMPLO CIA LTDA")
ver("produ miles", C.leer_produbanco(P_RECIBIDA_AMIGO)["monto"] == 1250.5)
d = C.leer_pichincha(I_SERVICIO)
ver("pich servicio", d and d["clase"] == "pago_servicio" and d["valor"] == 25 and d["comision"] == 0.45 and d["monto"] == 25.45
    and d["contraparte"] == "CONECEL CLARO PLANES Y RECARGAS")
d = C.leer_pichincha(I_TRANSF_1)
ver("pich transferencia", d and d["monto"] == 80 and d["contraparte"] == "Rosa Elena Quispe Tapia" and d["banco_otro"] == "BANCO BOLIVARIANO")
ver("pich deuna", C.leer_pichincha(I_TRANSF_DEUNA)["contraparte"] == "Jorge Andres Paz Lima")
d = C.leer_pichincha(I_TRANSF_PROPIA)
ver("pich transferencia exitosa", d and d["monto"] == 50 and d["contraparte"] == TIT)
ver("pich pago tc", C.leer_pichincha(I_PAGO_TC)["monto"] == 310.2)
d = C.leer_pichincha(I_REMESA)
ver("pich remesa", d and d["monto"] == 1500 and d["contraparte"] == "PEDRO PABLO MORA")
d = C.leer_pichincha(I_EMPRESAS)
ver("pich pago a terceros", d and d["monto"] == 450 and d["contraparte"] == "CONSULTORA EJEMPLO S A S" and "FACTURA" in d["descripcion"])
ver("pich login no es movimiento", C.leer_pichincha(I_LOGIN) is None)
ver("bonito persona", C.bonito("Carla Beatriz Torres Vega") == "Carla Torres")
ver("bonito empresa", C.bonito("FARMAEJEMPLO CIA LTDA").startswith("Farmaejemplo"))
ver("cuenta de banco", C.cuenta_de_banco("BANCO PICHINCHA") == "Pichincha" and C.cuenta_de_banco("Bolivariano") == "")

# --- titular ----------------------------------------------------------------------------------------------------
C.aprender_titular(" ".join(P_ENVIADA.split()))
ver("titular propio", C.es_titular("ANA LUCIA MORA PAREDES") and C.es_titular("ANA MORA LUCIA"))
ver("pariente no es titular", not C.es_titular("PEDRO PABLO MORA") and not C.es_titular("Carla Beatriz Torres Vega"))

# --- importación inicial: solo para el saldo, sin preguntar ---------------------------------------------------
AHORA[0] = datetime(2026, 11, 1, 9, 0, tzinfo=ZONA)
r = C.procesar_texto("Produbanco", P_ENVIADA.replace("12/11/2026", "28/10/2026"), datetime(2026, 10, 28, 18, 10), "gmail:viejo1", nuevo=False)
ver("importación no pregunta", r is None and C.pendientes() == [])
ver("importación no crea gasto", gastos.del_periodo(date(2026, 10, 1), date(2026, 10, 31)) == [])

# --- saldo inicial --------------------------------------------------------------------------------------------
ver("sin saldo", C.saldo("Produbanco")[0] is None)
AHORA[0] = datetime(2026, 11, 2, 9, 0, tzinfo=ZONA)
r = C.procesar("saldo pichincha 405, produbanco 236")
ver("poner saldos", "Pichincha" in r and "Produbanco" in r and C.saldo("Pichincha")[0] == 405 and C.saldo("Produbanco")[0] == 236)

# --- movimientos nuevos -----------------------------------------------------------------------------------------
AHORA[0] = datetime(2026, 11, 13, 20, 0, tzinfo=ZONA)
EV = {}


def corre(clave, banco, texto, cuando):
    r = C.procesar_texto(banco, texto, cuando, "gmail:" + clave)
    EV[clave] = r
    return r


r = corre("sueldo", "Produbanco", P_SUELDO, datetime(2026, 11, 9, 17, 10))
ver("sueldo automático", r and r[1][0] == "sueldo")
sueldos = [m for m in gastos.del_periodo(date(2026, 11, 1), date(2026, 11, 30), "ingreso") if m["categoria"] == "Sueldo"]
ver("sueldo como ingreso", len(sueldos) == 1 and sueldos[0]["monto"] == 700 and sueldos[0]["ref"] == "gmail:sueldo")
ver("sueldo llegó", C.sueldo_llego(date(2026, 11, 13)))
ver("no repite el mismo correo", corre("sueldo", "Produbanco", P_SUELDO, datetime(2026, 11, 9, 17, 10)) is None or
    len([m for m in gastos.del_periodo(date(2026, 11, 1), date(2026, 11, 30), "ingreso")]) == 1)

r = corre("tc", "Produbanco", P_PAGO_TC, datetime(2026, 11, 11, 22, 50))
ver("pago tc no es gasto", r and r[1][0] == "tarjeta" and not gastos.del_periodo(date(2026, 11, 11), date(2026, 11, 11), "gasto"))
r = corre("tc2", "Produbanco", P_PAGO_TC_OTRO, datetime(2026, 11, 10, 9, 15))
g = gastos.del_periodo(date(2026, 11, 10), date(2026, 11, 10), "gasto")
ver("comisión interbancaria es gasto", len(g) == 1 and g[0]["monto"] == 0.41 and g[0]["categoria"] == "Comisiones bancarias")
ver("pago recibido ignorado", corre("tc2b", "Produbanco", P_PAGO_RECIBIDO, datetime(2026, 11, 10, 9, 16)) is None)

gastos.anotar("gasto", 25, "claro", None, "", date(2026, 11, 13), "telegram", usar_foto=False)     # ya lo había escrito
r = corre("claro", "Pichincha", I_SERVICIO, datetime(2026, 11, 13, 8, 12))
g = [x for x in gastos.del_periodo(date(2026, 11, 13), date(2026, 11, 13), "gasto")]
ver("servicio unido al anotado a mano", len([x for x in g if x["monto"] == 25]) == 1 and any(x["ref"] == "gmail:claro" for x in g))
ver("servicio + comisión", any(x["monto"] == 0.45 for x in g))
texto, botones = C.texto_evento(r[1])
ver("aviso de servicio con categoría", "Hogar y servicios" in texto and botones)

r = corre("carla", "Produbanco", P_ENVIADA, datetime(2026, 11, 12, 18, 10))
ver("transferencia a persona pregunta", r and r[1][0] == "preguntar")
texto, filas = C.texto_evento(r[1])
ver("pregunta con botones", "Carla Torres" in texto and "¿Qué fue?" in texto and any("cta:gasto" in b["callback_data"] for f in filas for b in f))
cid = r[0]
ver("botones de categoría", any("cta:cat:" in b["callback_data"] for f in C.botones_categoria(cid) for b in f))
t = C.aplicar(cid, "gasto", "Regalos")
ver("aplicar gasto", "Regalos" in t and any(x["descripcion"] == "Transferencia a Carla Torres"
                                             for x in gastos.del_periodo(date(2026, 11, 12), date(2026, 11, 12), "gasto")))
ver("doble respuesta", "ya estaba" in C.aplicar(cid, "gasto", "Regalos"))
r = corre("carla2", "Produbanco", P_ENVIADA.replace("$140.00", "$60.00"), datetime(2026, 11, 13, 9, 0))
ver("aprendido la segunda vez", r and r[1][0] == "aprendido" and C.obtener(r[0])["decision"] == "gasto")
ver("aprendido con la misma categoría", any(x["monto"] == 60 and x["categoria"] == "Regalos"
                                            for x in gastos.del_periodo(date(2026, 11, 13), date(2026, 11, 13), "gasto")))

did = deudas.crear("Rosa", 100, "le_debo", "préstamo")
r = corre("rosa", "Pichincha", I_TRANSF_1, datetime(2026, 11, 12, 10, 0))
texto, filas = C.texto_evento(r[1])
ver("ofrece pago de deuda", any("Pago de mi deuda con Rosa" in b["text"] for f in filas for b in f))
t = C.aplicar(r[0], "deuda", str(did))
ver("pago de deuda aplicado", deudas.saldo(did) == 20 and "Rosa" in t)

r = corre("deuna", "Pichincha", I_TRANSF_DEUNA, datetime(2026, 11, 12, 11, 0))
t = C.aplicar(r[0], "prestamo")
ver("préstamo crea deuda", any(x["persona"] == "Jorge Paz" and x["sentido"] == "me_debe" for x in deudas.abiertas()))

r = corre("propia", "Pichincha", I_TRANSF_PROPIA, datetime(2026, 11, 12, 12, 0))
ver("propia mismo banco neutra", r is None and C.saldo("Pichincha")[1]["movs"] >= 0)

antes_prod = C.saldo("Produbanco")[0]
r = corre("a_produ", "Pichincha", I_TRANSF_A_PRODU, datetime(2026, 11, 13, 14, 0))
ver("propia a otro banco = interna", r and r[1][0] == "interna")
ver("entrada estimada en Produbanco", round(C.saldo("Produbanco")[0] - antes_prod, 2) == 200)
r = corre("de_pich", "Produbanco", P_RECIBIDA_PROPIA, datetime(2026, 11, 13, 15, 0))
ver("correo de llegada confirma sin duplicar", round(C.saldo("Produbanco")[0] - antes_prod, 2) == 200)
ver("nada de ingreso por la propia", not [x for x in gastos.del_periodo(date(2026, 11, 13), date(2026, 11, 13), "ingreso")])

r = corre("tcpich", "Pichincha", I_PAGO_TC, datetime(2026, 11, 11, 10, 0))
ver("pago tc pichincha", r and r[1][0] == "tarjeta")

r = corre("remesa", "Pichincha", I_REMESA, datetime(2026, 11, 10, 12, 0))
ver("remesa pregunta (pariente no es titular)", r and r[1][0] == "preguntar")
texto, _ = C.texto_evento(r[1])
ver("texto remesa", "remesa del exterior" in texto and "1.500" in texto)
t = C.aplicar(r[0], "no_contar")
ver("remesa no contar", "No lo cuento" in t)

r = corre("empresa", "Pichincha", I_EMPRESAS, datetime(2026, 11, 9, 10, 11))
t = C.aplicar(r[0], "ingreso")
ver("pago a terceros como ingreso", "ingreso" in t and any(x["monto"] == 450 for x in gastos.del_periodo(date(2026, 11, 9), date(2026, 11, 9), "ingreso")))

r = corre("amigo", "Produbanco", P_RECIBIDA_AMIGO, datetime(2026, 11, 11, 13, 20))
ver("recibida de persona pregunta", r and r[1][0] == "preguntar")
ver("login ignorado", corre("login", "Pichincha", I_LOGIN, datetime(2026, 11, 12, 8, 0)) is None)

# sueldo de una empresa que tiene deuda abierta → pregunta
deudas.crear("Farmaejemplo", 1400, "me_debe", "sueldos atrasados")
r = corre("sueldo2", "Produbanco", P_SUELDO.replace("$700.00", "$683.05"), datetime(2026, 11, 13, 10, 0))
texto, filas = C.texto_evento(r[1])
ver("sueldo con deuda abierta pregunta", r[1][0] == "preguntar" and any("Sueldo de este mes" in b["text"] for f in filas for b in f)
    and any("Farmaejemplo" in b["text"] for f in filas for b in f))

# --- saldo y ajuste -----------------------------------------------------------------------------------------------
s, det = C.saldo("Produbanco")
esperado = round(236 + 700 + 200 + 1250.5 + 683.05 - 100 - 250.41 - 140 - 60, 2)
ver("saldo Produbanco calculado", s == esperado)
sp, _ = C.saldo("Pichincha")
esperado_p = round(405 - 25.45 - 80 - 3.5 - 200 - 310.2 + 1500 + 450, 2)
ver("saldo Pichincha calculado", sp == esperado_p)
ahorros.guardar("Viaje", saldo=70, aporte=70, dia_aporte=20, banco="Produbanco")
AHORA[0] = datetime(2026, 11, 21, 9, 0, tzinfo=ZONA)
ver("aporte de ahorro restado", C.saldo("Produbanco")[0] == round(esperado - 70, 2))
AHORA[0] = datetime(2026, 12, 1, 9, 10, tzinfo=ZONA)
q = C.pregunta_saldo()
ver("pregunta del día 1", "Mi cálculo" in q and C.esperando())
r = C.procesar("pichincha 1700, produbanco " + str(round(esperado - 70 - 15, 2)))
ver("ajuste negativo explicado", "Salieron $15" in r and "sin aviso" in r)
ver("ajuste guardado", C.ajustes_recientes("Produbanco")[0]["monto"] == 15)
ver("saldo nuevo base", C.saldo("Produbanco")[0] == round(esperado - 85, 2))
AHORA[0] = datetime(2027, 1, 1, 9, 10, tzinfo=ZONA)
C.pregunta_saldo()
r = C.procesar("ok")
ver("ok confirma", "confirmado" in r and not C.esperando())
AHORA[0] = datetime(2027, 2, 1, 9, 10, tzinfo=ZONA)
C.pregunta_saldo()
s2 = C.saldo("Produbanco")[0]
r = C.procesar("produbanco " + str(round(s2 - 84, 2)))
ver("ajuste anterior parecido = posible débito fijo", "débito fijo" in r or "Salieron $84" in r)

# --- frases -------------------------------------------------------------------------------------------------------
AHORA[0] = datetime(2027, 2, 10, 12, 0, tzinfo=ZONA)
ver("ver saldo", C.interpretar("mi saldo") == {"accion": "ver"} and C.interpretar("¿cuánto tengo en el banco?") == {"accion": "ver"})
ver("tengo X en Y", C.interpretar("tengo 405 en pichincha") == {"accion": "poner", "saldos": {"Pichincha": 405}})
ver("saldo produ", C.interpretar("saldo produ 1.250,50") == {"accion": "poner", "saldos": {"Produbanco": 1250.5}})
NO = ["uber 3,20 con produbanco", "pagué 30 de internet con pichincha", "ahorro viaje 498", "le debo 200 a mi tío",
      "hay una sucursal de pichincha a 2 cuadras", "ok", "pichincha 405", "compré algo de 20 en produbanco",
      "tengo 3 tareas", "el saldo de Juan es 350"]
for n in NO:
    ver("no es saldo: " + n, C.interpretar(n) is None)
# --- respuestas en mensajes separados (13-11: «produbanco 236» después de «pichincha 405» no se entendía) -------
with closing(C._con()) as con, con:
    con.execute("DELETE FROM cuentas")
C.ESPERA.update(desde=None, faltan=[])
C.pregunta_saldo()
r = C.procesar("Pichincha 405")
ver("separado 1: pide la otra", "Pichincha" in r and "dígame el de Produbanco" in r and C.esperando())
r = C.procesar("Produbanco 236")
ver("separado 2: se entiende", r and "Produbanco" in r and C.saldo("Produbanco")[0] == 236 and not C.esperando())
with closing(C._con()) as con, con:
    con.execute("DELETE FROM cuentas")
C.pregunta_saldo()
C.procesar("pichincha: $405,20")
r = C.procesar("236")
ver("solo el número cuando falta una", r and C.saldo("Produbanco")[0] == 236 and C.saldo("Pichincha")[0] == 405.2)
with closing(C._con()) as con, con:
    con.execute("DELETE FROM cuentas WHERE nombre = 'Produbanco'")
C.ESPERA.update(desde=None, faltan=[])
ver("sin pregunta abierta, cuenta sin saldo", C.interpretar("produbanco 236") == {"accion": "poner", "saldos": {"Produbanco": 236}})
# --- saldo negativo (19-11): el Pichincha no avisa las transferencias recibidas -> preguntar el saldo real ---------
with closing(C._con()) as con, con:
    con.execute("DELETE FROM cuentas")
C.ESPERA.update(desde=None, faltan=[])
C.poner_saldo("Pichincha", 4.63, datetime(2026, 11, 13, 13, 0))
C.poner_saldo("Produbanco", 100, datetime(2026, 11, 13, 13, 0))
C._insertar(cuenta="Pichincha", cuando="2026-11-16T11:10:00", sentido="salida", monto=150.0, clase="pago_tarjeta",
            decision="no_contar", descripcion="Pago de tarjeta de prueba")
ver("negativo: el cálculo da menos de cero", C.saldo("Pichincha")[0] < 0)
avisos = C.revisar_negativos()
ver("negativo: pregunta solo por el Pichincha", len(avisos) == 1 and "Pichincha" in avisos[0] and "no manda correo" in avisos[0])
ver("negativo: deja abierta la respuesta", C.esperando() and C.ESPERA["faltan"] == ["Pichincha"])
ver("negativo: no repite el mismo día", C.revisar_negativos() == [])
ver("negativo: /saldo lo advierte", "Negativo" in C.estado())
r = C.procesar("320")
ver("negativo: «320» corrige el Pichincha", r and abs(C.saldo("Pichincha")[0] - 320) < 0.01 and not C.esperando())
ver("negativo: ya no avisa", C.revisar_negativos() == [] and "Negativo" not in C.estado())
ver("cuenta con saldo y sin pregunta: no", C.interpretar("pichincha 405") is None)
ver("número suelto sin pregunta: no", C.interpretar("236") is None)
C.procesar("produbanco 236")
ver("estado", "Pichincha" in C.estado() and "Produbanco" in C.estado() and "sin responder" in C.estado())

print("CUENTAS: " + str(BIEN + MAL) + " | BIEN: " + str(BIEN) + " | MAL: " + str(MAL))
