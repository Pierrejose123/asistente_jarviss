"""Prueba del AGENTE DE LA EMPRESA (Fase 3, 12-11). Base y config TEMPORALES; internet, IA y vectores simulados.
python modulos\\empresa\\pruebas\\prueba_empresa.py"""
import hashlib
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import numpy as np  # noqa: E402

from modulos.comun import db  # noqa: E402
TMP = Path(tempfile.mkdtemp())
db.ARCHIVO = TMP / "prueba.db"                                    # base temporal (bloquea Google y Telegram)
from modulos.comun.base import ZONA  # noqa: E402
from modulos.biblioteca import biblioteca  # noqa: E402
from modulos.noticias import noticias  # noqa: E402
from modulos.empresa import empresa as E  # noqa: E402

E.ARCHIVO = TMP / "empresa.json"
AHORA = [datetime(2026, 11, 13, 17, 30, tzinfo=ZONA)]               # viernes
E.ahora = lambda: AHORA[0]

FEEDS = {
    "inteligencia artificial Ecuador": [("Ecuador lanza plan nacional de inteligencia artificial para pymes - Primicias",
                                         "https://x/1", "El gobierno anunció capacitación en IA para pequeñas empresas")],
    "inteligencia artificial abogados": [("Despachos de abogados en Latinoamérica adoptan IA para revisar contratos - Legal Today",
                                          "https://x/2", "Abogados usan asistentes de IA")],
    "nueva herramienta de inteligencia artificial": [("Nueva herramienta de IA resume reuniones automáticamente - Xataka",
                                                      "https://x/3", "Una nueva herramienta")],
    "AI tools for small business": [("10 AI tools for small business owners - Forbes", "https://x/4", "List of tools")],
    "OpenAI OR Anthropic OR Gemini lanzamiento": [("Fútbol: resultados de la jornada - ESPN", "https://x/5", "deportes")],
    "Acme IA": [("Acme IA lanza chatbot de WhatsApp para abogados en Guayaquil - El Universo", "https://x/6",
                 "La empresa ecuatoriana Acme IA presentó un chatbot para despachos jurídicos")],
}


def leer_rss_falso(url, timeout=15):
    from urllib.parse import unquote_plus
    q = unquote_plus(re.search(r"q=(.*?)\+when", url).group(1))
    m = re.match(r'^"([^"]+)"', q)                                  # búsqueda de competidor: «"Nombre" (IA OR …)»
    q = m.group(1) if m else q.strip('"')
    if q == "IA empresas Ecuador":                                  # el mismo titular por otra búsqueda: no duplica
        return [(FEEDS["inteligencia artificial Ecuador"][0][0], "https://x/1b", "", )[:2] + (None, "")]
    return [(t, u, datetime(2026, 11, 13, 12, tzinfo=timezone.utc), r) for t, u, r in FEEDS.get(q, [])]


def vectores_falsos(textos, consulta=False):
    filas = []
    for t in textos:
        v = np.zeros(128, dtype=np.float32)
        for p in re.findall(r"\w{4,}", E._sin_tildes(t)):
            v[int(hashlib.md5(p.encode()).hexdigest(), 16) % 128] += 1
        filas.append(v / (np.linalg.norm(v) + 1e-9))
    return np.array(filas, dtype=np.float16)


IA = []


def ia_falsa(instruccion, max_tokens=700, esquema=None, ligero_permitido=False):
    IA.append(instruccion)
    if esquema is E.ESQUEMA_INFORME:
        return {"resumen": "Semana clave: Ecuador impulsa la IA en pymes.",
                "novedades": [{"n": 1, "por_que_importa": "Abre puertas con pymes"}, {"n": 99, "por_que_importa": "x"},
                              {"n": 2, "por_que_importa": "Su público ya lo usa"}],
                "competencia": "Acme IA lanzó un chatbot para abogados.",
                "oportunidades": ["Ofrecer a 3 abogados amigos un asistente gratis", "b", "c", "d"],
                "acciones": ["Hablar con 2 abogados", "Grabar un TikTok", "Armar una demo"],
                "borradores": [{"red": "Instagram", "tema": "IA para abogados", "texto": "¿Sabías que…? #IA"},
                               {"red": "TikTok", "tema": "3 usos de IA", "texto": "[Gancho] …"}]}
    if esquema is E.ESQUEMA_COMP:
        return {"empresas": [{"nombre": "Robots EC", "web": "https://robots.ec", "que_ofrecen": "Chatbots para pymes",
                              "es_competidor": True},
                             {"nombre": "El Universo", "web": "https://eluniverso.com", "que_ofrecen": "Noticias",
                              "es_competidor": False},
                             {"nombre": "Acme IA", "web": "https://acme.ec", "que_ofrecen": "IA", "es_competidor": True}]}
    if esquema is E.ESQUEMA_POST:
        return {"texto": "🤖 Post sobre " + instruccion.split("«")[1].split("»")[0]}
    return "• Idea 1\n• Idea 2"


noticias.leer_rss = leer_rss_falso
noticias.buscar_web = lambda consulta, n=5: [{"titulo": "Robots EC - chatbots", "url": "https://robots.ec/servicios",
                                              "extracto": "Automatizamos su negocio"},
                                             {"titulo": "Wikipedia IA", "url": "https://es.wikipedia.org/wiki/IA", "extracto": ""}]
biblioteca._ia = ia_falsa
biblioteca.vectores = vectores_falsos

bien, mal = 0, []


def ok(cond, que, extra=""):
    global bien
    if cond:
        bien += 1
    else:
        mal.append(que + ("  =>  " + str(extra)[:300] if extra != "" else ""))


# 1) config y frases
a = E.ajustes()
ok(E.ARCHIVO.exists() and a["informe"]["dia"] == "viernes" and "TikTok" in a["redes"], "config por defecto")
r = E.procesar("agrega competidor Acme IA (acme.ec)")
ok(r.startswith("🏁 Listo") and E.competidores()[0]["web"] == "acme.ec", "agregar competidor con web", r)
ok(E.procesar("agrega competidor acme ia").startswith("Ya lo"), "no duplica (sin tildes/mayúsculas)")
ok("Acme IA" in E.procesar("mis competidores"), "ver competidores")
FR = [("qué hay de nuevo en IA", str), ("novedades de inteligencia artificial", str), ("busca competidores", "descubrir"),
      ("hazme un post sobre IA para abogados", "borrador"), ("escríbeme un guion sobre chatbots para TikTok", "borrador"),
      ("dame ideas para mi empresa", "ideas"), ("informe de la empresa", "informe"), ("Jarvis, reporte semanal de mi empresa", "informe")]
for frase, esperado in FR:
    r = E.procesar(frase)
    if esperado is str:
        ok(isinstance(r, str), "frase: " + frase, r)
    else:
        ok(isinstance(r, dict) and r["tarea"] == esperado, "frase: " + frase, r)
r = E.procesar("escríbeme un guion sobre chatbots para TikTok")
ok(r["red"] == "TikTok" and r["tema"] == "chatbots", "red y tema del guion", r)
ok(E.procesar("hazme un post sobre IA para abogados")["red"] == "Instagram", "post = Instagram")
for frase in ["qué ideas tengo del negocio", "idea: un chatbot", "noticias de Nvidia", "mis deudas", "agua", "quita un vaso de agua",
              "hazme un resumen del día", "busca en mis notas competidores"]:
    ok(E.procesar(frase) is None, "no es de la empresa: " + frase, E.procesar(frase))

# 2) recoger
n = E.recoger()
ok(n == 6, "recoge 6 (sin el duplicado)", n)
ok(E.recoger() == 0, "la segunda vez no repite")
lista = E.hallazgos(7, 20)
titulos = [h["titulo"] for h in lista]
ok(titulos[0].startswith("Acme IA lanza") and lista[0]["categoria"] == "competidor", "competidor arriba", titulos)
ok(lista[0]["fuente"] == "El Universo" and " - " not in titulos[0], "fuente separada del titular", lista[0]["fuente"])
futbol = next(h for h in lista if "Fútbol" in h["titulo"])
ecu = next(h for h in lista if "Ecuador lanza" in h["titulo"])
ok(futbol["relevancia"] < ecu["relevancia"], "fútbol menos relevante que IA en Ecuador",
   (futbol["relevancia"], ecu["relevancia"]))

# 3) aviso de competidor (máx. 1 por día)
aviso = E.aviso_competidor()
ok(aviso and "Acme IA" in aviso, "aviso de competidor", aviso)
ok(E.aviso_competidor() is None, "solo un aviso por día")

# 4) informe
d = E.generar_informe()
ok(d and d["resumen"].startswith("Semana clave"), "informe generado", d)
ok(len(d["novedades"]) == 2 and d["novedades"][0]["titulo"] == titulos[0], "novedades con número válido", d["novedades"])
ok(len(d["oportunidades"]) == 3 and len(d["borradores"]) == 2, "3 oportunidades y 2 borradores")
ok(E.generar_informe() is None, "una vez por semana")
ok(E.generar_informe(forzar=True) is not None, "forzado (a pedido)")
t = E.texto_informe(E.ultimo_informe())
ok("🚀 Su empresa de IA" in t and "☐ Hablar con 2 abogados" in t and "borradores" in t, "texto del informe", t)
ok("abogados" in IA[-1] and "Acme IA" in IA[-1], "el informe usa público y competidores")

# 5) competidores descubiertos
nuevos = E.descubrir_competidores()
ok([x[1] for x in nuevos] == ["Robots EC"], "propone solo competidores nuevos reales", nuevos)
ok("Wikipedia" not in IA[-1], "filtra Wikipedia antes de la IA")
cid = nuevos[0][0]
ok(E.competidores("propuesto")[0]["nombre"] == "Robots EC", "queda propuesto")
E.cambiar_competidor(cid, "seguido")
ok(len(E.competidores()) == 2, "seguir propuesto")
ok(E.procesar("quita competidor robots").startswith("🗑️"), "quitar competidor")
ok(len(E.competidores()) == 1, "quedó uno")

# 6) borrador e ideas
b = E.borrador("IA para abogados", "TikTok")
ok(b and "IA para abogados" in b and "TikTok" in IA[-1], "borrador TikTok", b)
ok(E.borradores(10)[0]["red"] == "TikTok", "borrador guardado")
ok(E.ideas().startswith("💡"), "ideas")

# 6b) noticias que NO son del competidor y frases para quitarlos
E.agregar_competidor("Moks", "moks.com")
FEEDS["Moks"] = [("Mercado Libre invierte en startups latinas - Ecosistema Startup", "https://x/ml",
                  "Moks y otras empresas en el ecosistema"),
                 ("Moks lanza asistente de IA para tiendas - Primicias", "https://x/moks1", "nuevo asistente"),
                 ("Moks: los mejores zapatos de la temporada - Moda", "https://x/moks2", "calzado")]
_rss_viejo = noticias.leer_rss


def rss_moks(url, timeout=15):
    if "Moks" in url or "moks" in url.lower():
        return [(t, u, datetime(2026, 11, 13, 12, tzinfo=timezone.utc), r) for t, u, r in FEEDS["Moks"]]
    return _rss_viejo(url, timeout)


noticias.leer_rss = rss_moks
E.recoger()
moks = {h["titulo"]: h for h in E.hallazgos(7, 50)}
ok(moks["Moks lanza asistente de IA para tiendas"]["categoria"] == "competidor", "noticia real del competidor")
ok(moks.get("Mercado Libre invierte en startups latinas") is None or
   moks["Mercado Libre invierte en startups latinas"]["categoria"] != "competidor", "Mercado Libre NO es del competidor")
ok(all(h["categoria"] != "competidor" for h in E.hallazgos(7, 50) if "zapatos" in h["titulo"]) or print([dict(h) for h in E.hallazgos(7, 50) if "zapatos" in h["titulo"]]),
   "nombre corto sin tema de tecnología no cuenta")
with E._con() as con:                                  # un error viejo ya guardado se corrige solo
    con.execute("UPDATE emp_hallazgos SET categoria = 'competidor', competidor = (SELECT id FROM emp_competidores "
                "WHERE nombre = 'Moks') WHERE titulo LIKE 'Mercado Libre%'")
ok(E.revisar_competidores() >= 1, "corrige lo viejo")
AHORA[0] = datetime(2026, 11, 14, 9, 0, tzinfo=ZONA)
av = E.aviso_competidor()
ok(av is None or "Mercado Libre" not in av, "el aviso nunca es de Mercado Libre", av)
if av:
    ok(E.procesar("esa noticia no tiene que ver").startswith("👍"), "corregir aviso equivocado")
noticias.leer_rss = _rss_viejo
AHORA[0] = datetime(2026, 11, 13, 17, 30, tzinfo=ZONA)
QUITAR = ["quita a Moks", "elimina el competidor Moks", "borra a moks de mis competidores", "ya no sigas a Moks",
          "deja de seguir a Moks", "no quiero seguir a la empresa Moks", "Moks ya no es mi competidor",
          "no me interesa Moks", "saca a Moks de la lista", "elimina la empresa moks.com", "descarta a Moks porfa",
          "olvídate de Moks"]
for frase in QUITAR:
    E.agregar_competidor("Moks", "moks.com")
    r = E.procesar(frase)
    ok(r and r.startswith("🗑️") and not any(c["nombre"] == "Moks" for c in E.competidores()), "quitar: " + frase, r)
E.agregar_competidor("Moks", "moks.com")
seguidos = sorted(E.competidores(), key=lambda c: E._sin_tildes(c["nombre"]))
n = [i for i, c in enumerate(seguidos, 1) if c["nombre"] == "Moks"][0]
ok(E.procesar("quita el competidor " + str(n)).startswith("🗑️ Listo: ya no sigo a Moks"), "quitar por número")
r = E.procesar("elimina el competidor Zeta")
ok(r.startswith("No encuentro «zeta»") and "Competidores que sigue" in r, "no existe: muestra la lista", r)
E.agregar_competidor("Acme Labs", "")
r = E.procesar("quita el competidor acme")
ok(r.startswith("Hay varios parecidos"), "varios parecidos: pregunta", r)
E.cambiar_competidor(E.buscar_competidor("Acme Labs")["id"], "descartado")
for frase in ["borra la nota 3", "elimina el recordatorio de mañana", "quita un vaso de agua", "borra la deuda de Juan",
              "elimina el gasto de acme"]:
    ok(E.procesar(frase) is None, "no es quitar competidor: " + frase, E.procesar(frase))
ok(any(c["nombre"] == "Acme IA" for c in E.competidores()), "Acme IA sigue después de todo")

# 7) plan del dueño
r = E.procesar("mi plan de empresa")
ok(r.startswith("🚀 Lo que sé") and "(no lo sabe todavía)" in r, "ver plan vacío", r)
plantilla = E.procesar("actualiza mi plan de empresa")
ok("plan de empresa:" in plantilla and "Qué ofrece:" in plantilla, "plantilla del plan", plantilla)
r = E.procesar("plan de empresa:\nQue ofrece: asistentes de IA a medida\nHoras por semana: 10\nPor descubrir: qué le quita tiempo; nombre\nNada: x")
ok(r.startswith("✅ Plan actualizado") and "qué ofrece" in r, "guardar plan", r)
pl = E.ajustes()["plan"]
ok(pl["servicios"] == "asistentes de IA a medida" and pl["horas_semana"] == "10" and pl["por_descubrir"] == ["qué le quita tiempo", "nombre"],
   "plan guardado en la config", pl)
ok(E.procesar("plan de empresa:\nHoras por semana: 10").startswith("El plan ya"), "sin cambios")
E.generar_informe(forzar=True)
ok("asistentes de IA a medida" in IA[-1] and "Por descubrir: qué le quita tiempo" in IA[-1], "el informe usa el plan", IA[-1][:400])
ok(E.procesar("plan de negocio: algo") is None, "«plan de negocio:» sigue siendo del segundo cerebro")

# 8) panel
p = E.datos_panel()
ok(p["informe"] and p["hallazgos"] and p["competidores"] and p["borradores"] and p["plan"], "datos del panel",
   {k: bool(v) for k, v in p.items()})

print("EMPRESA:", bien + len(mal), "| BIEN:", bien, "| MAL:", len(mal))
for m in mal:
    print("  MAL:", m)
