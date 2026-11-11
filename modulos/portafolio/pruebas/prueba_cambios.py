"""Prueba de «compré / vendí» del portafolio (11-11). Base TEMPORAL; sin Google, sin Telegram, sin Yahoo.

    .\\.venv\\Scripts\\python.exe modulos\\portafolio\\pruebas\\prueba_cambios.py

1) Miles de frases generadas (compras, ventas, ventas parciales, con muletillas y formas de hablar).
2) Frases que NO son del portafolio (gastos, deudas, recordatorios, Cava, diario, alertas, noticias, agenda).
3) Conversación completa: cantidad y precio después, motivo al diario, borrar alertas, deshacer, nombre
   desconocido con «sí», «ya tengo…», informe nuevo de XTB que confirma los cambios, y los lotes de /portafolio.
"""
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))

TEMP = Path(tempfile.mkdtemp()) / "prueba_cambios.db"
from modulos.comun import db  # noqa: E402

db.ARCHIVO = TEMP
from modulos.comun import modo_prueba  # noqa: E402

assert modo_prueba.activo(), "La protección de pruebas no está activa: no sigo."


def _sin_red(*a, **k):
    raise RuntimeError("PRUEBA: no se puede usar Google ni Telegram")


try:
    from modulos.calendario import google_cal
    google_cal.servicio = _sin_red
except Exception:
    pass
import modulos.comun.base as base  # noqa: E402

base.enviar_telegram = _sin_red

from modulos.noticias import noticias  # noqa: E402
from modulos.alertas import alertas  # noqa: E402
from modulos.cava import cava  # noqa: E402
from modulos.portafolio import cambios, xtb  # noqa: E402

noticias.BD = alertas.BD = cava.BD = TEMP
for m in (noticias, alertas, cava):
    if hasattr(m, "_listo"):
        m._listo.clear()
alertas.cotizacion = lambda t: {"precio": 150.0, "previo": 148.0, "max52": 200.0, "min52": 100.0}
YAHOO = {"sofi": ("SOFI", "SoFi Technologies"), "rocket lab": ("RKLB", "Rocket Lab")}
cambios.buscar_yahoo = lambda q: YAHOO.get(q.lower())

INFORME = datetime(2026, 10, 28, 10, 0)


def lote(t, nombre, vol=2.0, precio=100.0):
    return {"ticker": t, "tipo": "BUY", "volumen": vol, "precio": precio, "fecha": datetime(2026, 5, 1),
            "producto": "", "precio_xtb": None, "posicion": "", "categoria": "STOCK", "nombre": nombre}


EXCEL = {"fecha_informe": INFORME, "mtime": INFORME, "caja": [], "cerradas": [], "archivo": "prueba.xlsx",
         "lotes": [lote("META.US", "Meta Platforms Inc"), lote("V.US", "Visa Inc"), lote("O.US", "Realty Income Corp"),
                   lote("KOF.US", "Coca-Cola Femsa SAB de CV"), lote("GOOGC.US", "Alphabet Inc Class C"),
                   lote("AMZN.US", "Amazon.com Inc", 4.0), lote("JPM.US", "JPMorgan Chase & Co")]}
cambios._leer_excel = lambda: EXCEL
xtb.leer = lambda ruta=None: EXCEL

fallos, total = [], 0


def revisar(frase, esperado):
    """esperado: None (no es del portafolio) o lista de (accion, ticker, extra_dict)."""
    global total
    total += 1
    r = cambios.interpretar(frase)
    if esperado is None:
        if r is not None:
            fallos.append(("NO debía entender", frase, r["cambios"]))
        return
    if r is None:
        fallos.append(("No entendió", frase, esperado))
        return
    obtenido = [(c["accion"], c.get("ticker")) for c in r["cambios"]]
    if obtenido != [(a, t) for a, t, _ in esperado]:
        fallos.append(("Distinto", frase, obtenido, "esperaba", [(a, t) for a, t, _ in esperado]))
        return
    for c, (_, _, extra) in zip(r["cambios"], esperado):
        for k, v in extra.items():
            if k == "motivo":
                if (r.get("motivo") or "") != v:
                    fallos.append(("Motivo", frase, r.get("motivo"), "esperaba", v))
            elif (c.get(k) is None) != (v is None) or (v is not None and abs(float(c.get(k)) - v) > 1e-6):
                fallos.append((k, frase, c.get(k), "esperaba", v))


# ------------------------------------------------------------------ 1) frases generadas ---
NOMBRES = [("Nvidia", "NVDA"), ("nvidia", "NVDA"), ("NVDA", "NVDA"), ("Apple", "AAPL"), ("Microsoft", "MSFT"),
           ("Tesla", "TSLA"), ("AMD", "AMD"), ("Palantir", "PLTR"), ("Coca-Cola", "KO"), ("Mercado Libre", "MELI"),
           ("Berkshire", "BRK-B"), ("McDonald's", "MCD"), ("Johnson & Johnson", "JNJ"), ("Netflix", "NFLX"),
           ("Disney", "DIS"), ("Broadcom", "AVGO"), ("JP Morgan", "JPM"), ("Meta", "META"), ("Visa", "V"),
           ("Realty Income", "O"), ("Amazon", "AMZN"), ("Coca Cola Femsa", "KOF"), ("Alphabet", "GOOG"),
           ("Google", "GOOG"), ("Rocket Lab", "RKLB"), ("nvda", "NVDA"), ("MSFT", "MSFT")]
PREFIJOS = ["", "oye jarvis, ", "Jarvis ", "anota que ", "oye, anota que ", "para que sepas, ", "bueno, ",
            "te cuento que ", "apunta que ", "por favor anota que ", "Oye Jarvis anota q ", "señor, "]
FINALES = ["", ".", "!", " señor", " jarvis", ", gracias"]
COMPRAS = [("compré {n}", {}), ("compre {n}", {}), ("ya compré {n}", {}), ("acabo de comprar {n}", {}),
           ("he comprado {n}", {}), ("hoy compré {n}", {}), ("ayer compré acciones de {n}", {}),
           ("compré 3 acciones de {n}", {"cantidad": 3}), ("compré 3 acciones de {n} a 140", {"cantidad": 3, "precio": 140}),
           ("compré {n} a 140", {"precio": 140}), ("compré 0.5 acciones de {n}", {"cantidad": .5}),
           ("compré 2,5 acciones de {n}", {"cantidad": 2.5}), ("compré media acción de {n}", {"cantidad": .5}),
           ("compré dos acciones de {n}", {"cantidad": 2}), ("me compré unas acciones de {n}", {}),
           ("invertí en {n}", {}), ("invertí 200 dólares en {n}", {}), ("metí plata en {n}", {}), ("entré en {n}", {}),
           ("abrí posición en {n}", {}), ("aumenté mi posición en {n}", {}), ("agrega {n} a mi portafolio", {}),
           ("añade {n} a la cartera", {}), ("pon {n} en mi portafolio", {}), ("compré más {n}", {}),
           ("compré {n} en xtb", {}), ("compré {n} otra vez", {}), ("compré {n} hoy", {}),
           ("adquirí acciones de {n}", {}), ("compré 4 acciones de {n} a 182 con 50", {"cantidad": 4, "precio": 182.5}),
           ("compré {n} a 99.90 cada una", {"precio": 99.9}), ("recién compré {n}", {}),
           ("compré {n} porque rompió la resistencia", {"motivo": "rompio la resistencia"}),
           ("acabo de comprar {n} en xStation", {}), ("he invertido en {n}", {})]
VENTAS = [("vendí {n}", {}), ("ya vendí {n}", {}), ("acabo de vender {n}", {}), ("he vendido {n}", {}),
          ("vendí todas mis acciones de {n}", {}), ("vendí todo {n}", {}), ("liquidé {n}", {}),
          ("me deshice de {n}", {}), ("me salí de {n}", {}), ("cerré mi posición en {n}", {}), ("ya no tengo {n}", {}),
          ("ya no tengo acciones de {n}", {}), ("saca {n} de mi portafolio", {}), ("quita {n} del portafolio", {}),
          ("elimina {n} de la cartera", {}), ("{n} ya no está en mi portafolio", {}), ("hoy vendí {n}", {}),
          ("vendí {n} porque ya no me convence", {"motivo": "ya no me convence"})]
PARCIALES = [("vendí la mitad de {n}", {"fraccion": .5}), ("vendí parte de {n}", {}),
             ("vendí 2 acciones de {n}", {"cantidad": 2}), ("reduje {n}", {}), ("vendí el 30% de {n}", {"fraccion": .3}),
             ("vendí un poco de {n}", {}), ("vendí una acción de {n}", {"cantidad": 1})]

for pref in PREFIJOS:
    for fin in FINALES[:3] if pref else FINALES:
        for nombre, t in NOMBRES:
            for plantilla, extra in COMPRAS:
                revisar(pref + plantilla.format(n=nombre) + fin, [("compra", t, extra)])
            for plantilla, extra in VENTAS:
                esperado_t = "KOF" if nombre == "Coca-Cola" else t        # vende la suya (Coca-Cola Femsa)
                revisar(pref + plantilla.format(n=nombre) + fin, [("venta", esperado_t, extra)])
            for plantilla, extra in PARCIALES:
                esperado_t = "KOF" if nombre == "Coca-Cola" else t
                revisar(pref + plantilla.format(n=nombre) + fin, [("parcial", esperado_t, extra)])

# Varias en una frase
MEZCLAS = [("vendí Visa y compré Nvidia", [("venta", "V", {}), ("compra", "NVDA", {})]),
           ("compré Nvidia y AMD", [("compra", "NVDA", {}), ("compra", "AMD", {})]),
           ("compré Apple, Microsoft y Tesla", [("compra", "AAPL", {}), ("compra", "MSFT", {}), ("compra", "TSLA", {})]),
           ("vendí Meta y JPM", [("venta", "META", {}), ("venta", "JPM", {})]),
           ("ayer vendí la mitad de Amazon y compré Palantir", [("parcial", "AMZN", {"fraccion": .5}), ("compra", "PLTR", {})]),
           ("me deshice de Realty Income y entré en Broadcom", [("venta", "O", {}), ("compra", "AVGO", {})]),
           ("compré Procter & Gamble", [("compra", "PG", {})]), ("compré Johnson and Johnson", [("compra", "JNJ", {})]),
           ("compré acciones de SOFI", [("compra", "SOFI", {})]), ("compré SOFI", [("compra", "SOFI", {})]),
           ("ya tengo Meta", [("compra", "META", {})]), ("tengo 3 acciones de Nvidia", [("compra", "NVDA", {"cantidad": 3})]),
           ("vendí Coca-Cola", [("venta", "KOF", {})])]
for frase, esperado in MEZCLAS:
    revisar(frase, esperado)

# ------------------------------------------------------------------ 2) frases que NO son del portafolio ---
NO_SON = """compré pan 3
compré pinceles por 12 con la gold
compré comida
compré un regalo para mi novia
compré el libro de Cava
compré café en Starbucks
compré unos audífonos en Amazon
compré en Amazon unos audífonos
compré algo en Amazon
compré spotify por 10
compré meta por 20 con la gold
compré la meta de ahorro del viaje
vendí la bici en 50
vendí mi carro
vendí 5 abonos
uber 3.20 con diners
gasté 15 en el super
almuerzo 4.50
sueldo 800
le debo 200 a mi tío
Juan me debe 500 por la laptop
Juan me pagó 100
recuérdame que compre Nvidia mañana
recuérdame comprar acciones de Apple el viernes
avísame si NVDA baja de 120
avísame si V sube 35 % desde mi compra
decisión: compro V porque rompió la resistencia de 340
decisión: vendo META porque está cara
trade NVDA compra 140 stop 132 objetivo 160
cerré el trade 3 a 155
cerrar trade 3 a 155
nota cava: NVDA rompe 140
compré Nvidia en demo
compré 2 de NVDA en práctica
quiero comprar Nvidia
quiero vender Visa
debería vender Visa?
¿compré Nvidia?
si compro Nvidia qué pasa
voy a comprar Apple
pienso vender Meta
tengo que vender Visa
me gustaría comprar Tesla
¿cuánto gané con Nvidia?
¿qué noticias hay de Nvidia?
cuéntame más de la 3
¿cómo va mi portafolio?
¿tengo clase mañana?
¿tengo tareas?
ya tengo la tarea lista
ahora tengo hambre
tengo sueño
vendí la idea al cliente
salí de clases
salí de casa temprano
cerré la ventana
me salí de la reunión
compré entradas para el cine
compré gasolina por 20
compré en Walmart
le dije a mi novia que compré Nvidia
qué acciones me recomiendas comprar
vendí mi alma
compré tiempo
entré en la clase de Multimedia
entré a Teams
reduje el gasto en comida
bajé de peso
metí la pata
invertí tiempo en el proyecto
cuando compre Nvidia te aviso
la meta del mes es ahorrar 100
no compré nada hoy
borra el gasto de uber
deshaz lo último
mis alertas
mi diario
hola jarvis
gracias
sí
no""".split("\n")
for frase in NO_SON:
    revisar(frase, None)

print("Frases revisadas:", total)

# ------------------------------------------------------------------ 3) conversación completa ---
def paso(frase, debe_contener=None, debe_ser_none=False):
    global total
    total += 1
    r = cambios.procesar(frase)
    if debe_ser_none:
        if r is not None:
            fallos.append(("Conversación: NO debía responder", frase, r))
        return r
    if r is None or (debe_contener and debe_contener.lower() not in r.lower()):
        fallos.append(("Conversación", frase, r, "esperaba", debe_contener))
    return r


cambios._ultima_respuesta_mia = lambda minutos=15: True
paso("compré Nvidia", "compró NVDA")
tiene, _ = cambios.tenencias()
assert "NVDA" in tiene, tiene
assert "NVDA" in noticias.mis_acciones(forzar=True), "las noticias no siguen NVDA"
paso("fueron 3 acciones a 140", "3 acciones a 140")
f = cambios.ultimo()
assert f["cantidad"] == 3 and f["precio"] == 140, dict(f)
paso("porque rompió la resistencia de 135", "diario")
with alertas._con() as con:
    d = con.execute("SELECT * FROM decisiones ORDER BY id DESC LIMIT 1").fetchone()
assert d and d["ticker"] == "NVDA" and d["accion"] == "compra" and "resistencia" in d["motivo"], d and dict(d)

alertas.crear({"ticker": "V", "tipo": "nivel", "direccion": "baja", "valor": 300.0, "referencia": None}, "prueba")
r = paso("vendí Visa", "¿las borro?")
assert "V" not in noticias.mis_acciones(forzar=True), "las noticias siguen V"
paso("sí", "Borré 1 alerta")
assert not [a for a in alertas.activas() if a["ticker"] == "V"]

paso("vendí la mitad de Amazon", "la mitad de AMZN")
assert "AMZN" in cambios.tenencias()[0], "con venta parcial la acción se queda"
paso("deshaz lo último", "quité el cambio")
paso("compré 2 acciones de AMD", "2 acciones")
f = cambios.ultimo()
assert f["precio"] == 150 and f["precio_aprox"] == 1, dict(f)
paso("a 120", "a 120")
assert cambios.ultimo()["precio"] == 120 and not cambios.ultimo()["precio_aprox"]
paso("no compré AMD", "quité el cambio")
assert "AMD" not in cambios.tenencias()[0]

paso("compré SOFI", "¿Se refiere a SOFI")
paso("sí", "compró SOFI")
assert "SOFI" in cambios.tenencias()[0]
paso("compré acciones de Empresa Inventada", "No reconozco")
paso("ya tengo Meta", "ya está en su portafolio")
paso("¿tengo Visa?", "No, señor")
paso("¿todavía tengo Meta?", "Sí, señor")
paso("¿tengo clase mañana?", debe_ser_none=True)
paso("qué acciones tengo", "Sus acciones")
paso("mis cambios del portafolio", "Cambios desde su último informe")
paso("compré pan 3", debe_ser_none=True)
paso("sí", debe_ser_none=True)                       # sin nada pendiente: no responde

cambios._ultima_respuesta_mia = lambda minutos=15: False
paso("deshaz lo último", debe_ser_none=True)           # lo último no fue del portafolio: lo atiende otro módulo

# Lotes para /portafolio
lotes = [lote("AMZN.US", "Amazon", 4.0), lote("V.US", "Visa"), lote("META.US", "Meta")]
nuevos, notas = cambios.ajustar_lotes(lotes, INFORME, lambda t: xtb.a_yahoo(t))
tickers = sorted({xtb.a_yahoo(l["ticker"]) for l in nuevos})
assert "V" not in tickers and "NVDA" in tickers and "SOFI" not in tickers, tickers
assert "SOFI" in notas["sin_cantidad"], notas
nv = [l for l in nuevos if l["ticker"] == "NVDA"][0]
assert nv["volumen"] == 3 and nv["precio"] == 140, nv

# Informe nuevo de XTB: lo contado antes pasa a confirmado y manda el Excel
EXCEL["fecha_informe"] = datetime.now() + timedelta(minutes=5)
n = cambios.conciliar_con_ultimo()
assert n >= 3 and not cambios.activos(), (n, [dict(x) for x in cambios.activos()])
assert "V" in cambios.tenencias()[0], "con el informe nuevo, manda el Excel"
assert "V" in cambios.vendidas(), "la venta reciente sigue contando para quitar su calendario de Google"

print("Total de casos:", total)
if fallos:
    print("\nFALLOS:", len(fallos))
    for x in fallos[:60]:
        print(" -", x)
    sys.exit(1)
print("TODO BIEN: %d de %d (100 %%)" % (total, total))
