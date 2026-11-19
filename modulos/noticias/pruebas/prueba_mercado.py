"""Prueba del mercado en vivo (17-11): índices con historia, resultados, Fed, datos de EE. UU., modos y envío.
Base TEMPORAL; sin internet, sin IA real, sin Telegram. Datos INVENTADOS.

    .\\.venv\\Scripts\\python.exe modulos\\noticias\\pruebas\\prueba_mercado.py
"""
import re
import sys
import tempfile
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))

TEMP = Path(tempfile.mkdtemp()) / "prueba_mercado.db"
from modulos.comun import db  # noqa: E402

db.ARCHIVO = TEMP
from modulos.comun import modo_prueba  # noqa: E402

assert modo_prueba.activo(), "La protección de pruebas no está activa: no sigo."


def _sin_red(*a, **k):
    raise RuntimeError("PRUEBA: no se puede usar internet ni Telegram")


import modulos.comun.base as base  # noqa: E402

base.enviar_telegram = _sin_red
import requests  # noqa: E402

requests.get = requests.post = _sin_red
cerebro = types.ModuleType("modulos.ia.cerebro")
cerebro.config = lambda: {"modelo": "prueba", "keep_alive": "5m", "ollama": "http://ia-falsa", "opciones": {}}
cerebro.memoria = types.SimpleNamespace(historial=lambda n: [], guardar_turno=lambda *a: None)
sys.modules["modulos.ia.cerebro"] = cerebro

from modulos.noticias import mercado, noticias  # noqa: E402
import os  # noqa: E402

os.environ.pop("FRED_API_KEY", None)          # la prueba no usa su clave real de FRED (ni internet)
from zoneinfo import ZoneInfo  # noqa: E402

NY = ZoneInfo("America/New_York")
noticias.BD = TEMP
noticias._listo.clear()
mercado._listo.clear()
ACCIONES = {"META": "Meta Platforms", "JPM": "JPMorgan", "O": "Realty Income"}
noticias.mis_acciones = lambda forzar=False: dict(ACCIONES)
mercado.mis_acciones = lambda: dict(ACCIONES)
mercado.CARPETA = TEMP.parent / "mercado"
PRECIOS = {}
mercado.precio = lambda s: PRECIOS.get(s, (None, None))
IA = {"llamadas": 0}


def ia_falsa(mensajes, esquema, num_predict=900):
    IA["llamadas"] += 1
    props = esquema["properties"]
    if "que_dijo" in props:
        return {"que_dijo": ["Punto uno", "Punto dos", "Punto tres"], "tono": "neutral",
                "esperaba_mercado": "Según titulares, se esperaba que mantuviera.", "que_puede_pasar": "Si la inflación baja, podría recortar.",
                "impacto_acciones": "Realty Income es la más sensible a tasas.", "impacto_mundo": "Dólar estable."}
    if "puntos" in props:
        return {"puntos": ["Dijo A", "Dijo B"]}
    return {"resumen": "Elevó su previsión de ingresos para el próximo trimestre."}


mercado.ia_json = ia_falsa
fallos, total = [], 0


def ok(condicion, que):
    global total
    total += 1
    if not condicion:
        fallos.append(que)


def limpio(t):
    return re.sub(r"<[^>]+>", "", t or "")


# ---------------------------------------------------------------- 1. índices con historia (serie inventada)
def serie_inventada():
    """Sube, cae 40 % (como 2000-02), recupera; corrección de 15 %; cae 25 %; recupera; máximo; hoy −3 %."""
    s, v, d = [], 100.0, date(2000, 1, 3)

    def tramo(dias, cambio_total):
        nonlocal v, d
        paso = (1 + cambio_total) ** (1 / dias)
        for _ in range(dias):
            d += timedelta(days=1)
            while d.weekday() >= 5:
                d += timedelta(days=1)
            v *= paso
            s.append((d, v))
    tramo(200, 0.50)       # máximo
    tramo(300, -0.40)      # bajista −40 %
    tramo(500, 0.70)       # recupera y nuevo máximo
    tramo(60, -0.15)       # corrección −15 %
    tramo(120, 0.25)       # recupera
    tramo(50, -0.10)       # bajista −25 % (con un día de −3,5 %)
    v *= 0.965
    d += timedelta(days=1)
    s.append((d, v))
    tramo(50, -0.1366)
    tramo(250, 0.45)       # máximo nuevo
    tramo(30, -0.02)       # algo abajo
    v *= 0.97              # hoy −3 %
    d += timedelta(days=1)
    s.append((d, v))
    return s


S = serie_inventada()
a = mercado.analizar(S)
ok(a is not None, "analizar devolvió None")
ok(abs(a["dia"] - (-3.0)) < 0.01, "caída del día mal: %s" % a["dia"])
ok(-6 < a["dd"] < -4, "distancia al máximo mal: %s" % a["dd"])
ok(a["etiqueta"] == "cerca de máximos", "etiqueta: " + a["etiqueta"])
fondos = sorted(round(e["fondo_pct"]) for e in a["episodios"])
ok(fondos == [-40, -25, -15], "episodios: %s" % fondos)
ok(all(e["recupero"] for e in a["episodios"]), "todos los episodios pasados se recuperaron")
ok(a["peor_desde"] is not None and abs(a["peor_desde"][1] - (-3.5)) < 0.01, "«mayor caída desde» mal: %s" % (a["peor_desde"],))
c = mercado.comparables(a)
ok(c and c["n"] == 3 and abs(c["mediana_fondo"] - (-25)) < 1, "comparables: %s" % c)
t = limpio(mercado.texto_indice("Nasdaq", a))
ok("bajo su máximo histórico" in t and "mayor caída en un día desde" in t, "texto del índice: " + t)
ok("tuvo 3 caídas de más del 10 %" in t and "Las peores:" in t, "comparación histórica: " + t)
ok(mercado.etiqueta(-21).startswith("mercado bajista") and mercado.etiqueta(-12).startswith("corrección"), "etiquetas")
ok(mercado.etiqueta(-0.1) == "en máximos históricos", "máximos")

# hoy: alerta de índices (se finge que hoy es el último día de la serie y la bolsa está abierta)
hoy_ny = mercado.hora_ny().date()
S2 = [(hoy_ny - timedelta(days=len(S) - 1 - i), v) for i, (_d, v) in enumerate(S)]
mercado.historial = lambda sim: list(S2[:-1])
PRECIOS.update({"^IXIC": (S2[-1][1], S2[-2][1]), "^GSPC": (None, None), "^DJI": (None, None),
                "^VIX": (32.0, 24.0), "^TNX": (4.40, 4.20), "DX-Y.NYB": (99.0, 98.5)})
real_dia_bolsa = mercado.dia_de_bolsa
mercado.dia_de_bolsa = lambda d, a=None: True
_hora = mercado.hora_ny
mercado.hora_ny = lambda t=None: datetime.combine(hoy_ny, datetime.min.time(), NY).replace(hour=11)
r = mercado.revisar_indices()
textos = [limpio(x[1]) for x in r]
ok(any(p == 3 and "Nasdaq" in tx and "−3,0 %" in tx.replace("-", "−") for (p, _), tx in zip(r, textos)),
   "alerta de caída del Nasdaq: %s" % textos)
ok(any("VIX" in tx for tx in textos), "alerta del VIX")
ok(any("bono" in tx and "20 puntos" in tx for tx in textos), "alerta del bono: %s" % textos)
ok(mercado.revisar_indices() == [], "no repite la misma alerta")
PRECIOS["^IXIC"] = (S2[-2][1] * 0.955, S2[-2][1])          # empeora a −4,5 %: avisa otra vez, prioridad máxima
r = mercado.revisar_indices()
ok(len(r) == 1 and r[0][0] == 4, "al empeorar avisa de nuevo con prioridad 4: %s" % r)

# ---------------------------------------------------------------- 2. resultados
ok(mercado.veredicto(1.10, 1.00)[0] == "superó" and mercado.veredicto(0.90, 1.00)[0] == "falló", "veredicto")
ok(mercado.veredicto(1.005, 1.00)[0] == "en línea", "en línea")
ok(abs(mercado.veredicto(1.10, 1.00)[1] - 10) < 1e-9, "sorpresa %")
fecha_res = datetime.combine(hoy_ny, datetime.min.time(), NY).replace(hour=16, minute=5)
mercado.proximos_resultados = lambda t: ({"fecha": fecha_res, "bpa_est": 7.50, "ing_est": 51.2e9,
                                          "historial": [(fecha_res - timedelta(days=90 * k), 7.0, 6.5, 7.7) for k in (4, 3, 2, 1)]}
                                         if t == "META" else None)
REAL = {"bpa": None}
mercado.resultado_real = lambda t, f: (REAL["bpa"], 52.0e9 if REAL["bpa"] else None)
mercado.precio_extendido = lambda t: (612.0, 600.0)
TIT = []
mercado.titulares = lambda horas=24, ticker=None, patron=None, limite=6: \
    [f for f in TIT if (not ticker or f["ticker"] == ticker) and (not patron or re.search(patron, f["titulo"], re.I))][:limite]
mercado.hora_ny = lambda t=None: fecha_res.replace(hour=10)      # mañana del día de resultados
r = mercado.revisar_resultados()
ok(len(r) == 1 and "presenta resultados hoy después del cierre" in limpio(r[0][1]), "aviso previo: %s" % r)
ok("$7,50" in limpio(r[0][1]) and "51,2 mil millones" in limpio(r[0][1]) and "4 veces" in limpio(r[0][1]),
   "lo esperado en el aviso previo: " + limpio(r[0][1]))
ok(mercado.revisar_resultados() == [], "no repite el aviso previo")
mercado.hora_ny = lambda t=None: fecha_res.replace(minute=8)       # 16:08: salió el titular, aún sin números
TIT.append({"ticker": "META", "titulo": "Meta beats estimates as ad revenue jumps", "fuente": "CNBC",
            "publicado": datetime.now(timezone.utc).isoformat()})
r = mercado.revisar_resultados()
ok(len(r) == 1 and r[0][0] == 3 and "según titulares" in limpio(r[0][1]), "titular primero: %s" % r)
REAL["bpa"] = 8.02
TIT.append({"ticker": "META", "titulo": "Meta raises revenue outlook for fourth quarter", "fuente": "Reuters",
            "publicado": datetime.now(timezone.utc).isoformat()})
mercado.hora_ny = lambda t=None: fecha_res.replace(minute=20)
r = mercado.revisar_resultados()
tx = limpio(r[0][1]) if r else ""
ok(len(r) == 1 and "superó" in tx and "+6,9 %" in tx and "52,0 mil millones" in tx, "resultado: " + tx)
ok("+2,0 %" in tx and "Elevó su previsión" in tx and "usted decide" in tx, "reacción y previsiones: " + tx)
ok(mercado.revisar_resultados() == [], "no repite el resultado")
with mercado.closing(mercado._con()) as con:
    ok(con.execute("SELECT COUNT(*) n FROM mercado_reaccion WHERE motivo LIKE 'resultados de META'").fetchone()["n"] == 1,
       "agenda la reacción del día siguiente")

# ---------------------------------------------------------------- 3. Fed
COMUNICADO = ("Recent indicators suggest that economic activity has been expanding at a solid pace. In support of its goals, "
              "the Committee decided to lower the target range for the federal funds rate by 1/4 percentage point to "
              "3-1/4 to 3-1/2 percent. Voting for the monetary policy action were A, B and C. "
              "Voting against the action were Persona Uno and Persona Dos, who preferred no change.")
c = mercado.leer_comunicado(COMUNICADO)
ok(c["rango"] == (3.25, 3.5) and c["accion"] == "bajó" and c["cuanto"] == 0.25, "comunicado: %s" % c)
ok(c["contra"] == ["Persona Uno", "Persona Dos", "who preferred no change"] or len(c["contra"]) >= 2, "votos en contra: %s" % c)
c2 = mercado.leer_comunicado("the Committee decided to maintain the target range for the federal funds rate at 3-1/2 to "
                             "3-3/4 percent.")
ok(c2["rango"] == (3.5, 3.75) and c2["accion"] == "mantuvo" and c2["contra"] == [], "mantener: %s" % c2)
ok(mercado.clasificar_fed("discursos", "Warsh, Economic Outlook") == ("presidente", "Warsh"), "presidente")
ok(mercado.clasificar_fed("discursos", "Gobernadora, Payments") == ("gobernador", "Gobernadora"), "gobernador")
ok(mercado.clasificar_fed("monetaria", "Federal Reserve issues FOMC statement")[0] == "decision", "decisión")
ok(mercado.clasificar_fed("monetaria", "Minutes of the Federal Open Market Committee, October 27-28, 2026")[0] == "actas", "actas")

FEED = {"monetaria": [("Minutes of the FOMC, September", "https://fed.prueba/actas-sep", None, "")],
        "discursos": [("Persona, Old speech", "https://fed.prueba/viejo", None, "")]}
mercado.leer_rss = lambda url: FEED["monetaria" if "monetary" in url else "discursos"]
mercado.texto_pagina = lambda url, maximo=7000: COMUNICADO if "statement" in url else "Texto oficial de prueba."
ok(mercado.revisar_fed() == [], "la primera vez solo aprende lo que ya existía")
FEED["monetaria"].insert(0, ("Federal Reserve issues FOMC statement", "https://fed.prueba/statement", None, ""))
FEED["discursos"].insert(0, ("Warsh, The Economic Outlook", "https://fed.prueba/warsh", None, ""))
FEED["discursos"].insert(0, ("Gobernadora, Payments innovation", "https://fed.prueba/pagos", None, ""))
r = mercado.revisar_fed()
tipos = [(p, limpio(x).split("\n")[0]) for p, x in r]
ok(any(p == 4 and "DECISIÓN DE LA FED" in x for p, x in tipos), "decisión con prioridad 4: %s" % tipos)
dec = limpio(next(x for p, x in r if p == 4))
ok("bajó las tasas en 3,25–3,50 %" in dec and "0,25 puntos" in dec and "Persona Uno" in dec, "hechos de la decisión: " + dec)
ok("Qué esperaba el mercado" in dec and "Sus acciones" in dec and "usted decide" in dec, "análisis de la decisión: " + dec)
ok(any(p == 3 and "presidente de la Fed" in x for p, x in tipos), "discurso del presidente: %s" % tipos)
ok(not any("Payments" in x for p, x in tipos), "discurso sin tema monetario no avisa: %s" % tipos)
ok(mercado.revisar_fed() == [], "no repite")
ok(mercado.estado("fed_rango") == "3.25,3.5", "guarda el rango")

# ---------------------------------------------------------------- 4. datos de EE. UU. (FRED)
def csv_fred(sid, valores, inicio=date(2014, 1, 1)):
    filas = ["observation_date," + sid]
    d = inicio
    for v in valores:
        filas.append(d.isoformat() + "," + ("." if v is None else str(v)))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return "\n".join(filas)


v_conf = [90 + (i % 7) for i in range(140)] + [None, 51.0]          # se desploma: el más bajo de la serie
serie = mercado.leer_fred(csv_fred("UMCSENT", v_conf))
ok(len(serie) == 141 and serie[-1][1] == 51.0, "leer FRED ignora '.'")
p, tx = mercado.interpretar("UMCSENT", serie)
tx = limpio(tx)
ok(p == 2 and "51,0" in tx and "más bajo de toda la serie" in tx and "mala" in tx, "confianza: " + tx)
ipc = [100 * (1.002 ** i) for i in range(150)]
ipc[-1] = ipc[-2] * 1.01                                            # salto de inflación
p, tx = mercado.interpretar("CPIAUCSL", mercado.leer_fred(csv_fred("CPIAUCSL", ipc)))
tx = limpio(tx)
ok(p == 3 and "Inflación anual" in tx and "más alto desde" in tx or "más alto de toda" in tx, "inflación: " + tx)
ok("menos margen para bajar tasas" in tx, "significado inflación: " + tx)
emp = [150000 + 150 * i for i in range(130)] + [150000 + 150 * 129 + 20]
p, tx = mercado.interpretar("PAYEMS", mercado.leer_fred(csv_fred("PAYEMS", emp)))
ok("+20 mil" in limpio(tx) and "−" not in limpio(tx).split("\n")[0][:5], "empleos (cambio): " + limpio(tx))
URLS = {"UMCSENT": csv_fred("UMCSENT", v_conf[:-1])}
mercado.leer_url = lambda url, timeout=20, intentos=1: URLS.get(re.search(r"id=(\w+)", url).group(1), "observation_date,X\n")
ok(mercado.revisar_macro() == [], "la primera vez solo guarda")
URLS["UMCSENT"] = csv_fred("UMCSENT", v_conf)
r = mercado.revisar_macro()
ok(len(r) == 1 and "Confianza del consumidor" in r[0][1], "dato nuevo avisa: %s" % r)
ok(mercado.revisar_macro() == [], "no repite el dato")
LLAMADAS = []


def fred_caido(url, timeout=20, intentos=1):
    LLAMADAS.append(url)
    raise TimeoutError("Read timed out")


mercado.leer_url = fred_caido
ok(mercado.revisar_macro() == [] and len(LLAMADAS) == 1, "si FRED no responde, para en la primera serie: %d" % len(LLAMADAS))
ok(mercado.fred_en_pausa() and mercado.revisar_macro() == [] and len(LLAMADAS) == 1, "y queda en pausa 3 h")
mercado.os.environ["FRED_API_KEY"] = "clave-de-prueba"
ok(not mercado.fred_en_pausa(), "al poner la clave, la pausa del CSV ya no aplica")
mercado.poner_estado("fred_pausa_hasta", None)
mercado.leer_url = lambda url, timeout=20, intentos=1: ('{"observations":[{"date":"2026-09-01","value":"55.1"},'
                                                       '{"date":"2026-10-01","value":"."},{"date":"2026-11-01","value":"50.3"}]}'
                                                       if "api_key=clave-de-prueba" in url else _sin_red())
ok(mercado.serie_fred("UMCSENT") == [(date(2026, 9, 1), 55.1), (date(2026, 11, 1), 50.3)], "API oficial con clave")
del mercado.os.environ["FRED_API_KEY"]

# ---------------------------------------------------------------- 5. modos, silencio, cupo y «Mientras dormía»
ok("más noticias" in mercado.procesar("más noticias") and mercado.modo() == "mas", "modo más")
ok("menos noticias" in mercado.procesar("Jarvis, menos noticias") and mercado.modo() == "menos", "modo menos")
ok("normal" in mercado.procesar("noticias normal") and mercado.modo() == "normal", "modo normal")
ok("silencio hasta mañana" in mercado.procesar("silencio hasta mañana") and mercado.modo() == "silencio", "silencio")
ok(mercado.procesar("¿cuánto gasté hoy?") is None, "no se mete con otras frases")
dia = datetime(2026, 11, 17, 12, 0, tzinfo=base.ZONA)
ok(mercado.repartir([(3, "resultados X")], dia) == [], "en silencio solo pasa lo enorme")
ok(mercado.repartir([(4, "DECISIÓN")], dia) == ["DECISIÓN"], "lo enorme pasa en silencio")
mercado.poner_estado("silencio_hasta", None)
mercado.poner_estado("modo", "normal")
with mercado.closing(mercado._con()) as con, con:
    con.execute("DELETE FROM mercado_cola")
    con.execute("DELETE FROM mercado_enviados")
ok(mercado.repartir([(1, "titular menor")], dia) == [], "modo normal no manda prioridad 1")
noche = datetime(2026, 11, 17, 23, 30, tzinfo=base.ZONA)
ok(mercado.repartir([(3, "Fed habló"), (2, "dato de empleo")], noche) == [], "de noche se guarda")
manana = datetime(2026, 11, 18, 6, 5, tzinfo=base.ZONA)
r = mercado.repartir([], manana)
ok(len(r) == 1 and "Mientras dormía" in r[0] and "Fed habló" in r[0] and "dato de empleo" in r[0], "mientras dormía: %s" % r)
ok(mercado.repartir([], manana) == [], "la cola quedó vacía")
with mercado.closing(mercado._con()) as con, con:
    con.execute("DELETE FROM mercado_enviados")
mucho = [(2, "aviso %d" % i) for i in range(9)]
r = mercado.repartir(mucho, dia)
ok(len(r) == 1 and r[0].count("aviso") == 6, "cupo de 6 por hora agrupado en un mensaje: %s" % r)
r = mercado.repartir([(3, "importante")], dia)
ok(len(r) == 1 and "importante" in r[0], "prioridad 3 pasa aunque se llene el cupo")
ok(len(mercado.agrupar(["x" * 3000, "y" * 3000])) == 2, "parte mensajes largos")

# ---------------------------------------------------------------- 6. cadencia en vivo
mercado.dia_de_bolsa = real_dia_bolsa
mercado.hora_ny = _hora
A = mercado.ajustes()
def ny(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=NY)
ok(mercado.cadencia(ny(2026, 11, 17, 11, 0), A) == 300, "bolsa abierta: 5 min")
ok(mercado.cadencia(ny(2026, 11, 17, 8, 31), A) == 120, "datos de las 8:30: 2 min")
ok(mercado.cadencia(ny(2026, 12, 9, 14, 10), A) == 120, "decisión de la Fed: 2 min")
ok(mercado.cadencia(ny(2026, 11, 18, 14, 5), A) == 120, "actas de la Fed: 2 min")
ok(mercado.cadencia(ny(2026, 11, 17, 23, 0), A) == 1800, "noche: 30 min")
ok(mercado.cadencia(ny(2026, 11, 21, 11, 0), A) == 1800, "sábado: 30 min")
ok(mercado.cadencia(ny(2026, 11, 26, 11, 0), A) == 1800, "feriado (Acción de Gracias): 30 min")
ok(mercado.bolsa_abierta(ny(2026, 11, 17, 9, 45), A) and not mercado.bolsa_abierta(ny(2026, 11, 17, 16, 1), A), "horario")
ok(mercado.en_silencio(datetime(2026, 11, 17, 23, 0, tzinfo=base.ZONA), A) and
   not mercado.en_silencio(datetime(2026, 11, 17, 7, 0, tzinfo=base.ZONA), A), "horas de silencio")
ok(mercado._hora_local_de_ny(date(2026, 12, 9), 14, 0) == datetime(2026, 12, 9, 19, 0, tzinfo=timezone.utc)
   .astimezone(base.ZONA).strftime("%H:%M"), "hora local de la Fed")
ev = mercado.eventos_fed(date(2026, 11, 16), date(2026, 11, 20))
ok(len(ev) == 1 and ev[0][1] == "actas de la Fed", "agenda: actas del 18/11: %s" % ev)

# ---------------------------------------------------------------- 7. comandos sin choques con otros módulos
dup = {}
for archivo in (RAIZ / "modulos").rglob("*.py"):
    if ".antes" in archivo.name or "pruebas" in archivo.parts:
        continue
    for nombre in re.findall(r"CommandHandler\(\s*\"(\w+)\"", archivo.read_text(encoding="utf-8", errors="ignore")):
        dup.setdefault(nombre, set()).add(archivo.name)
for cmd in ("mercado", "macro", "resultados", "agenda_mercado"):
    ok(len(dup.get(cmd, set())) <= 1, "/%s ya lo usa otro módulo: %s" % (cmd, dup.get(cmd)))

print("Casos:", total)
if fallos:
    print("\nFALLOS:", len(fallos))
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("MERCADO: TODO BIEN %d de %d (100 %%)" % (total, total))
