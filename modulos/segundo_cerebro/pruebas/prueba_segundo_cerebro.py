"""Prueba del SEGUNDO CEREBRO (Fase 1, 12-11). Base TEMPORAL; la IA y los vectores se simulan (no usa Ollama,
Google ni Telegram).   python modulos\\segundo_cerebro\\pruebas\\prueba_segundo_cerebro.py"""
import hashlib
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # la consola de Windows no se cae con emojis
except Exception:
    pass
import numpy as np  # noqa: E402

from modulos.comun import db  # noqa: E402
db.ARCHIVO = Path(tempfile.mkdtemp()) / "prueba.db"            # base temporal (bloquea Google y Telegram)
from modulos.comun.base import ZONA  # noqa: E402
from modulos.biblioteca import biblioteca  # noqa: E402
from modulos.ia import memoria  # noqa: E402
memoria.INICIALES = ["Prefiere que lo llamen solo 'senor' y que lo traten de usted."]   # no depende de su config real
from modulos.segundo_cerebro import segundo_cerebro as sc  # noqa: E402

AHORA = [datetime(2026, 11, 15, 18, 0, tzinfo=ZONA)]
sc.ahora = lambda: AHORA[0]

SINONIMOS = {"cobrar": "precio", "tarifa": "precio", "precios": "precio", "clientes": "cliente", "pymes": "pyme",
             "empresas": "pyme", "negocios": "pyme", "ingles": "idioma", "english": "idioma"}


def _vec_falso(textos, consulta=False):
    """Vectores simulados: bolsa de palabras con sinónimos (para probar la búsqueda por significado)."""
    filas = []
    for t in textos:
        v = np.zeros(256, dtype=np.float32)
        for p in re.findall(r"\w{3,}", sc._sin_tildes(t)):
            p = SINONIMOS.get(p, p)
            v[int(hashlib.md5(p.encode()).hexdigest(), 16) % 256] += 1
        v /= np.linalg.norm(v) + 1e-9
        filas.append(v)
    return np.array(filas, dtype=np.float16)


IA_LLAMADAS = []


def _ia_falsa(instruccion, max_tokens=700, esquema=None, ligero_permitido=False):
    IA_LLAMADAS.append(instruccion[:60])
    if esquema is sc.ESQUEMA_ORDEN:
        return {"area": "negocio" if "cliente" in instruccion.lower() else "personal", "tipo": "idea",
                "etiquetas": ["Ventas", "ventas", "clientes"]}
    if esquema is sc.ESQUEMA_REVISION:
        return {"datos": ["Quiere fundar una empresa de IA en Ecuador.", "Estudia inglés cada noche.",
                          "Prefiere que lo llamen solo 'señor' y que lo traten de usted."]}   # este último ya se sabe
    return "• Resumen de prueba"


biblioteca.vectores = _vec_falso
biblioteca._ia = _ia_falsa
sc.SIM_MIN = 0.31                                  # los vectores simulados son más pobres que los reales

bien, mal = 0, []


def ok(cond, que, extra=""):
    global bien
    if cond:
        bien += 1
    else:
        mal.append(que + ("  →  " + str(extra) if extra else ""))


def limpiar():
    with sc._con() as con:
        con.execute("DELETE FROM notas")
        con.execute("DELETE FROM cerebro_revision")


# 1) CAPTURA: (frase, tipo esperado, área esperada o None, texto guardado esperado o None)
CAPTURAS = [
    ("idea: vender cursos de IA a pymes de Guayaquil", "idea", "negocio", "Vender cursos de IA a pymes de Guayaquil"),
    ("Idea - un bot de WhatsApp para restaurantes", "idea", None, "Un bot de WhatsApp para restaurantes"),
    ("nota: el instituto cierra en diciembre", "nota", "estudios", None),
    ("plan de negocio: primero 3 clientes piloto gratis", "plan", "negocio", None),
    ("plan: levantarme a las 6 para estudiar", "plan", None, None),
    ("meta: conseguir 10 clientes este año", "meta", "negocio", None),
    ("objetivo: llegar a B2 de inglés", "meta", "estudios", None),
    ("costumbre: leo 20 minutos antes de dormir", "costumbre", None, None),
    ("hábito: tomar agua al despertar", "costumbre", "salud", None),
    ("aprendizaje: los clientes pagan por resultados, no por horas", "aprendizaje", "negocio", None),
    ("negocio: ofrecer capacitaciones de IA a colegios", "idea", "negocio", None),
    ("para el negocio: hacer videos cortos en TikTok", "idea", "negocio", None),
    ("tengo una idea: una app para recordar deberes", "idea", None, "Una app para recordar deberes"),
    ("se me ocurrió hacer un curso de prompts para profesores", "idea", None, None),
    ("una idea para el negocio: chatbot para clínicas", "idea", "negocio", None),
    ("decidí dejar el café después de las 4", "decision", None, None),
    ("he decidido enfocarme en pymes primero", "decision", "negocio", None),
    ("aprendí que vender es escuchar más que hablar", "aprendizaje", "negocio", None),
    ("me di cuenta de que rindo más estudiando en la mañana", "aprendizaje", "estudios", None),
    ("mi meta es correr 5 km sin parar", "meta", "salud", None),
    ("me propongo dormir 7 horas", "meta", "salud", None),
    ("guarda esta idea: un podcast sobre IA en Ecuador", "idea", None, "Un podcast sobre IA en Ecuador"),
    ("anota en mi segundo cerebro que quiero aprender a negociar", "nota", None, "Quiero aprender a negociar"),
    ("apunta esta idea plantillas de prompts para abogados", "idea", None, None),
    ("guárdame esta nota: revisar contratos antes de firmar", "nota", None, None),
    ("Jarvis, idea: newsletter semanal de IA", "idea", "negocio", None),
    ("oye jarvis tengo una idea: talleres los sábados", "idea", None, None),
]
for frase, tipo, area, guardado in CAPTURAS:
    limpiar()
    cap = sc.interpretar_captura(frase)
    r = sc.procesar(frase)
    n = sc.ultimas(1)
    ok(cap is not None and r and r.startswith("🧠 Guardado") and n, "captura: " + frase, r)
    if n:
        ok(n[0]["tipo"] == tipo, "tipo: " + frase, n[0]["tipo"])
        if area:
            ok(n[0]["area"] == area, "área: " + frase, n[0]["area"])
        if guardado:
            ok(n[0]["texto"] == guardado, "texto: " + frase, n[0]["texto"])

# 2) NO captura al inicio (son de otros módulos o no son notas)
NO_ES = ["decisión: compro Nvidia porque bajó", "nota decisión 3: salió bien", "decidí comprar 5 acciones de Visa",
         "decidí vender AMD", "Juan me debe 50", "anota que Juan me debe 50", "anota el deber de inglés para el viernes",
         "recuérdame la idea de llamar a Juan mañana", "almuerzo 4.50", "mis deudas", "aprendí", "hola",
         "¿qué dice Pablo Gil de META?", "resúmeme el video de Cava", "tengo que pagar la luz",
         "decidí que el presupuesto de comida es 150", "anota que mañana tengo examen",
         "anota que el viernes a las 5 tengo reunión", "qué ideas tengo del negocio", "mis ideas",
         "según mis videos qué es el PER", "planifica la semana", "decidí gastar 20 en uber"]
for frase in NO_ES:
    limpiar()
    ok(sc.procesar(frase) is None and not sc.ultimas(1), "no debe capturar al inicio: " + frase, sc.procesar(frase))

# 3) «anota que …» suelto: solo al FINAL y sin fecha ni monto
limpiar()
ok(sc.procesar("anota que me gusta trabajar de noche", final=True).startswith("🧠 Lo anoté"), "anota suelto al final")
ok(sc.procesar("anota que mañana tengo examen", final=True) is None, "anota con fecha no es nota")
ok(sc.procesar("anota que Juan me debe 50", final=True) is None, "anota con dinero no es nota")
ok(sc.procesar("anota que pan", final=True) is None, "anota muy corto no es nota")

# 4) repetida
limpiar()
sc.procesar("idea: vender cursos de IA a pymes")
r = sc.procesar("idea: vender cursos de IA a pymes")
ok(r.startswith("🧠 Eso ya estaba") and len(sc.ultimas(10)) == 1, "no duplica", r)

# 5) consultas y búsqueda (palabras y significado)
limpiar()
for f in ["idea: vender cursos de IA a pymes de Guayaquil", "meta: conseguir 10 clientes este año",
          "decidí cobrar por proyecto y no por hora", "costumbre: estudio inglés 30 minutos cada noche",
          "idea: bot de WhatsApp para restaurantes", "aprendí que los clientes pagan por resultados"]:
    sc.procesar(f)
ok(sc.ordenar_pendientes() >= 6, "ordenar calcula vectores")
with sc._con() as con:
    sin_vec = con.execute("SELECT COUNT(*) FROM notas WHERE vec IS NULL").fetchone()[0]
ok(sin_vec >= 0, "vectores")
sc.ordenar_pendientes()                                    # recalcula los que cambiaron de etiquetas
with sc._con() as con:
    ok(con.execute("SELECT COUNT(*) FROM notas WHERE vec IS NULL").fetchone()[0] == 0, "todas con vector al final")
    fila = con.execute("SELECT * FROM notas WHERE texto LIKE 'Conseguir 10 clientes%'").fetchone()
ok(fila["tipo"] == "meta" and fila["ordenada"] == 1, "la IA no cambia el tipo que dijo el usuario", dict(fila))
ok(fila["etiquetas"] == "ventas, clientes", "etiquetas limpias y sin repetir", fila["etiquetas"])

r = sc.procesar("qué ideas tengo del negocio", final=True)
ok(r and "Vender cursos" in r and "WhatsApp" in r and "Conseguir" not in r, "ideas del negocio (solo ideas)", r)
r = sc.procesar("mis ideas", final=True)
ok(r and r.count("💡") == 2, "mis ideas", r)
r = sc.procesar("mis metas", final=True)
ok(r and "10 clientes" in r, "mis metas", r)
r = sc.procesar("mis notas", final=True)
ok(r and r.count("#") == 6, "mis notas (todas)", r)
r = sc.procesar("¿qué había pensado sobre la tarifa?", final=True)
ok(r and "cobrar por proyecto" in r, "por significado: tarifa → cobrar", r)
r = sc.procesar("qué tengo anotado sobre clientes", final=True)
ok(r and "10 clientes" in r and "resultados" in r, "por palabras: clientes", r)
r = sc.procesar("busca en mis notas WhatsApp", final=True)
ok(r and "restaurantes" in r, "busca en mis notas", r)
ok(sc.procesar("busca en mis notas dinosaurios", final=True).startswith("No encuentro"), "busca sin resultado")
ok(sc.procesar("¿qué había pensado sobre dinosaurios?", final=True) is None, "pensado sin resultado deja pasar a la IA")
r = sc.procesar("resume mis ideas del negocio", final=True)
ok(r and "Resumen de prueba" in r, "resume mis ideas del negocio", r)
r = sc.procesar("mi segundo cerebro", final=True)
ok(r and "6 notas" in r, "estado", r)
ok(sc.procesar("qué nota saqué en la materia de diseño", final=True) is None, "notas de clase no son del cerebro")

# 6) contexto para la IA del chat
ctx = sc.contexto("cuánto debería cobrar a mis clientes por un proyecto")
ok("SEGUNDO CEREBRO" in ctx and "cobrar por proyecto" in ctx, "contexto para la IA", ctx)
ok(sc.contexto("hola qué tal") == "", "sin contexto en charla corta")

# 7) borrar
nid = sc.ultimas(1)[0]["id"]
ok(sc.procesar("borra la nota " + str(nid), final=True).startswith("🗑️"), "borrar nota")
ok(sc.obtener(nid) is None, "borrada de verdad")
ok(sc.procesar("borra la nota 9999", final=True).startswith("No encuentro"), "borrar inexistente")

# 8) revisión semanal
memoria.recuerdos()                                        # siembra la memoria inicial
r = sc.preparar_revision()
ok(r and "Guardó 5 notas" in r["texto"] and len(r["propuestas"]) == 2, "revisión: 2 propuestas nuevas", r)
ok(sc.preparar_revision() is None, "revisión una sola vez por semana")
rid, dato = r["propuestas"][0]
ok(sc.responder_propuesta(rid, True).startswith("✅"), "confirmar propuesta")
ok(any(x["dato"] == dato for x in memoria.recuerdos()), "pasó a la memoria permanente")
ok(sc.responder_propuesta(rid, True).startswith("Eso ya"), "no se confirma dos veces")
ok(sc.responder_propuesta(r["propuestas"][1][0], False).startswith("❌"), "descartar propuesta")
limpiar()
AHORA[0] = datetime(2026, 11, 22, 18, 0, tzinfo=ZONA)
ok(sc.preparar_revision() is None, "sin notas en la semana: no manda nada")

print("SEGUNDO CEREBRO:", bien + len(mal), "| BIEN:", bien, "| MAL:", len(mal))
for m in mal:
    print("  MAL:", m)
