"""Prueba con la PROPUESTA REAL del 13-11 (trabajo #1, amigo abogado), que salió con inventos y errores.
La IA simulada devuelve ese mismo texto malo en el borrador Y en la corrección (el peor caso: la IA no corrige nada)
y el revisor de IA dice «ok». El control en código tiene que dejarla limpia igual.
Base, carpeta y config TEMPORALES; internet, IA, Google y Telegram simulados o bloqueados.
python modulos\\equipo\\pruebas\\prueba_propuesta_real.py"""
import json
import re
import sys
import tempfile
from datetime import datetime
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
from modulos.biblioteca import biblioteca  # noqa: E402
from modulos.noticias import noticias  # noqa: E402
from modulos.segundo_cerebro import segundo_cerebro as sc  # noqa: E402
from modulos.empresa import empresa  # noqa: E402
from modulos.equipo import control  # noqa: E402
from modulos.equipo import equipo as Q  # noqa: E402

try:                                                     # ninguna prueba toca Google ni Telegram
    from modulos.calendario import google_cal
    google_cal.servicio = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Google bloqueado en la prueba"))
except Exception:
    pass
base.enviar_telegram = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Telegram bloqueado en la prueba"))

Q.NOMBRE = "Ana"   # nombre de prueba (el real sale de NOMBRE_USUARIO en el .env)
FICHA = {
    "nombre": "Centro de mediación (amigo abogado)",
    "palabras": ["mediaci", "amigo abogado"],
    "sector": "centro de mediación (legal)",
    "situacion": "Amigo abogado que trabaja en un centro de mediación. Demo gratis para aprender; todavía no la ha visto.",
    "hecho": [
        {"texto": "Registro de casos con las partes, la materia y una descripción", "clave": "registro de casos"},
        {"texto": "Audiencias por sala y mediador, con aviso si hay choque de horario", "clave": "choque"},
        {"texto": "Agenda de hoy, mañana, la semana o por mediador; mover o cancelar audiencias", "clave": "por mediador"},
        {"texto": "Invitaciones en Word (.docx) y texto listo para WhatsApp", "clave": "invitaci"},
        {"texto": "Si una parte no asiste: segunda invitación y constancia de imposibilidad", "clave": "imposibilidad"},
        {"texto": "Borradores de actas (acuerdo total, parcial o imposibilidad) con la estructura del Art. 47 de la Ley "
                  "de Arbitraje y Mediación, marcados BORRADOR para revisar", "clave": "art. 47"},
        {"texto": "Resumen del mes con la tasa de acuerdos", "clave": "tasa de acuerdo"},
        {"texto": "Respuestas a preguntas frecuentes del centro", "clave": "preguntas frecuentes"}],
    "se_puede": ["Poner los datos reales del centro", "Un asistente propio para el centro", "Atender por WhatsApp"],
    "no_ofrecer": ["simulador", "cláusulas", "jurisprudencia"],
    "vocabulario": {"actas procesales": "actas de mediación", "plazos procesales": "fechas de audiencias e invitaciones"},
}
Q.ARCHIVO = TMP / "equipo.json"
Q.ARCHIVO.write_text(json.dumps({"carpeta": str(TMP / "salida"), "clientes": [FICHA]}, ensure_ascii=False), encoding="utf-8")
empresa.ARCHIVO = TMP / "empresa.json"
Q.ahora = lambda: datetime(2026, 11, 13, 9, 20, tzinfo=ZONA)
sc.vectores = None
try:
    sc._vector = lambda *a, **k: None
except Exception:
    pass

MALA = (Path(__file__).parent / "datos" / "propuesta_mala_13-11.md").read_text(encoding="utf-8")
FUENTES = [
    ("Inteligencia artificial para abogados en Ecuador 2026 | Mokenla", "https://www.mokenla.com/blog/ia-abogados-ecuador",
     "La IA ayuda en tareas repetitivas pero el análisis, la negociación y la responsabilidad profesional siguen siendo del abogado"),
    ("IA Legal: Automatiza tareas repetitivas en tu despacho", "https://www.crata-ai.com/es/post/futuro", "Agentes que automatizan tareas del despacho"),
    ("DERECHO E INTELIGENCIA ARTIFICIAL - Abogados Ecuatorianos", "https://www.abogadosecuatorianos.org/blog/derecho-ia",
     "La IA reduce el tiempo de investigación legal y revisión de documentos"),
    ("Gestión de tareas en litigación", "https://pp.lexis.com.ec/blog/gestion-de-tareas", "Un expediente sin plan es improvisación con fechas"),
    ("The Basic Structure of the Ecuadorian Legal System", "https://www.nyulawglobal.org/globalex/Ecuador1.html",
     "El sistema de Ecuador se basa en leyes escritas vinculantes, no en precedentes"),
    ("Acceso a la Justicia y Equidad en el Sistema Legal Ecuatoriano", "https://revistaczambos.utelvtsd.edu.ec/article/45",
     "Hay barreras de acceso a la justicia por costos operativos y demoras en las respuestas"),
    ("Recent Legal Reforms in Ecuador", "https://generisonline.com/recent-legal-reforms-in-ecuador/", "Reformas recientes"),
    ("Cresta – IA para centros de contacto, automatización de conversaciones y orientación para agentes en tiempo real",
     "https://news.google.com/rss/articles/CBMi0AFB", "Cresta orienta en tiempo real a los agentes de centros de contacto"),
    ("Lexi - Asistente Legal con IA para Ecuador", "https://lexiecuador.com/", "Existe Lexi, asistente legal con IA"),
    ("Alhelí - Asistente Legal IA", "https://www.alheli.ai/",
     "Existe Alhelí, que permite consultar grandes volúmenes de documentos PDF y legislación en lenguaje natural sin perder el contexto"),
    ("LEXIS IA en el derecho ecuatoriano", "https://www.lexis.com.ec/blog/legaltech/lexis-ia", "Lexis IA"),
    ("Cómo un despacho puede usar IA en MEDIACIÓN y CONFLICTOS", "https://asesor.legal/ia-en-mediacion/", "IA en mediación"),
    ("Simulador de mediación con IA - Práctica y feedback | Mediate8", "https://www.mediate8.com/?l=es",
     "Existe Mediate8, simulador de conversaciones de mediación realistas con práctica y feedback"),
    ("Home - Bot Mediation", "https://botmediation.com/",
     "Existe Bot Mediation: chatbot de primera atención rápida para resolución de disputas fuera del horario"),
    ("Las 5 mejores herramientas de IA para documentos legales", "https://sonix.ai/ai/es/ai-para-documentos-juridicos/",
     "Herramientas que redactan correos legales formales y verifican cláusulas en contratos"),
]
LLAMADAS = []


def ia_falsa(instruccion, max_tokens=700, esquema=None, ligero_permitido=False):
    LLAMADAS.append(instruccion)
    if "Eres el CEO" in instruccion:
        return {"tipo": "propuesta", "objetivo": "Generar una propuesta comercial personalizada para un abogado en Ecuador "
                "que incluye investigación de necesidades, soluciones de IA a medida y un piloto gratuito.",
                "cliente": "Amigo abogado en un centro de mediación",
                "instrucciones": ["Qué problemas tienen los abogados de centros de mediación en Ecuador",
                                  "Qué soluciones de IA existen para abogados y mediación",
                                  "Propuesta con necesidades, soluciones, piloto gratuito y preguntas", "Próximos pasos"]}
    if "búsquedas cortas" in instruccion:
        return {"busquedas": ["IA abogados Ecuador"]}
    if "Extrae de 4 a 10 hallazgos" in instruccion:
        return {"hallazgos": [{"texto": FUENTES[i][2], "fuente": i + 1} for i in range(len(FUENTES))][:10]
                + [{"texto": FUENTES[i][2], "fuente": i + 1} for i in range(10, len(FUENTES))]}
    if "Eres el redactor" in instruccion:
        return MALA                                      # peor caso: ni el borrador ni la corrección cambian nada
    if "Eres el revisor" in instruccion:
        return {"ok": True, "problemas": [], "nota": "bien"}   # el revisor de IA no ve nada
    if "Eres el organizador" in instruccion:
        return {"acciones": [{"tipo": "tarea", "texto": "Mostrarle la demo de mediación a mi amigo", "dias": 2}]}
    return {}


def buscar_falso(consulta, n=5):
    return [{"titulo": t, "url": u, "extracto": e[:120]} for t, u, e in FUENTES]


biblioteca._ia = ia_falsa
noticias.buscar_web = buscar_falso

BIEN, MAL = 0, 0


def ver(nombre, cond):
    global BIEN, MAL
    if cond:
        BIEN += 1
    else:
        MAL += 1
        print("MAL:", nombre)


# --- funciones sueltas del control ----------------------------------------------------------------------------
ver("invento: hablé con", control.inventos("Hablé con varios profesionales del área."))
ver("invento: entrenado con leyes", control.inventos("Un asistente entrenado con las leyes ecuatorianas."))
ver("invento: nuestros clientes", control.inventos("Nuestros clientes ahorran tiempo."))
ver("no invento: verdad", not control.inventos("Ya armé una demo que agenda audiencias y redacta borradores de actas."))
ver("no invento: hablar en futuro", not control.inventos("Me gustaría hablar contigo 20 minutos para mostrarte la demo."))
ver("no invento: revisamos el avance", not control.inventos("Cada semana revisamos el avance y ajustamos el asistente."))
ver("colada", control.coladas("Hola. Deja abierta la puerta a cualquier otra cosa que me pida. Chao.",
                              ["haz una propuesta y deja abierta la puerta a cualquier otra cosa que me pida"]))
ver("no colada", not control.coladas("Te propongo un piloto gratis de un mes.", ["haz una propuesta para mi amigo abogado"]))
ver("pregunta presupuesto en gratis",
    control.preguntas_malas("* ¿Qué presupuesto tienes para esta prueba gratuita?", "propuesta", False))
ver("pregunta marca", control.preguntas_malas("* ¿Tienes preferencia sobre el nombre de la marca?", "propuesta", False))
ver("pregunta buena", not control.preguntas_malas("* ¿Qué tarea te quita más tiempo?", "propuesta", True))
ver("firma mala → nombre", "**Ana**" in control.firmar("Saludos,\n\n**Tu amigo en IA**", "Ana"))
ver("firma que falta → nombre", control.firmar("Gracias.\n\nSaludos cordiales,", "Ana").rstrip().endswith("**Ana**"))
ver("firma pública sin nombre no cambia", control.firmar("Saludos,\n\n**Tu amigo en IA**", "Usuario").endswith("IA**"))
ver("vocabulario", control.vocabulario("Redacción de actas procesales", FICHA["vocabulario"]) == "Redacción de actas de mediación")
ver("frases con negrita", control._frases("**Deja la puerta.** Si hay algo más, aquí estoy.") ==
    ["**Deja la puerta.**", "Si hay algo más, aquí estoy."])
ver("quitar frase deja el resto", control.quitar_frases("Hola, colega. Como sabes, estamos trabajando juntos. Mi objetivo "
                                                        "es ayudarte.", ["Como sabes, estamos trabajando juntos."])
    == "Hola, colega. Mi objetivo es ayudarte.")
ver("quitar título de viñeta quita la viñeta",
    control.quitar_frases("- **Asistente:** Conoce la ley. Esto ahorra tiempo.\n- Otra cosa útil para ti.",
                          ["**Asistente:** Conoce la ley."]) == "- Otra cosa útil para ti.")
ver("producto: portada", Q.es_producto("https://www.alheli.ai/") and Q.es_producto("https://www.mediate8.com/?l=es"))
ver("producto: artículo no", not Q.es_producto("https://www.mokenla.com/blog/ia-abogados-ecuador"))
ver("sector sensible", Q.sector_sensible("propuesta para mi amigo abogado") and not Q.sector_sensible("post para TikTok de memes"))
ver("ficha por palabras", (Q.cliente_para("haz una propuesta para mi amigo abogado") or {}).get("nombre", "").startswith("Centro"))
ver("sin ficha para otro", Q.cliente_para("haz una propuesta para una panadería") is None)
ver("título corto", len(control.titulo_corto("Texto sin título", "x " * 100)[0]) <= 81)

# --- el trabajo completo con la propuesta real ----------------------------------------------------------------
PEDIDO = ("haz una propuesta para mi amigo abogado que trabaja en un centro de mediación: investiga sus necesidades, "
          "propón asistentes de IA a medida con un piloto gratis, y deja abierta la puerta a cualquier otra cosa que me pida")
tid = Q.crear(PEDIDO)
t = Q.ejecutar(tid, lambda x: None)
R = t["resultado"]
CUERPO = R.split("\n## Fuentes")[0]
ver("terminó", t["estado"] == "lista")
ver("redactor recibió la ficha", any("YA ESTÁ HECHO" in x and "Art. 47" in x for x in LLAMADAS if "Eres el redactor" in x))
ver("redactor recibió las reglas y el nombre", any("Firma con el nombre del dueño: Ana" in x for x in LLAMADAS))
CORR = [x for x in LLAMADAS if "EL REVISOR PIDIÓ CORREGIR" in x]
ver("se pidió corrección aunque la IA dijo ok", len(CORR) == 1)
ver("corrección pide quitar el invento", CORR and "habló" in CORR[0])
ver("corrección pide quitar lo colado", CORR and "se coló" in CORR[0])
ver("corrección pide la demo", CORR and "YA está hecho" in CORR[0])
ver("sin «Hablé con»", "Hablé con" not in R and "revisamos el contexto" not in R)
ver("sin «Como sabes, estamos trabajando»", "estamos trabajando en un proyecto juntos" not in R)
ver("sin instrucción colada", "Deja abierta la puerta" not in R)
ver("se queda lo útil del cierre", "Quedo atento a tus respuestas" in R)
ver("sin «entrenado con leyes»", not re.search(r"entrenad\w*[^.\n]{0,60}leyes", R, re.I))
ver("sin pregunta de presupuesto", "presupuesto" not in CUERPO.lower())
ver("sin pregunta de marca", "nombre de la marca" not in CUERPO)
ver("se quedan las preguntas buenas", "más tiempo" in CUERPO and "redacción de documentos o en gestión" in CUERPO)
ver("sin simulador", "Simulador" not in CUERPO)
ver("sin jurisprudencia", "jurisprudencial" not in CUERPO)
ver("vocabulario del sector", "actas procesales" not in CUERPO and "actas de mediación" in CUERPO)
ver("firmado con el nombre", "**Ana**" in R and "Tu amigo en IA" not in R)
ver("sección de la demo", "## Lo que ya funciona (demo)" in CUERPO and "Art. 47" in CUERPO)
ver("sección de confidencialidad", "## Confidencialidad de tus datos" in CUERPO)
ver("secciones antes de la firma", CUERPO.index("Confidencialidad") < CUERPO.index("**Ana**"))
plazos = next((l for l in CUERPO.splitlines() if "fechas de audiencias e invitaciones" in l), "")
ver("cita de Cresta quitada", plazos and "[" not in plazos)
ver("Cresta fuera de las fuentes", "Cresta" not in R)
ver("cita buena se queda", re.search(r"leyes escritas vinculantes \[\d+\]", CUERPO))
nums = re.findall(r"^\[(\d+)\]", R.split("## Fuentes")[1], re.M) if "## Fuentes" in R else []
ver("fuentes renumeradas 1..k", nums and nums == [str(i) for i in range(1, len(nums) + 1)])
citados = sorted({int(n) for n in re.findall(r"\[(\d+)\]", CUERPO)})
ver("cada cita tiene su fuente", citados == [int(n) for n in nums])
ver("productos marcados", all("(página de un producto)" in l for l in R.split("## Fuentes")[1].splitlines()
                                if any(d in l for d in ("alheli.ai/", "botmediation.com/"))))
ver("sin líneas vacías triples", "\n\n\n" not in R)
plan = json.loads(Q.obtener(tid)["plan"])
ver("título corto del texto", plan.get("titulo", "").startswith("Propuesta para nuestro amigo abogado"))
contenido = Path(t["archivo"]).read_text(encoding="utf-8")
ver("archivo con título corto", contenido.startswith("# Propuesta para nuestro amigo abogado"))
ver("título no repetido en el cuerpo", contenido.count("Propuesta para nuestro amigo abogado") == 1)
ver("nombre de archivo corto", len(Path(t["archivo"]).name) <= 75)
ver("revisión guarda el control", "control" in json.loads(Q.obtener(tid)["revision"]))

# --- un texto bueno no se toca --------------------------------------------------------------------------------
BUENO = ("## Propuesta para tu centro de mediación\n\nHola. Ya armé una demo que agenda audiencias por sala y avisa si hay "
         "choque, prepara invitaciones y borradores de actas con la estructura del Art. 47 [1].\n\n"
         "## Confidencialidad\n- Datos inventados en la demo.\n\nSaludos,\n\n**Ana**")
fb = [{"n": 1, "titulo": "Ley de Arbitraje y Mediación Art. 47 actas", "url": "https://x/ley", "extracto": "estructura de las actas"}]
limpio, fs, cambios = Q.limpiar(BUENO, "propuesta para mi amigo abogado", {"tipo": "propuesta", "pasos": []}, fb, FICHA, True)
ver("texto bueno sin cambios", limpio == BUENO and cambios == [])
ver("texto bueno sin problemas", Q.problemas_en_codigo(BUENO, "propuesta", {"tipo": "propuesta", "pasos": []}, fb, FICHA, True) == [])

print("PROPUESTA REAL: " + str(BIEN + MAL) + " | BIEN: " + str(BIEN) + " | MAL: " + str(MAL))
if MAL == 0:
    print("\n----- Así queda la propuesta -----\n" + contenido)
