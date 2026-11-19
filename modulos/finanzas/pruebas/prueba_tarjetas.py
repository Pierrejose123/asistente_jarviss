"""Prueba de TARJETAS (paso 8, 13-11): lectura de estados de cuenta (formato real de Pichincha y Produbanco con datos
INVENTADOS), correo de diferido, cuotas por mes, «¿me alcanza?», frases y avisos de pago. Base TEMPORAL; sin Gmail,
Google ni Telegram. python modulos\\finanzas\\pruebas\\prueba_tarjetas.py"""
import sys
import tempfile
from contextlib import closing
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
from modulos.finanzas import ahorros, cuentas, gastos, presupuesto, tarjetas as T  # noqa: E402

AHORA = [datetime(2026, 11, 13, 12, 0, tzinfo=ZONA)]
for mod in (T, gastos, presupuesto, ahorros, cuentas):
    mod.ahora = lambda: AHORA[0]

BIEN, MAL = 0, 0


def ver(nombre, cond):
    global BIEN, MAL
    if cond:
        BIEN += 1
    else:
        MAL += 1
        print("MAL:", nombre)


ESTADO_PICHINCHA = """TARJETA VISA
 4Pág. 1 de
FECHA DE EMISIÓN: 03 NOV 2026
MORA PAREDES ANA LUCIA
FECHA MÁXIMA DE PAGO
ATENCIÓN
18 NOV 2026
DETALLE DE MOVIMIENTOS
SALDO ANTERIOR 410.00
07/10 123456 SU PAGO "MUCHAS GRACIAS" 200.00-
03/11 INT. FINANCIAMIENTO N/D 3.10
MORA PAREDES ANA LUCIA    123-xxxx-xxxx-456  * PRINCIPAL VISA PLATINUM *   ID: 1700000000
22/12 123456 EFECTIVO EXPRESS BP DIFERIDO 52.30 52.30(11/12)
11/05 1234567 DIF CON INTERNACIONAL ONLINE DIFERIDO 40.00(FINAL)
05/09 1234567 DIF CON INTERNACIONAL ONLINE DIFERIDO 30.00 210.00(2/9)
06/10 123456 DIF CON NACIONAL ONLINE DIFERIDO 45,10 496,10(13/24)
SUBTOTAL : 167.40
TOTAL CONSUMOS MES 167.40
758,40SALDO DIFERIDO A FACTURAR
TOTAL A PAGAR USD 380.50
PAGO MINIMO 95.20
"""
ESTADO_PRODUBANCO = """Estado
de cuenta
ANA EJEMPLO
Fecha De Emisión : 10/30/2026 Fecha Máx. de Pago : 11/16/2026 Cupos (US$) Autorizado Utilizado Disponible
Periodo :  10/01/2026  - 10/30/2026 Rotativo 2000.00 350.00 1650.00
Pagos Vencidos : 0 Monto Vencido : 0.00 Diferido 2000.00 0.00 2000.00
Pagos Mínimo : 40.25 Total a Pagar : 350.75 ExtraCupo 0.00 0.00 0.00
Detalle de movimientos del período
09/29/2026 123456789012 DLC*UBER RIDES SJ.SJ.AVE  CRI 840 CONS. 5.20 + 1.0000 5.20 +
Plazo Factor
  3 meses                     2.10%
  6 meses                     4.05%
 12 meses                     7.90%
"""
ESTADO_PRODU_CON_DIF = ESTADO_PRODUBANCO.replace("Diferido 2000.00 0.00 2000.00", "Diferido 2000.00 600.00 1400.00")
CORREO_DIF = ("96 MORA PAREDES ANA LUCIA 1700000000 TARJETA DE CRÉDITO Tu diferido fue realizado con éxito Hola, recuerda que "
              "tu diferido se verá reflejado en los movimientos. Resumen de tu diferido Total a pagar $ 642.00 Valor diferido $ 600.00 "
              "Plazo 6 Interés generado $ 42.00 Tu interés generado se calcula en función a la tasa Cuotas a pagar Valor $ 107.00 "
              "Valor diferido $ 600.00 Número de consumos diferidos 1")

# --- lectores -------------------------------------------------------------------------------------------------
r = T.leer_estado_pichincha(ESTADO_PICHINCHA)
ver("pich emisión", r["emision"] == date(2026, 11, 3))
ver("pich fecha máxima", r["fecha_max"] == date(2026, 11, 18))
ver("pich total y mínimo", r["total"] == 380.5 and r["minimo"] == 95.2)
ver("pich saldo diferido", r["saldo_diferido"] == 758.4)
ver("pich 4 líneas", len(r["diferidos"]) == 4)
ex = next(d for d in r["diferidos"] if "Efectivo" in d["descripcion"])
ver("pich cuota 11/12", ex["cuota"] == 52.3 and ex["pagadas"] == 11 and ex["total_cuotas"] == 12 and ex["saldo"] == 52.3)
ver("pich coma decimal", any(d["cuota"] == 45.1 and d["saldo"] == 496.1 for d in r["diferidos"]))
ver("pich final", any(d.get("final") for d in r["diferidos"]))
ver("pich sin aviso (cuadra)", r["aviso"] == "")
mal = T.leer_estado_pichincha(ESTADO_PICHINCHA.replace("758,40SALDO", "999,00SALDO"))
ver("si no cuadra estima y avisa", mal["aviso"] and next(d for d in mal["diferidos"] if d["total_cuotas"] == 9)["saldo"] == 210.0)
p = T.leer_estado_produbanco(ESTADO_PRODUBANCO)
ver("produ fechas mes/día", p["emision"] == date(2026, 10, 30) and p["fecha_max"] == date(2026, 11, 16))
ver("produ total y mínimo", p["total"] == 350.75 and p["minimo"] == 40.25)
ver("produ factores", p["factores"].get(6) == 4.05 and p["factores"].get(12) == 7.9)
ver("produ sin diferidos sin aviso", p["diferidos"] == [] and p["aviso"] == "")
ver("produ diferido sin detalle avisa", "no pude leer" in T.leer_estado_produbanco(ESTADO_PRODU_CON_DIF)["aviso"])
c = T.leer_correo_diferido(CORREO_DIF)
ver("correo diferido", c == {"valor": 600, "plazo": 6, "cuota": 107, "interes": 42})
ver("correo que no es", T.leer_correo_diferido("Realizaste una compra") is None)

# --- guardar y cuotas ---------------------------------------------------------------------------------------------
ver("guardar estado", T.guardar_estado(r, "gmail:est1") is not None)
ver("no repite", T.guardar_estado(r, "gmail:est1") is None)
T.guardar_estado(p, "gmail:est2")
ver("3 diferidos activos (sin el final)", len(T.activos()) == 3)
ver("factor guardado", T.factor(6) == 4.05)
dic, _ = T.cuotas_del_mes("2026-12")
ver("cuotas diciembre", dic == round(52.3 + 30 + 45.1, 2))
ene, _ = T.cuotas_del_mes("2027-01")
ver("enero sin efectivo express", ene == round(30 + 45.1, 2))
ver("último mes 2/9", T.ultimo_mes(next(d for d in T.activos() if d["total_cuotas"] == 9)) == "2027-06")
ver("último mes 13/24", T.ultimo_mes(next(d for d in T.activos() if d["total_cuotas"] == 24)) == "2027-10")

# correo de diferido: une con la compra y queda provisional
gastos.anotar("gasto", 600, "Laptop Tienda", "Otros", "Pichincha Platinum", date(2026, 11, 10), "correo", "gmail:compra",
              usar_foto=False)
ev = T.procesar_correo_diferido(CORREO_DIF, "gmail:dif1")
ver("diferido del correo", ev and ev[0] == "diferido")
x = next(d for d in T.activos() if d["id"] == ev[1])
ver("con la descripción de la compra", x["descripcion"] == "Laptop Tienda" and x["cuota"] == 107 and x["origen"] == "correo")
ver("primera cuota en diciembre", T.cuotas_del_mes("2026-12")[0] == round(dic + 107, 2) and T.ultimo_mes(x) == "2027-05")
ver("la compra sigue siendo UN gasto", len([g for g in gastos.del_periodo(date(2026, 11, 1), date(2026, 11, 30), "gasto")
                                           if g["monto"] == 600]) == 1)
ver("texto diferido nuevo", "107" in T.texto_diferido_nuevo(ev[1], ev[2]) and "mayo" in T.texto_diferido_nuevo(ev[1], ev[2]))

# un estado de cuenta más nuevo reemplaza lo provisional y lo viejo
AHORA[0] = datetime(2026, 12, 4, 12, 0, tzinfo=ZONA)
dic_estado = ESTADO_PICHINCHA.replace("03 NOV 2026", "03 DIC 2026").replace("18 NOV 2026", "18 DIC 2026") \
    .replace("52.30 52.30(11/12)", "52.30(FINAL)").replace("30.00 210.00(2/9)", "30.00 180.00(3/9)") \
    .replace("45,10 496,10(13/24)", "45,10 451,00(14/24)").replace("11/05 1234567 DIF CON INTERNACIONAL ONLINE DIFERIDO 40.00(FINAL)\n", "") \
    + "10/11 1234567 DIF CON NACIONAL ONLINE DIFERIDO 107.00 535.00(1/6)\n"
dic_estado = dic_estado.replace("758,40SALDO", "1166,00SALDO")
T.guardar_estado(T.leer_estado_pichincha(dic_estado), "gmail:est3")
pich = [d for d in T.activos() if d["tarjeta"] == "Pichincha Platinum"]
ver("estado nuevo reemplaza (3 activos Pichincha)", len(pich) == 3 and all(d["origen"] == "estado" for d in pich))
ver("estado viejo no pisa al nuevo", T.guardar_estado(T.leer_estado_pichincha(ESTADO_PICHINCHA), "gmail:est1b") is not None
    and len([d for d in T.activos() if d["tarjeta"] == "Pichincha Platinum"]) == 3)
ver("cuotas enero tras el nuevo estado", T.cuotas_del_mes("2027-01")[0] == round(30 + 45.1 + 107, 2))

# Diners a mano
d = T.interpretar("diferí la consola de 450 a 3 meses con diners")
ver("frase diferí", d == {"accion": "diferi", "que": "consola", "monto": 450, "plazo": 3, "tarjeta": "Diners"})
ver("anotar diferí", "150" in T.ejecutar(d) and any(x["tarjeta"] == "Diners" for x in T.activos()))

# --- me alcanza ---------------------------------------------------------------------------------------------------
presupuesto.poner_ajuste("sueldo", 700) if hasattr(presupuesto, "poner_ajuste") else None
try:
    with closing(presupuesto._con()) as con, con:
        con.execute("INSERT OR REPLACE INTO finanzas_ajustes (clave, valor) VALUES ('sueldo', '700')")
except Exception as exc:
    print("no pude poner el sueldo:", exc)
ver("sueldo puesto", presupuesto.sueldo() == 700)
for mes, total in ((9, 300), (10, 340), (11, 320)):
    for i in range(4):
        gastos.anotar("gasto", total / 4, "Varios", "Otros", "", date(2026, mes, 10 + i), "telegram", usar_foto=False)
gastos.anotar("gasto", 900, "Compra grande", "Otros", "", date(2026, 10, 20), "telegram", usar_foto=False)
n, meses = T.gasto_normal()
ver("gasto normal sin compras grandes (laptop 600 y 900)", meses == 3 and n == round((300 + 340 + 320) / 3, 2))
a = T.me_alcanza(300, 6)
ver("cuota con factor", a["factor"] == 4.05 and a["cuota"] == round(300 * 1.0405 / 6, 2))
ver("veredicto existe", a["veredicto"] in ("si", "justo", "no"))
a2 = T.me_alcanza(300, 6, con_interes=False)
ver("sin interés", a2["cuota"] == 50)
grande = T.me_alcanza(6000, 6)
ver("compra imposible = no", grande["veredicto"] == "no" and "No le alcanza" in T.texto_alcanza(grande))
ver("texto me alcanza", "Cómo lo calculé" in T.texto_alcanza(a, "laptop") and "decisión es suya" in T.texto_alcanza(a))
ver("límite 30 %", T.me_alcanza(1500, 6)["pct_cuotas"] > 30)

# --- frases -------------------------------------------------------------------------------------------------------
SI = {"¿me alcanza para comprar una laptop de 900 a 6 meses?": (900, 6), "si difiero 1.200 a 12 meses me alcanza?": (1200, 12),
      "quiero comprarme un celular de $650 a 9 meses": (650, 9), "puedo diferir a 3 meses 300?": (300, 3),
      "me alcanza 450 dólares a 6 cuotas sin intereses": (450, 6)}
for f, (m, pz) in SI.items():
    d = T.interpretar(f)
    ver("alcanza: " + f, d and d["accion"] == "alcanza" and d["monto"] == m and d["plazo"] == pz)
ver("sin interés detectado", T.interpretar("me alcanza 450 dólares a 6 cuotas sin intereses")["sin_interes"])
ver("qué compra", T.interpretar("quiero comprarme un celular de $650 a 9 meses")["que"] == "celular")
ver("ver diferidos", T.interpretar("mis diferidos") == {"accion": "ver"} and T.interpretar("¿cuánto pago de cuotas?") == {"accion": "ver"})
ver("ver tarjetas", T.interpretar("¿cuándo tengo que pagar las tarjetas?") == {"accion": "tarjetas"}
    and T.interpretar("/credito") == {"accion": "tarjetas"} and T.interpretar("mis tarjetas de crédito") == {"accion": "tarjetas"})
ver("/tarjetas y «mis tarjetas» son de la biblioteca", T.interpretar("/tarjetas") is None and T.interpretar("mis tarjetas") is None)
NO = ["compré una laptop de 900 en la tienda", "almuerzo 4.50", "tengo 6 meses de gimnasio", "me debe 300 a 3 meses",
      "uber 3,20 con diners", "en 6 meses viajo"]
for f in NO:
    ver("no: " + f, T.interpretar(f) is None)

# --- textos y avisos de pago --------------------------------------------------------------------------------------
t = T.texto_diferidos()
ver("texto diferidos", "Sus diferidos" in t and "Cuotas por mes" in t and "consola" in t.lower())
AHORA[0] = datetime(2026, 12, 15, 9, 0, tzinfo=ZONA)
v = T.pagos_por_vencer(AHORA[0].date())
ver("aviso 3 días antes", len(v) == 1 and v[0][0]["tarjeta"] == "Pichincha Platinum")
ver("texto de aviso", "18/12" in T.texto_por_vencer(*v[0], hoy=AHORA[0].date()) and "mínimo" in T.texto_por_vencer(*v[0], hoy=AHORA[0].date()))
cuentas._insertar(cuenta="Produbanco", cuando="2026-12-10T10:00:00", sentido="salida", monto=380.5, clase="pago_tarjeta",
                  decision="no_contar", banco_otro="BANCO PICHINCHA", ref="gmail:pago")
ver("ya pagado no avisa", T.pagos_por_vencer(AHORA[0].date()) == [])
ver("tarjetas muestra pagado", "✅ Pagada" in T.texto_tarjetas())
ver("texto estado", "Pagar hasta el 18/11" in T.texto_estado(r) and "Terminó de pagar" in T.texto_estado(r))

# --- Diners (13-11): estado de cuenta, pagos y anulación ----------------------------------------------------------
ESTADO_DINERS = """N°  123456789012345
Estado de cuenta
Página 1 de 6
18 NOV 2026
Fecha máxima de pago:
04 OCT 2026 AL 03 NOV 2026SAN RAFAEL
MORA PAREDES ANA LUCIA
03/NOV/2026
FECHA DE CORTE:
Resumen
Fecha máxima de pago: 18 NOV 2026
476,83Mínimo a pagar:
491,63Total a pagar:
Página 2 de 6
Detalle de movimientos
(*) Hace referencia a tus consumos diferidos de meses anteriores. 1.172,04Saldos y diferidos pendientes*
IVAVALORESTABLECIMIENTOFECHA Nº VALE CUOTA SALDO DIF.
Consumo período actual
07/11 1234567 DIFERIDO INTERNACIONAL ONLINE (FINAL) 35.10
21/04 1234567 DIFERIDO INTERNACIONAL ONLINE (7/9) 61.20 122.40
22/08 2 DTF BERMAT S C C (2/12) 40.00 400.00
08/06 123456 PMZ - LG SHOP (5/12) 75.00 525.00
14/10 1234567 ECUA EL ESPANOL E003 QUICEN 12.50
SUBTOTAL DE CONSUMOS: 223.80
Crédito diferido
Plazo 3 4 5 6 7 8 9 12 24 36
Factor 2.50% 3.10% 3.70% 4.30% 4.90% 5.50% 6.10% 8.00% 15.20% 22.90%
"""
dn = T.leer_estado_diners(ESTADO_DINERS)
ver("diners emisión", dn["emision"] == date(2026, 11, 3))
ver("diners fecha máxima", dn["fecha_max"] == date(2026, 11, 18))
ver("diners total y mínimo", dn["total"] == 491.63 and dn["minimo"] == 476.83)
ver("diners 4 diferidos (sin el consumo normal)", len(dn["diferidos"]) == 4)
lg = next(d for d in dn["diferidos"] if "Lg Shop" in d["descripcion"])
ver("diners cuota y saldo", lg["cuota"] == 75 and lg["saldo"] == 525 and lg["pagadas"] == 5 and lg["total_cuotas"] == 12)
ver("diners saldo incluye otros: sin aviso", dn["aviso"] == "")
ver("diners factores", dn["factores"].get(6) == 4.3 and dn["factores"].get(36) == 22.9)
AHORA[0] = datetime(2026, 11, 13, 12, 0, tzinfo=ZONA)
T.guardar_estado(dn, "gmail:diners1")
dif_diners = [d for d in T.activos() if d["tarjeta"] == "Diners"]
ver("estado de Diners: 3 del banco + el anotado a mano después del corte", len(dif_diners) == 4
    and len([d for d in dif_diners if d["origen"] == "estado"]) == 3)
T.REMITENTES_ESTADO = {"example.com": "Diners"}      # en la PC sale de config/bancos.json (privado)
ver("remitente del estado de Diners", T.banco_estado("Estado de Cuenta Diners Club <info@example.com>") == "Diners")
ver("remitente falso no", T.banco_estado("x <info@example.com.estafa.xyz>") != "Diners")
ver("sin config/bancos.json no se busca en Gmail", T._buscar(None, "", "newer_than:1d", 5) == [])
PAGO_DINERS = ("96 ¡Gracias por tu pago! ¡Hola, MORA PAREDES ANA LUCIA! ¡Gracias por el pago a tu Diners Club ! Monto recibido: "
               "378.00 Fecha de pago: 05/11/2026 El valor pendiente de pago es $ 113.63 . Si lo requiere")
pg = T.leer_pago_diners(PAGO_DINERS)
ver("pago diners", pg == {"monto": 378, "fecha": date(2026, 11, 5), "pendiente": 113.63})
T.guardar_pago("Diners", pg, "gmail:pd1")
ver("pagado diners por confirmación", T.pagado_desde("Diners", "2026-11-03") == 378)
I_PAGO_DINERS = ("Mora Paredes Ana Lucia Tu cédula termina en: ******* 1234 Pago tarjeta de crédito El pago solicitado será debitado "
                 "de su cuenta, y acreditado en 1 hora. Detalle Cuenta de origen: ******9876 Banco destino: BANCO DINERS CLUB Tarjeta "
                 "acreditada: 3608******2431 Fecha: 05/11/2026 Nombre del beneficiario: Ana Mora P Identificación beneficiario: "
                 "1700000000 Monto: USD 378 Número de documento: 1")
dp = cuentas.leer_pichincha(I_PAGO_DINERS)
ver("pago desde Pichincha a Diners", dp["clase"] == "pago_tarjeta" and dp["monto"] == 378 and "DINERS" in dp["banco_otro"])
cuentas._insertar(cuenta="Pichincha", cuando="2026-11-05T10:00:00", sentido="salida", monto=378, clase="pago_tarjeta",
                  decision="no_contar", banco_otro=dp["banco_otro"], ref="gmail:pp1")
ver("el mismo pago no se cuenta dos veces", T.pagado_desde("Diners", "2026-11-03") == 378)
res = {x["tarjeta"]: x for x in T.resumen_tarjetas()}
ver("resumen tiene Diners", "Diners" in res and res["Diners"]["falta"] == round(491.63 - 378, 2) and len(res["Diners"]["diferidos"]) == 4)
ver("resumen pagos de Diners", res["Diners"]["pagos"] and res["Diners"]["pagos"][0]["origen"] == "desde Pichincha")
panel = T.datos_panel()
ver("panel por tarjeta", {x["tarjeta"] for x in panel["tarjetas"]} >= {"Diners", "Pichincha Platinum"} and len(panel["cuotas_meses"]) == 6)
ctx = T.contexto_ia()
ver("contexto IA", ctx.startswith("TARJETAS") and "Diners" in ctx and "Lg Shop" in ctx and "Cuotas por mes" in ctx)
from modulos.finanzas import perfil  # noqa: E402
ver("perfil.contexto_ia incluye tarjetas", "TARJETAS" in perfil.contexto_ia())
ver("texto diferidos con avance", "va en la 5 de 12" in T.texto_diferidos())

from modulos.finanzas import correos  # noqa: E402
ANULA = ("96 El pago con tu Diners Club no fue procesado. ¡Hola, MORA PAREDES ANA LUCIA! Fecha y hora de este mensaje: 2026-11-12 "
         "13:27 La compra realizada con tu Diners Club 431 por un monto de USD 20.00 el 2026-11-12 13:27 en AVANCE DE EFECTIVO D ha "
         "sido anulada. Recuerda")
ver("anulación es reverso", correos.es_reverso("Notificación anulación DINERS CLUB", ANULA))
g = correos.leer_generico(ANULA)
ver("anulación legible", g and g["monto"] == 20 and g["comercio"] == "AVANCE DE EFECTIVO D")
pid = gastos.crear_pendiente({"monto": 20, "descripcion": "Avance De Efectivo D [gmail:av1]", "medio": "Diners", "fecha": date(2026, 11, 12)})
ev = correos.procesar_reverso("Diners", ANULA, "Notificación anulación DINERS CLUB", "gmail:anula1", datetime(2026, 11, 12, 13, 28))
ver("anulación descarta el avance pendiente", ev[1]["tipo"] == "pendiente" and gastos.pendiente(pid)["estado"] == "descartado")
ver("texto anulación", "ya no le pregunto" in correos.texto_reverso(ev[1]))

# --- diferido de otra persona (13-11) ----------------------------------------------------------------------------
lg = next(d for d in T.activos() if "Lg Shop" in d["descripcion"])
antes_feb = T.cuotas_del_mes("2027-02")[0]
d = T.interpretar("el diferido #" + str(lg["id"]) + " es de Juan")
ver("frase dueño por número", d and d["accion"] == "duenos" and d["acciones"][0]["ids"] == [lg["id"]]
    and d["acciones"][0]["persona"] == "Juan")
r = T.ejecutar(d)
ver("marcado (modo simple: sin «le debe»)", "lo paga Juan" in r and "le debe" not in r and "«listo»" in r)
ver("ya no cuenta en sus cuotas", T.cuotas_del_mes("2027-02")[0] == round(antes_feb - 75, 2))
ver("pero sí con incluir_otros", T.cuotas_del_mes("2027-02", incluir_otros=True)[0] == antes_feb)
c = T.cuenta_dueno(lg)
ver("Juan debe la cuota de este mes", c["facturadas"] == 1 and c["debe"] == 75 and c["restante"] == 525)
ver("cerrar la sesión", "Quedaron así" in T.ejecutar(T.interpretar("listo")) and not T._en_sesion())
ver("frase por descripción", T.interpretar("el diferido de lg shop no es mío, es de juan")["acciones"][0]["ids"] == [lg["id"]])
ver("frase es mío", T.interpretar("el diferido #" + str(lg["id"]) + " es mío")["acciones"][0]["mio"])
ver("no confunde: mis diferidos", T.interpretar("mis diferidos") == {"accion": "ver"})
ver("no confunde: diferido sin dueño", T.interpretar("el diferido de la laptop") is None)

# --- varios mensajes seguidos (13-11: el 2.º mensaje terminaba en «¿borro el deber de Creativa?») -----------------
otros_ids = [x["id"] for x in T.activos() if x["tarjeta"] == "Diners" and x["id"] != lg["id"]]
A, B = otros_ids[0], otros_ids[1]
bermat = next(x for x in T.activos() if "Bermat" in x["descripcion"])
T.marcar_dueno(lg["id"], None)
r1 = T.ejecutar(T.interpretar("el diferido #" + str(lg["id"]) + " no es mío, es de Juan"))
ver("seguido 1", "lo paga Juan" in r1 and T._en_sesion())
d2 = T.interpretar("y el #" + str(A))
ver("seguido 2: «y el #N» usa a Juan", d2 and d2["acciones"][0]["ids"] == [A] and d2["acciones"][0]["persona"] == "Juan")
T.ejecutar(d2)
d3 = T.interpretar("el de bermat tampoco es mío")
ver("seguido 3: por descripción y «tampoco»", d3 and d3["acciones"][0]["ids"] == [bermat["id"]] and d3["acciones"][0]["persona"] == "Juan")
T.ejecutar(d3)
ver("en sesión, un gasto no se toma", T.interpretar("almuerzo 4.50") is None and T.interpretar("5 dólares de uber") is None
    and T.interpretar("tengo 3 tareas") is None)
r5 = T.ejecutar(T.interpretar("listo"))
ver("resumen al terminar", r5.count("→ lo paga Juan") == 3 and not T._en_sesion())
for i in (lg["id"], A, bermat["id"]):
    T.marcar_dueno(i, None)
# varios en un mensaje
d = T.interpretar("los diferidos #" + str(lg["id"]) + ", #" + str(A) + " y #" + str(bermat["id"]) + " son de Pedro")
ver("varios en un mensaje", d and sorted(d["acciones"][0]["ids"]) == sorted([lg["id"], A, bermat["id"]]) and d["acciones"][0]["persona"] == "Pedro")
T.ejecutar(d)
ver("los 3 de Pedro", all(T.dueno(x)["dueno"] == "Pedro" for x in T.activos() if x["id"] in (lg["id"], A, bermat["id"])))
T.ejecutar(T.interpretar("listo"))
# mensaje largo con varias líneas
largo = "el diferido #" + str(lg["id"]) + " es de Juan\nel #" + str(A) + " también\nel de bermat es de mi hermano"
d = T.interpretar(largo)
ver("mensaje largo: 3 acciones", d and len(d["acciones"]) == 3)
T.ejecutar(d)
ver("largo aplicado", T.dueno(lg)["dueno"] == "Juan" and T.dueno(next(x for x in T.activos() if x["id"] == A))["dueno"] == "Juan"
    and T.dueno(bermat)["dueno"] == "mi hermano")
T.ejecutar(T.interpretar("listo"))
# sin decir de quién → pregunta → responde con otro mensaje
T.SESION["persona"] = None
T.marcar_dueno(A, None)
r = T.ejecutar(T.interpretar("el diferido #" + str(A) + " no es mío"))
ver("pregunta de quién es", "¿De quién es el #" + str(A) in r)
ver("«gracias» no es un nombre", T.interpretar("gracias") is None)
d = T.interpretar("de mi tía")
ver("respuesta suelta", d and d["acciones"][0]["ids"] == [A] and d["acciones"][0]["persona"] == "mi tía")
T.ejecutar(d)
ver("aplicado a mi tía", T.dueno(next(x for x in T.activos() if x["id"] == A))["dueno"] == "mi tía")
T.ejecutar(T.interpretar("listo"))
ver("fuera de sesión «listo» no es nuestro", T.interpretar("listo") is None)
ver("fuera de sesión «y el 5» no es nuestro", T.interpretar("y el " + str(A)) is None)
T.marcar_dueno(A, None)
T.marcar_dueno(bermat["id"], None)
T.marcar_dueno(lg["id"], "Juan")

# Juan transfiere → pago del diferido, no ingreso
P_JUAN = ("Estimado/a MORA PAREDES ANA LUCIA Fecha y Hora: 14/noviembre/2026 10:00 Transacción: Transferencia Recibida Produbanco "
          "Detalle Enviada por: JUAN CARLOS VERA LOPEZ Banco Origen: BANCO PICHINCHA Beneficiario: MORA PAREDES ANA LUCIA Cuenta "
          "Beneficiario: XXXXXX12345 Monto: $75.00 Descripción: cuota lg Referencia: 77 Atentamente")
r = cuentas.procesar_texto("Produbanco", P_JUAN, datetime(2026, 11, 14, 10, 0), "gmail:juan1")
ver("transferencia de Juan = pago del diferido", r and r[1][0] == "reembolso")
ver("no es ingreso", not [g for g in gastos.del_periodo(date(2026, 11, 14), date(2026, 11, 14), "ingreso")])
ver("Juan al día", T.cuenta_dueno(lg)["debe"] == 0 and T.cuenta_dueno(lg)["pagado"] == 75)
texto, botones = cuentas.texto_evento(r[1])
ver("aviso de pago de Juan: no es ingreso, sin seguimiento", "Juan Vera" in texto and "No es ingreso" in texto and "debe" not in texto
    and "noreemb" in botones[0][0]["callback_data"])
q = cuentas.no_era_reembolso(r[0])
ver("no era para el diferido → pregunta", q and "¿Qué fue?" in q[0] and T.cuenta_dueno(lg)["pagado"] == 0)
cuentas.aplicar(r[0], "no_contar")
r2 = cuentas.procesar_texto("Produbanco", P_JUAN.replace("Referencia: 77", "Referencia: 78"), datetime(2026, 11, 15, 10, 0), "gmail:juan2")
ver("el siguiente vuelve a ser pago del diferido", r2 and r2[1][0] == "reembolso")
ver("otro con el mismo nombre suelto no", not T.diferidos_de_persona("PEDRO PEREZ"))
# nombre que no coincide con el del banco («mi hermano»): 1 toque y se aprende
bermat = next(x for x in T.activos() if "Bermat" in x["descripcion"])
T.marcar_dueno(bermat["id"], "mi hermano")
P_HNO = P_JUAN.replace("JUAN CARLOS VERA LOPEZ", "LUIS FERNANDO MORA PAREDES").replace("Referencia: 77", "Referencia: 90")
r = cuentas.procesar_texto("Produbanco", P_HNO, datetime(2026, 11, 15, 11, 0), "gmail:hno1")
ver("hermano sin aprender: pregunta", r and r[1][0] == "preguntar")
texto, filas = cuentas.texto_evento(r[1])
boton = next((b for f in filas for b in f if "Paga el diferido de mi hermano" in b["text"]), None)
ver("botón «Paga el diferido de mi hermano»", boton is not None)
t = cuentas.aplicar(r[0], "reembolso", boton["callback_data"].split(":")[3])
ver("aplicado y aprendido", "Desde ahora reconozco" in t and not [g for g in gastos.del_periodo(date(2026, 11, 15), date(2026, 11, 15), "ingreso")])
r = cuentas.procesar_texto("Produbanco", P_HNO.replace("Referencia: 90", "Referencia: 91"), datetime(2026, 11, 16, 11, 0), "gmail:hno2")
ver("la próxima vez solo", r and r[1][0] == "reembolso")
ver("un desconocido no", not T.diferidos_de_persona("MARIA JOSE PAZ"))
T.marcar_dueno(bermat["id"], None)

# nuevo estado de cuenta: el dueño sigue al diferido
AHORA[0] = datetime(2026, 12, 4, 12, 0, tzinfo=ZONA)
nuevo = ESTADO_DINERS.replace("03/NOV/2026", "03/DIC/2026").replace("18 NOV 2026", "18 DIC 2026").replace("(5/12) 75.00 525.00", "(6/12) 75.00 450.00")
T.guardar_estado(T.leer_estado_diners(nuevo), "gmail:diners2")
lg2 = next(d for d in T.activos() if "Lg Shop" in d["descripcion"])
ver("dueño se mantiene con el estado nuevo", lg2["id"] != lg["id"] and T.dueno(lg2) and T.dueno(lg2)["dueno"] == "Juan")
ver("ahora debe la cuota nueva", T.cuenta_dueno(lg2)["facturadas"] == 2 and T.cuenta_dueno(lg2)["debe"] == 75)
ver("estado avisa que el total incluye lo de Juan", "incluye $75 de diferidos que pagan otras personas (Juan)" in T.texto_estado(T.leer_estado_diners(nuevo))
    and "le debe" not in T.texto_estado(T.leer_estado_diners(nuevo)))
ver("diferidos muestra la sección de otros", "Los paga otra persona" in T.texto_diferidos() and "Juan" in T.texto_diferidos())
ver("credito muestra a Juan sin deuda", "lo paga Juan" in T.texto_tarjetas() and "le debe" not in T.texto_tarjetas())
ver("diferidos sin seguimiento de pagos", "Le pagó" not in T.texto_diferidos() and "le debe" not in T.texto_diferidos())
ver("contexto IA con Juan", "lo paga Juan" in T.contexto_ia())
panel_d = next(x for t in T.datos_panel()["tarjetas"] for x in t["diferidos"] if "Lg Shop" in x["descripcion"])
ver("panel con dueño", panel_d["otro"]["dueno"] == "Juan")
# provisional con dueño que pasa al estado de cuenta (cambia la fecha de compra)
did = T.nuevo_diferido("Pichincha Platinum", "Bici", 50, 4)
T.marcar_dueno(did, "Rosa")
est4 = dic_estado.replace("03 DIC 2026", "03 ENE 2027").replace("18 DIC 2026", "18 ENE 2027") + "28/12 1234567 DIF CON NACIONAL ONLINE DIFERIDO 50.00 150.00(1/4)\n"
AHORA[0] = datetime(2027, 1, 4, 12, 0, tzinfo=ZONA)
T.guardar_estado(T.leer_estado_pichincha(est4), "gmail:est4")
bici = next(d for d in T.activos() if d["tarjeta"] == "Pichincha Platinum" and d["total_cuotas"] == 4)
ver("dueño pasa del provisional al del estado", T.dueno(bici) and T.dueno(bici)["dueno"] == "Rosa")

print("TARJETAS: " + str(BIEN + MAL) + " | BIEN: " + str(BIEN) + " | MAL: " + str(MAL))
