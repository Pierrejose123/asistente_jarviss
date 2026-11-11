"""Prueba de las secciones nuevas del resumen (11-11): Ecuador, Trump, petróleo, tecnología, cripto, leyes del dinero.
Base TEMPORAL; sin internet, sin IA real, sin Google ni Telegram.

    .\\.venv\\Scripts\\python.exe modulos\\noticias\\pruebas\\prueba_secciones.py
"""
import json
import re
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))

TEMP = Path(tempfile.mkdtemp()) / "prueba_xtb.db"
from modulos.comun import db  # noqa: E402

db.ARCHIVO = TEMP
from modulos.comun import modo_prueba  # noqa: E402

assert modo_prueba.activo(), "La protección de pruebas no está activa: no sigo."


def _sin_red(*a, **k):
    raise RuntimeError("PRUEBA: no se puede usar internet, Google ni Telegram")


try:
    from modulos.calendario import google_cal
    google_cal.servicio = _sin_red
except Exception:
    pass
import modulos.comun.base as base  # noqa: E402

base.enviar_telegram = _sin_red
import requests  # noqa: E402

requests.get = _sin_red                                     # nada sale a internet

# IA y modos falsos (solo dentro de esta prueba)
modos = types.ModuleType("modulos.comun.modos")
modos.en_modo_ligero = lambda: False
sys.modules["modulos.comun.modos"] = modos
import modulos.comun  # noqa: E402

modulos.comun.modos = modos
cerebro = types.ModuleType("modulos.ia.cerebro")
cerebro.config = lambda: {"modelo": "prueba", "keep_alive": "5m", "ollama": "http://ia-falsa", "opciones": {}}
cerebro._simple = lambda texto: "lectura de prueba"
cerebro.memoria = types.SimpleNamespace(historial=lambda n: [], guardar_turno=lambda *a: None)
sys.modules["modulos.ia.cerebro"] = cerebro
try:
    import modulos.ia
    modulos.ia.cerebro = cerebro
except Exception:
    pass

from modulos.noticias import noticias, xtb_latam  # noqa: E402
from modulos.alertas import alertas  # noqa: E402
from modulos.cava import cava  # noqa: E402
from modulos.portafolio import cambios, xtb  # noqa: E402

noticias.BD = alertas.BD = cava.BD = TEMP
for m in (noticias, alertas, cava, xtb_latam):
    if hasattr(m, "_listo"):
        m._listo.clear()
cava.contexto_mercado = lambda *a, **k: ""
EXCEL = {"fecha_informe": datetime(2026, 10, 28), "mtime": datetime(2026, 10, 28), "caja": [], "cerradas": [],
         "archivo": "prueba.xlsx", "lotes": [
             {"ticker": t, "tipo": "BUY", "volumen": 1.0, "precio": 100.0, "fecha": datetime(2026, 5, 1), "nombre": n,
              "categoria": "STOCK", "precio_xtb": None, "producto": "", "posicion": ""}
             for t, n in (("GOOGC.US", "Alphabet Inc Class C"), ("META.US", "Meta Platforms Inc"), ("V.US", "Visa Inc"))]}
xtb.leer = lambda ruta=None: EXCEL
cambios._leer_excel = lambda: EXCEL

fallos, total = [], 0


def ok(condicion, que):
    global total
    total += 1
    if not condicion:
        fallos.append(que)



ahora_utc = datetime.now(timezone.utc)
NOTICIAS = [  # (titulo, entradilla, fuente_config, tipo)
    ("Noboa firma decreto que sube el IVA al 15 % en Ecuador", "El presidente Daniel Noboa firmó el decreto.", "Noboa", "ecuador"),
    ("Asamblea Nacional aprueba ley de inversiones en Ecuador", "La ley fue aprobada con 80 votos.", "Leyes Ecuador", "ecuador"),
    ("Partido de fútbol en Quito termina empatado", "El clásico terminó 1 a 1.", "Ecuador", "ecuador"),
    ("Trump publicó en Truth Social que subirá aranceles a China", "El presidente escribió anoche.", "Trump", "politica"),
    ("Trump says he will raise tariffs on China in Truth Social post", "The president wrote late Monday.", "Trump (EN)", "politica"),
    ("El petróleo Brent sube 3 % por recortes de la OPEP", "La OPEP acordó recortar producción.", "Petróleo", "energia"),
    ("OpenAI presenta un nuevo modelo de inteligencia artificial", "La empresa mostró su nuevo sistema.", "Google Tecnología", "tecnologia"),
    ("Samsung lanza un nuevo smartphone plegable", "El teléfono llega en diciembre.", "Xataka", "tecnologia"),
    ("Apple prepara un iPhone más delgado", "Según reportes, saldría en 2027.", "The Verge", "tecnologia"),
    ("Bitcoin supera los 120.000 dólares por primera vez", "La criptomoneda marcó un récord.", "Cripto", "cripto"),
    ("Ethereum cae 5 % tras un hackeo en un exchange", "Los inversores vendieron.", "Cointelegraph", "cripto"),
    ("La SEC aprueba una nueva regla para stablecoins", "La regla entra en vigor en 2027.", "Money laws", "regulacion"),
    ("Fed's Powell says rates will stay high for longer", "The Federal Reserve chair spoke on Tuesday.", "CNBC", "economia"),
    ("Visa beats estimates as payments volume grows", "Visa reported quarterly earnings above forecasts.", "Yahoo Finance", "empresa"),
    ("Meta shares jump after earnings beat", "Meta Platforms posted strong results.", "Yahoo Finance", "empresa"),
]
a = noticias.ajustes()
tema_de = {f["nombre"]: f.get("tema") for f in a["fuentes"]}
ok(a["version"] == 3 and len(a["fuentes"]) >= 20 and a.get("secciones"), "config v3 con fuentes y secciones")
acciones_prueba = noticias.mis_acciones(forzar=True)
with noticias._con() as con:
    for i, (t, e, fuente, tipo) in enumerate(NOTICIAS):
        tickers, temas, evento = noticias.etiquetar(t, e, acciones_prueba)
        if tema_de.get(fuente) and tema_de[fuente] not in temas:
            temas.append(tema_de[fuente])
        con.execute("INSERT INTO noticias (clave, titulo, url, fuente, tipo, publicado, entradilla, tickers, temas, evento, "
                    "guardada) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("s%d" % i, t, "https://ejemplo.com/s%d" % i, fuente, tipo,
                     (ahora_utc - timedelta(minutes=30 + 10 * i)).isoformat(timespec="minutes"), e, ",".join(tickers),
                     ",".join(temas), int(evento), ahora_utc.isoformat(timespec="minutes")))

t, temas, _ = noticias.etiquetar("Bitcoin y Ethereum suben", "", {})
ok("Cripto" in temas and "Mercados" not in temas, "temas de cripto: " + str(temas))
t, temas, _ = noticias.etiquetar("Noboa envía reforma tributaria a la Asamblea", "", {})
ok("Ecuador" in temas and "Leyes y dinero" in temas, "temas de Ecuador: " + str(temas))


def ia_falsa(url, json=None, timeout=None):
    prompt = json["messages"][0]["content"]
    nums = [int(x) for x in re.findall(r"\n(\d+)\. \[", "\n" + prompt.split("NOTICIAS:\n", 1)[1])]
    datos = {"general": "Resumen general.", "lectura": "Lectura.",
             "noticias": [{"n": n, "titulo": "T%d" % n, "resumen": "Una frase de la noticia %d." % n} for n in nums]}
    return types.SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                 json=lambda: {"message": {"content": __import__("json").dumps(datos)}})


requests.post = ia_falsa
mensajes = noticias.resumen_manana()
texto = "\n".join(mensajes)
plano = re.sub(r"<[^>]+>", "", texto)
for sec in ("🇪🇨 Ecuador", "🇺🇸 Trump", "🛢 Petróleo y energía", "💻 Tecnología", "₿ Cripto", "⚖️ Leyes y dinero",
            "📈 Sus acciones"):
    ok(sec in plano, "falta la sección " + sec)
with noticias._con() as con:
    elegidas = [r["clave"] for r in con.execute("SELECT clave FROM noticias_ultimo ORDER BY n")]
ok(len(mensajes) <= 2, "más de 2 mensajes: %d" % len(mensajes))
ok(len(elegidas) <= 4 + 8 + 10, "demasiadas noticias: %d" % len(elegidas))
ok(not ("s3" in elegidas and "s4" in elegidas), "la misma noticia de Trump salió dos veces")
ok("s0" in elegidas and "s1" in elegidas, "faltan las importantes de Ecuador (decreto y ley)")
ok("s2" not in elegidas, "el fútbol le ganó a una ley de Ecuador")
ok(sum(1 for c in elegidas if c in ("s6", "s7", "s8")) == 2, "Tecnología debe tener 2")
ok(len(elegidas) == len(set(elegidas)), "noticia repetida")

# alertas: todo en un solo mensaje
with noticias._con() as con:
    con.execute("UPDATE noticias SET evento=1, alertada=0 WHERE clave IN ('s13','s14')")
alertas_msgs = noticias.alertas_eventos()
ok(len(alertas_msgs) == 1 and alertas_msgs[0].count("⚡") == 2, "alertas en un mensaje: " + str(alertas_msgs))

print("Casos:", total)
if fallos:
    print("\nFALLOS:", len(fallos))
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("TODO BIEN: %d de %d (100 %%)" % (total, total))
