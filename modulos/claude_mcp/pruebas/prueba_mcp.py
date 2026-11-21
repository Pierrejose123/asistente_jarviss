"""Prueba del servidor MCP de Jarvis (19-11): protocolo y herramientas. Base TEMPORAL, sin internet, sin IA, datos
INVENTADOS.
    .\\.venv\\Scripts\\python.exe modulos\\claude_mcp\\pruebas\\prueba_mcp.py
"""
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
CONSOLA = sys.__stdout__
TMP = Path(tempfile.mkdtemp())
INFORME = RAIZ / "logs" / "prueba_mcp.log"          # copia del resultado (para leerlo con jarvis_registros)


def _anotar(texto):
    try:
        INFORME.parent.mkdir(exist_ok=True)
        with open(INFORME, "a", encoding="utf-8") as f:
            f.write(texto)
    except Exception:
        pass


def _error(tipo, valor, tb):
    import traceback
    _anotar("ERROR:\n" + "".join(traceback.format_exception(tipo, valor, tb)))
    sys.__excepthook__(tipo, valor, tb)


sys.excepthook = _error

from modulos.comun import db  # noqa: E402

db.ARCHIVO = TMP / "prueba_mcp.db"
from modulos.comun import modo_prueba  # noqa: E402

assert modo_prueba.activo(), "La protección de pruebas no está activa: no sigo."


def _sin_red(*a, **k):
    raise RuntimeError("PRUEBA: no se puede usar internet, Telegram ni la IA")


import modulos.comun.base as base  # noqa: E402

base.enviar_telegram = _sin_red
import requests  # noqa: E402

requests.get = requests.post = _sin_red

from modulos.claude_mcp import servidor_mcp as S  # noqa: E402
S._log = lambda texto: None                  # la prueba no escribe en logs/mcp.log (no cuenta como error real)
from modulos.ia import cerebro  # noqa: E402

cerebro._llamar = _sin_red                     # si algo intentara usar la IA local, falla la prueba
fallos, total = [], 0


def ok(cond, que):
    global total
    total += 1
    if not cond:
        fallos.append(que)


def llamar(nombre, args=None, mid=1):
    r = S.atender({"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": nombre, "arguments": args or {}}})
    return r["result"]["content"][0]["text"], r["result"]["isError"]


# ---------------------------------------------------------------- protocolo (proceso real, como lo arranca Claude)
mensajes = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "prueba", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            {"jsonrpc": "2.0", "id": 4, "method": "no/existe"}]
entrada = "\n".join(json.dumps(m) for m in mensajes) + "\nesto no es json\n"
p = subprocess.run([sys.executable, str(RAIZ / "modulos" / "claude_mcp" / "servidor_mcp.py")], input=entrada.encode("utf-8"),
                   capture_output=True, timeout=60)
lineas = [json.loads(l) for l in p.stdout.decode("utf-8").splitlines() if l.strip()]
ok(len(lineas) == 5, "5 respuestas (la notificación no responde): %d" % len(lineas))
ini = lineas[0]["result"] if lineas else {}
ok(ini.get("protocolVersion") == "2025-06-18" and ini.get("serverInfo", {}).get("name") == "jarvis", "initialize")
ok("jarvis_contexto" in ini.get("instructions", ""), "instrucciones para Claude")
nombres = [t["name"] for t in lineas[1]["result"]["tools"]] if len(lineas) > 1 else []
ok(len(nombres) == 13 and "jarvis_biblioteca" in nombres and "jarvis_nota" in nombres and "jarvis_notas" in nombres and "jarvis_github" in nombres and "jarvis_pedir" in nombres and "jarvis_recordar" in nombres, "lista de herramientas: %s" % nombres)
ok(all(t["inputSchema"]["type"] == "object" for t in S.HERRAMIENTAS), "esquemas válidos")
ok(len(lineas) > 2 and lineas[2] == {"jsonrpc": "2.0", "id": 3, "result": {}}, "ping")
ok(len(lineas) > 3 and lineas[3]["error"]["code"] == -32601, "método desconocido")
ok(len(lineas) > 4 and lineas[4]["error"]["code"] == -32700, "JSON inválido")
ok(p.stdout.decode("utf-8").count("\n") == len(lineas), "stdout solo tiene protocolo (nada de print)")
r = S.atender({"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
ok(r["result"]["protocolVersion"] == S.PROTOCOLOS[0], "versión desconocida -> la más nueva")
ok(S.atender({"jsonrpc": "2.0", "method": "notifications/cancelled"}) is None, "notificación sin respuesta")
r = S.atender({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nada", "arguments": {}}})
ok(r["error"]["code"] == -32602, "herramienta desconocida")

# ---------------------------------------------------------------- memoria compartida (aprende de él)
t, e = llamar("jarvis_recordar", {"dato": "Prefiere los resúmenes cortos y con viñetas"})
ok(not e and t.startswith("Guardado #"), "recordar: " + t)
rid = int(t.split("#")[1].split(":")[0])
t2, _ = llamar("jarvis_recordar", {"dato": "Prefiere los resúmenes cortos y con viñetas"})
ok(t2.startswith("Guardado #%d" % rid), "no duplica el mismo recuerdo")
t, _ = llamar("jarvis_contexto")
ctx = json.loads(t)
ok(any(m["id"] == rid and "viñetas" in m["dato"] for m in ctx["memoria"]), "el contexto trae la memoria")
ok("dia" in ctx, "el contexto trae el día")
t, _ = llamar("jarvis_recordar", {"dato": "Prefiere resúmenes cortos, con viñetas y en español", "reemplaza": rid})
ok(t.startswith("Actualizado #%d" % rid), "reemplazar un recuerdo")
from modulos.ia import memoria  # noqa: E402

ok(any(r["dato"].endswith("en español") for r in memoria.recuerdos()), "Jarvis (Telegram) ve el mismo recuerdo")
ok(llamar("jarvis_olvidar", {"id": rid})[0] == "Olvidado." and not any(r["id"] == rid for r in memoria.recuerdos()),
   "olvidar")
ok(llamar("jarvis_olvidar", {"id": 99999})[0] == "No existe ese id.", "olvidar id inexistente")
ok(llamar("jarvis_recordar", {"dato": "  "})[0] == "Falta el dato.", "dato vacío")

# ---------------------------------------------------------------- segundo cerebro desde Claude
from modulos.segundo_cerebro import segundo_cerebro as SC  # noqa: E402
t, e = llamar("jarvis_nota", {"texto": "Ofrecer a abogados un asistente que resuma expedientes", "tipo": "idea",
                              "area": "negocio", "etiquetas": "abogados, expedientes"})
ok(not e and t.startswith("Guardada") and "💡" in t, "nota: guarda una idea: %s" % t)
nota = SC.ultimas(1)[0]
ok(nota["origen"] == "claude" and nota["area"] == "negocio" and nota["etiquetas"] == "abogados, expedientes",
   "nota: origen claude, área y etiquetas")
t, _ = llamar("jarvis_nota", {"texto": "Ofrecer a abogados un asistente que resuma expedientes", "tipo": "idea"})
ok(t.startswith("Ya estaba"), "nota: no duplica")
t, _ = llamar("jarvis_nota", {"texto": "Cobrar 30 dólares al mes por el asistente de abogados", "tipo": "decision",
                              "area": "negocio"})
llamar("jarvis_nota", {"texto": "Estudiar inglés media hora antes de dormir", "tipo": "costumbre", "area": "estudios"})
t, _ = llamar("jarvis_notas", {"consulta": "abogados"})
ok("expedientes" in t and "30 dólares" in t and "inglés" not in t, "notas: busca por palabra: %s" % t)
t, _ = llamar("jarvis_notas", {"area": "estudios"})
ok("inglés" in t and "abogados" not in t, "notas: filtra por área")
t, _ = llamar("jarvis_notas", {"tipo": "decision"})
ok("30 dólares" in t and "expedientes" not in t, "notas: filtra por tipo")
ok(llamar("jarvis_notas", {"consulta": "zzzz inexistente"})[0].startswith("Sin notas"), "notas: sin resultados")
t, _ = llamar("jarvis_nota", {"texto": "Cobrar 40 dólares al mes por el asistente de abogados", "tipo": "decision",
                              "reemplaza": nota["id"] + 1})
ok(t.startswith("Actualizada") and "40 dólares" in SC.obtener(nota["id"] + 1)["texto"]
   and "40 dólares" in llamar("jarvis_notas", {"consulta": "dólares"})[0], "nota: corrige una existente: %s" % t)
ok(llamar("jarvis_nota", {"texto": "x", "tipo": "idea"})[0] == "Falta el texto.", "nota: texto vacío")
ok(llamar("jarvis_nota", {"texto": "algo", "tipo": "idea", "reemplaza": 9999})[0].startswith("No existe"),
   "nota: reemplaza inexistente")
ok("jarvis_nota" in S.INSTRUCCIONES and "jarvis_notas" in S.INSTRUCCIONES, "instrucciones: explican el segundo cerebro")

# ---------------------------------------------------------------- biblioteca (carpeta y base TEMPORALES)
from modulos.biblioteca import biblioteca as BIB  # noqa: E402
CARPETA = TMP / "biblio"
(CARPETA / "Introduccion a la Animacion").mkdir(parents=True)
(CARPETA / "Fotografia II").mkdir(parents=True)
(CARPETA / "Introduccion a la Animacion" / "clase 3 principios.md").write_text(
    "# Clase 3\nLos doce principios de la animación. El squash and stretch da peso y flexibilidad. "
    "El timing define cuántos fotogramas dura cada acción. La anticipación prepara al público antes del movimiento "
    "principal y el seguimiento hace que las partes sueltas sigan moviéndose después de que el cuerpo se detiene.",
    encoding="utf-8")
(CARPETA / "Fotografia II" / "exposicion.md").write_text(
    "# Exposición\nEl triángulo de exposición: apertura, velocidad de obturación e ISO. "
    "Una apertura grande deja entrar más luz y reduce la profundidad de campo. Una velocidad lenta congela menos el "
    "movimiento y un ISO alto agrega ruido a la imagen, por eso conviene subirlo solo cuando falta luz.",
    encoding="utf-8")
import os  # noqa: E402
for _f in CARPETA.rglob("*.md"):
    os.utime(_f, (1700000000, 1700000000))           # la biblioteca ignora archivos que se están escribiendo (< 60 s)


def _sin_ollama(*a, **k):
    raise BIB.Pausa("PRUEBA: Ollama apagado")       # como en la PC con Ollama apagado: busca solo por palabras


BIB.vectores = _sin_ollama
_aj = BIB.ajustes()
_aj.update({"carpeta": str(CARPETA), "base": str(TMP / "biblio.db"), "excluir": []})
BIB.ajustes = lambda: dict(_aj)
assert str(BIB.ruta_base()).startswith(str(TMP)), "la biblioteca de prueba no es temporal"
BIB.actualizar()
t, e = llamar("jarvis_biblioteca", {"accion": "estado"})
ok(not e and "2 archivos" in t, "biblioteca: estado: %s" % t[:80])
t, _ = llamar("jarvis_biblioteca", {"accion": "buscar", "consulta": "squash and stretch"})
ok("[1] Clase 3" in t and "Animacion" in t and "peso y flexibilidad" in t and "obturación" not in t,
   "biblioteca: busca y cita archivo: %s" % t[:120])
t, _ = llamar("jarvis_biblioteca", {"accion": "buscar", "consulta": "apertura", "materia": "fotografía"})
ok("Exposición" in t and "Materia: Fotografia II" in t and "squash" not in t, "biblioteca: filtra por materia: %s" % t[:120])
ok(llamar("jarvis_biblioteca", {"accion": "buscar", "consulta": "zzzz qwerty"})[0].startswith("Nada"),
   "biblioteca: sin resultados")
ok(llamar("jarvis_biblioteca", {"accion": "buscar"})[0] == "Falta la consulta.", "biblioteca: sin consulta")
t, _ = llamar("jarvis_biblioteca", {"accion": "documento", "consulta": "exposicion"})
ok("«Exposición» (Fotografia II" in t, "biblioteca: documento por nombre: %s" % t[:80])

# ---------------------------------------------------------------- pedir a Jarvis (solo módulos exactos)
t, e = llamar("jarvis_pedir", {"texto": "recuérdame comprar pan mañana a las 5 de la tarde"})
ok(not e and "pan" in t.lower() and not t.startswith("sin_respuesta"), "recordatorio por jarvis_pedir: " + t[:160])
t, e = llamar("jarvis_pedir", {"texto": "¿cuál es la capital de Francia?"})
ok(not e and t.startswith("sin_respuesta"), "sin módulo exacto -> sin_respuesta (no usa la IA local): " + t[:120])
ok(llamar("jarvis_pedir", {"texto": ""})[0] == "Falta el texto.", "texto vacío")

# ---------------------------------------------------------------- panel, mercado, registros, pruebas, reinicio
t, e = llamar("jarvis_panel", {"secciones": ["hoy", "inventada"]})
ok(not e and json.loads(t).keys() <= {"hoy"}, "panel: solo secciones válidas: " + t[:120])
S_mercado = types.SimpleNamespace(texto_mercado=lambda: "<b>Mercado</b> S&amp;P 500 +1 %", texto_macro=lambda: "Macro",
                                  texto_resultados=lambda q: "Resultados " + q, agenda_semana=lambda: "Agenda",
                                  proximo_fed=lambda: "Fed", ajustes=lambda: {"indices": {"^IXIC": "Nasdaq"}},
                                  analizar=lambda s: {"x": 1}, serie_viva=lambda s: [],
                                  texto_indice=lambda n, a: "Historia de " + n)
sys.modules["modulos.noticias.mercado"] = S_mercado
import modulos.noticias as paquete_noticias  # noqa: E402

paquete_noticias.mercado = S_mercado
ok(llamar("jarvis_mercado", {"consulta": "mercado"})[0] == "Mercado S&P 500 +1 %", "mercado sin HTML")
ok(llamar("jarvis_mercado", {"consulta": "indice", "nombre": "nasdaq"})[0] == "Historia de Nasdaq", "índice")
ok(llamar("jarvis_mercado", {"consulta": "resultados", "nombre": "META"})[0] == "Resultados META", "resultados")
(RAIZ / "logs").mkdir(exist_ok=True)
t, e = llamar("jarvis_registros")
ok(not e and "mcp" in t, "lista de registros: " + t[:100])
t, e = llamar("jarvis_registros", {"nombre": "mcp", "lineas": 5})
ok(not e and "jarvis_" in t, "últimas líneas del registro de MCP")
ok(llamar("jarvis_registros", {"nombre": "../.env"})[0].startswith("No existe"), "no sale de la carpeta logs")
S.lista_pruebas = lambda f="": [Path("modulos/x/pruebas/prueba_uno.py")]
S.correr_prueba = lambda p: (True, "X: TODO BIEN 3 de 3")
ok(llamar("jarvis_pruebas", {"filtro": "x"})[0].startswith("1 de 1 bien"), "pruebas")
lanzados = []
S.aparte = lambda args: lanzados.append(args)
S.MARCA_REINICIO = TMP / "reinicio_pedido.txt"
t, _ = llamar("jarvis_reiniciar")
ok(lanzados and lanzados[0][-1] == "reiniciar" and S.MARCA_REINICIO.exists(), "reiniciar lanza control.py y deja la marca")
malos = S.prohibidos([".env", "modulos/x.py", "datos/asistente.db", "credenciales/token.json", "para_claude_salida.txt",
                      "claude_ejecutar.cmd", "config/client_secret_123.json", "modulos/finanzas/datos_util.py"])
ok(malos == [".env", "datos/asistente.db", "credenciales/token.json", "para_claude_salida.txt", "claude_ejecutar.cmd",
             "config/client_secret_123.json"], "github: bloquea secretos y datos: %s" % malos)
ok(S.NOMBRE == "el usuario" or S.NOMBRE not in json.dumps(S.HERRAMIENTAS, ensure_ascii=False),
   "las herramientas no llevan nombres personales")
S.MAX_TEXTO = 50
ok(S.recortar("x" * 80).endswith("(recortado)"), "recorta respuestas enormes")
ok(S.compacto({"a": None, "b": [], "c": {"d": ""}, "e": 1}) == '{"e":1}', "JSON compacto sin vacíos")

resultado = "Casos: %d\n" % total
if fallos:
    resultado += "\nFALLOS: %d\n" % len(fallos) + "".join(" - %s\n" % f for f in fallos)
else:
    resultado += "MCP: TODO BIEN %d de %d (100 %%)\n" % (total, total)
_anotar(resultado)
CONSOLA.write(resultado)
CONSOLA.flush()
sys.exit(1 if fallos else 0)
