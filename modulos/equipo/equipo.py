"""Equipo de agentes (Fase 4): un CEO reparte el trabajo entre especialistas y un revisor lo controla. IA local.

Agentes:
  🧑‍💼 CEO          entiende el pedido y arma el plan (pasos fijos según el tipo de trabajo; el CEO solo los afina)
  🔎 Investigador  busca en internet (DuckDuckGo), en lo que juntó el agente de la empresa y en el segundo cerebro
  📊 Analista      usa los datos del usuario (dinero, hábitos, sueño, tareas, portafolio en %)
  ✍️ Redactor      escribe el entregable (propuesta, post, informe, plan)
  🗓️ Organizador   propone próximos pasos: notas (solas) y tareas (solo con ✅ del usuario)
  ✅ Revisor       compara el resultado con el pedido; si falla, el redactor corrige UNA vez
Pedidos: «equipo: …», «que el equipo …», «pídele al equipo …», «/equipo …». «estado del equipo», «trabajos del equipo».
Programados: «cada lunes a las 8 que el equipo …» (lista: «trabajos programados»; quitar: «quita el trabajo programado 2»).
Mejora continua: cuando el usuario dice «no era eso», «te equivocaste», «no entendiste»… se anota el mensaje anterior
y la respuesta; «fallos de la semana» los lista (y el domingo van en el informe del equipo si hay).
El entregable se guarda como .md (carpeta de config/equipo.json; por defecto I:\\Jarvis\\equipo si existe el disco I)
y se manda por Telegram. Tablas eq_tareas, eq_acciones, eq_programadas, eq_fallos.

v3 (13-11): fichas de clientes (config/equipo.json → "clientes": lo que YA está hecho, lo que se puede hacer, lo que no se
ofrece y su vocabulario) y control en código (control.py) antes y después de la corrección: frases inventadas, instrucciones
coladas, preguntas de presupuesto en algo gratis o por la marca del dueño, citas que no respaldan la frase, firma con el
nombre del dueño, sección de confidencialidad en sectores sensibles y título corto.
"""
import json
import re
import unicodedata
from contextlib import closing
from datetime import timedelta
from pathlib import Path

from modulos.comun import db
from modulos.comun.base import CONFIG, DIAS, NOMBRE, RAIZ, ahora, registro
from modulos.equipo import control

log = registro("equipo")
ARCHIVO = CONFIG / "equipo.json"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS eq_tareas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pedido TEXT NOT NULL, tipo TEXT, estado TEXT NOT NULL DEFAULT 'en cola',
    plan TEXT, bitacora TEXT DEFAULT '[]', resultado TEXT, archivo TEXT, revision TEXT, origen TEXT DEFAULT 'usuario',
    creado TEXT NOT NULL, terminado TEXT
);
CREATE TABLE IF NOT EXISTS eq_acciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tarea INTEGER, tipo TEXT, texto TEXT, fecha TEXT,
    estado TEXT DEFAULT 'pendiente', creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eq_programadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, dia TEXT NOT NULL, hora TEXT NOT NULL, pedido TEXT NOT NULL,
    activo INTEGER DEFAULT 1, ultima TEXT, creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eq_fallos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pedido TEXT, respuesta TEXT, queja TEXT, creado TEXT NOT NULL
);
"""

AGENTES = {"ceo": "🧑‍💼 CEO", "investigador": "🔎 Investigador", "analista": "📊 Analista", "redactor": "✍️ Redactor",
           "organizador": "🗓️ Organizador", "revisor": "✅ Revisor"}

# Pasos fijos por tipo de trabajo (más confiable que dejar que un modelo chico invente el plan).
PLANTILLAS = {
    "propuesta": [("investigador", "Qué problemas y tareas que quitan tiempo tiene este tipo de cliente en su trabajo diario "
                                   "(en Ecuador o Latinoamérica si hay datos)."),
                  ("investigador", "Qué soluciones con asistentes de IA, automatizaciones o chatbots existen para esas "
                                   "tareas, con ejemplos reales."),
                  ("redactor", "Propuesta de servicio para el cliente: necesidades detectadas, solución con asistentes "
                               "a medida, plan piloto gratis, preguntas para la primera reunión y próximos pasos."),
                  ("organizador", "Próximos pasos concretos para llevar la propuesta al cliente.")],
    "contenido": [("investigador", "Novedades y temas actuales que interesan al público del negocio."),
                  ("redactor", "Plan de contenido: ideas de publicaciones con gancho, texto o guion y día sugerido."),
                  ("organizador", "Tareas para grabar o publicar cada pieza.")],
    "investigacion": [("investigador", "Investigar el tema pedido con fuentes."),
                      ("redactor", "Informe claro: qué es, para qué le sirve al usuario, pros y contras, conclusión.")],
    "plan_semana": [("analista", "Situación actual del usuario: tareas y entregas, hábitos, sueño y dinero."),
                    ("redactor", "Plan de la semana por días, realista con su tiempo, con prioridades."),
                    ("organizador", "Tareas concretas de la semana.")],
    "otro": [("investigador", "Lo que haga falta saber para cumplir el pedido."),
             ("redactor", "El entregable que pide el usuario.")],
}
PIDE_PLAN = """Eres el CEO de un equipo de agentes que trabaja para el dueño de una empresa nueva de IA en Ecuador.
PEDIDO DEL DUEÑO: «{pedido}»

Clasifica el pedido en un tipo: propuesta (para un cliente), contenido (redes sociales), investigacion (averiguar algo),
plan_semana (organizar su semana) u otro. Luego escribe, para cada paso de la plantilla de ese tipo, una instrucción
CONCRETA adaptada al pedido (quién es el cliente, qué sector, qué pide exactamente). Plantillas:
{plantillas}

JSON: {{"tipo": "...", "objetivo": "una frase", "cliente": "quién es el cliente o el público (o vacío)",
"instrucciones": ["instrucción del paso 1", "paso 2", ...]}}"""
ESQUEMA_PLAN = {"type": "object", "properties": {
    "tipo": {"type": "string", "enum": list(PLANTILLAS)}, "objetivo": {"type": "string"}, "cliente": {"type": "string"},
    "instrucciones": {"type": "array", "items": {"type": "string"}, "maxItems": 6}},
    "required": ["tipo", "objetivo", "instrucciones"]}


def _sin_tildes(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


SECTORES_CONFIDENCIALES = ["abogad", "legal", "juridic", "mediaci", "notari", "clinic", "medic", "salud", "contador",
                           "contab", "psicolog", "odontolog", "seguro", "financ"]
CONFIDENCIALIDAD = """## Confidencialidad de tus datos
- En la demo solo se usan nombres y casos inventados.
- Antes de usar datos reales firmamos un acuerdo de confidencialidad y definimos juntos qué datos entran.
- La IA del piloto corre en una computadora propia (IA local): los textos de tus casos no se envían a servicios externos.
- Si más adelante algo tuviera que ir a la nube (por ejemplo WhatsApp), te explico antes qué datos y dónde quedan, y decides tú.
- Se respeta la Ley Orgánica de Protección de Datos Personales y puedes pedir que se borre todo cuando quieras."""


def ajustes():
    defecto = {"carpeta": str(Path("I:/Jarvis/equipo")) if Path("I:/").exists() else str(RAIZ / "datos" / "equipo"),
               "max_busquedas": 3, "resultados_por_busqueda": 6, "clientes": [],
               "sectores_confidenciales": SECTORES_CONFIDENCIALES, "confidencialidad": CONFIDENCIALIDAD}
    try:
        datos = json.loads(ARCHIVO.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        datos = dict(defecto)
        try:
            ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    except Exception as exc:
        log.warning("config/equipo.json no se pudo leer (%s)", exc)
        datos = dict(defecto)
    for k, v in defecto.items():
        datos.setdefault(k, v)
    return datos


def cliente_para(*textos):
    """La ficha de config/equipo.json → "clientes" cuyas palabras aparecen en el pedido o en el cliente del CEO."""
    s = control.sin_tildes(" ".join(t or "" for t in textos))
    mejor, puntos = None, 0
    for c in ajustes().get("clientes") or []:
        p = sum(1 for w in c.get("palabras") or [] if control.sin_tildes(w) in s)
        if p > puntos:
            mejor, puntos = c, p
    return mejor


def texto_cliente(c):
    if not c:
        return "(no hay ficha de este cliente: no prometas cosas hechas; habla de lo que se podría hacer)"
    partes = ["CLIENTE: " + c.get("nombre", "") + (" (" + c["sector"] + ")" if c.get("sector") else "")]
    if c.get("situacion"):
        partes.append("SITUACIÓN REAL: " + c["situacion"])
    if c.get("hecho"):
        partes.append("YA ESTÁ HECHO Y FUNCIONA (demo; es lo más fuerte, preséntalo primero y con detalle):\n"
                      + "\n".join("- " + h["texto"] for h in c["hecho"]))
    if c.get("se_puede"):
        partes.append("SE PUEDE HACER DESPUÉS (ofrécelo como siguiente paso, no como hecho):\n"
                      + "\n".join("- " + x for x in c["se_puede"]))
    if c.get("no_ofrecer"):
        partes.append("NO OFREZCAS: " + ", ".join(c["no_ofrecer"]))
    if c.get("vocabulario"):
        partes.append("PALABRAS CORRECTAS DEL SECTOR: " + "; ".join("no «" + a + "», sino «" + b + "»"
                                                                  for a, b in c["vocabulario"].items()))
    return "\n".join(partes)


def sector_sensible(*textos):
    s = control.sin_tildes(" ".join(t or "" for t in textos))
    return any(control.sin_tildes(w) in s for w in ajustes().get("sectores_confidenciales") or [])


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def _ia(instruccion, max_tokens=900, esquema=None):
    from modulos.biblioteca import biblioteca
    return biblioteca._ia(instruccion, max_tokens=max_tokens, esquema=esquema)


# --- tareas ---------------------------------------------------------------------------------------------------
def crear(pedido, origen="usuario"):
    with closing(_con()) as con, con:
        return con.execute("INSERT INTO eq_tareas (pedido, origen, creado) VALUES (?, ?, ?)",
                           (pedido.strip()[:1500], origen, ahora().isoformat(timespec="seconds"))).lastrowid


def obtener(tid):
    with closing(_con()) as con:
        f = con.execute("SELECT * FROM eq_tareas WHERE id = ?", (tid,)).fetchone()
    return dict(f) if f else None


def tareas(n=10):
    with closing(_con()) as con:
        return [dict(f) for f in con.execute("SELECT * FROM eq_tareas ORDER BY id DESC LIMIT ?", (n,))]


def _actualizar(tid, **campos):
    with closing(_con()) as con, con:
        con.execute("UPDATE eq_tareas SET " + ", ".join(k + " = ?" for k in campos) + " WHERE id = ?",
                    list(campos.values()) + [tid])


def _anotar(tid, agente, texto, aviso=None):
    t = obtener(tid)
    bit = json.loads(t["bitacora"] or "[]")
    bit.append({"agente": agente, "texto": texto[:400], "hora": ahora().strftime("%H:%M")})
    _actualizar(tid, bitacora=json.dumps(bit, ensure_ascii=False))
    if aviso:
        try:
            aviso(AGENTES.get(agente, agente) + ": " + texto[:200])
        except Exception:
            pass


# --- agentes --------------------------------------------------------------------------------------------------
def ceo(pedido):
    texto_pl = "\n".join("- " + tipo + ": " + " | ".join(a + ": " + i for a, i in pasos) for tipo, pasos in PLANTILLAS.items())
    r = _ia(PIDE_PLAN.format(pedido=pedido, plantillas=texto_pl), max_tokens=700, esquema=ESQUEMA_PLAN) or {}
    tipo = r.get("tipo") if r.get("tipo") in PLANTILLAS else _tipo_por_palabras(pedido)
    instrucciones = [str(x) for x in (r.get("instrucciones") or [])]
    pasos = []
    for i, (agente, base) in enumerate(PLANTILLAS[tipo]):
        inst = instrucciones[i].strip() if i < len(instrucciones) and len(instrucciones[i].strip()) > 15 else base
        pasos.append({"agente": agente, "instruccion": inst})
    return {"tipo": tipo, "objetivo": str(r.get("objetivo") or pedido)[:300], "cliente": str(r.get("cliente") or "")[:200],
            "pasos": pasos}


def _tipo_por_palabras(pedido):
    s = _sin_tildes(pedido)
    if re.search(r"propuesta|cotizaci|ofrecer(le)?|cliente|presentar(le)?", s):
        return "propuesta"
    if re.search(r"contenido|post|publicaci|tiktok|instagram|reel|guion", s):
        return "contenido"
    if re.search(r"semana|organiza|planifica|agenda", s):
        return "plan_semana"
    if re.search(r"investiga|averigua|busca|compara|que es|sirve", s):
        return "investigacion"
    return "otro"


ESQUEMA_BUSQUEDAS = {"type": "object", "properties": {"busquedas": {"type": "array", "items": {"type": "string"},
                                                                     "maxItems": 4}}, "required": ["busquedas"]}
ESQUEMA_HALLAZGOS = {"type": "object", "properties": {"hallazgos": {"type": "array", "maxItems": 10, "items": {
    "type": "object", "properties": {"texto": {"type": "string"}, "fuente": {"type": "integer"}},
    "required": ["texto", "fuente"]}}}, "required": ["hallazgos"]}


def investigador(instruccion, pedido):
    """Devuelve {'texto': resumen con [n], 'fuentes': [{'n','titulo','url'}]}."""
    from modulos.noticias import noticias
    a = ajustes()
    r = _ia("Escribe de 2 a " + str(a["max_busquedas"]) + " búsquedas cortas para internet (3-6 palabras, en español; "
            "una puede ser en inglés si ayuda) para esta investigación:\n" + instruccion + "\n(Pedido original: «" + pedido
            + "»)\nJSON: {\"busquedas\": [\"...\"]}", max_tokens=200, esquema=ESQUEMA_BUSQUEDAS) or {}
    busquedas = [b for b in (r.get("busquedas") or []) if isinstance(b, str) and b.strip()][:a["max_busquedas"]] or [instruccion[:80]]
    fuentes, vistos = [], set()
    for b in busquedas:
        try:
            for x in noticias.buscar_web(b, n=a["resultados_por_busqueda"]):
                if x["url"] in vistos:
                    continue
                vistos.add(x["url"])
                fuentes.append({"n": len(fuentes) + 1, "titulo": x["titulo"][:150], "url": x["url"], "extracto": x["extracto"][:300],
                                "producto": es_producto(x["url"])})
        except Exception as exc:
            log.info("Búsqueda «%s» falló: %s", b, exc)
    extra = []
    try:
        from modulos.empresa import empresa
        palabras = set(re.findall(r"\w{5,}", _sin_tildes(instruccion + " " + pedido)))
        for h in empresa.hallazgos(30, 40):
            if len(palabras & set(re.findall(r"\w{5,}", _sin_tildes(h["titulo"])))) >= 2:
                fuentes.append({"n": len(fuentes) + 1, "titulo": h["titulo"][:150], "url": h["enlace"] or "",
                                "extracto": (h["resumen"] or "")[:200]})
    except Exception:
        pass
    try:
        from modulos.segundo_cerebro import segundo_cerebro as sc
        for nota, sim, pal in sc.buscar(pedido + " " + instruccion, n=4):
            if (sim or 0) >= 0.5 or pal:
                extra.append("- (nota del dueño, " + nota["creado"][:10] + ") " + nota["texto"][:250])
    except Exception:
        pass
    if not fuentes and not extra:
        return {"texto": "No encontré información en internet para esto (¿hay conexión?).", "fuentes": []}
    lista = "\n".join("[" + str(f["n"]) + "] " + ("(PÁGINA DE UN PRODUCTO, posible competencia) " if f.get("producto") else "")
                      + f["titulo"] + " — " + f["extracto"] for f in fuentes[:18])
    r = _ia("Investigación: " + instruccion + "\n\nResultados de búsqueda (numerados):\n" + lista
            + ("\n\nNotas del dueño:\n" + "\n".join(extra) if extra else "")
            + "\n\nExtrae de 4 a 10 hallazgos ÚTILES y concretos para el pedido «" + pedido + "». Cada hallazgo en una "
            "frase, con el número de la fuente que lo respalda (0 si viene de las notas del dueño). NO inventes nada que "
            "no esté en los resultados. Si la fuente es la página de un producto, el hallazgo solo puede decir «existe X, "
            "que hace Y» (no es un dato del sector). JSON: {\"hallazgos\": [{\"texto\": \"...\", \"fuente\": 1}]}",
            max_tokens=900, esquema=ESQUEMA_HALLAZGOS) or {}
    usadas, lineas = set(), []
    for h in r.get("hallazgos") or []:
        n = h.get("fuente") if isinstance(h.get("fuente"), int) else 0
        if n and not 1 <= n <= len(fuentes):
            n = 0
        texto_h = str(h.get("texto", "")).strip()
        if n:
            usadas.add(n)
            f = fuentes[n - 1]
            f["hallazgo"] = (f.get("hallazgo", "") + " " + texto_h).strip()
        lineas.append("- " + texto_h + (" [" + str(n) + "]" if n else ""))
    return {"texto": "\n".join(lineas) or "Sin hallazgos claros.",
            "fuentes": [f for f in fuentes if f["n"] in usadas]}


def es_producto(url):
    """La portada de un sitio (sin ruta) suele ser la página de venta de un producto."""
    m = re.match(r"https?://[^/]+(/[^?#]*)?", url or "")
    ruta = (m.group(1) if m else "") or "/"
    return ruta.strip("/") in ("", "es", "en", "home", "inicio", "index.html")


def analista(instruccion):
    partes = []
    for nombre, funcion in [("tareas", _datos_tareas), ("hábitos", _datos_habitos), ("sueño", _datos_sueno),
                            ("dinero", _datos_dinero)]:
        try:
            partes.append(nombre.upper() + ":\n" + funcion())
        except Exception as exc:
            log.info("Analista sin %s: %s", nombre, exc)
    datos = "\n\n".join(partes) or "(sin datos)"
    texto = _ia("Eres analista. Con estos datos del usuario, responde: " + instruccion + "\nSé breve (viñetas), concreto y "
                "usa solo los datos.\n\n" + datos, max_tokens=600)
    return {"texto": str(texto).strip()}


def _datos_tareas():
    from modulos.tareas import tareas as t
    return "\n".join("- " + x["titulo"] + " (" + x["materia"] + ", " + t.fecha_bonita(x["entrega"]) + ")"
                     for x in t.pendientes(hasta=(ahora().date() + timedelta(days=10)).isoformat())) or "(sin pendientes)"


def _datos_habitos():
    from modulos.vida import habitos_vida
    return habitos_vida.texto_semana()


def _datos_sueno():
    from modulos.vida import sueno
    r = sueno.analisis(7)
    return json.dumps({k: v for k, v in r.items() if k not in ("consejos", "relaciones")}, ensure_ascii=False)


def _datos_dinero():
    from modulos.finanzas import gastos, presupuesto
    hoy = ahora().date()
    a, b = gastos.mes(hoy.year, hoy.month)
    total = sum(g["monto"] for g in gastos.del_periodo(a, min(b, hoy), "gasto"))
    disponible, _ = presupuesto.disponible_mes(hoy)
    return "Gastado este mes: " + str(round(total, 2)) + (" de " + str(disponible) + " disponibles" if disponible else "")


def _plan_empresa():
    try:
        from modulos.empresa import empresa
        a = empresa.ajustes()
        return "NEGOCIO: " + a["negocio"] + "\nPÚBLICO: " + a["publico_inicial"] + "\nPLAN:\n" + empresa.texto_plan(a)
    except Exception:
        return ""


PIDE_REDACCION = """Eres el redactor del equipo. Escribe en español claro, ecuatoriano neutro, en Markdown (títulos con ##,
viñetas). Usa SOLO la información de abajo; donde algo no se sabe, dilo o conviértelo en una pregunta para el cliente.
Cita las fuentes con [n] SOLO si la fuente dice exactamente eso. Nada de cifras inventadas.

REGLAS QUE NO SE ROMPEN:
- No escribas que el dueño hizo algo que no está en los datos: nada de «hablé con profesionales», «revisamos casos»,
  «nuestros clientes», «años de experiencia». Tampoco supongas un proyecto conjunto que no existe.
- Ofrece SOLO lo que está en «YA ESTÁ HECHO» y «SE PUEDE HACER» de la ficha del cliente. Nunca digas que la IA está
  «entrenada con las leyes» ni que «conoce la legislación»; nada de «nunca se equivoca» ni garantías.
- Las páginas de productos (posible competencia) solo sirven para decir «ya existen herramientas como X».
- Preguntas para el cliente: solo sobre SU trabajo. Si el piloto es gratis, no preguntes presupuesto. Nunca le
  preguntes el nombre de la marca del dueño (eso lo decide el dueño).
- No copies frases del pedido ni de estas instrucciones dentro del texto.
- Usa el vocabulario correcto del sector del cliente.
- Firma con el nombre del dueño: {nombre}.
{extra}
PEDIDO DEL DUEÑO: «{pedido}»
OBJETIVO: {objetivo}
CLIENTE / PÚBLICO: {cliente}
QUÉ ESCRIBIR: {instruccion}

SOBRE EL NEGOCIO DEL DUEÑO:
{empresa}

FICHA DEL CLIENTE:
{ficha}

LO QUE ENCONTRÓ EL EQUIPO:
{contexto}
{correcciones}"""

PIDE_REVISION = """Eres el revisor del equipo. Compara el resultado con el pedido.
PEDIDO: «{pedido}»
OBJETIVO: {objetivo}
INVESTIGACIÓN DISPONIBLE (lo único que se puede afirmar como dato):
{contexto}

RESULTADO:
{resultado}

Revisa: ¿responde al pedido completo?, ¿inventa datos, cifras o experiencias del dueño («hablé con…», «nuestros
clientes»)?, ¿promete algo que no está hecho (IA «entrenada con las leyes»)?, ¿se coló alguna instrucción del pedido
dentro del texto?, ¿se contradice (pregunta presupuesto de algo gratis)?, ¿cada [n] respalda de verdad la frase?,
¿falta algo importante?, ¿se entiende? JSON: {{"ok": true/false, "problemas": ["..."], "nota": "1 frase"}}"""
ESQUEMA_REVISION = {"type": "object", "properties": {"ok": {"type": "boolean"}, "problemas": {"type": "array",
                    "items": {"type": "string"}, "maxItems": 6}, "nota": {"type": "string"}}, "required": ["ok", "problemas"]}


def redactor(pedido, plan, instruccion, contexto, problemas=None, ficha=None, sensible=False):
    correcciones = ("\nEL REVISOR PIDIÓ CORREGIR ESTO (corrígelo todo):\n" + "\n".join("- " + p for p in problemas)
                    if problemas else "")
    extra = ("- Incluye una sección «## Confidencialidad de tus datos» (el cliente maneja datos delicados).\n"
             if sensible and plan.get("tipo") == "propuesta" else "")
    texto = _ia(PIDE_REDACCION.format(pedido=pedido, objetivo=plan["objetivo"], cliente=plan["cliente"] or "(no se dijo)",
                                      instruccion=instruccion, empresa=_plan_empresa() or "(sin datos)",
                                      ficha=texto_cliente(ficha), nombre=NOMBRE, extra=extra,
                                      contexto=contexto[:6000] or "(nada)", correcciones=correcciones), max_tokens=2200)
    return str(texto).strip()


def revisor(pedido, plan, resultado, contexto):
    r = _ia(PIDE_REVISION.format(pedido=pedido, objetivo=plan["objetivo"], contexto=contexto[:4000] or "(nada)",
                                 resultado=resultado[:6000]), max_tokens=500, esquema=ESQUEMA_REVISION) or {}
    problemas = [str(p) for p in (r.get("problemas") or []) if str(p).strip()][:6]
    return {"ok": bool(r.get("ok", True)) and not (r.get("ok") is False), "problemas": problemas,
            "nota": str(r.get("nota") or "")[:200]}


def _instrucciones_internas(pedido, plan):
    return [pedido] + [p["instruccion"] for p in plan.get("pasos", [])] + [i for pasos in PLANTILLAS.values() for _, i in pasos]


def _gratis(plan, ficha):
    s = " ".join([plan.get("objetivo", ""), plan.get("cliente", ""), (ficha or {}).get("situacion", "")])
    return plan.get("tipo") == "propuesta" or bool(control.GRATIS.search(s))


def problemas_en_codigo(resultado, pedido, plan, fuentes, ficha=None, sensible=False):
    """Lo que el control en código encuentra (para pedírselo al redactor en la corrección)."""
    p = []
    if ficha and ficha.get("hecho") and control.menciona_hecho(resultado, ficha) < 3:
        p.append("no menciona lo que YA está hecho para este cliente (la demo): preséntalo primero")
    if sensible and plan.get("tipo") == "propuesta" and not control.tiene_confidencialidad(resultado):
        p.append("falta la sección de confidencialidad de los datos del cliente")
    for frase, motivo in control.inventos(resultado)[:4]:
        p.append(motivo + ": «" + frase[:120] + "» (quítalo o dilo con la verdad)")
    for frase in control.coladas(resultado, _instrucciones_internas(pedido, plan))[:2]:
        p.append("se coló una instrucción del pedido en el texto: «" + frase[:100] + "» (bórrala)")
    for linea, motivo in control.preguntas_malas(resultado, plan.get("tipo"), _gratis(plan, ficha))[:2]:
        p.append(motivo + ": «" + linea.strip()[:100] + "» (bórrala)")
    for frase, n in control.citas_flojas(resultado, fuentes)[:3]:
        p.append("la fuente [" + str(n) + "] no dice eso: «" + frase[:90] + "» (quita la cita o la frase)")
    return p


def limpiar(resultado, pedido, plan, fuentes, ficha=None, sensible=False):
    """Arregla a la fuerza lo que la IA no corrigió. Devuelve (texto, fuentes, cambios)."""
    cambios = []
    t = control.vocabulario(resultado, (ficha or {}).get("vocabulario"))
    malas = [f for f, _ in control.inventos(t)] + control.coladas(t, _instrucciones_internas(pedido, plan))
    if malas:
        cambios.append(str(len(malas)) + " frases inventadas o coladas quitadas")
        t = control.quitar_frases(t, malas)
    lineas = [l for l, _ in control.preguntas_malas(t, plan.get("tipo"), _gratis(plan, ficha))]
    lineas += control.vinetas_prohibidas(t, (ficha or {}).get("no_ofrecer"))
    if lineas:
        cambios.append(str(len(lineas)) + " líneas que no iban quitadas")
        t = control.quitar_lineas(t, lineas)
    flojas = control.citas_flojas(t, fuentes)
    if flojas:
        cambios.append(str(len(flojas)) + " citas que no respaldaban la frase quitadas")
        t = control.quitar_citas(t, flojas)
    t, fuentes = control.renumerar_fuentes(t, fuentes)
    if ficha and ficha.get("hecho") and control.menciona_hecho(t, ficha) < 3:
        cambios.append("agregada la sección de lo que ya funciona")
        t = control.insertar_antes_del_cierre(t, control.seccion_hecho(ficha))
    if sensible and plan.get("tipo") == "propuesta" and not control.tiene_confidencialidad(t):
        cambios.append("agregada la sección de confidencialidad")
        t = control.insertar_antes_del_cierre(t, ajustes().get("confidencialidad") or CONFIDENCIALIDAD)
    if plan.get("tipo") == "propuesta":
        firmado = control.firmar(t, NOMBRE)
        if firmado != t:
            cambios.append("firmado con su nombre")
        t = firmado
    return t, fuentes, cambios


ESQUEMA_ACCIONES = {"type": "object", "properties": {"acciones": {"type": "array", "maxItems": 5, "items": {
    "type": "object", "properties": {"tipo": {"type": "string", "enum": ["tarea", "nota"]}, "texto": {"type": "string"},
                                     "dias": {"type": "integer"}}, "required": ["tipo", "texto"]}}}, "required": ["acciones"]}


def organizador(tid, pedido, instruccion, resultado):
    """Notas al segundo cerebro (solas) y tareas (pendientes de ✅). Devuelve el texto y las acciones pendientes."""
    r = _ia("Eres el organizador. A partir de este trabajo, propone de 2 a 4 próximos pasos concretos para el dueño "
            "(tipo «tarea», con días desde hoy para hacerlo) y como mucho 1 «nota» con lo más importante para recordar.\n"
            "Pedido: «" + pedido + "»\nQué hacer: " + instruccion + "\n\nTrabajo:\n" + resultado[:3000]
            + "\nJSON: {\"acciones\": [{\"tipo\": \"tarea\", \"texto\": \"...\", \"dias\": 2}]}",
            max_tokens=500, esquema=ESQUEMA_ACCIONES) or {}
    pendientes, lineas = [], []
    for ac in (r.get("acciones") or [])[:5]:
        texto = str(ac.get("texto", "")).strip()[:200]
        if len(texto) < 5:
            continue
        if ac.get("tipo") == "nota":
            try:
                from modulos.segundo_cerebro import segundo_cerebro as sc
                sc.guardar(texto, "nota", "negocio", origen="auto")
                lineas.append("📝 Guardé en su segundo cerebro: " + texto)
            except Exception:
                pass
            continue
        dias = ac.get("dias") if isinstance(ac.get("dias"), int) and 0 <= ac.get("dias") <= 60 else 3
        fecha = (ahora().date() + timedelta(days=dias)).isoformat()
        with closing(_con()) as con, con:
            aid = con.execute("INSERT INTO eq_acciones (tarea, tipo, texto, fecha, creado) VALUES (?, 'tarea', ?, ?, ?)",
                              (tid, texto, fecha, ahora().isoformat(timespec="seconds"))).lastrowid
        pendientes.append({"id": aid, "texto": texto, "fecha": fecha})
    return {"texto": "\n".join(lineas), "pendientes": pendientes}


def aprobar(aid, si):
    with closing(_con()) as con, con:
        a = con.execute("SELECT * FROM eq_acciones WHERE id = ?", (aid,)).fetchone()
        if not a or a["estado"] != "pendiente":
            return "Eso ya estaba respondido."
        con.execute("UPDATE eq_acciones SET estado = ? WHERE id = ?", ("aprobada" if si else "rechazada", aid))
    if not si:
        return "❌ No la agendo: " + a["texto"]
    from modulos.tareas import tareas as t
    t.crear("Empresa", a["texto"], a["fecha"])
    return "✅ Tarea agendada para el " + t.fecha_bonita(a["fecha"]) + ": " + a["texto"]


# --- orquestar ------------------------------------------------------------------------------------------------
def ejecutar(tid, aviso=None):
    """Hace todo el trabajo. aviso(texto) recibe el avance (opcional). Devuelve la tarea terminada (dict)."""
    t = obtener(tid)
    pedido = t["pedido"]
    try:
        _actualizar(tid, estado="planificando")
        plan = ceo(pedido)
        _actualizar(tid, tipo=plan["tipo"], plan=json.dumps(plan, ensure_ascii=False), estado="trabajando")
        _anotar(tid, "ceo", "Plan (" + plan["tipo"] + "): " + " → ".join(AGENTES[p["agente"]].split(" ", 1)[1]
                                                                         for p in plan["pasos"]), aviso)
        contexto, fuentes, resultado, organizar = [], [], "", None
        ficha = cliente_para(pedido, plan.get("cliente"))
        sensible = sector_sensible(pedido, plan.get("cliente"), (ficha or {}).get("sector"))
        if ficha:
            _anotar(tid, "ceo", "Ficha del cliente: " + ficha.get("nombre", "?"), aviso)
        for paso in plan["pasos"]:
            ag, inst = paso["agente"], paso["instruccion"]
            if ag == "investigador":
                r = investigador(inst, pedido)
                mapa, por_url = {}, {f["url"]: f["n"] for f in fuentes if f["url"]}
                for f in r["fuentes"]:                 # numeración única en todo el trabajo, sin fuentes repetidas
                    if f["url"] and f["url"] in por_url:
                        mapa[f["n"]] = por_url[f["url"]]
                    else:
                        mapa[f["n"]] = len(fuentes) + 1
                        fuentes.append({**f, "n": mapa[f["n"]]})
                        por_url[f["url"]] = mapa[f["n"]]
                texto = re.sub(r"\[(\d+)\]", lambda m: "[" + str(mapa.get(int(m.group(1)), m.group(1))) + "]", r["texto"])
                contexto.append("INVESTIGACIÓN — " + inst + "\n" + texto)
                _anotar(tid, ag, str(len(r["fuentes"])) + " fuentes: " + inst, aviso)
            elif ag == "analista":
                r = analista(inst)
                contexto.append("DATOS DEL USUARIO — " + inst + "\n" + r["texto"])
                _anotar(tid, ag, inst, aviso)
            elif ag == "redactor":
                resultado = redactor(pedido, plan, inst, "\n\n".join(contexto), ficha=ficha, sensible=sensible)
                _anotar(tid, ag, "Borrador listo (" + str(len(resultado.split())) + " palabras).", aviso)
                _actualizar(tid, estado="revisando")
                rev = revisor(pedido, plan, resultado, "\n\n".join(contexto))
                de_codigo = problemas_en_codigo(resultado, pedido, plan, fuentes, ficha, sensible)
                problemas = de_codigo + [x for x in rev["problemas"] if x not in de_codigo]
                if problemas and (de_codigo or not rev["ok"]):
                    _anotar(tid, "revisor", "Pidió corregir: " + "; ".join(problemas)[:300], aviso)
                    resultado = redactor(pedido, plan, inst, "\n\n".join(contexto), problemas[:12], ficha, sensible)
                    rev2 = revisor(pedido, plan, resultado, "\n\n".join(contexto))
                    rev = {"ok": rev2["ok"], "problemas": rev2["problemas"], "nota": "corregido una vez. " + rev2["nota"]}
                resultado, fuentes, cambios = limpiar(resultado, pedido, plan, fuentes, ficha, sensible)
                if cambios:
                    _anotar(tid, "revisor", "Control en código: " + "; ".join(cambios), aviso)
                    rev["control"] = cambios
                _anotar(tid, "revisor", "Aprobado. " + rev["nota"] if rev["ok"] else
                        "Quedan dudas: " + "; ".join(rev["problemas"])[:300], aviso)
                _actualizar(tid, revision=json.dumps(rev, ensure_ascii=False))
            elif ag == "organizador":
                organizar = (inst,)
        if fuentes:
            resultado += "\n\n## Fuentes\n" + "\n".join("[" + str(f["n"]) + "] " + f["titulo"] + (" — " + f["url"] if f["url"] else "")
                                                       + (" (página de un producto)" if f.get("producto") else "")
                                                       for f in fuentes)
        pendientes = []
        if organizar and resultado:
            o = organizador(tid, pedido, organizar[0], resultado)
            pendientes = o["pendientes"]
            _anotar(tid, "organizador", str(len(pendientes)) + " tareas propuestas (esperan su ✅). " + o["texto"], aviso)
        titulo, del_texto = control.titulo_corto(resultado, plan["objetivo"])
        if del_texto:                                    # el primer ## pasa a ser el título del documento
            resultado = resultado.split("\n", 1)[1].lstrip("\n") if "\n" in resultado else ""
        plan["titulo"] = titulo
        _actualizar(tid, plan=json.dumps(plan, ensure_ascii=False))
        archivo = guardar_archivo(tid, plan, resultado)
        _actualizar(tid, resultado=resultado, archivo=archivo, estado="lista", terminado=ahora().isoformat(timespec="seconds"))
        try:
            from modulos.segundo_cerebro import segundo_cerebro as sc
            sc.guardar("El equipo terminó: " + plan["objetivo"][:150] + " (trabajo #" + str(tid) + ")", "nota", "negocio",
                       origen="auto")
        except Exception:
            pass
        out = obtener(tid)
        out["pendientes"] = pendientes
        return out
    except Exception as exc:
        log.warning("El equipo falló en la tarea %s: %s", tid, exc)
        _actualizar(tid, estado="falló", resultado="No se pudo terminar: " + str(exc)[:300])
        raise


def guardar_archivo(tid, plan, resultado):
    carpeta = Path(ajustes()["carpeta"])
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        titulo = plan.get("titulo") or control.titulo_corto("", plan["objetivo"])[0]
        nombre = ahora().strftime("%Y-%m-%d") + "_" + str(tid) + "_" + re.sub(r"[^a-z0-9]+", "_",
                                                                             _sin_tildes(titulo))[:50].strip("_") + ".md"
        ruta = carpeta / nombre
        ruta.write_text("# " + titulo + "\n\n_Trabajo #" + str(tid) + " del equipo · " + ahora().strftime("%d/%m/%Y")
                        + "_\n\n" + resultado, encoding="utf-8")
        return str(ruta)
    except Exception as exc:
        log.warning("No pude guardar el archivo del trabajo %s: %s", tid, exc)
        return None


def texto_bitacora(t):
    bit = json.loads(t.get("bitacora") or "[]")
    return "\n".join(b["hora"] + " " + AGENTES.get(b["agente"], b["agente"]) + ": " + b["texto"] for b in bit)


# --- programados y fallos -------------------------------------------------------------------------------------
def programar(dia, hora_txt, pedido):
    with closing(_con()) as con, con:
        return con.execute("INSERT INTO eq_programadas (dia, hora, pedido, creado) VALUES (?, ?, ?, ?)",
                           (dia, hora_txt, pedido, ahora().isoformat(timespec="seconds"))).lastrowid


def programadas():
    with closing(_con()) as con:
        return [dict(f) for f in con.execute("SELECT * FROM eq_programadas WHERE activo = 1 ORDER BY id")]


def toca_programadas(momento=None):
    """Las programadas que deben correr ahora (y las marca). [dict]"""
    m = momento or ahora()
    hoy, dia = m.date().isoformat(), DIAS[m.weekday()]
    salida = []
    with closing(_con()) as con, con:
        for p in con.execute("SELECT * FROM eq_programadas WHERE activo = 1").fetchall():
            if p["dia"] not in (dia, "todos") or p["ultima"] == hoy or m.strftime("%H:%M") < p["hora"]:
                continue
            con.execute("UPDATE eq_programadas SET ultima = ? WHERE id = ?", (hoy, p["id"]))
            salida.append(dict(p))
    return salida


def registrar_fallo(queja):
    from modulos.ia import memoria
    h = memoria.historial(2)
    pedido = next((x["content"] for x in h if x["role"] == "user"), "")
    respuesta = next((x["content"] for x in h if x["role"] == "assistant"), "")
    with closing(_con()) as con, con:
        con.execute("INSERT INTO eq_fallos (pedido, respuesta, queja, creado) VALUES (?, ?, ?, ?)",
                    (pedido[:500], respuesta[:500], queja[:300], ahora().isoformat(timespec="seconds")))
    return pedido


def fallos(dias=7):
    desde = (ahora() - timedelta(days=dias)).isoformat()
    with closing(_con()) as con:
        return [dict(f) for f in con.execute("SELECT * FROM eq_fallos WHERE creado >= ? ORDER BY id", (desde,))]


def texto_fallos(dias=7):
    lista = fallos(dias)
    if not lista:
        return "👍 No tengo fallos anotados en los últimos " + str(dias) + " días."
    return ("🔧 Fallos de los últimos " + str(dias) + " días (" + str(len(lista)) + "). Mándeselos a Claude para arreglarlos "
            "con pruebas:\n\n" + "\n".join(str(i) + ". Usted: «" + f["pedido"][:120] + "»\n   Respondí: «" + f["respuesta"][:120]
                                           + "»\n   Queja: «" + f["queja"][:80] + "»" for i, f in enumerate(lista, 1)))


# --- frases ---------------------------------------------------------------------------------------------------
_R = r"^\W*(?:jarvis\W+|oye\W+|por\s+favor\W+)*"
PEDIDO = re.compile(_R + r"(?:/?equipo\s*[:,\-–]?\s+|que\s+(?:el\s+)?equipo\s+|p[ií]de(?:le)?\s+al\s+equipo\s+(?:que\s+)?|"
                    r"dile\s+al\s+equipo\s+(?:que\s+)?|equipo,?\s+(?:por\s+favor\s+)?)(.{8,})$", re.I | re.S)
ESTADO = re.compile(_R + r"(?:estado\s+del\s+equipo|qu[eé]\s+(?:est[aá]\s+haciendo|hace)\s+el\s+equipo|"
                    r"(?:trabajos|tareas)\s+del\s+equipo|c[oó]mo\s+va\s+el\s+equipo)\W*$", re.I)
PROGRAMAR = re.compile(_R + r"cada\s+(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|d[ií]a)"
                       r"(?:\s+a\s+las\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|de\s+la\s+(?:mañana|tarde|noche))?)?\s*,?\s+"
                       r"(?:que\s+)?(?:el\s+)?equipo\s+(.{8,})$", re.I | re.S)
VER_PROG = re.compile(_R + r"(?:trabajos|tareas)\s+programad[oa]s(?:\s+del\s+equipo)?\W*$", re.I)
QUITAR_PROG = re.compile(_R + r"(?:quita|borra|elimina|cancela)\s+(?:el\s+|la\s+)?(?:trabajo|tarea)\s+programad[oa]\s+#?(\d+)\W*$", re.I)
QUEJA = re.compile(r"^\W*(?:no\s+(?:era|es)\s+eso|te\s+equivocaste|no\s+me\s+entendiste|no\s+entendiste|eso\s+est[aá]\s+mal|"
                   r"respuesta\s+equivocada|no\s+es\s+lo\s+que\s+(?:te\s+)?ped[ií]|me\s+entendiste\s+mal)\b", re.I)
VER_FALLOS = re.compile(_R + r"(?:(?:fallos|errores)\s+(?:de\s+la\s+semana|del\s+asistente|anotados)|qu[eé]\s+fallos\s+tuviste)\W*$", re.I)


def procesar(texto):
    """str (respuesta directa), {'tarea': id} (lanzar en segundo plano) o None."""
    t = (texto or "").strip()
    if not t:
        return None
    if QUEJA.match(t):
        pedido = registrar_fallo(t)
        if len(t.split()) > 7:                 # trae la corrección en el mismo mensaje: que lo atienda el resto
            return None
        return ("📝 Anotado como fallo para mejorarlo" + (": «" + pedido[:80] + "»" if pedido else "") + ". "
                "¿Qué esperaba que hiciera? Dígamelo con otras palabras y lo intento de nuevo.")
    if VER_FALLOS.match(t):
        return texto_fallos()
    m = PROGRAMAR.match(t)
    if m:
        dia = _sin_tildes(m.group(1))
        dia = "todos" if dia == "dia" else dia
        h = int(m.group(2) or 8)
        sufijo = _sin_tildes(m.group(4) or "")
        if ("pm" in sufijo or "tarde" in sufijo or "noche" in sufijo) and h < 12:
            h += 12
        hora_txt = "%02d:%02d" % (min(h, 23), int(m.group(3) or 0))
        pid = programar(dia, hora_txt, m.group(5).strip())
        return ("🗓️ Listo: " + ("cada día" if dia == "todos" else "cada " + m.group(1).lower()) + " a las " + hora_txt
                + " el equipo hará: «" + m.group(5).strip()[:120] + "» (programado #" + str(pid) + ").")
    if VER_PROG.match(t):
        lista = programadas()
        return ("🗓️ Trabajos programados:\n" + "\n".join("#" + str(p["id"]) + " " + ("cada día" if p["dia"] == "todos" else
                "cada " + p["dia"]) + " " + p["hora"] + ": " + p["pedido"][:100] for p in lista)) if lista else \
            "No hay trabajos programados. Ej.: «cada lunes a las 8 que el equipo prepare mi plan de contenido»."
    m = QUITAR_PROG.match(t)
    if m:
        with closing(_con()) as con, con:
            hecho = con.execute("UPDATE eq_programadas SET activo = 0 WHERE id = ? AND activo = 1",
                                (int(m.group(1)),)).rowcount
        return "🗑️ Quité el trabajo programado #" + m.group(1) + "." if hecho else "No encuentro ese trabajo programado."
    if ESTADO.match(t):
        lista = tareas(5)
        if not lista:
            return "El equipo no ha hecho trabajos todavía. Pídale algo: «equipo: …»."
        return "🤖 Trabajos del equipo:\n" + "\n".join("#" + str(x["id"]) + " [" + x["estado"] + "] " + x["pedido"][:90]
                                                      for x in lista)
    m = PEDIDO.match(t)
    if m:
        return {"tarea": crear(m.group(1))}
    return None


def datos_panel():
    return {"tareas": [{"id": x["id"], "pedido": x["pedido"], "estado": x["estado"], "tipo": x["tipo"],
                        "resultado": x["resultado"], "bitacora": json.loads(x["bitacora"] or "[]"),
                        "fecha": (x["creado"] or "")[:16].replace("T", " ")} for x in tareas(8)],
            "programadas": programadas(), "fallos": len(fallos(7))}
