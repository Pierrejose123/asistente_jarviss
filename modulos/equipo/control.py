"""Control de calidad EN CÓDIGO para los entregables del equipo (v3, 13-11). No usa IA.

Nació de la primera propuesta para el amigo abogado, que:
  - inventó experiencias («Hablé con varios profesionales…»), prometió «entrenado con las leyes ecuatorianas»,
  - dejó colada una instrucción del pedido («Deja abierta la puerta a cualquier otra cosa que me pida»),
  - preguntó por el «presupuesto» de una prueba «gratuita» y por el nombre de la marca del dueño,
  - firmó «Tu amigo en IA», citó fuentes que no decían eso y no mencionó la demo que ya existía.

revisar(texto, ...) → lista de problemas (para que el redactor corrija una vez).
limpiar(texto, ...) → texto arreglado a la fuerza (lo que la IA no corrigió se quita o se completa).
"""
import re
import unicodedata


def sin_tildes(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _palabras(t):
    return re.findall(r"[a-zñ0-9]+", sin_tildes(t))


# --- experiencias o promesas inventadas ------------------------------------------------------------------------
INVENTOS = [
    (r"\b(?:habl[eé]|hablamos|convers[eé]|conversamos|entrevist[eé]|entrevistamos|encuest[eé]|encuestamos|"
     r"me\s+reun[ií]|nos\s+reunimos|consult[eé]|consultamos)\s+(?:con|a)\b", "dice que el dueño habló o se reunió con gente"),
    (r"\b(?:revisamos|analizamos|estudiamos)\s+(?:varios|muchos|cientos|decenas|expedientes|casos\s+(?:reales|de)|el\s+contexto|el\s+sector|la\s+situaci[oó]n)\b",
     "dice que el dueño revisó o analizó casos que no revisó"),
    (r"\bnuestros\s+(?:clientes|casos\s+de\s+[eé]xito)\b|\bhemos\s+(?:ayudado|trabajado\s+con|implementado)\b|"
     r"\ba[nñ]os\s+de\s+experiencia\b|\bcasos\s+de\s+[eé]xito\s+(?:con|en)\b", "inventa clientes o experiencia previa"),
    (r"\b(?:entrenad[oa]s?|capacitad[oa]s?|especializad[oa]s?)\b[^.\n]{0,60}\b(?:leyes|legislaci[oó]n|normativa|c[oó]digo)\b|"
     r"\bconoce\s+(?:toda\s+)?la\s+(?:legislaci[oó]n|ley|normativa)\b", "promete una IA entrenada con las leyes (no existe)"),
    (r"\bnunca\s+se\s+equivoca\b|\bgarantiza(?:mos)?\b|\b100\s*%\s+(?:seguro|exacto|preciso)\b", "promete cosas imposibles"),
    (r"\bcomo\s+sabes,?\s+(?:estamos|ya\s+estamos)\s+trabajando\b", "supone un proyecto conjunto que no existe"),
]


def inventos(texto):
    """[(frase, motivo)] con las frases que inventan algo."""
    salida = []
    for linea in texto.splitlines():
        for frase in _frases(linea):
            for patron, motivo in INVENTOS:
                if re.search(patron, frase, re.I):
                    salida.append((frase.strip(), motivo))
                    break
    return salida


_CORTE = re.compile(r"[.!?](?:\*\*|__|\*|_|»|\"|\))*(?=\s+[¿¡\"«(*_A-ZÁÉÍÓÚÑ0-9])")


_ABREV = re.compile(r"(?:\b(?:art|arts|ej|sr|sra|dr|dra|lic|ing|pag|p[aá]g|num|n[uú]m|no|etc|vs|aprox|av|ec|s\.a)|\b[a-z])$", re.I)


def _frases(linea):
    """Frases de una línea; las marcas de cierre (** » ") se quedan con su frase. No corta en «Art. 47» ni «Ej.»."""
    partes, inicio = [], 0
    for m in _CORTE.finditer(linea):
        if linea[m.start()] == "." and _ABREV.search(linea[inicio:m.start()]):
            continue
        partes.append(linea[inicio:m.end()])
        inicio = m.end()
    partes.append(linea[inicio:])
    return [p.strip() for p in partes if p.strip()]


# --- instrucciones coladas ------------------------------------------------------------------------------------
def coladas(texto, instrucciones, n=6):
    """Frases del resultado que copian 6+ palabras seguidas del pedido o de las instrucciones internas."""
    gramas = set()
    for ins in instrucciones:
        p = _palabras(ins)
        gramas.update(tuple(p[i:i + n]) for i in range(len(p) - n + 1))
    salida = []
    for linea in texto.splitlines():
        if linea.startswith("#"):
            continue
        for frase in _frases(linea):
            p = _palabras(frase)
            if any(tuple(p[i:i + n]) in gramas for i in range(len(p) - n + 1)):
                salida.append(frase.strip())
    return salida


# --- preguntas que no van -------------------------------------------------------------------------------------
GRATIS = re.compile(r"gratu[ií]t|gratis|sin\s+costo|sin\s+pagar|piloto\s+libre", re.I)
DINERO = re.compile(r"presupuesto|invertir|inversi[oó]n|pagar|cu[aá]nto\s+(?:cuesta|costar[ií]a|dinero)|precio", re.I)
MARCA = re.compile(r"nombre\s+(?:de\s+)?(?:la\s+|tu\s+|nuestra\s+|una\s+)?marca|c[oó]mo\s+(?:llamar|se\s+llam)\w*\s+(?:el\s+)?(?:proyecto|marca)", re.I)


def preguntas_malas(texto, tipo, gratis_en_todo):
    """Líneas que preguntan por dinero en algo gratis, o por la marca del dueño (en propuestas)."""
    salida = []
    for linea in texto.splitlines():
        if "?" not in linea and not re.match(r"\s*[-*\d]", linea):
            continue
        if DINERO.search(linea) and (GRATIS.search(linea) or gratis_en_todo) and "?" in linea:
            salida.append((linea, "pregunta por presupuesto en algo que es gratis"))
        elif tipo == "propuesta" and MARCA.search(linea) and "?" in linea:
            salida.append((linea, "le pregunta al cliente el nombre de la marca del dueño"))
    return salida


# --- citas ----------------------------------------------------------------------------------------------------
GENERICAS = set("""inteligencia artificial automatizacion automatizar automatica automatico herramienta herramientas
asistente asistentes tiempo tiempos real reales centro centros sistema sistemas solucion soluciones empresa empresas
negocio negocios trabajo trabajos tareas tarea proceso procesos ayuda ayudar puede pueden permite permiten forma
gestion gestionar mejor mejorar mayor manera datos informacion digital digitales servicio servicios cliente clientes
usuarios usuario nuevo nueva nuevos nuevas tecnologia tecnologias chatbot chatbots modelo modelos agente agentes
traves sobre segun entre desde hasta donde cuando mientras tambien ademas pueden puedes podemos parte todos todas
ecuador ecuatoriano ecuatoriana ecuatorianos latinoamerica america mundo general generales""".split())


def _distintivas(t):
    return {w[:5] for w in _palabras(t) if len(w) >= 5 and w not in GENERICAS}


def citas_flojas(texto, fuentes):
    """[(frase, n)]: frases que citan [n] sin compartir al menos 2 palabras distintivas con esa fuente."""
    por_n = {f["n"]: f for f in fuentes}
    salida = []
    for linea in texto.split("\n## Fuentes")[0].splitlines():
        for frase in _frases(linea):
            for m in re.finditer(r"\[(\d+)\]", frase):
                n = int(m.group(1))
                f = por_n.get(n)
                if not f:
                    salida.append((frase, n))
                    continue
                base = " ".join([f.get("titulo", ""), f.get("extracto", ""), f.get("hallazgo", "")])
                propias = _distintivas(frase)
                if len(propias & _distintivas(base)) < min(2, max(1, len(propias))):
                    salida.append((frase, n))
    return salida


def quitar_citas(texto, flojas):
    for frase, n in flojas:
        nueva = re.sub(r"\s?\[" + str(n) + r"\]", "", frase)
        texto = texto.replace(frase, nueva, 1)
    return texto


def renumerar_fuentes(texto, fuentes):
    """Deja solo las fuentes citadas, numeradas 1..k, y cambia los [n] del texto."""
    citadas = []
    for m in re.finditer(r"\[(\d+)\]", texto):
        n = int(m.group(1))
        if n not in citadas and any(f["n"] == n for f in fuentes):
            citadas.append(n)
    mapa = {n: i for i, n in enumerate(citadas, 1)}
    texto = re.sub(r"\[(\d+)\]", lambda m: "[" + str(mapa[int(m.group(1))]) + "]" if int(m.group(1)) in mapa else "", texto)
    texto = re.sub(r" +([.,;:])", r"\1", texto)
    nuevas = [{**f, "n": mapa[f["n"]]} for f in fuentes if f["n"] in mapa]
    return texto, sorted(nuevas, key=lambda f: f["n"])


# --- quitar frases y líneas -----------------------------------------------------------------------------------
_VINETA = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def quitar_frases(texto, frases):
    """Quita esas frases. Si en una viñeta cae la primera frase (la del título en negrita), se va toda la viñeta."""
    frases = {_sin_vineta(f) for f in frases if f and f.strip()}
    if not frases:
        return texto
    salida = []
    for linea in texto.splitlines():
        partes = _frases(linea)
        quedan = [p for p in partes if _sin_vineta(p) not in frases]
        if len(quedan) == len(partes):
            salida.append(linea)
            continue
        es_vineta = bool(_VINETA.match(linea))
        if es_vineta and partes and _sin_vineta(partes[0]) in frases:
            continue
        resto = " ".join(quedan).strip()
        solo = re.sub(r"[\s*_>#\-•]|\d+[.)]", "", resto)
        if len(solo) < 12 or len(_palabras(resto)) < 4:
            continue
        if es_vineta and not _VINETA.match(resto):
            resto = _VINETA.match(linea).group(0) + resto
        salida.append(resto)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(salida)).strip()


def _sin_vineta(f):
    return _VINETA.sub("", f.strip()).strip()


def quitar_lineas(texto, lineas):
    fuera = {l for l in lineas}
    return re.sub(r"\n{3,}", "\n\n", "\n".join(l for l in texto.splitlines() if l not in fuera)).strip()


# --- firma, vocabulario, secciones obligatorias ---------------------------------------------------------------
FIRMA_MALA = re.compile(r"^\s*\**\s*(?:tu\s+amig[oa]\b.*|\[?\s*tu\s+nombre\s*\]?|\[?\s*nombre\s*\]?|el\s+equipo\b.*|"
                        r"tu\s+socio\b.*|tu\s+aliado\b.*|equipo\s+de\s+ia\b.*|\[firma\])\s*\**\s*$", re.I)
SALUDO = re.compile(r"^\s*\**\s*(?:saludos(?:\s+cordiales)?|un\s+abrazo|atentamente|quedo\s+atento|abrazo|gracias)\b.*$", re.I)


def firmar(texto, nombre):
    if not nombre or nombre == "Usuario":
        return texto
    lineas = texto.splitlines()
    cola = range(max(0, len(lineas) - 8), len(lineas))
    for i in cola:
        if FIRMA_MALA.match(lineas[i]):
            lineas[i] = "**" + nombre + "**"
            return "\n".join(lineas)
    if any(nombre.lower() in lineas[i].lower() for i in cola):
        return texto
    for i in reversed(list(cola)):
        if SALUDO.match(lineas[i]):
            lineas.insert(i + 1, "\n**" + nombre + "**")
            return "\n".join(lineas)
    return texto


def vocabulario(texto, cambios):
    for viejo, nuevo in (cambios or {}).items():
        texto = re.sub(r"(?i)\b" + re.escape(viejo) + r"\b",
                       lambda m: nuevo[0].upper() + nuevo[1:] if m.group(0)[0].isupper() else nuevo, texto)
    return texto


def vinetas_prohibidas(texto, terminos):
    if not terminos:
        return []
    pats = [re.compile(re.escape(sin_tildes(t)), re.I) for t in terminos]
    return [l for l in texto.splitlines()                      # las preguntas al cliente sí pueden nombrarlo
            if _VINETA.match(l) and "?" not in l and any(p.search(sin_tildes(l)) for p in pats)]


def menciona_hecho(texto, cliente):
    """Cuántas cosas de la ficha «hecho» del cliente nombra el texto."""
    s = sin_tildes(texto)
    return sum(1 for h in cliente.get("hecho") or [] if sin_tildes(h.get("clave") or h["texto"].split()[0]) in s)


def seccion_hecho(cliente):
    lineas = ["## Lo que ya funciona (demo)",
              cliente.get("intro_hecho") or "Esto no es una idea: ya armé una demo que puedes probar conmigo. Hoy hace:"]
    lineas += ["- " + h["texto"] for h in cliente.get("hecho") or []]
    if cliente.get("se_puede"):
        lineas += ["", "Si te sirve, el siguiente paso sería:"] + ["- " + x for x in cliente["se_puede"]]
    return "\n".join(lineas)


def tiene_confidencialidad(texto):
    return bool(re.search(r"confidencial|privacidad|protecci[oó]n\s+de\s+datos|datos\s+personales", texto, re.I))


def insertar_antes_del_cierre(texto, seccion):
    """Pone la sección antes del cierre (saludo/firma o último ## de cierre) o al final."""
    lineas = texto.splitlines()
    for i, l in enumerate(lineas):
        if re.match(r"^#{2,3}\s+(?:cierre|despedida|pr[oó]ximos\s+pasos|siguiente\s+paso)", l, re.I):
            return "\n".join(lineas[:i] + [seccion, ""] + lineas[i:])
    for i in range(len(lineas) - 1, max(-1, len(lineas) - 10), -1):
        if SALUDO.match(lineas[i]):
            return "\n".join(lineas[:i] + [seccion, ""] + lineas[i:])
    return texto.rstrip() + "\n\n" + seccion


def titulo_corto(resultado, objetivo, n=80):
    """Título del archivo: el primer ## del texto si está arriba; si no, el objetivo recortado."""
    for l in resultado.splitlines()[:3]:
        if l.startswith("## ") and len(_palabras(l)) >= 4:      # un título de verdad, no «## Necesidades»
            return l[3:].strip(" #*"), True
    t = re.sub(r"\s+", " ", objetivo or "Trabajo del equipo").strip().rstrip(".")
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return t, False
