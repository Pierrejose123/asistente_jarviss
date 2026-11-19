"""Jarvis como servidor MCP para Claude (19-11). Claude (app de escritorio o teléfono vía Dispatch) usa a Jarvis como
herramientas: consulta su panel, le pide cosas igual que por Telegram, guarda lo que aprende de usted, revisa registros,
corre pruebas y reinicia el bot.

- Sin dependencias: habla MCP (JSON-RPC 2.0 por stdin/stdout, una línea por mensaje) con la librería estándar.
- Todo queda en la PC: la base, la memoria y los registros no salen de aquí; Claude solo ve lo que una herramienta
  devuelve cuando usted le pregunta algo.
- Rápido: arranca sin cargar módulos; cada herramienta importa solo lo que necesita y devuelve texto compacto.
- Memoria compartida: lo que Claude guarda con jarvis_recordar es la misma memoria («recuerdos») que usa Jarvis en
  Telegram y voz, así ambos aprenden de usted.

Claude Desktop lo arranca solo (config: claude_desktop_config.json → mcpServers.jarvis). Para registrarlo:
    .\\.venv\\Scripts\\python.exe modulos\\claude_mcp\\registrar.py
"""
import json
import re
import sys
import time
import traceback
from html import unescape
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

VERSION = "1.0"
PROTOCOLOS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_TEXTO = 12000
SALIDA = sys.stdout.buffer           # el canal MCP; todo lo demás (print de los módulos) va a stderr
sys.stdout = sys.stderr

def _quien():
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv(RAIZ / ".env")
    except Exception:
        pass
    return (os.getenv("NOMBRE_USUARIO") or "el usuario").strip(), (os.getenv("ZONA_HORARIA") or "America/Guayaquil").strip()


NOMBRE, ZONA_TXT = _quien()
INSTRUCCIONES = (
    "Jarvis es el asistente personal local de " + NOMBRE + " (zona " + ZONA_TXT + ") que corre en su PC: agenda, deberes "
    "de Moodle, recordatorios, hábitos y sueño, finanzas (cuentas, tarjetas, deudas, gastos, ahorros), portafolio, "
    "noticias y mercado. Al empezar una conversación sobre su vida o su día, llama jarvis_contexto. Para acciones o "
    "preguntas puntuales usa jarvis_pedir con la frase tal como él la diría a Jarvis (por ejemplo «recuérdame pagar la "
    "luz el viernes», «almuerzo 4.50», «¿qué deberes tengo esta semana?», «mi saldo»). Cuando te cuente algo duradero "
    "de sí mismo (preferencias, datos estables, correcciones), guárdalo con jarvis_recordar en una frase corta. Los "
    "montos y datos personales quedan en su PC: no los repitas fuera de lo que pidió. En finanzas solo informas, él "
    "decide. Antes de jarvis_github con accion=subir, pide su confirmación explícita.")

PANEL = ["hoy", "agenda", "tareas", "recordatorios", "dinero", "sueno", "salud", "semana", "ingles", "bolsa",
         "sistema", "empresa", "equipo", "negocio"]
_FUNC_PANEL = {"hoy": "_hoy", "agenda": "_agenda", "tareas": "_tareas", "recordatorios": "_recordatorios_deberes",
               "dinero": "_dinero", "sueno": "_sueno", "salud": "_salud", "semana": "_semana", "ingles": "_ingles",
               "bolsa": "_bolsa", "sistema": "_sistema", "empresa": "_empresa", "equipo": "_equipo",
               "negocio": "_negocio"}

HERRAMIENTAS = [
    {"name": "jarvis_contexto",
     "description": "Lo esencial para ayudar al usuario: lo que Jarvis sabe de él (memoria) y su día (fecha, hábitos, "
                    "agenda, deberes y recordatorios próximos). Llamar al inicio de una conversación personal.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": True}},
    {"name": "jarvis_panel",
     "description": "Datos del panel de vida de Jarvis en JSON compacto. Secciones: " + ", ".join(PANEL) +
                    ". Pide solo las que necesites (dinero = cuentas, tarjetas, deudas, ahorros, inversión).",
     "inputSchema": {"type": "object", "properties": {"secciones": {"type": "array", "items": {"type": "string", "enum": PANEL}}},
                     "required": ["secciones"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "jarvis_pedir",
     "description": "Le dice algo a Jarvis como si el usuario le escribiera por Telegram y devuelve la respuesta. Usa solo "
                    "los módulos exactos de Jarvis (sin su IA local): recordatorios, deberes, gastos, deudas, saldo, "
                    "tarjetas y diferidos, ahorros, hábitos, sueño, portafolio, alertas, noticias, mercado, segundo "
                    "cerebro. Si Jarvis no lo entiende devuelve «sin_respuesta». Puede crear o cambiar registros.",
     "inputSchema": {"type": "object", "properties": {"texto": {"type": "string", "description": "La frase, en español."}},
                     "required": ["texto"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    {"name": "jarvis_recordar",
     "description": "Guarda en la memoria local de Jarvis (compartida con Telegram y voz) un dato duradero sobre el usuario, "
                    "en una frase corta. Si ya existe uno parecido que lo corrige, pasa su id en reemplaza.",
     "inputSchema": {"type": "object", "properties": {"dato": {"type": "string"}, "reemplaza": {"type": "integer"}},
                     "required": ["dato"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    {"name": "jarvis_olvidar",
     "description": "Borra de la memoria de Jarvis el recuerdo con ese id (los ids salen en jarvis_contexto). Solo si "
                    "el usuario lo pide.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": True}},
    {"name": "jarvis_mercado",
     "description": "Mercado con números calculados por código: «mercado» (índices, distancia al máximo, bono, dólar, "
                    "próxima Fed), «indice» (historia completa de nasdaq, s&p 500 o dow: pasar nombre), «macro» (datos "
                    "de EE. UU.), «resultados» (fechas y sorpresas de sus empresas; ticker opcional), «agenda» (Fed y "
                    "resultados de la semana).",
     "inputSchema": {"type": "object", "properties": {
         "consulta": {"type": "string", "enum": ["mercado", "indice", "macro", "resultados", "agenda"]},
         "nombre": {"type": "string", "description": "Índice (nasdaq, s&p 500, dow) o ticker (META)."}},
         "required": ["consulta"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "jarvis_registros",
     "description": "Últimas líneas de un registro de Jarvis (logs/<nombre>.log), para revisar fallas. Sin nombre, "
                    "lista los registros con su última modificación.",
     "inputSchema": {"type": "object", "properties": {"nombre": {"type": "string"},
                                                      "lineas": {"type": "integer", "minimum": 5, "maximum": 300}}},
     "annotations": {"readOnlyHint": True}},
    {"name": "jarvis_pruebas",
     "description": "Corre las pruebas automáticas de Jarvis (base temporal, no tocan datos reales) y devuelve el "
                    "resumen. filtro opcional: nombre del módulo o de la prueba (mercado, cuentas, tarjetas…).",
     "inputSchema": {"type": "object", "properties": {"filtro": {"type": "string"}}},
     "annotations": {"readOnlyHint": True}},
    {"name": "jarvis_reiniciar",
     "description": "Reinicia el bot de Jarvis (Telegram y voz) para cargar código nuevo. Tarda ~30 s; avisa por Telegram.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    {"name": "jarvis_github",
     "description": "Guarda los cambios en el repositorio privado de la PC (commit local, nunca sube secretos) y arma "
                    "la copia pública con su escaneo de datos personales. accion=revisar: commit privado + arma y "
                    "escanea la copia pública, sin subir. accion=subir: lo mismo y, si el escaneo está limpio, la sube "
                    "a GitHub. Pedir confirmación al usuario antes de subir.",
     "inputSchema": {"type": "object", "properties": {"accion": {"type": "string", "enum": ["revisar", "subir"]},
                                                      "mensaje": {"type": "string", "description": "Qué cambió (commit)."}},
                     "required": ["accion"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}},
]


# ------------------------------------------------------------------ utilidades ---
def _log(texto):
    try:
        (RAIZ / "logs").mkdir(exist_ok=True)
        with open(RAIZ / "logs" / "mcp.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except Exception:
        pass


def plano(texto):
    """HTML de Telegram -> texto (sin etiquetas)."""
    return unescape(re.sub(r"<[^>]+>", "", texto or "")).strip()


def compacto(obj):
    """Quita vacíos y serializa sin espacios (menos texto para Claude = más rápido y barato)."""
    vacio = (None, "", [], {})

    def limpiar(x):
        if isinstance(x, dict):
            return {k: v for k, v in ((k, limpiar(v)) for k, v in x.items()) if v not in vacio}
        if isinstance(x, (list, tuple)):
            return [v for v in (limpiar(v) for v in x) if v not in vacio]
        return x
    return json.dumps(limpiar(obj), ensure_ascii=False, separators=(",", ":"), default=str)


def recortar(texto):
    return texto if len(texto) <= MAX_TEXTO else texto[:MAX_TEXTO] + "\n…(recortado)"


# ------------------------------------------------------------------ herramientas ---
def h_contexto(_a):
    from modulos.ia import memoria
    from modulos.vida import servidor
    recuerdos = [{"id": r["id"], "dato": r["dato"]} for r in memoria.recuerdos()]
    dia = {k: servidor._seguro(k, getattr(servidor, _FUNC_PANEL[k])) for k in ("hoy", "agenda", "tareas", "recordatorios")}
    return compacto({"memoria": recuerdos, "dia": dia})


def h_panel(a):
    from modulos.vida import servidor
    pedidas = [s for s in (a.get("secciones") or []) if s in _FUNC_PANEL] or ["hoy"]
    return compacto({s: servidor._seguro(s, getattr(servidor, _FUNC_PANEL[s])) for s in pedidas})


def h_pedir(a):
    texto = " ".join(str(a.get("texto") or "").split())
    if not texto:
        return "Falta el texto."
    from modulos.ia import cerebro
    r, _ = cerebro.responder(texto, canal="claude", sin_ia=True)
    return plano(r) if r else "sin_respuesta: Jarvis no tiene un módulo exacto para eso; respóndelo tú con el contexto."


def h_recordar(a):
    from modulos.ia import memoria
    dato = " ".join(str(a.get("dato") or "").split())
    if not dato:
        return "Falta el dato."
    if a.get("reemplaza"):
        ok = memoria.actualizar(int(a["reemplaza"]), dato)
        return ("Actualizado #%d: %s" % (int(a["reemplaza"]), dato)) if ok else "No existe ese id."
    rid = memoria.recordar(dato)
    return "Guardado #%d: %s" % (rid, dato)


def h_olvidar(a):
    from modulos.ia import memoria
    return "Olvidado." if memoria.olvidar(int(a.get("id") or 0)) else "No existe ese id."


def h_mercado(a):
    from modulos.noticias import mercado
    c, nombre = a.get("consulta"), str(a.get("nombre") or "")
    if c == "macro":
        return plano(mercado.texto_macro())
    if c == "resultados":
        return plano(mercado.texto_resultados(nombre))
    if c == "agenda":
        return plano(mercado.agenda_semana() + "\n\n" + (mercado.proximo_fed() or ""))
    if c == "indice":
        q = nombre.lower().replace("&", "").replace(" ", "")
        for sim, nom in mercado.ajustes()["indices"].items():
            if q and (q in nom.lower().replace("&", "").replace(" ", "") or q in sim.lower()):
                return plano(mercado.texto_indice(nom, mercado.analizar(mercado.serie_viva(sim))))
        return "Índice desconocido. Use nasdaq, s&p 500 o dow."
    return plano(mercado.texto_mercado())


def h_registros(a):
    carpeta = RAIZ / "logs"
    nombre = re.sub(r"[^\w.-]", "", str(a.get("nombre") or "")).replace(".log", "")
    if not nombre:
        filas = sorted(carpeta.glob("*.log"), key=lambda p: -p.stat().st_mtime)
        return "\n".join("%s  %s  %d KB" % (p.stem, time.strftime("%d/%m %H:%M", time.localtime(p.stat().st_mtime)),
                                            p.stat().st_size // 1024) for p in filas)
    archivo = carpeta / (nombre + ".log")
    if not archivo.exists():
        return "No existe logs/%s.log" % nombre
    n = int(a.get("lineas") or 40)
    with open(archivo, "rb") as f:                       # lee solo el final (los registros pueden ser grandes)
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 200 * n))
        lineas = f.read().decode("utf-8", errors="replace").splitlines()
    return "\n".join(lineas[-n:])


LENTAS = ("prueba_propuesta_real",)            # usan la IA y tardan: solo si se piden por nombre
PYTHON = RAIZ / ".venv" / "Scripts" / "python.exe"
PYTHONW = RAIZ / ".venv" / "Scripts" / "pythonw.exe"
MARCA_REINICIO = RAIZ / "datos" / "reinicio_pedido.txt"   # el bot la ve al volver y avisa por Telegram


def lista_pruebas(filtro=""):
    todas = sorted((RAIZ / "modulos").glob("*/pruebas/prueba_*.py"))
    f = filtro.lower().strip()
    if f:
        return [p for p in todas if f in p.stem.lower() or f in p.parts[-3].lower()]
    return [p for p in todas if p.stem not in LENTAS]


def correr_prueba(ruta):
    import os
    import subprocess
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run([str(PYTHON if PYTHON.exists() else sys.executable), str(ruta)], cwd=str(RAIZ),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, env=env,
                           stdin=subprocess.DEVNULL, creationflags=0x08000000 if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        return False, "tardó más de 5 minutos"
    lineas = [l.strip() for l in (r.stdout + "\n" + r.stderr).splitlines() if l.strip() and " INFO " not in l]
    clave = [l for l in lineas if "TODO BIEN" in l.upper() or "FALLOS" in l.upper()]
    resumen = clave[-1] if clave else (lineas[-1] if lineas else "sin salida")
    fallos = [l for l in lineas if l.startswith("- ")][:5] if r.returncode else []
    return r.returncode == 0, resumen[:150] + "".join("\n    " + f[:140] for f in fallos)


def aparte(args):
    """Proceso independiente y sin ventana (sobrevive al reinicio del bot)."""
    import os
    import subprocess
    banderas = (0x00000200 | 0x08000000) if os.name == "nt" else 0
    subprocess.Popen(args, cwd=str(RAIZ), creationflags=banderas, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def h_pruebas(a):
    pruebas = lista_pruebas(str(a.get("filtro") or ""))
    if not pruebas:
        return "No hay pruebas con ese filtro."
    salida, bien = [], 0
    for p in pruebas:
        ok, resumen = correr_prueba(p)
        bien += ok
        salida.append(("OK  " if ok else "MAL ") + p.parts[-3] + "/" + p.stem.replace("prueba_", "") + ": " + resumen)
    return ("%d de %d bien\n" % (bien, len(pruebas))) + "\n".join(salida)


def h_reiniciar(_a):
    MARCA_REINICIO.parent.mkdir(exist_ok=True)
    MARCA_REINICIO.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
    aparte([str(PYTHONW if PYTHONW.exists() else PYTHON), str(RAIZ / "modulos" / "comun" / "control.py"), "reiniciar"])
    return "Reiniciando el bot. En ~30 s llega «✅ Asistente reiniciado» por Telegram."


PROHIBIDOS = re.compile(r"(^|/)(\.env$|credenciales/|datos/|logs/|token\.json$|[^/]*\.token\.json$|client_secret[^/]*\.json$|"
                       r"para_claude_[^/]*$|claude_ejecutar\.cmd$)", re.I)


def prohibidos(nombres):
    """Archivos que jamás deben entrar a un commit (secretos, datos, archivos de trabajo con Claude)."""
    return [n for n in nombres if PROHIBIDOS.search(n.replace("\\", "/"))]


def git(*args, cwd=None, timeout=120):
    import subprocess
    r = subprocess.run(["git", *args], cwd=str(cwd or RAIZ), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr).strip()


def h_github(a):
    import subprocess
    accion = a.get("accion") if a.get("accion") in ("revisar", "subir") else "revisar"
    mensaje = " ".join(str(a.get("mensaje") or "").split())[:120] or ("Actualización " + time.strftime("%d/%m/%Y %H:%M"))
    salida = []
    git("add", "-A")
    _, preparados = git("diff", "--cached", "--name-only")
    malos = prohibidos(preparados.splitlines())
    if malos:
        git("reset", "-q")
        return "DETENIDO: estos archivos no pueden ir a git (revise .gitignore): " + ", ".join(malos[:10])
    if preparados.strip():
        code, out = git("commit", "-q", "-m", mensaje)
        salida.append(("Repositorio privado: guardado «%s» (%d archivos)." % (mensaje, len(preparados.splitlines())))
                      if code == 0 else "Repositorio privado: no se pudo guardar: " + out[-300:])
    else:
        salida.append("Repositorio privado: sin cambios.")
    exportar = RAIZ / "herramientas_privadas" / "exportar_publico.py"
    if not exportar.exists():
        return "\n".join(salida + ["No encontré herramientas_privadas/exportar_publico.py (copia pública)."])
    args = [str(PYTHON if PYTHON.exists() else sys.executable), str(exportar)] + (["--subir"] if accion == "subir" else [])
    try:
        r = subprocess.run(args, cwd=str(RAIZ), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=300, stdin=subprocess.DEVNULL, env=dict(__import__("os").environ, PYTHONIOENCODING="utf-8"))
        salida.append("Copia pública:\n" + (r.stdout + r.stderr).strip()[-3000:])
    except subprocess.TimeoutExpired:
        salida.append("Copia pública: tardó más de 5 minutos (¿GitHub pidió iniciar sesión en el navegador de la PC?).")
    return "\n".join(salida)


FUNCIONES = {"jarvis_contexto": h_contexto, "jarvis_panel": h_panel, "jarvis_pedir": h_pedir,
             "jarvis_recordar": h_recordar, "jarvis_olvidar": h_olvidar, "jarvis_mercado": h_mercado,
             "jarvis_registros": h_registros, "jarvis_pruebas": h_pruebas, "jarvis_reiniciar": h_reiniciar,
             "jarvis_github": h_github}


# ------------------------------------------------------------------ protocolo MCP ---
def atender(msg):
    """Un mensaje JSON-RPC -> respuesta (dict) o None si es una notificación."""
    metodo, mid, p = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:                                         # notificaciones (initialized, cancelled…): sin respuesta
        return None
    if metodo == "initialize":
        pedido = p.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": pedido if pedido in PROTOCOLOS else PROTOCOLOS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "jarvis", "version": VERSION}, "instructions": INSTRUCCIONES}}
    if metodo == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if metodo == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": HERRAMIENTAS}}
    if metodo == "tools/call":
        nombre, args = p.get("name"), p.get("arguments") or {}
        funcion = FUNCIONES.get(nombre)
        if not funcion:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Herramienta desconocida: %s" % nombre}}
        inicio = time.time()
        try:
            texto, error = recortar(str(funcion(args))), False
        except Exception as exc:
            texto, error = "Error en %s: %s" % (nombre, exc), True
            _log("ERROR %s: %s" % (nombre, traceback.format_exc()[-800:]))
        _log("%s %s %.1fs%s" % (nombre, ",".join(sorted(args)) or "-", time.time() - inicio, " ERROR" if error else ""))
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": texto}], "isError": error}}
    if metodo in ("resources/list", "prompts/list"):
        return {"jsonrpc": "2.0", "id": mid, "result": {metodo.split("/")[0]: []}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Método no soportado: %s" % metodo}}


def enviar(obj):
    SALIDA.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    SALIDA.flush()


def main(entrada=None):
    entrada = entrada or sys.stdin.buffer
    _log("Servidor MCP iniciado (v%s)" % VERSION)
    for linea in entrada:
        linea = linea.strip()
        if not linea:
            continue
        try:
            msg = json.loads(linea.decode("utf-8") if isinstance(linea, bytes) else linea)
        except Exception:
            enviar({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}})
            continue
        lote = msg if isinstance(msg, list) else [msg]
        respuestas = [r for r in (atender(m) for m in lote if isinstance(m, dict)) if r]
        if respuestas:
            enviar(respuestas if isinstance(msg, list) else respuestas[0])


if __name__ == "__main__":
    main()
