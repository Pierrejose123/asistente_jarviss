"""Prueba del EQUIPO DE AGENTES (Fase 4, 13-11). Base, carpeta y config TEMPORALES; internet e IA simulados.
python modulos\\equipo\\pruebas\\prueba_equipo.py"""
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
from modulos.comun.base import ZONA  # noqa: E402
from modulos.biblioteca import biblioteca  # noqa: E402
from modulos.noticias import noticias  # noqa: E402
from modulos.segundo_cerebro import segundo_cerebro as sc  # noqa: E402
from modulos.empresa import empresa  # noqa: E402
from modulos.equipo import equipo as Q  # noqa: E402

Q.ARCHIVO = TMP / "equipo.json"
Q.ARCHIVO.write_text(json.dumps({"carpeta": str(TMP / "salida")}), encoding="utf-8")
empresa.ARCHIVO = TMP / "empresa.json"
AHORA = [datetime(2026, 11, 13, 10, 0, tzinfo=ZONA)]                 # viernes
Q.ahora = lambda: AHORA[0]
sc.vectores = None
try:
    sc._vector = lambda *a, **k: None
except Exception:
    pass

LLAMADAS = []
REVISIONES = [{"ok": False, "problemas": ["Falta el plan piloto gratis"], "nota": "incompleto"},
              {"ok": True, "problemas": [], "nota": "bien"}]


def ia_falsa(instruccion, max_tokens=700, esquema=None, ligero_permitido=False):
    LLAMADAS.append(instruccion)
    if "Eres el CEO" in instruccion:
        return {"tipo": "propuesta", "objetivo": "Propuesta de asistentes de IA para un centro de mediación",
                "cliente": "Centro de mediación con varios abogados",
                "instrucciones": ["Qué tareas repetitivas tienen los centros de mediación y sus abogados en Ecuador",
                                  "Qué herramientas de IA existen para agendar audiencias, actas y seguimiento de casos",
                                  "Propuesta para el centro de mediación con piloto gratis", "Pasos para presentarla"]}
    if "búsquedas cortas" in instruccion:
        return {"busquedas": ["centros de mediación Ecuador problemas", "IA para abogados actas"]}
    if "Extrae de 4 a 10 hallazgos" in instruccion:
        return {"hallazgos": [{"texto": "Los centros redactan actas de mediación a mano", "fuente": 1},
                              {"texto": "Agendar audiencias quita mucho tiempo", "fuente": 2},
                              {"texto": "Dato inventado con fuente inexistente", "fuente": 99}]}
    if "Eres el redactor" in instruccion:
        corrige = "EL REVISOR PIDIÓ CORREGIR" in instruccion
        return "## Necesidades\n- Actas a mano [1]\n## Solución\nAsistente que redacta actas." + \
            ("\n## Plan piloto gratis\n1 mes sin costo." if corrige else "")
    if "Eres el revisor" in instruccion:
        return REVISIONES.pop(0) if REVISIONES else {"ok": True, "problemas": []}
    if "Eres el organizador" in instruccion:
        return {"acciones": [{"tipo": "tarea", "texto": "Llamar a mi amigo para agendar la reunión", "dias": 2},
                             {"tipo": "tarea", "texto": "Imprimir la propuesta", "dias": 99},
                             {"tipo": "nota", "texto": "Al centro de mediación le duele redactar actas"},
                             {"tipo": "tarea", "texto": "x"}]}
    return {}


def buscar_falso(consulta, n=5):
    if "mediaci" in consulta:
        return [{"titulo": "Centros de mediación en Ecuador: retos", "url": "https://a/1", "extracto": "actas manuales"},
                {"titulo": "Cómo agendar audiencias", "url": "https://a/2", "extracto": "agenda"}]
    return [{"titulo": "Centros de mediación en Ecuador: retos", "url": "https://a/1", "extracto": "repetido"},
            {"titulo": "IA para abogados", "url": "https://a/3", "extracto": "herramientas"}]


biblioteca._ia = ia_falsa
noticias.buscar_web = buscar_falso
TAREAS_CREADAS = []
from modulos.tareas import tareas as T  # noqa: E402
T.crear = lambda materia, titulo, entrega, hora=None: TAREAS_CREADAS.append((materia, titulo, entrega)) or 1

BIEN, MAL = 0, 0


def ver(nombre, cond):
    global BIEN, MAL
    if cond:
        BIEN += 1
    else:
        MAL += 1
        print("MAL:", nombre)


# --- frases ---------------------------------------------------------------------------------------------------
PEDIDOS = ["equipo: haz una propuesta para mi amigo abogado", "Equipo, investiga qué es n8n y si me sirve",
           "que el equipo prepare un plan de contenido para TikTok", "pídele al equipo que organice mi semana",
           "dile al equipo que busque clientes posibles en Quito", "/equipo haz una propuesta para una clínica",
           "jarvis, que el equipo haga una propuesta para un centro de mediación"]
for p in PEDIDOS:
    r = Q.procesar(p)
    ver("pedido: " + p, isinstance(r, dict) and "tarea" in r)
NO_PEDIDOS = ["el equipo de fútbol ganó", "anota que el equipo de Liga juega el sábado", "gasté 20 en equipo de audio",
              "idea: armar un equipo de ventas", "cuánto me deben", "equipo", "qué hora es"]
for p in NO_PEDIDOS:
    ver("no pedido: " + p, Q.procesar(p) is None)
ver("estado", "Trabajos del equipo" in Q.procesar("estado del equipo"))
ver("estado 2", "Trabajos del equipo" in Q.procesar("¿qué está haciendo el equipo?"))
ver("tipo palabras propuesta", Q._tipo_por_palabras("haz una propuesta para un cliente") == "propuesta")
ver("tipo palabras contenido", Q._tipo_por_palabras("ideas de posts para tiktok") == "contenido")
ver("tipo palabras semana", Q._tipo_por_palabras("organiza mi semana") == "plan_semana")
ver("tipo palabras investigación", Q._tipo_por_palabras("investiga qué es n8n") == "investigacion")

# --- programados ----------------------------------------------------------------------------------------------
r = Q.procesar("cada lunes a las 8 que el equipo prepare mi plan de contenido")
ver("programar lunes", "cada lunes a las 08:00" in r)
r = Q.procesar("cada viernes a las 5 pm, que el equipo revise cómo me fue en la semana")
ver("programar pm", "17:00" in r)
r = Q.procesar("cada día el equipo me prepare un resumen de noticias de IA")
ver("programar diario", "cada día a las 08:00" in r)
ver("ver programados", Q.procesar("trabajos programados").count("#") == 3)
AHORA[0] = datetime(2026, 11, 16, 7, 0, tzinfo=ZONA)                 # lunes 7:00 → todavía no
ver("todavía no", Q.toca_programadas() == [])
AHORA[0] = datetime(2026, 11, 16, 8, 5, tzinfo=ZONA)
toca = Q.toca_programadas()
ver("lunes 8:05 toca lunes y diario", sorted(p["dia"] for p in toca) == ["lunes", "todos"])
ver("no repite", Q.toca_programadas() == [])
ver("quitar programado", "Quité" in Q.procesar("quita el trabajo programado 1"))
ver("quitar inexistente", "No encuentro" in Q.procesar("borra la tarea programada 77"))
ver("quedan 2", len(Q.programadas()) == 2)
AHORA[0] = datetime(2026, 11, 13, 10, 0, tzinfo=ZONA)

# --- trabajo completo -----------------------------------------------------------------------------------------
sc.guardar("Mi amigo del centro de mediación dice que pierden tiempo con las actas", "nota", "negocio")
avisos = []
tid = Q.crear("haz una propuesta para mi amigo abogado que trabaja en un centro de mediación con varios abogados")
t = Q.ejecutar(tid, avisos.append)
ver("estado lista", t["estado"] == "lista")
ver("tipo propuesta", t["tipo"] == "propuesta")
plan = json.loads(t["plan"])
ver("plan 4 pasos", [p["agente"] for p in plan["pasos"]] == ["investigador", "investigador", "redactor", "organizador"])
ver("instrucción del CEO usada", "mediación" in plan["pasos"][0]["instruccion"])
ver("revisor pidió corregir y se corrigió", "Plan piloto gratis" in t["resultado"])
ver("revisión final ok", json.loads(t["revision"])["ok"])
ver("fuentes al final", "## Fuentes" in t["resultado"] and "https://a/1" in t["resultado"])
ver("fuente inexistente no citada", "[99]" not in t["resultado"])
ver("fuentes sin duplicar", t["resultado"].count("https://a/1") == 1)
nums = re.findall(r"^\[(\d+)\]", t["resultado"].split("## Fuentes")[1], re.M)
ver("fuentes numeradas seguidas (solo las citadas)", nums == [str(i) for i in range(1, len(nums) + 1)] and len(nums) >= 1)
ver("archivo guardado", t["archivo"] and Path(t["archivo"]).exists() and Path(t["archivo"]).suffix == ".md")
ver("archivo con título", Path(t["archivo"]).read_text(encoding="utf-8").startswith("# Propuesta de asistentes"))
ver("2 tareas pendientes (no la de 1 letra)", len(t["pendientes"]) == 2)
ver("días fuera de rango → 3", t["pendientes"][1]["fecha"] == "2026-11-16")
ver("nada agendado sin visto", TAREAS_CREADAS == [])
ver("nota automática al segundo cerebro", any("le duele redactar actas" in n["texto"] for n in sc.ultimas(20)))
ver("nota de trabajo terminado", any("El equipo terminó" in n["texto"] for n in sc.ultimas(20)))
ver("avisos de avance", any("CEO" in a for a in avisos) and any("Revisor" in a for a in avisos))
ver("bitácora", "Organizador" in Q.texto_bitacora(Q.obtener(tid)))
ver("redactor recibió el plan de empresa", any("SOBRE EL NEGOCIO" in x and "NEGOCIO:" in x for x in LLAMADAS))
ver("redactor recibió nota del dueño", any("nota del dueño" in x for x in LLAMADAS))
ver("redactor recibió investigación", any("Actas" in x or "actas" in x for x in LLAMADAS if "Eres el redactor" in x))

# aprobar
a1, a2 = t["pendientes"]
ver("aprobar", "agendada" in Q.aprobar(a1["id"], True) and TAREAS_CREADAS[0][1].startswith("Llamar"))
ver("rechazar", "No la agendo" in Q.aprobar(a2["id"], False) and len(TAREAS_CREADAS) == 1)
ver("doble respuesta", "ya estaba" in Q.aprobar(a1["id"], True) and len(TAREAS_CREADAS) == 1)

# CEO que falla → plantilla por palabras
biblioteca._ia = lambda *a, **k: {} if "CEO" in a[0] else ia_falsa(*a, **k)
p = Q.ceo("investiga qué es n8n y si me sirve")
ver("CEO sin respuesta usa plantilla", p["tipo"] == "investigacion" and len(p["pasos"]) == 2)
biblioteca._ia = ia_falsa


# falla de la IA → estado falló
def ia_rota(*a, **k):
    raise RuntimeError("Ollama apagado")


biblioteca._ia = ia_rota
tid2 = Q.crear("haz una propuesta para una clínica")
try:
    Q.ejecutar(tid2)
    ver("debía fallar", False)
except RuntimeError:
    ver("estado falló", Q.obtener(tid2)["estado"] == "falló")
biblioteca._ia = ia_falsa

# sin internet
noticias.buscar_web = lambda *a, **k: (_ for _ in ()).throw(OSError("sin red"))
r = Q.investigador("algo rarísimo xyz", "pedido xyz")
ver("sin internet no revienta", isinstance(r, dict) and "fuentes" in r)
noticias.buscar_web = buscar_falso

# --- fallos / mejora continua ---------------------------------------------------------------------------------
from modulos.ia import memoria  # noqa: E402
memoria.guardar_turno("cuánto gasté en comida", "Gastó 300 en transporte")
r = Q.procesar("no era eso")
ver("queja anotada", "Anotado como fallo" in r and "cuánto gasté" in r)
ver("queja con corrección pasa al resto", Q.procesar("te equivocaste, quería saber lo de comida de este mes") is None)
ver("2 fallos", len(Q.fallos()) == 2)
ver("ver fallos", "Fallos de los últimos 7 días (2)" in Q.procesar("fallos de la semana"))
ver("no queja normal", Q.procesar("no, gracias") is None and Q.procesar("no era tan caro el almuerzo") is None)
ver("panel", len(Q.datos_panel()["tareas"]) >= 2 and Q.datos_panel()["fallos"] == 2)

print("EQUIPO: " + str(BIEN + MAL) + " | BIEN: " + str(BIEN) + " | MAL: " + str(MAL))
