"""Agente de la empresa de IA (Fase 3): investiga solo y arma un informe semanal. Todo con la IA local.

- Cada 6 h, en silencio: noticias de IA (mundo, Latinoamérica, Ecuador), herramientas nuevas, IA para el público que
  eligió (al inicio: profesionales amigos como abogados, gratis para ganar experiencia; después pymes) y lo que
  publican los competidores que sigue. Se puntúa por palabras y por significado (vectores de la biblioteca); no
  usa la IA grande por cada noticia.
- Una vez por semana busca competidores nuevos en internet (DuckDuckGo) y los PROPONE (botones Seguir/Descartar).
- Viernes 17:30 (config/empresa.json): informe con novedades, competencia, 3 oportunidades, 3 acciones de la semana y
  borradores para Instagram y TikTok. Usa también sus ideas, metas y decisiones del segundo cerebro. Queda en el panel.
- Aviso inmediato SOLO si un competidor que sigue publica algo muy relevante (máx. 1 por día).
Frases: «qué hay de nuevo en IA», «mis competidores», «agrega competidor X (web)», «quita competidor X»,
«busca competidores», «hazme un post sobre X (para TikTok)», «ideas para la empresa», «informe de la empresa».
Tablas emp_hallazgos, emp_competidores, emp_informes, emp_borradores en datos/asistente.db.
"""
import hashlib
import json
import re
import unicodedata
from contextlib import closing
from datetime import timedelta
from urllib.parse import quote_plus, urlparse

from modulos.comun import db
from modulos.comun.base import CONFIG, ahora, registro

log = registro("empresa")
ARCHIVO = CONFIG / "empresa.json"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS emp_hallazgos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, clave TEXT UNIQUE, titulo TEXT NOT NULL, enlace TEXT, fuente TEXT,
    fecha TEXT, resumen TEXT, categoria TEXT, competidor INTEGER, relevancia REAL DEFAULT 0,
    avisado INTEGER DEFAULT 0, creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emp_competidores (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, web TEXT, descripcion TEXT,
    origen TEXT DEFAULT 'manual', estado TEXT DEFAULT 'seguido', creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emp_informes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, semana TEXT, datos TEXT NOT NULL, creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emp_borradores (
    id INTEGER PRIMARY KEY AUTOINCREMENT, red TEXT, tema TEXT, texto TEXT NOT NULL, origen TEXT,
    creado TEXT NOT NULL
);
"""

PREDETERMINADO = {
    "negocio": "Empresa de inteligencia artificial en Ecuador: ayudar a negocios y profesionales a usar IA de verdad "
               "(automatizar tareas, atención al cliente, documentos), no solo para investigar o hacer deberes.",
    "publico_inicial": "Profesionales amigos (abogados, contadores y similares), gratis al principio para ganar "
                       "experiencia y casos de éxito; después pymes.",
    "redes": ["Instagram", "TikTok"],
    "plan": {
        "marca": "", "servicios": "", "como_trabaja": "", "sabe_hacer": "", "horas_semana": "",
        "presupuesto": "", "meta_3_meses": "", "captacion": "", "no_quiere": "", "por_descubrir": [],
    },
    "informe": {"dia": "viernes", "hora": "17:30"},
    "aviso_competidor": True,
    "busquedas": [
        {"q": "inteligencia artificial Ecuador", "cat": "ia_ecuador", "region": "EC"},
        {"q": "IA empresas Ecuador", "cat": "ia_ecuador", "region": "EC"},
        {"q": "inteligencia artificial pymes Latinoamérica", "cat": "ia_latam"},
        {"q": "inteligencia artificial abogados", "cat": "publico"},
        {"q": "IA para despachos jurídicos", "cat": "publico"},
        {"q": "inteligencia artificial contadores", "cat": "publico"},
        {"q": "automatización con IA negocios", "cat": "oportunidad"},
        {"q": "nueva herramienta de inteligencia artificial", "cat": "herramientas"},
        {"q": "OpenAI OR Anthropic OR Gemini lanzamiento", "cat": "ia_mundo", "idioma": "en"},
        {"q": "AI tools for small business", "cat": "herramientas", "idioma": "en"},
        {"q": "AI for lawyers", "cat": "publico", "idioma": "en"},
    ],
    "buscar_competidores": ["agencia de inteligencia artificial Ecuador", "automatización con IA para empresas Ecuador",
                            "chatbot WhatsApp para negocios Ecuador", "consultoría inteligencia artificial Guayaquil",
                            "consultoría inteligencia artificial Quito", "IA para abogados Ecuador"],
}
CATEGORIA = {"ia_ecuador": "🇪🇨 IA en Ecuador", "ia_latam": "🌎 IA en Latinoamérica", "ia_mundo": "🌍 IA en el mundo",
             "herramientas": "🛠️ Herramientas", "publico": "⚖️ Su público", "oportunidad": "💡 Oportunidades",
             "competidor": "🏁 Competencia"}
PALABRAS_CLAVE = {
    3: r"ecuador|guayaquil|quito|cuenca|abogad|jur[ií]dic|despacho|contador|contabl|pyme|peque[nñ]as? empresas?|"
       r"emprend|whatsapp|chatbot|atenci[oó]n al cliente|automatiza",
    2: r"latinoam[eé]rica|latam|am[eé]rica latina|colombia|per[uú]|m[eé]xico|negocio|empresa|small business|lawyer|"
       r"legal|productividad|agente|asistente",
    1: r"inteligencia artificial|\bia\b|\bai\b|openai|chatgpt|gemini|anthropic|claude|llm|modelo de lenguaje|"
       r"lanz|nueva herramienta|launch|release",
}


def _sin_tildes(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def ajustes():
    try:
        datos = json.loads(ARCHIVO.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        datos = json.loads(json.dumps(PREDETERMINADO))
        try:
            ARCHIVO.parent.mkdir(exist_ok=True)
            ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            log.info("No pude crear config/empresa.json: %s", exc)
    except Exception as exc:
        log.warning("config/empresa.json no se pudo leer (%s): uso los valores por defecto", exc)
        datos = json.loads(json.dumps(PREDETERMINADO))
    for k, v in PREDETERMINADO.items():
        datos.setdefault(k, v)
    return datos


CAMPOS_PLAN = [("marca", "Nombre de la marca"), ("servicios", "Qué ofrece"), ("como_trabaja", "Cómo trabaja"),
               ("sabe_hacer", "Qué sabe hacer"), ("horas_semana", "Horas por semana"), ("presupuesto", "Presupuesto"),
               ("meta_3_meses", "Meta a 3 meses"), ("captacion", "Cómo conseguir clientes"),
               ("no_quiere", "Lo que no quiere"), ("por_descubrir", "Por descubrir")]


def texto_plan(a=None):
    """El plan del dueño en texto, para la IA y para mostrarlo."""
    a = a or ajustes()
    plan = a.get("plan") or {}
    lineas = []
    for clave, nombre in CAMPOS_PLAN:
        v = plan.get(clave)
        if isinstance(v, list):
            v = "; ".join(str(x) for x in v if str(x).strip())
        lineas.append("- " + nombre + ": " + (str(v).strip() or "(no lo sabe todavía)"))
    return "\n".join(lineas)


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def _clave(titulo):
    base = re.sub(r"[^a-z0-9 ]", " ", _sin_tildes(titulo))
    return hashlib.sha1(" ".join(base.split())[:90].encode()).hexdigest()[:16]


# --- competidores ---------------------------------------------------------------------------------------------
def competidores(estado="seguido"):
    with closing(_con()) as con:
        if estado:
            return con.execute("SELECT * FROM emp_competidores WHERE estado = ? ORDER BY nombre", (estado,)).fetchall()
        return con.execute("SELECT * FROM emp_competidores ORDER BY estado, nombre").fetchall()


def _dominio(web):
    if not web:
        return ""
    w = web if "://" in web else "http://" + web
    return (urlparse(w).netloc or "").lower().removeprefix("www.")


def agregar_competidor(nombre, web="", descripcion="", origen="manual", estado="seguido"):
    nombre = " ".join((nombre or "").split()).strip(" .,;")[:80]
    if len(nombre) < 2:
        return None, False
    dom = _dominio(web)
    with closing(_con()) as con, con:
        for f in con.execute("SELECT * FROM emp_competidores").fetchall():
            if _sin_tildes(f["nombre"]) == _sin_tildes(nombre) or (dom and _dominio(f["web"]) == dom):
                if origen == "manual" and f["estado"] != "seguido":
                    con.execute("UPDATE emp_competidores SET estado = 'seguido' WHERE id = ?", (f["id"],))
                    return f["id"], True
                return f["id"], False
        cid = con.execute("INSERT INTO emp_competidores (nombre, web, descripcion, origen, estado, creado) "
                          "VALUES (?, ?, ?, ?, ?, ?)", (nombre, web or "", descripcion or "", origen, estado,
                                                         ahora().isoformat(timespec="seconds"))).lastrowid
    return cid, True


def cambiar_competidor(cid, estado):
    with closing(_con()) as con, con:
        f = con.execute("SELECT nombre FROM emp_competidores WHERE id = ?", (cid,)).fetchone()
        if not f:
            return None
        con.execute("UPDATE emp_competidores SET estado = ? WHERE id = ?", (estado, cid))
    return f["nombre"]


def _limpia_nombre(texto):
    t = _sin_tildes(texto or "").strip(" .,;:!?¿¡\"'«»")
    t = re.sub(r"^(?:a\s+|al\s+|la\s+|el\s+|los\s+|las\s+)?(?:empresa|compania|competidor(?:a)?|competencia|agencia|startup)"
               r"(?:\s+(?:llamada|que\s+se\s+llama))?\s+", "", t)
    t = re.sub(r"^(?:a|al|la|el)\s+", "", t)
    t = re.sub(r"\s+(?:de\s+(?:mis\s+|la\s+lista\s+de\s+|los\s+)?(?:competidores|competencia|empresas(?:\s+que\s+sigo)?|"
               r"la\s+lista|lista)|por\s+favor|porfa|ya|tambien)$", "", t)
    return t.strip(" .,;:!?\"'«»")


def buscar_competidor(texto, incluir_descartados=False, estricto=False):
    """El competidor que nombra el texto: número de la lista, nombre exacto, parte del nombre o web. None si no hay."""
    lista = [c for c in competidores(None) if incluir_descartados or c["estado"] != "descartado"]
    t = _limpia_nombre(texto)
    if not t:
        return None
    m = re.fullmatch(r"(?:n(?:umero|ro)?\.?\s*)?#?(\d{1,2})", t)
    if m:
        orden = sorted([c for c in lista if c["estado"] == "seguido"], key=lambda c: _sin_tildes(c["nombre"]))
        i = int(m.group(1)) - 1
        return orden[i] if 0 <= i < len(orden) else None
    exactos = [c for c in lista if _sin_tildes(c["nombre"]) == t or (_dominio(c["web"]) and _dominio(c["web"]) == t)]
    if exactos:
        return exactos[0]
    if estricto:
        return None

    def parecido(c):
        n, w = _sin_tildes(c["nombre"]), _dominio(c["web"])
        return ((len(t) >= 3 and (n.startswith(t) or (w and w.startswith(t)))) or (len(t) >= 4 and t in n)
                or (len(n) >= 3 and re.search(r"(?<![\w])" + re.escape(n) + r"(?![\w])", t)))
    hallados = [c for c in lista if parecido(c)]
    if len(hallados) == 1:
        return hallados[0]
    return hallados or None                                # varios: que el usuario elija


def quitar_competidor(nombre):
    c = buscar_competidor(nombre)
    if isinstance(c, dict) or (c is not None and not isinstance(c, list)):
        cambiar_competidor(c["id"], "descartado")
        return c["nombre"]
    return None


ESQUEMA_COMP = {"type": "object", "properties": {"empresas": {"type": "array", "maxItems": 8, "items": {
    "type": "object", "properties": {"nombre": {"type": "string"}, "web": {"type": "string"},
                                     "que_ofrecen": {"type": "string"}, "es_competidor": {"type": "boolean"}},
    "required": ["nombre", "web", "que_ofrecen", "es_competidor"]}}}, "required": ["empresas"]}
NO_COMPETIDOR = re.compile(r"wikipedia|youtube|facebook\.com|instagram\.com|tiktok|linkedin\.com/in/|gob\.ec|"
                           r"\.gov|universidad|\.edu|ibm\.com|microsoft|google\.|amazon\.|openai|elcomercio|eluniverso|"
                           r"primicias|expreso|forbes|reddit|indeed|computrabajo|glassdoor", re.I)


def descubrir_competidores():
    """Busca en internet empresas que ofrecen IA en Ecuador y las deja PROPUESTAS. Devuelve [(id, nombre, web, que)]."""
    from modulos.biblioteca import biblioteca
    from modulos.noticias import noticias
    resultados, vistos = [], set()
    for consulta in ajustes()["buscar_competidores"]:
        for r in noticias.buscar_web(consulta, n=8):
            dom = _dominio(r["url"])
            if not dom or dom in vistos or NO_COMPETIDOR.search(r["url"]):
                continue
            vistos.add(dom)
            resultados.append("- " + r["titulo"][:120] + " | " + r["url"][:120] + " | " + r["extracto"][:220])
    if not resultados:
        return []
    r = biblioteca._ia("Estos son resultados de búsqueda. Identifica las EMPRESAS O PERSONAS que venden servicios de "
                       "inteligencia artificial, automatización o chatbots a negocios o profesionales en Ecuador o "
                       "Latinoamérica (posibles competidores de una empresa nueva de IA en Ecuador). Ignora noticias, "
                       "universidades, gobiernos, grandes tecnológicas y bolsas de empleo. Para cada una: nombre, web "
                       "(la del resultado), qué ofrecen (máx. 15 palabras) y es_competidor (true/false).\n\n"
                       + "\n".join(resultados[:30]), max_tokens=900, esquema=ESQUEMA_COMP)
    nuevos = []
    for e in r.get("empresas") or []:
        if not e.get("es_competidor") or NO_COMPETIDOR.search(e.get("web", "") or ""):
            continue
        cid, nuevo = agregar_competidor(e.get("nombre", ""), e.get("web", ""), e.get("que_ofrecen", ""),
                                        origen="descubierto", estado="propuesto")
        if cid and nuevo:
            nuevos.append((cid, e["nombre"], e.get("web", ""), e.get("que_ofrecen", "")))
    log.info("Competidores propuestos: %d", len(nuevos))
    return nuevos


# --- recoger --------------------------------------------------------------------------------------------------
def _url_google(q, region=None, idioma="es", dias=3):
    if idioma == "en":
        return ("https://news.google.com/rss/search?q=" + quote_plus(q) + "+when:" + str(dias)
                + "d&hl=en-US&gl=US&ceid=US:en")
    gl = region or "US"
    return ("https://news.google.com/rss/search?q=" + quote_plus(q) + "+when:" + str(dias) + "d&hl=es-419&gl=" + gl
            + "&ceid=" + gl + ":es-419")


CONTEXTO_IA = r"inteligencia artificial|\bia\b|\bai\b|chatbot|automatiza|asistente|agente|software|tecnolog|startup|digital"


def es_del_competidor(c, titulo, resumen, enlace):
    """¿Esta noticia es DE ese competidor? El nombre tiene que estar en el TITULAR (palabra completa, sin tildes)
    o el enlace ser de su web. El resumen no basta: Google News mete ahí titulares de otras noticias."""
    nombre = _sin_tildes(c["nombre"]).strip()
    dom = _dominio(c["web"])
    if dom and dom in (enlace or "").lower():
        return True
    if not nombre or not re.search(r"(?<![\w])" + re.escape(nombre) + r"(?![\w])", _sin_tildes(titulo)):
        return False
    if len(nombre.split()) == 1 and len(nombre) <= 6:       # nombres cortos/comunes: además, que hable de tecnología
        return bool(re.search(CONTEXTO_IA, _sin_tildes(titulo + " " + (resumen or ""))))
    return True


def _consulta_competidor(c):
    nombre = '"' + c["nombre"] + '"'
    return nombre + " (inteligencia artificial OR IA OR chatbot OR automatización OR asistente)"


def revisar_competidores():
    """Corrige lo ya guardado: si una noticia marcada como del competidor no lo es, pasa a general y baja su nota."""
    comps = {c["id"]: c for c in competidores(None)}
    arreglados = 0
    with closing(_con()) as con, con:
        for h in con.execute("SELECT * FROM emp_hallazgos WHERE categoria = 'competidor'").fetchall():
            c = comps.get(h["competidor"])
            if c is None or c["estado"] == "descartado" or not es_del_competidor(c, h["titulo"], h["resumen"], h["enlace"]):
                con.execute("UPDATE emp_hallazgos SET categoria = 'oportunidad', competidor = NULL, "
                            "relevancia = MAX(0, relevancia - 4) WHERE id = ?", (h["id"],))
                arreglados += 1
    return arreglados


def _puntaje_palabras(texto):
    s = _sin_tildes(texto)
    return sum(peso * min(2, len(re.findall(patron, s))) for peso, patron in PALABRAS_CLAVE.items())


def _perfil_vector():
    from modulos.biblioteca import biblioteca
    a = ajustes()
    m = biblioteca.vectores([a["negocio"] + " " + a["publico_inicial"]], consulta=True)
    return None if m is None else m[0]


# --- filtro: solo noticias de IA y bien clasificadas (19-11) --------------------------------------------------
HABLA_IA = re.compile(r"inteligencia artificial|\bia\b|\bai\b|\ba\.i\.|chatgpt|openai|gemini|anthropic|claude|copilot|"
                      r"\bllms?\b|chatbots?|agentes? (?:de ia|inteligentes?|virtuales?|autonomos?)|automatiza|"
                      r"machine learning|aprendizaje automatico|generativ|legaltech|algoritmo|deepseek|mistral|"
                      r"artificial intelligence|\bagents?\b|automation")
DEPORTE = re.compile(r"\bmundial\b|\bsub[- ]?\d{2}\b|\bpartido\b|\bgol(?:es)?\b|\bseleccion\b|\bliga\b|\bcopa\b|"
                     r"futbol|campeonato|\bvence\b|\bempata|\bmarcador\b|eliminatorias|\bdebut\b|tenis|ciclismo|boxeo")
ECUADOR = re.compile(r"ecuador|quito|guayaquil|cuenca|manta|ambato|loja|machala|samborondon|mintel")
EUROPA = re.compile(r"espana|espanol(?:a|es|as)?\b|madrid|barcelona|valencia|sevilla|bilbao|navarra|europa|europe|"
                    r"\buk\b|alemania|francia|italia")
LATAM = re.compile(r"latinoamerica|latam|america latina|colombia|peru|mexico|chile|argentina|bolivia|venezuela|"
                   r"uruguay|paraguay|panama|costa rica|guatemala|brasil")


def filtrar(c):
    """La categoría correcta del hallazgo, o None si no sirve (no es de IA, es deporte…). Los de competidores no se tocan."""
    cat = c.get("categoria")
    if cat == "competidor":
        return cat
    titulo = _sin_tildes(c.get("titulo"))
    todo = titulo + " " + _sin_tildes(re.sub(r"<[^>]+>", " ", c.get("resumen") or ""))
    if DEPORTE.search(titulo) and not HABLA_IA.search(titulo):
        return None
    if not HABLA_IA.search(todo):
        return None
    if cat == "ia_ecuador" and not ECUADOR.search(todo):
        return "ia_latam" if LATAM.search(todo) and not EUROPA.search(titulo) else "ia_mundo"
    if cat == "ia_latam" and EUROPA.search(titulo) and not LATAM.search(titulo):
        return "ia_mundo"
    return cat


def limpiar_guardados(dias=30):
    """Aplica el filtro a lo ya guardado: borra lo que no sirve y corrige categorías. Devuelve (borrados, movidos)."""
    desde = (ahora() - timedelta(days=dias)).isoformat()
    borrados = movidos = 0
    with closing(_con()) as con, con:
        for f in con.execute("SELECT * FROM emp_hallazgos WHERE creado >= ? AND categoria != 'competidor'",
                             (desde,)).fetchall():
            nueva = filtrar(dict(f))
            if nueva is None:
                con.execute("DELETE FROM emp_hallazgos WHERE id = ?", (f["id"],))
                borrados += 1
            elif nueva != f["categoria"]:
                con.execute("UPDATE emp_hallazgos SET categoria = ? WHERE id = ?", (nueva, f["id"]))
                movidos += 1
    if borrados or movidos:
        log.info("Filtro: borré %d hallazgos que no eran de IA y moví %d de categoría", borrados, movidos)
    return borrados, movidos


def recoger():
    """Lee las búsquedas y los competidores. Guarda lo nuevo con su relevancia (0-10). Devuelve cuántos nuevos."""
    from modulos.noticias import noticias
    a = ajustes()
    pedidos = [(b, _url_google(b["q"], b.get("region"), b.get("idioma", "es")), None) for b in a["busquedas"]]
    revisar_competidores()
    try:
        limpiar_guardados()
    except Exception as exc:
        log.info("Filtro de guardados falló: %s", exc)
    comps = {c["id"]: c for c in competidores()}
    for c in comps.values():
        pedidos.append(({"q": c["nombre"], "cat": "competidor"}, _url_google(_consulta_competidor(c), "EC", dias=7),
                        c["id"]))
    candidatos = []
    with closing(_con()) as con:
        ya = {f["clave"] for f in con.execute("SELECT clave FROM emp_hallazgos WHERE creado >= ?",
                                                (( ahora() - timedelta(days=30)).isoformat(),))}
    for b, url, cid in pedidos:
        try:
            items = noticias.leer_rss(url)
        except Exception as exc:
            log.info("No pude leer «%s»: %s", b["q"], exc)
            continue
        for titulo, enlace, fecha, resumen in items[:15]:
            clave = _clave(titulo)
            if clave in ya:
                continue
            ya.add(clave)
            fuente = ""
            m = re.search(r"\s+-\s+([^-]{2,40})$", titulo)
            if m:
                fuente, titulo = m.group(1).strip(), titulo[:m.start()].strip()
            categoria, de_quien = b["cat"], cid
            if cid is not None and not es_del_competidor(comps[cid], titulo, resumen, enlace):
                categoria, de_quien = "oportunidad", None     # salió en la búsqueda pero no es de él
            c_nuevo = {"clave": clave, "titulo": titulo, "enlace": enlace, "fuente": fuente,
                       "fecha": fecha.isoformat() if fecha else None, "resumen": resumen,
                       "categoria": categoria, "competidor": de_quien}
            c_nuevo["categoria"] = filtrar(c_nuevo)
            if c_nuevo["categoria"]:                  # None: no es de IA o es deporte → fuera
                candidatos.append(c_nuevo)
    if not candidatos:
        return 0
    perfil = None
    try:
        perfil = _perfil_vector()
    except Exception as exc:
        log.info("Sin vectores para puntuar (se usa solo palabras): %s", exc)
    sims = [None] * len(candidatos)
    if perfil is not None:
        try:
            import numpy as np
            from modulos.biblioteca import biblioteca
            m = biblioteca.vectores([c["titulo"] + ". " + (c["resumen"] or "")[:200] for c in candidatos])
            if m is not None:
                sims = list(m.astype(np.float32) @ np.asarray(perfil, dtype=np.float32))
        except Exception as exc:
            log.info("Vectores fallaron: %s", exc)
    with closing(_con()) as con, con:
        for c, sim in zip(candidatos, sims):
            palabras = _puntaje_palabras(c["titulo"] + " " + (c["resumen"] or ""))
            rel = min(10.0, palabras * 0.6 + (max(0.0, float(sim) - 0.3) * 20 if sim is not None else 0))
            if c["categoria"] == "competidor":
                rel = min(10.0, rel + 3)
            con.execute("INSERT OR IGNORE INTO emp_hallazgos (clave, titulo, enlace, fuente, fecha, resumen, categoria, "
                        "competidor, relevancia, creado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (c["clave"], c["titulo"], c["enlace"], c["fuente"], c["fecha"], c["resumen"], c["categoria"],
                         c["competidor"], round(rel, 1), ahora().isoformat(timespec="seconds")))
    log.info("Empresa: %d hallazgos nuevos", len(candidatos))
    return len(candidatos)


def hallazgos(dias=7, limite=20, categoria=None, minimo=0.0):
    desde = (ahora() - timedelta(days=dias)).isoformat()
    sql = "SELECT * FROM emp_hallazgos WHERE creado >= ? AND relevancia >= ?"
    args = [desde, minimo]
    if categoria:
        sql += " AND categoria = ?"
        args.append(categoria)
    with closing(_con()) as con:
        filas = con.execute(sql + " ORDER BY relevancia DESC, id DESC LIMIT ?", args + [limite * 3]).fetchall()
    salida, vistos = [], []
    for f in filas:                                     # sin titulares casi iguales
        palabras = set(re.findall(r"\w{4,}", _sin_tildes(f["titulo"])))
        if any(len(palabras & v) >= max(3, len(palabras) * 0.6) for v in vistos):
            continue
        vistos.append(palabras)
        salida.append(f)
        if len(salida) >= limite:
            break
    return salida


def aviso_competidor():
    """Texto del aviso inmediato (un competidor seguido publicó algo muy relevante) o None. Máx. 1 por día."""
    if not ajustes().get("aviso_competidor", True):
        return None
    hoy = ahora().date().isoformat()
    with closing(_con()) as con, con:
        if con.execute("SELECT 1 FROM emp_hallazgos WHERE avisado = 1 AND substr(creado, 1, 10) = ?", (hoy,)).fetchone():
            return None
        filas = con.execute("SELECT h.*, c.nombre AS comp, c.web AS cweb, c.estado AS cestado FROM emp_hallazgos h "
                            "JOIN emp_competidores c ON c.id = h.competidor WHERE h.categoria = 'competidor' AND "
                            "h.avisado = 0 AND h.relevancia >= 7 AND h.creado >= ? ORDER BY h.relevancia DESC",
                            ((ahora() - timedelta(days=1)).isoformat(),)).fetchall()
        f = next((x for x in filas if x["cestado"] == "seguido" and
                  es_del_competidor({"nombre": x["comp"], "web": x["cweb"]}, x["titulo"], x["resumen"], x["enlace"])), None)
        if not f:
            return None
        con.execute("UPDATE emp_hallazgos SET avisado = 1 WHERE id = ?", (f["id"],))
    return ("🏁 " + f["comp"] + " sale en esta noticia:\n" + f["titulo"] + (" (" + f["fuente"] + ")" if f["fuente"] else "")
            + "\n" + (f["enlace"] or "") + "\n\nSi no tiene que ver, dígame «esa noticia no tiene que ver».")


def noticia_equivocada():
    """El usuario dice que el último aviso no era del competidor: se corrige y deja de contar."""
    with closing(_con()) as con, con:
        f = con.execute("SELECT * FROM emp_hallazgos WHERE avisado = 1 AND creado >= ? ORDER BY id DESC LIMIT 1",
                        ((ahora() - timedelta(days=3)).isoformat(),)).fetchone()
        if not f:
            return None
        con.execute("UPDATE emp_hallazgos SET categoria = 'oportunidad', competidor = NULL, relevancia = 0, avisado = 2 "
                    "WHERE id = ?", (f["id"],))
    return f["titulo"]


# --- informe semanal ------------------------------------------------------------------------------------------
ESQUEMA_INFORME = {"type": "object", "properties": {
    "resumen": {"type": "string"},
    "novedades": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {
        "n": {"type": "integer"}, "por_que_importa": {"type": "string"}}, "required": ["n", "por_que_importa"]}},
    "competencia": {"type": "string"},
    "oportunidades": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
    "acciones": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
    "borradores": {"type": "array", "maxItems": 2, "items": {"type": "object", "properties": {
        "red": {"type": "string"}, "tema": {"type": "string"}, "texto": {"type": "string"}},
        "required": ["red", "tema", "texto"]}}},
    "required": ["resumen", "novedades", "competencia", "oportunidades", "acciones", "borradores"]}

PIDE_INFORME = """Eres el asesor de una empresa NUEVA de inteligencia artificial en Ecuador. Ecuador es de los países que menos usa IA y casi solo la usan para investigar o hacer deberes: ahí está la oportunidad.

EL NEGOCIO: {negocio}
PÚBLICO AL INICIO: {publico}
SU PLAN (lo que el dueño dijo):
{plan}
REDES: {redes}
LO QUE EL DUEÑO YA PENSÓ (su segundo cerebro):
{notas}
COMPETIDORES QUE SIGUE: {competidores}

LO QUE SE ENCONTRÓ ESTA SEMANA (numerado):
{hallazgos}

Devuelve JSON, en español claro, concreto y SIN inventar datos que no estén arriba:
- resumen: 2 frases sobre lo más importante de la semana para este negocio.
- novedades: las 3 a 5 noticias más útiles (n = su número) y por qué le importan A ÉL (1 frase).
- competencia: 1-2 frases sobre los competidores (si no hay datos, dilo).
- oportunidades: 3 oportunidades concretas y realistas que encajen con SU PLAN (lo que ofrece, lo que sabe hacer, su meta a 3 meses y cómo quiere conseguir clientes); nada de lo que dijo que no quiere hacer.
- acciones: 3 acciones pequeñas para la próxima semana que quepan en sus horas disponibles (cada una en menos de 2 horas). Si en «Por descubrir» hay algo pendiente, al menos una acción debe ayudar a averiguarlo (por ejemplo, preguntas concretas para hacerle a un amigo).
- borradores: 1 para Instagram (texto del post con gancho, cuerpo corto y 5 hashtags) y 1 para TikTok (guion de 30-45 s: gancho de 3 s, 3 puntos y cierre con llamada a la acción). Tono cercano, ecuatoriano neutro, que eduque sobre usar IA de verdad en el trabajo."""


def _notas_negocio():
    try:
        from modulos.segundo_cerebro import segundo_cerebro as sc
        notas = sc.ultimas(6, "idea", "negocio") + sc.ultimas(4, "meta") + sc.ultimas(4, "decision", "negocio") \
            + sc.ultimas(4, "plan", "negocio")
        return "\n".join("- (" + sc.NOMBRE_TIPO.get(n["tipo"], n["tipo"]) + ") " + n["texto"][:200] for n in notas) or "(nada aún)"
    except Exception:
        return "(nada aún)"


def semana_actual(fecha=None):
    a, s, _ = (fecha or ahora()).isocalendar()
    return str(a) + "-W" + str(s).zfill(2)


def generar_informe(forzar=False):
    """Arma el informe con la IA local y lo guarda. Devuelve el dict o None (sin datos / ya hecho). Lanza Pausa."""
    from modulos.biblioteca import biblioteca
    semana = semana_actual()
    if not forzar:
        with closing(_con()) as con:
            if con.execute("SELECT 1 FROM emp_informes WHERE semana = ?", (semana,)).fetchone():
                return None
    lista = hallazgos(7, 18, minimo=1.5)
    if not lista:
        return None
    a = ajustes()
    texto_h = "\n".join(str(i + 1) + ". [" + CATEGORIA.get(h["categoria"], h["categoria"]) + "] " + h["titulo"][:160]
                        + (" — " + h["resumen"][:160] if h["resumen"] else "") for i, h in enumerate(lista))
    comps = ", ".join(c["nombre"] for c in competidores()) or "(todavía ninguno)"
    r = biblioteca._ia(PIDE_INFORME.format(negocio=a["negocio"], publico=a["publico_inicial"], plan=texto_plan(a),
                                          redes=", ".join(a["redes"]),
                                          notas=_notas_negocio(), competidores=comps, hallazgos=texto_h),
                       max_tokens=1800, esquema=ESQUEMA_INFORME)
    if not r or not r.get("resumen"):
        return None
    novedades = []
    for nv in r.get("novedades") or []:
        try:
            h = lista[int(nv.get("n", 0)) - 1]
        except (ValueError, IndexError, TypeError):
            continue
        novedades.append({"titulo": h["titulo"], "enlace": h["enlace"], "fuente": h["fuente"],
                          "categoria": h["categoria"], "por_que": str(nv.get("por_que_importa", ""))[:300]})
    datos = {"semana": semana, "fecha": ahora().strftime("%d/%m/%Y"), "resumen": str(r.get("resumen", ""))[:600],
             "novedades": novedades, "competencia": str(r.get("competencia", ""))[:500],
             "oportunidades": [str(x)[:300] for x in (r.get("oportunidades") or [])][:3],
             "acciones": [str(x)[:250] for x in (r.get("acciones") or [])][:3],
             "borradores": [{"red": str(b.get("red", ""))[:20], "tema": str(b.get("tema", ""))[:120],
                             "texto": str(b.get("texto", ""))[:2500]} for b in (r.get("borradores") or [])][:2],
             "competidores": [c["nombre"] for c in competidores()]}
    with closing(_con()) as con, con:
        con.execute("INSERT INTO emp_informes (semana, datos, creado) VALUES (?, ?, ?)",
                    (semana, json.dumps(datos, ensure_ascii=False), ahora().isoformat(timespec="seconds")))
        for b in datos["borradores"]:
            con.execute("INSERT INTO emp_borradores (red, tema, texto, origen, creado) VALUES (?, ?, ?, 'informe', ?)",
                        (b["red"], b["tema"], b["texto"], ahora().isoformat(timespec="seconds")))
    return datos


def ultimo_informe():
    with closing(_con()) as con:
        f = con.execute("SELECT datos FROM emp_informes ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(f["datos"]) if f else None


def texto_informe(d):
    """Para Telegram (texto plano, sin los borradores completos: van aparte)."""
    if not d:
        return "Todavía no hay informe. Escriba «informe de la empresa» para armarlo ahora."
    lineas = ["🚀 Su empresa de IA – semana " + d["fecha"], "", d["resumen"]]
    if d["novedades"]:
        lineas += ["", "📰 Lo que importa:"]
        for i, n in enumerate(d["novedades"], 1):
            lineas.append(str(i) + ". " + n["titulo"] + ("\n   → " + n["por_que"] if n["por_que"] else ""))
    lineas += ["", "🏁 Competencia: " + (d["competencia"] or "sin novedades.")]
    if d["oportunidades"]:
        lineas += ["", "💡 Oportunidades:"] + ["• " + x for x in d["oportunidades"]]
    if d["acciones"]:
        lineas += ["", "✅ Para esta semana:"] + ["☐ " + x for x in d["acciones"]]
    if d["borradores"]:
        lineas += ["", "✍️ Le dejé " + str(len(d["borradores"])) + " borradores (" + ", ".join(b["red"] for b in d["borradores"])
                   + "): se los mando abajo y están en el panel."]
    return "\n".join(lineas)


# --- a pedido -------------------------------------------------------------------------------------------------
ESQUEMA_POST = {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"]}


def borrador(tema, red="Instagram"):
    """Un borrador nuevo con la IA local, usando lo investigado sobre el tema. Lanza Pausa."""
    from modulos.biblioteca import biblioteca
    a = ajustes()
    relacionados = [h for h in hallazgos(14, 40) if set(re.findall(r"\w{4,}", _sin_tildes(tema)))
                    & set(re.findall(r"\w{4,}", _sin_tildes(h["titulo"] + " " + (h["resumen"] or ""))))][:5]
    contexto = "\n".join("- " + h["titulo"] for h in relacionados) or "(sin noticias relacionadas)"
    forma = ("guion de 30-45 s para TikTok: gancho de 3 s, 3 puntos cortos y cierre con llamada a la acción; indica entre "
             "corchetes qué se ve en pantalla" if "tiktok" in red.lower() else
             "post de Instagram: gancho en la primera línea, cuerpo corto en párrafos de 1-2 líneas, llamada a la acción "
             "y 5 hashtags")
    r = biblioteca._ia("Escribe un " + forma + " sobre: «" + tema + "». Es para la empresa: " + a["negocio"] + " Público: "
                       + a["publico_inicial"] + " Lo que ofrece: " + str((a.get("plan") or {}).get("servicios") or "")
                       + ". Tono cercano, ecuatoriano neutro, que eduque sobre usar IA de verdad en "
                       "el trabajo, sin exagerar ni inventar cifras. Noticias recientes que puede usar si vienen al caso:\n"
                       + contexto + "\n\nJSON: {\"texto\": \"...\"}", max_tokens=900, esquema=ESQUEMA_POST)
    texto = str(r.get("texto", "")).strip()
    if not texto:
        return None
    with closing(_con()) as con, con:
        con.execute("INSERT INTO emp_borradores (red, tema, texto, origen, creado) VALUES (?, ?, ?, 'pedido', ?)",
                    (red, tema[:120], texto[:3000], ahora().isoformat(timespec="seconds")))
    return texto


def borradores(n=6):
    with closing(_con()) as con:
        return con.execute("SELECT * FROM emp_borradores ORDER BY id DESC LIMIT ?", (n,)).fetchall()


def ideas():
    from modulos.biblioteca import biblioteca
    a = ajustes()
    lista = hallazgos(14, 12)
    r = biblioteca._ia("Eres asesor de una empresa nueva de IA en Ecuador. Negocio: " + a["negocio"] + " Público inicial: "
                       + a["publico_inicial"] + "\nSu plan:\n" + texto_plan(a) + "\nLo que el dueño ya pensó:\n" + _notas_negocio()
                       + "\nNoticias recientes:\n" + "\n".join("- " + h["titulo"][:150] for h in lista)
                       + "\n\nDa 5 ideas concretas de servicios o primeros pasos (una por línea, empezando con '• '), "
                       "que encajen con su plan (y nada de lo que no quiere hacer), sin inventar datos.", max_tokens=600)
    return "💡 Ideas para su empresa:\n\n" + str(r).strip()


def texto_novedades():
    lista = hallazgos(3, 8)
    if not lista:
        return ("Todavía no tengo novedades guardadas. El agente revisa cada 6 horas; si acaba de instalarse, "
                "pruebe en un rato.")
    return "🚀 Lo más relevante para su empresa (3 días):\n\n" + "\n".join(
        CATEGORIA.get(h["categoria"], "•").split(" ")[0] + " " + h["titulo"] + (" (" + h["fuente"] + ")" if h["fuente"] else "")
        for h in lista)


def texto_competidores():
    seguidos, propuestos = competidores("seguido"), competidores("propuesto")
    if not seguidos and not propuestos:
        return ("🏁 Todavía no sigue a ningún competidor. Escriba «busca competidores» y los busco en internet, o "
                "«agrega competidor Nombre (web)».")
    seguidos = sorted(seguidos, key=lambda c: _sin_tildes(c["nombre"]))
    lineas = ["🏁 Competidores que sigue:"] + ([str(i) + ". " + c["nombre"] + (" – " + c["descripcion"] if c["descripcion"] else "")
                                              + (" (" + c["web"] + ")" if c["web"] else "") for i, c in enumerate(seguidos, 1)]
                                             or ["(ninguno)"])
    if seguidos:
        lineas.append("\nPara quitar uno: «quita el competidor 2» o «elimina a " + seguidos[0]["nombre"] + "».")
    if propuestos:
        lineas += ["", "Propuestos (sin confirmar): " + ", ".join(c["nombre"] for c in propuestos)]
    return "\n".join(lineas)


# --- frases ---------------------------------------------------------------------------------------------------
_R = r"^\W*(?:jarvis\W+|oye\W+|por\s+favor\W+)*"
NOVEDADES = re.compile(_R + r"(?:qu[eé]\s+hay\s+de\s+nuevo\s+en\s+(?:la\s+)?(?:ia|inteligencia\s+artificial)|"
                       r"novedades\s+(?:de|en)\s+(?:la\s+)?(?:ia|inteligencia\s+artificial)|"
                       r"noticias\s+(?:de|sobre)\s+(?:la\s+)?(?:ia|inteligencia\s+artificial)(?:\s+para\s+(?:mi|la)\s+empresa)?|"
                       r"qu[eé]\s+(?:hay|encontraste)\s+para\s+(?:mi|la)\s+empresa)\W*$", re.I)
VER_COMP = re.compile(_R + r"(?:mis\s+)?competidores|(?:qui[eé]nes\s+son\s+)?mi\s+competencia|ver\s+competidores\W*$", re.I)
AGREGAR = re.compile(_R + r"(?:agrega|a[nñ]ade|sigue\s+a|seguir\s+a)\s+(?:al\s+|como\s+)?(?:competidor|competencia)\s*:?\s*"
                     r"(.+?)(?:\s*[\(,]\s*((?:https?://)?[\w.-]+\.[a-z]{2,}[^\s)]*)\)?)?\W*$", re.I)
_VERBO_QUITAR = (r"(?:quita(?:me)?|quitar|borra(?:me)?|borrar|elimina(?:me)?|eliminar|saca(?:me)?|sacar|remueve|descarta|"
                 r"olv[ií]da(?:te\s+de)?|deja\s+de\s+seguir(?:\s+a)?|ya\s+no\s+sigas(?:\s+a)?|no\s+sigas(?:\s+a)?|"
                 r"(?:ya\s+)?no\s+quiero\s+seguir(?:\s+a)?|para\s+de\s+seguir(?:\s+a)?)")
QUITAR = re.compile(_R + _VERBO_QUITAR + r"\s+(?:a\s+|al\s+)?(?:(?:la\s+|el\s+)?(?:empresa|competidor(?:a)?|competencia)\s+)?"
                    r"(.+?)\W*$", re.I)
NO_ES_COMP = re.compile(_R + r"(.+?)\s+(?:ya\s+)?no\s+(?:es|son)\s+(?:mi\s+|un\s+|una\s+)?(?:competidor(?:a|es)?|competencia)"
                        r"|^\W*no\s+me\s+interesa(?:\s+seguir\s+a)?\s+(.+?)\W*$", re.I)
SOBRE_COMP = re.compile(r"competidor|competencia|empresas?\s+que\s+sigo|de\s+la\s+lista|seguir\s+a|sigas", re.I)
EQUIVOCADA = re.compile(_R + r"(?:esa|la)\s+(?:noticia|nota)\s+(?:no\s+tiene\s+que\s+ver|no\s+es\s+(?:de|del|sobre)\s+(?:mi\s+|el\s+)?"
                        r"competidor\w*|est[aá]\s+mal|es\s+un\s+error|no\s+era)|^\W*(?:eso|ese\s+aviso)\s+no\s+tiene\s+que\s+ver"
                        r"|^\W*noticia\s+equivocada", re.I)
BUSCAR = re.compile(_R + r"(?:busca|encuentra|investiga)(?:me)?\s+(?:a\s+)?(?:mis\s+|los\s+|nuevos\s+)?competidores\W*$", re.I)
POST = re.compile(_R + r"(?:haz(?:me)?|escr[ií]be(?:me)?|cr[eé]a(?:me)?|dame|prep[aá]rame)\s+(?:un|una)\s+"
                  r"(post|publicaci[oó]n|guion|gui[oó]n|video|reel|tiktok)\s+(?:de\s+\w+\s+)?(?:sobre|de|acerca\s+de)\s+(.+?)"
                  r"(?:\s+para\s+(instagram|tiktok|ig))?\W*$", re.I)
IDEAS = re.compile(_R + r"(?:dame\s+)?ideas\s+(?:para|de)\s+(?:mi|la)\s+(?:empresa|negocio)(?:\s+de\s+ia)?\W*$", re.I)
VER_PLAN = re.compile(_R + r"(?:mi\s+plan\s+de\s+(?:la\s+)?empresa|plan\s+de\s+mi\s+empresa|qu[eé]\s+sabes\s+de\s+mi\s+empresa)\W*$", re.I)
ACTUALIZA_PLAN = re.compile(_R + r"(?:actualiza|cambia|editar?|modifica)\s+(?:mi\s+)?(?:el\s+)?plan\s+de\s+(?:la\s+|mi\s+)?empresa\W*$", re.I)
PLAN_TEXTO = re.compile(r"^\W*plan\s+de\s+(?:la\s+|mi\s+)?empresa\s*:\s*(.+)$", re.I | re.S)
INFORME = re.compile(_R + r"(?:informe|reporte|resumen)\s+(?:semanal\s+)?(?:de\s+)?(?:la|mi)\s+empresa\W*$", re.I)


def guardar_plan(cambios):
    """Mezcla los cambios en config/empresa.json → plan. Devuelve los campos cambiados."""
    a = ajustes()
    plan = dict(a.get("plan") or {})
    hechos = []
    for clave, valor in cambios.items():
        if clave == "por_descubrir":
            valor = [x.strip(" -•") for x in re.split(r"[;\n]", valor) if x.strip(" -•")]
        if plan.get(clave) != valor:
            plan[clave] = valor
            hechos.append(clave)
    a["plan"] = plan
    ARCHIVO.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
    return hechos


def leer_plan_texto(texto):
    """«Campo: valor» por línea (los nombres de CAMPOS_PLAN, sin importar tildes). {clave: valor}"""
    nombres = {_sin_tildes(n): c for c, n in CAMPOS_PLAN} | {_sin_tildes(c).replace("_", " "): c for c, _ in CAMPOS_PLAN}
    cambios = {}
    for linea in texto.splitlines():
        m = re.match(r"^\s*[-•]?\s*([^:]{3,40}):\s*(.*)$", linea)
        if not m:
            continue
        clave = nombres.get(_sin_tildes(m.group(1)).strip())
        if clave:
            valor = m.group(2).strip()
            cambios[clave] = "" if valor.lower() in ("(no lo sabe todavía)", "no se", "no sé") else valor
    return cambios


def procesar(texto):
    """Respuesta directa, o un dict {'tarea': ..., ...} para lo que usa la IA (lo hace telegram en segundo plano),
    o None si no es para este módulo."""
    t = (texto or "").strip()
    m = PLAN_TEXTO.match(t)
    if m:
        cambios = leer_plan_texto(m.group(1))
        if not cambios:
            return "No encontré campos. Escriba «actualiza mi plan de empresa» y le mando la plantilla."
        hechos = guardar_plan(cambios)
        nombres = dict(CAMPOS_PLAN)
        return ("✅ Plan actualizado: " + ", ".join(nombres[c].lower() for c in hechos) + ". El próximo informe ya lo usa."
                if hechos else "El plan ya estaba así; no cambié nada.")
    if not t or len(t) > 300:
        return None
    if VER_PLAN.match(t):
        return "🚀 Lo que sé de su empresa:\n\n" + texto_plan() + "\n\nPara cambiarlo: «actualiza mi plan de empresa»."
    if ACTUALIZA_PLAN.match(t):
        return ("Copie este mensaje, cambie lo que quiera (puede borrar las líneas que no cambian) y mándemelo:\n\n"
                "plan de empresa:\n" + texto_plan().replace("- ", ""))
    if NOVEDADES.match(t):
        return texto_novedades()
    m = AGREGAR.match(t)
    if m:
        cid, nuevo = agregar_competidor(m.group(1), m.group(2) or "")
        if not cid:
            return "¿Cómo se llama el competidor? Ej.: «agrega competidor Acme IA (acme.ec)»."
        return ("🏁 Listo: sigo a " + m.group(1).strip() + ". Revisaré sus noticias cada 6 h." if nuevo
                else "Ya lo estaba siguiendo.")
    if BUSCAR.match(t):
        return {"tarea": "descubrir"}
    if VER_COMP.match(t):
        return texto_competidores()
    if EQUIVOCADA.match(t):
        titulo = noticia_equivocada()
        return ("👍 Entendido: «" + titulo[:90] + "» ya no cuenta como noticia de su competidor." if titulo
                else "No tengo avisos recientes de competidores para corregir.")
    m = QUITAR.match(t) or NO_ES_COMP.match(t)
    habla_de_comp = bool(SOBRE_COMP.search(t) or NO_ES_COMP.match(t))
    if m and (habla_de_comp or buscar_competidor(next(g for g in m.groups() if g), estricto=True)):
        texto_nombre = next(g for g in m.groups() if g)
        c = buscar_competidor(texto_nombre, estricto=not habla_de_comp)
        if isinstance(c, list):
            return ("Hay varios parecidos: " + ", ".join(x["nombre"] for x in c) + ". ¿Cuál quito? Dígame el nombre completo "
                    "o el número de «mis competidores».")
        if c:
            cambiar_competidor(c["id"], "descartado")
            arreglados = revisar_competidores()
            return ("🗑️ Listo: ya no sigo a " + c["nombre"] + "." + (" Saqué " + str(arreglados) + " noticias suyas del panel."
                                                                       if arreglados else ""))
        if SOBRE_COMP.search(t) or NO_ES_COMP.match(t):
            return ("No encuentro «" + _limpia_nombre(texto_nombre) + "» entre sus competidores.\n\n" + texto_competidores())
    m = POST.match(t)
    if m:
        red = "TikTok" if re.search(r"tiktok|video|reel|gui", (m.group(3) or m.group(1)), re.I) else "Instagram"
        return {"tarea": "borrador", "tema": m.group(2).strip(), "red": red}
    if IDEAS.match(t):
        return {"tarea": "ideas"}
    if INFORME.match(t):
        return {"tarea": "informe"}
    return None


def datos_panel():
    return {"informe": ultimo_informe(),
            "hallazgos": [{"titulo": h["titulo"], "enlace": h["enlace"], "fuente": h["fuente"], "categoria":
                           CATEGORIA.get(h["categoria"], h["categoria"]), "relevancia": h["relevancia"],
                           "fecha": (h["creado"] or "")[:10]} for h in hallazgos(7, 15, minimo=2)],
            "competidores": [{"id": c["id"], "nombre": c["nombre"], "web": c["web"], "descripcion": c["descripcion"],
                              "estado": c["estado"]} for c in competidores(None) if c["estado"] != "descartado"],
            "borradores": [{"red": b["red"], "tema": b["tema"], "texto": b["texto"], "fecha": b["creado"][:10]}
                           for b in borradores(6)],
            "informe_cuando": ajustes()["informe"],
            "plan": [{"campo": n, "valor": ("; ".join(v) if isinstance(v, list) else str(v or ""))}
                     for c, n in CAMPOS_PLAN for v in [(ajustes().get("plan") or {}).get(c)]]}
