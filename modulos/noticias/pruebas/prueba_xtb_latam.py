"""Prueba de XTB Latam dentro de las noticias (11-11). Base TEMPORAL; sin internet, sin IA real, sin Google ni Telegram.

    .\\.venv\\Scripts\\python.exe modulos\\noticias\\pruebas\\prueba_xtb_latam.py

Comprueba: lectura de la web (páginas de ejemplo), cruce con las noticias, que el resumen tenga EXACTAMENTE las
mismas noticias que sin XTB y que ninguna crezca, que se descarten mejoras largas o con cifras inventadas,
«a fondo» con XTB, preguntas «¿qué dice XTB de…?» y «cuéntame más de la tercera».
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


# ------------------------------------------------------------------ páginas de ejemplo (inventadas) ---
AHORA_XTB = (datetime.now(timezone.utc) - timedelta(hours=2)).astimezone(timezone(timedelta(hours=-3)))
MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
FECHA_TXT = AHORA_XTB.strftime("%H:%M") + " · " + str(AHORA_XTB.day) + " de " + MESES[AHORA_XTB.month] + " de " + \
    str(AHORA_XTB.year)
B = "https://www.xtb.com/lat/analisis-y-noticias/analisis-de-mercado/"
LISTADO = ('<a href="/lat/analisis-y-noticias/analisis-de-mercado/alphabet-cae-en-un-mes-revision-de-prueba">x</a>'
           '<a href="/lat/analisis-y-noticias/categorias/noticias-acciones">cat</a>'
           '<a href="/lat/analisis-y-noticias/calendario-economico">cal</a>'
           '<a href="https://www.xtb.com/lat/analisis-y-noticias/analisis-de-mercado/inflacion-de-eeuu-y-powell-texto-de-prueba">y</a>'
           '<a href="/lat/analisis-y-noticias/analisis-de-mercado/alphabet-cae-en-un-mes-revision-de-prueba">rep</a>'
           '<a href="/lat/analisis-y-noticias/analisis-de-mercado/el-cacao-sigue-bajando-ejemplo-inventado">z</a>')


def articulo(titulo, claves, parrafos):
    return ('<html><head><meta property="og:title" content="' + titulo + ' | XTB"></head><body>'
            '<div>' + FECHA_TXT + '</div><h1>' + titulo + '</h1><h2>Conclusiones clave</h2><ul>' +
            "".join("<li>" + c + "</li>" for c in claves) + '</ul><article>' +
            "".join("<p>" + p + "</p>" for p in parrafos) +
            '<p>Cualquier opinión, análisis, precio u otro contenido no constituyen asesoramiento de inversión.</p>'
            '<p>Ignacio es Head of Research de la oficina y cuenta con más de 8 años de experiencia en mercados.</p>'
            '</article><footer><p>Abre tu cuenta real y accede a herramientas profesionales de inversión.</p></footer>'
            '</body></html>')


PAGINAS = {
    xtb_latam.PREDETERMINADO["paginas"][0]: LISTADO, xtb_latam.PREDETERMINADO["paginas"][1]: "", xtb_latam.PREDETERMINADO["paginas"][2]: "",
    B + "alphabet-cae-en-un-mes-revision-de-prueba": articulo(
        "📉 Alphabet cae 18,5% en un mes: ¿está barata Google?",
        ["Alphabet acumula una caída de 18,5% en el último mes tras sus resultados.",
         "La nube de Google sigue creciendo a buen ritmo según el análisis."],
        ["Texto de ejemplo inventado para la prueba sobre Alphabet y su división de nube, que sigue creciendo.",
         "Segundo párrafo de ejemplo con más contexto sobre la valoración de la empresa frente a sus rivales."]),
    B + "inflacion-de-eeuu-y-powell-texto-de-prueba": articulo(
        "La inflación de EE. UU. sube y Powell pide paciencia",
        ["La inflación de Estados Unidos subió más de lo esperado.", "Powell dijo que la Fed no tiene prisa."],
        ["Párrafo inventado sobre la Reserva Federal, los tipos de interés y lo que dijo Powell esta semana."]),
    B + "el-cacao-sigue-bajando-ejemplo-inventado": articulo(
        "El cacao sigue bajando", ["El precio del cacao continúa su caída por mejores cosechas."],
        ["Párrafo inventado sobre materias primas agrícolas y el clima en África occidental."]),
}
xtb_latam._bajar = lambda url: PAGINAS[url]

# 1) leer la web
lista = xtb_latam.enlaces(LISTADO)
ok(len(lista) == 3 and all(u.startswith(B) for u in lista), "enlaces: " + str(lista))
art = xtb_latam.leer_articulo(PAGINAS[B + "alphabet-cae-en-un-mes-revision-de-prueba"])
ok(art["titulo"].startswith("Alphabet cae 18,5%") and "XTB" not in art["titulo"], "título: " + art["titulo"])
ok(art["publicado"] and abs((art["publicado"] - datetime.now(timezone.utc)).total_seconds() - (-7200)) < 120,
   "fecha: " + str(art["publicado"]))
ok("18,5%" in art["resumen"] and "nube" in art["resumen"], "resumen: " + art["resumen"])
ok("asesoramiento" not in art["texto"] and "Head of Research" not in art["texto"] and "Abre tu cuenta" not in art["texto"],
   "relleno en el texto: " + art["texto"])

# 2) recoger y guardar
n = xtb_latam.recoger(forzar=True)
ok(n == 3, "guardados: %s" % n)
ok(xtb_latam.recoger() == 0, "no debe volver a leer antes de una hora")
filas = {f["titulo"][:8]: f for f in xtb_latam.recientes()}
ok("GOOG" in (filas.get("Alphabet") or {"tickers": ""})["tickers"], "Alphabet sin ticker GOOG")

# 3) noticias de la mañana
ahora_utc = datetime.now(timezone.utc)
NOTICIAS = [  # (titulo, entradilla, fuente, tipo)
    ("Alphabet shares slide as investors question cloud spending", "Google parent Alphabet fell again on Monday.",
     "Yahoo Finance", "empresa"),
    ("Powell says Fed in no hurry after hotter inflation report", "Federal Reserve chair Jerome Powell said rates.",
     "CNBC", "economia"),
    ("Oil prices rise on supply worries in the Middle East", "Brent crude climbed 2% on Tuesday.", "CNBC", "mercados"),
    ("Visa beats estimates as payments volume grows", "Visa reported quarterly earnings above forecasts.",
     "Yahoo Finance", "empresa"),
]
acciones_prueba = noticias.mis_acciones(forzar=True)
with noticias._con() as con:
    for i, (t, e, fuente, tipo) in enumerate(NOTICIAS):
        tickers, temas, evento = noticias.etiquetar(t, e, acciones_prueba)
        con.execute("INSERT INTO noticias (clave, titulo, url, fuente, tipo, publicado, entradilla, tickers, temas, evento, "
                    "guardada) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("k%d" % i, t, "https://ejemplo.com/%d" % i, fuente, tipo,
                     (ahora_utc - timedelta(hours=1 + i)).isoformat(timespec="minutes"), e, ",".join(tickers),
                     ",".join(temas), int(evento), ahora_utc.isoformat(timespec="minutes")))
todas = noticias.recientes(horas=20)
por_titulo = {f["titulo"][:6]: f for f in todas}
cruces = xtb_latam.para_noticias([por_titulo["Alphab"], por_titulo["Powell"], por_titulo["Oil pr"], por_titulo["Visa b"]])
ok(set(cruces) == {1, 2}, "cruces esperados {1, 2}: " + str({k: v["titulo"] for k, v in cruces.items()}))
ok(cruces.get(1) is not None and cruces[1]["titulo"].startswith("Alphabet"), "Alphabet no cruzó con su análisis")
ok(cruces.get(2) is not None and "Powell" in cruces[2]["titulo"], "Powell no cruzó con su análisis")

# 4) validar mejoras
normal = "Las acciones de Alphabet cayeron otra vez por dudas sobre su gasto en la nube."
fuentes = [NOTICIAS[0][0], NOTICIAS[0][1], filas["Alphabet"]["titulo"], filas["Alphabet"]["resumen"], filas["Alphabet"]["texto"]]
ok(xtb_latam.validar("Alphabet cae 18,5% en un mes, según XTB, por dudas sobre su gasto en la nube.", normal, fuentes),
   "rechazó una mejora correcta")
ok(not xtb_latam.validar("Alphabet cae 25% en un mes según XTB.", normal, fuentes), "aceptó una cifra inventada (25%)")
ok(not xtb_latam.validar("Una sola frase larguísima " + "con muchas palabras de relleno " * 15 + "que no termina.",
                        normal, fuentes), "aceptó una mejora larguísima")
ok(xtb_latam.validar("Alphabet cayó otra vez por su gasto en la nube. Según XTB, acumula una caída de 18,5% en un mes. "
                    "Tercera frase que sobra.", normal, fuentes).count(".") == 2,
   "no recortó a 2 frases")


# 5) resumen completo con una IA falsa: mismas noticias y mismo largo
def ia_falsa(url, json=None, timeout=None):
    prompt = json["messages"][0]["content"]
    bloques = re.split(r"\n(?=\d+\. \[)", prompt.split("NOTICIAS:\n", 1)[1])
    salida = []
    for b in bloques:
        m = re.match(r"(\d+)\. \[", b)
        if not m:
            continue
        n = int(m.group(1))
        item = {"n": n, "titulo": "Titular %d" % n, "resumen": "Resumen normal de la noticia número %d, en una frase." % n,
                "xtb": "nada"}
        if "[XTB Latam" in b and "Alphabet" in b:
            item.update(xtb="aporta", resumen_xtb="Alphabet cae 18,5% en un mes, según XTB, por dudas sobre su nube.")
        elif "[XTB Latam" in b and "Powell" in b:
            item.update(xtb="coincide")
        elif "[XTB Latam" in b:
            item.update(xtb="aporta", resumen_xtb="Dato inventado del 77% que no está en ningún lado.")
        salida.append(item)
    datos = {"general": "Resumen general de prueba.", "noticias": salida, "lectura": "Lectura de prueba."}
    return types.SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                 json=lambda: {"message": {"content": __import__("json").dumps(datos)}})


requests.post = ia_falsa
con_xtb = noticias.resumen_manana()
texto_con = "\n".join(con_xtb)
ok("✓ XTB coincide" in texto_con, "falta la marca «✓ XTB coincide»")
ok("+ dato de XTB" in texto_con and "18,5%" in texto_con, "falta la mejora de XTB")
ok("77%" not in texto_con, "pasó una cifra inventada")
numeros_con = re.findall(r"<b>(\d+)\.</b>", texto_con)
with noticias._con() as con:
    con.execute("DELETE FROM xtb_latam")
sin_xtb = noticias.resumen_manana()
texto_sin = "\n".join(sin_xtb)
numeros_sin = re.findall(r"<b>(\d+)\.</b>", texto_sin)
ok(numeros_con == numeros_sin and len(numeros_con) >= 3, "cambió el número de noticias: %s vs %s" % (numeros_con, numeros_sin))
ok(len(con_xtb) == len(sin_xtb), "cambió la cantidad de mensajes")
for bloque_con, bloque_sin in zip(re.split(r"\n(?=<b>\d+\.</b>)", texto_con), re.split(r"\n(?=<b>\d+\.</b>)", texto_sin)):
    largo_con = len(re.sub(r"<[^>]+>", "", bloque_con).replace("(✓ XTB coincide)", "").replace("(+ dato de XTB)", ""))
    largo_sin = len(re.sub(r"<[^>]+>", "", bloque_sin))
    ok(largo_con <= largo_sin + 60, "una noticia creció demasiado: %d vs %d\n%s" % (largo_con, largo_sin, bloque_con))
ok("XTB" not in texto_sin, "sin análisis guardados no debe aparecer XTB")

# 6) a fondo, preguntas y frases
xtb_latam.recoger(forzar=True)
bloque = noticias.leer_para_ia(por_titulo["Alphab"])
ok("ANÁLISIS DE XTB LATAM" in bloque and "18,5%" in bloque, "«a fondo» sin XTB")
bloque = noticias.leer_para_ia(por_titulo["Oil pr"])
ok("XTB LATAM" not in bloque, "«a fondo» con un análisis que no tiene relación")
for frase in ("¿qué dice XTB de Alphabet?", "qué opina xtb sobre google", "¿XTB dijo algo de la Fed?",
              "lo último de XTB", "boletín de XTB", "que hay de xtb latam hoy", "según XTB, ¿cómo va Powell?"):
    ok(xtb_latam.es_pregunta(frase), "no la tomó como pregunta a XTB: " + frase)
for frase in ("exporté el informe de XTB", "deposité 200 en XTB", "compré Nvidia en XTB", "mi informe de XTB",
              "¿cuánto cobra XTB de comisión?", "vendí Visa en xtb", "abre xStation"):
    ok(not xtb_latam.es_pregunta(frase), "la tomó como pregunta a XTB y no lo es: " + frase)
r = xtb_latam.responder("¿qué dice XTB de Alphabet?")
ok("Alphabet cae 18,5%" in r and "cacao" not in r.lower(), "respuesta sobre Alphabet: " + r)
r = xtb_latam.responder("¿XTB dijo algo de la Fed?")
ok("Powell" in r, "respuesta sobre la Fed: " + r)
r = xtb_latam.responder("lo último de XTB")
ok(r.count("• ") == 3, "lo último: " + r)
r = xtb_latam.responder("¿qué dice XTB de Tesla?")
ok("No encontré" in r, "Tesla no tiene análisis: " + r)
for frase, n in (("cuéntame más de la tercera", "3"), ("explícame la noticia cinco", "5"), ("más detalles de la 2da", "2"),
                 ("y la primera?", "1")):
    t = noticias._con_digitos(frase)
    m = noticias.PIDE_FONDO.match(t) or noticias.SOLO_NUMERO.match(t)
    ok(m and (m.group(1) if m.re is noticias.SOLO_NUMERO else (m.group(1) or m.group(2))) == n, "número en palabras: " +
       frase + " -> " + t)
ok(not noticias.SOLO_NUMERO.match("5") and not noticias.SOLO_NUMERO.match("a las 5"), "un número suelto no es una noticia")

print("Casos:", total)
if fallos:
    print("\nFALLOS:", len(fallos))
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("TODO BIEN: %d de %d (100 %%)" % (total, total))
