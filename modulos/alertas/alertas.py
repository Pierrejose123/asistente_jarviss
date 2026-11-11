"""Fase 2, paso 5: alertas de precio, reglas propias, diario de decisiones y calendario de resultados.

ALERTAS (todo se calcula en código; la IA no interviene):
  "avísame si V sube 35 % desde mi compra"      -> referencia = su precio medio de compra (XTB)
  "avísame si NVDA baja de 120" / "si META supera 700" / "si NVDA rompe la resistencia de 140"
  "avísame si AMZN cae 5 % en un día"           -> se rearma cada día
  "avísame si GOOG cae 15 % desde su máximo"    -> máximo de 52 semanas
  "avísame si JPM toca su máximo de 52 semanas" / "... su mínimo ..."
  "avísame si KOF sube 10 %"                    -> desde el precio de hoy
  "mis alertas" · "borra la alerta 3" · /alertas · /alerta NVDA < 120
  Se revisan cada 10 min en horario de la bolsa de EE. UU. Aviso por Telegram y Windows, una vez.

DIARIO DE DECISIONES (cuenta real):
  "decisión: compro V porque rompió la resistencia de 340"   (también vendo / mantengo / reduzco)
  Se guarda el precio del momento y el S&P 500. A 1, 3 y 6 meses le muestra cómo le fue frente al
  S&P y le pregunta si su motivo se cumplió. Si en un informe nuevo de XTB aparece una compra sin
  decisión anotada, le pregunta por qué compró.  "mi diario" · /diario

CALENDARIO: próximos resultados trimestrales y fechas de dividendo de sus acciones (Yahoo Finance).
  Aviso 2 días antes y el mismo día por la mañana. /calendario

El asistente INFORMA: no opera ni decide.
"""
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modulos.comun.base import RAIZ, ahora, registro  # noqa: E402

log = registro("alertas")
BD = RAIZ / "datos" / "asistente.db"
NUM = r"(\d+(?:[.,]\d+)?)"
REVISIONES = (30, 90, 180)                  # días: 1, 3 y 6 meses
_listo = []


# ------------------------------------------------------------------ base ---
def _con():
    con = sqlite3.connect(BD, timeout=30)
    con.row_factory = sqlite3.Row
    if not _listo:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS alertas_precio (id INTEGER PRIMARY KEY, ticker TEXT, tipo TEXT, direccion TEXT,
                valor REAL, referencia REAL, texto TEXT, creada TEXT, estado TEXT DEFAULT 'activa', disparada TEXT,
                ultimo_dia TEXT);
            CREATE TABLE IF NOT EXISTS decisiones (id INTEGER PRIMARY KEY, fecha TEXT, ticker TEXT, accion TEXT,
                precio REAL, sp500 REAL, motivo TEXT, revisadas TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS decisiones_lotes (clave TEXT PRIMARY KEY, visto TEXT);
            CREATE TABLE IF NOT EXISTS calendario_avisos (clave TEXT PRIMARY KEY, enviado TEXT);
        """)
        _listo.append(True)
    return con


def _num(t):
    return float(t.replace(",", "."))


def _b(x):
    if x is None:
        return "-"
    return ("%.2f" % x).rstrip("0").rstrip(".").replace(".", ",")


def _pct(x):
    return ("+" if x > 0 else "") + ("%.1f" % x).replace(".", ",") + " %"


def _sin_tildes(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


# ------------------------------------------------------------------ precios ---
def cotizacion(ticker):
    """{'precio', 'previo', 'max52', 'min52'} desde Yahoo Finance, o None."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
    except Exception as exc:
        log.info("yfinance no disponible: %s", exc)
        return None

    def dato(nombre):
        try:                                   # fast_info.get() solo acepta camelCase: se leen los atributos
            v = getattr(t.fast_info, nombre)
            return float(v) if v else None
        except Exception:
            return None

    precio = dato("last_price")
    if precio:
        return {"precio": precio, "previo": dato("previous_close") or precio,
                "max52": dato("year_high"), "min52": dato("year_low")}
    try:                                       # plan B: historial de un año
        h = t.history(period="1y", interval="1d")
        if len(h):
            cierres = h["Close"].dropna()
            return {"precio": float(cierres.iloc[-1]), "previo": float(cierres.iloc[-2]) if len(cierres) > 1 else float(cierres.iloc[-1]),
                    "max52": float(h["High"].max()), "min52": float(h["Low"].min())}
    except Exception as exc:
        log.info("Sin cotización de %s: %s", ticker, exc)
    return None


def precio_compra(ticker):
    """Precio medio de compra de su portafolio de XTB (en la moneda de la acción), o None."""
    try:
        from modulos.portafolio import portafolio
        for p in portafolio.calcular()["posiciones"]:
            if p["yahoo"].upper() == ticker.upper():
                return float(p["promedio"])
    except Exception as exc:
        log.info("Sin precio de compra de %s: %s", ticker, exc)
    return None


def mercado_abierto():
    try:
        from modulos.cava import cava
        return cava.mercado_abierto()
    except Exception:
        return False


# ------------------------------------------------------------------ entender la regla ---
PIDE_ALERTA = re.compile(r"^\W*(?:por\s+favor\W+)?(?:av[ií]s(?:a|ame|eme|ar)|al[eé]rt(?:a|ame)|notif[ií]ca(?:me)?|"
                         r"dime|me\s+avis(?:a|as|ar[ií]as)|quiero\s+(?:saber|que\s+me\s+avises)|pon(?:me)?\s+una\s+alerta|"
                         r"crea\s+una\s+alerta|alerta)\b.*?\b(?:si|cuando|en\s+cuanto|apenas)\b", re.I | re.S)
ARRIBA = r"\b(?:sub[ea]\w*|supera\w*|pasa\w*\s+(?:de|los|las|el|la)|rompe\w*|llega\w*\s+a|alcanza\w*|por\s+encima|encima|arriba|mayor|gana\w*)\b|>"
ABAJO = r"\b(?:baj[ae]\w*|ca[ei]\w*|cay\w*|perfora\w*|pierde\w*|por\s+debajo|debajo|menor|retrocede\w*|desplom\w*)\b|<"


NO_SON = {"el", "la", "los", "las", "mi", "mis", "su", "sus", "una", "un", "baja", "sube", "todo", "toda", "todos", "algo",
          "esto", "eso", "esa", "nada", "alguna", "algun", "bolsa", "precio", "dolar", "oro", "cae", "tengo", "hay", "se"}


def _ticker(texto):
    """Ticker por símbolo, por nombre de empresa o por una palabra corta tras 'si/cuando'."""
    acciones = {}
    try:
        from modulos.noticias import noticias
        acciones = noticias.mis_acciones()
    except Exception:
        pass
    bajo = _sin_tildes(texto)
    for t, nombre in acciones.items():
        if re.search(r"(?<![\w$])\$?" + re.escape(t) + r"(?!\w)", texto) or \
                (nombre and nombre != t and re.search(r"(?<!\w)" + re.escape(_sin_tildes(nombre.split()[0])) + r"(?!\w)", bajo)):
            return t
    try:
        from modulos.cava import cava
        encontrados = [t for t in cava.tickers_en(texto) if not t.startswith("^")]
        if encontrados:
            return encontrados[0]
    except Exception:
        pass
    # Ticker desconocido: en mayúsculas ("TSLA") o seguido de un verbo de precio ("si tsla baja de 200")
    m = re.search(r"\b(?:si|cuando|apenas)\s+(?:la\s+acci[oó]n\s+de\s+|el\s+precio\s+de\s+)?\$?([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?)\b"
                  r"(\s+(?:sub|baj|ca[eiy]|super|romp|perfor|lleg|toc|pas|alcanz|pierd|gan)\w*)?", texto, re.I)
    if m and _sin_tildes(m.group(1)) not in NO_SON \
            and (m.group(1).isupper() or m.group(2)):
        return m.group(1).upper()
    return None


def interpretar(texto):
    """dict de la alerta o texto pidiendo lo que falta."""
    ticker = _ticker(texto)
    if not ticker:
        return "¿De qué acción es la alerta? Ejemplo: «avísame si V sube 35 % desde mi compra»."
    bajo = _sin_tildes(texto)
    sin_ticker = re.sub(r"(?<!\w)" + re.escape(ticker) + r"(?!\w)", " ", texto, flags=re.I)
    pct = re.search(NUM + r"\s*(?:%|por\s*ciento)", sin_ticker, re.I)
    nivel = re.search(r"(?<![\w.,])\$?" + NUM + r"(?!\s*(?:%|por\s*ciento|d[ií]as?|semanas?|meses?))", sin_ticker, re.I)
    arriba, abajo = re.search(ARRIBA, bajo), re.search(ABAJO, bajo)
    direccion = "arriba" if arriba and (not abajo or arriba.start() < abajo.start()) else ("abajo" if abajo else None)

    if re.search(r"m[aá]ximo\w*\s+(?:de\s+)?(?:52\s+semanas|del\s+a[nñ]o|anual)|nuevo\s+m[aá]ximo|m[aá]ximos?\s+anual", bajo) and not pct:
        return {"ticker": ticker, "tipo": "max52", "direccion": "arriba", "valor": None, "referencia": None}
    if re.search(r"m[ií]nimo\w*\s+(?:de\s+)?(?:52\s+semanas|del\s+a[nñ]o|anual)|nuevo\s+m[ií]nimo", bajo) and not pct:
        return {"ticker": ticker, "tipo": "min52", "direccion": "abajo", "valor": None, "referencia": None}
    if pct:
        valor = _num(pct.group(1))
        if not direccion:
            return "¿Sube o baja? Ejemplo: «avísame si " + ticker + " sube " + _b(valor) + " %»."
        if re.search(r"desde\s+(?:mi|la|su)\s+compra|desde\s+que\s+(?:la\s+|lo\s+)?compr|(?:mi|su)\s+precio\s+de\s+compra|"
                     r"de\s+(?:mi|lo\s+que)\s+(?:pagu|compr)|sobre\s+(?:mi|su)\s+compra", bajo):
            ref = precio_compra(ticker)
            if not ref:
                return ("No encuentro " + ticker + " en su portafolio de XTB para saber su precio de compra. "
                        "Dígame el precio: «avísame si " + ticker + " llega a 459».")
            return {"ticker": ticker, "tipo": "compra", "direccion": direccion, "valor": valor, "referencia": ref}
        if re.search(r"desde\s+(?:su|el)\s+m[aá]ximo|del\s+m[aá]ximo", bajo):
            return {"ticker": ticker, "tipo": "desde_max", "direccion": "abajo", "valor": valor, "referencia": None}
        if re.search(r"en\s+un\s+(?:solo\s+)?d[ií]a|en\s+el\s+d[ií]a|en\s+una\s+sesi[oó]n|de\s+golpe|diario|cada\s+d[ií]a|hoy", bajo):
            return {"ticker": ticker, "tipo": "dia", "direccion": direccion, "valor": valor, "referencia": None}
        c = cotizacion(ticker)
        if not c:
            return "No pude ver el precio de " + ticker + " ahora para tomarlo como punto de partida. Inténtelo en un rato."
        return {"ticker": ticker, "tipo": "desde_hoy", "direccion": direccion, "valor": valor, "referencia": c["precio"]}
    if nivel:
        valor = _num(nivel.group(1))
        if not direccion:
            c = cotizacion(ticker)
            direccion = ("arriba" if c and valor > c["precio"] else "abajo") if c else None
            if not direccion:
                return "¿Le aviso cuando suba o cuando baje de " + _b(valor) + "?"
        return {"ticker": ticker, "tipo": "nivel", "direccion": direccion, "valor": valor, "referencia": None}
    return ("¿A qué precio o porcentaje? Ejemplos: «avísame si " + ticker + " baja de 120», «si " + ticker +
            " sube 10 %», «si " + ticker + " cae 5 % en un día».")


def objetivo(a, c=None):
    """Precio que dispara la alerta (o None si depende del día)."""
    signo = 1 if a["direccion"] == "arriba" else -1
    if a["tipo"] == "nivel":
        return a["valor"]
    if a["tipo"] in ("compra", "desde_hoy"):
        return a["referencia"] * (1 + signo * a["valor"] / 100)
    if c and a["tipo"] == "dia":
        return c["previo"] * (1 + signo * a["valor"] / 100)
    if c and a["tipo"] == "desde_max" and c.get("max52"):
        return c["max52"] * (1 - a["valor"] / 100)
    if c and a["tipo"] == "max52":
        return c.get("max52")
    if c and a["tipo"] == "min52":
        return c.get("min52")
    return None


def describir(a):
    flecha = "sube" if a["direccion"] == "arriba" else "baja"
    t = a["ticker"] + " "
    if a["tipo"] == "nivel":
        return t + ("supera " if a["direccion"] == "arriba" else "baja de ") + _b(a["valor"])
    if a["tipo"] == "compra":
        return t + flecha + " " + _b(a["valor"]) + " % desde su compra (" + _b(a["referencia"]) + " → " + _b(objetivo(a)) + ")"
    if a["tipo"] == "desde_hoy":
        return t + flecha + " " + _b(a["valor"]) + " % desde " + _b(a["referencia"]) + " (→ " + _b(objetivo(a)) + ")"
    if a["tipo"] == "dia":
        return t + flecha + " " + _b(a["valor"]) + " % en un día"
    if a["tipo"] == "desde_max":
        return t + "cae " + _b(a["valor"]) + " % desde su máximo de 52 semanas"
    return t + ("toca su máximo de 52 semanas" if a["tipo"] == "max52" else "toca su mínimo de 52 semanas")


def crear(datos, texto=""):
    with _con() as con:
        cur = con.execute("INSERT INTO alertas_precio (ticker, tipo, direccion, valor, referencia, texto, creada) "
                          "VALUES (?,?,?,?,?,?,?)", (datos["ticker"], datos["tipo"], datos["direccion"], datos["valor"],
                                                     datos["referencia"], texto[:200], ahora().isoformat(timespec="minutes")))
        return cur.lastrowid


def obtener(aid):
    with _con() as con:
        return con.execute("SELECT * FROM alertas_precio WHERE id=?", (aid,)).fetchone()


def activas():
    with _con() as con:
        return con.execute("SELECT * FROM alertas_precio WHERE estado='activa' ORDER BY id").fetchall()


def borrar(aid):
    with _con() as con:
        return con.execute("UPDATE alertas_precio SET estado='borrada' WHERE id=? AND estado!='borrada'", (aid,)).rowcount > 0


def ya_se_cumple(datos):
    """Texto si la condición ya se cumple hoy (no tiene sentido crearla), o None."""
    c = cotizacion(datos["ticker"])
    obj = objetivo(datos, c)
    if not c or obj is None:
        return None
    if (c["precio"] >= obj) if datos["direccion"] == "arriba" else (c["precio"] <= obj):
        t = datos["ticker"]
        texto = "Eso ya se cumple, señor: " + t + " está en " + _b(c["precio"])
        if datos.get("referencia"):
            cambio = (c["precio"] / datos["referencia"] - 1) * 100
            texto += " (" + _pct(cambio) + (" desde su compra a " if datos["tipo"] == "compra" else " desde ") + _b(datos["referencia"]) + ")"
            siguiente = int(abs(cambio) // 5 * 5 + 5)
            ejemplo = ("avísame si " + t + (" sube " if datos["direccion"] == "arriba" else " baja ") + str(siguiente) + " %" +
                       (" desde mi compra" if datos["tipo"] == "compra" else ""))
        else:
            ejemplo = "avísame si " + t + (" supera " if datos["direccion"] == "arriba" else " baja de ") + _b(round(c["precio"] * (1.05 if datos["direccion"] == "arriba" else 0.95)))
        return texto + ".\nNo la creé porque sonaría al instante. ¿Otro objetivo? Por ejemplo: «" + ejemplo + "»."
    return None


def texto_nueva(aid):
    a = obtener(aid)
    c = cotizacion(a["ticker"])
    lineas = ["🔔 Alerta #" + str(aid) + " creada: " + describir(a) + "."]
    obj = objetivo(a, c)
    if c and obj:
        falta = (obj / c["precio"] - 1) * 100
        lineas.append("Ahora está en " + _b(c["precio"]) + ": le falta " + _pct(falta) + ".")
    elif c:
        lineas.append("Ahora está en " + _b(c["precio"]) + ".")
    lineas.append("Reviso cada 10 min en horario de bolsa de EE. UU. y le aviso una vez" +
                  (" (cada día que pase)." if a["tipo"] == "dia" else ".") + " Verlas: «mis alertas».")
    if a["tipo"] in ("compra", "desde_hoy") and a["direccion"] == "arriba" and a["valor"] >= 30:
        lineas.append("Si quiere, al llegar repasamos con su diario por qué la compró.")
    return "\n".join(lineas)


def borrar_por_frase(texto, resto):
    lista = activas()
    if not lista:
        return "No tiene alertas activas, señor."
    if re.search(r"\btodas\b", texto, re.I):
        for a in lista:
            borrar(a["id"])
        return "🗑 Borré sus " + str(len(lista)) + " alertas."
    ticker = _ticker("si " + resto) if resto.strip() else None
    elegidas = [a for a in lista if a["ticker"] == ticker] if ticker else [max(lista, key=lambda a: a["id"])]
    if not elegidas:
        return "No tiene alertas activas de " + ticker + ". Véalas con «mis alertas»."
    a = max(elegidas, key=lambda a: a["id"])
    borrar(a["id"])
    return "🗑 Borré la alerta #" + str(a["id"]) + ": " + describir(a) + "."


def texto_lista():
    lista = activas()
    if not lista:
        return ("No tiene alertas activas, señor. Cree una así: «avísame si V sube 35 % desde mi compra» o "
                "«avísame si NVDA baja de 120».")
    lineas = ["🔔 Sus alertas (" + str(len(lista)) + "):"]
    for a in lista:
        c = cotizacion(a["ticker"])
        obj = objetivo(a, c)
        extra = ""
        if c and obj:
            extra = " · ahora " + _b(c["precio"]) + " (falta " + _pct((obj / c["precio"] - 1) * 100) + ")"
        elif c:
            extra = " · ahora " + _b(c["precio"])
        lineas.append("• #" + str(a["id"]) + " " + describir(a) + extra)
    return "\n".join(lineas) + "\n\nBorrar: «borra la alerta N»."


def revisar_alertas():
    """Devuelve los avisos de las alertas que se cumplieron (una vez; las diarias, una vez por día)."""
    if not mercado_abierto():
        return []
    hoy = ahora().date().isoformat()
    mensajes = []
    cache = {}
    for a in activas():
        if a["tipo"] == "dia" and a["ultimo_dia"] == hoy:
            continue
        c = cache.get(a["ticker"]) or cotizacion(a["ticker"])
        cache[a["ticker"]] = c
        if not c:
            continue
        obj = objetivo(a, c)
        if obj is None:
            continue
        cumple = c["precio"] >= obj if a["direccion"] == "arriba" else c["precio"] <= obj
        if not cumple:
            continue
        with _con() as con:
            if a["tipo"] == "dia":
                con.execute("UPDATE alertas_precio SET ultimo_dia=? WHERE id=?", (hoy, a["id"]))
            else:
                con.execute("UPDATE alertas_precio SET estado='disparada', disparada=? WHERE id=?",
                            (ahora().isoformat(timespec="minutes"), a["id"]))
        texto = ("🔔 <b>Alerta #" + str(a["id"]) + "</b>: " + describir(a) + ".\nAhora: " + _b(c["precio"]) +
                 " (hoy " + _pct((c["precio"] / c["previo"] - 1) * 100) + ")")
        if a["referencia"]:
            texto += " · desde su referencia " + _pct((c["precio"] / a["referencia"] - 1) * 100)
        motivo = ultima_decision(a["ticker"])
        if motivo:
            texto += ("\n\n📓 Su decisión del " + motivo["fecha"][:10] + " (" + _frase_accion(motivo["accion"], motivo["ticker"]) +
                      "): «" + motivo["motivo"] + "»")
        texto += "\n\nSolo le informo, señor: usted decide."
        mensajes.append(texto)
        try:
            from modulos.clases import avisos
            avisos.notificar_windows("Alerta " + a["ticker"], describir(a))
        except Exception:
            pass
    return mensajes


# ------------------------------------------------------------------ diario de decisiones ---
DECISION = re.compile(r"^\W*(?:decisi[oó]n|diario|bit[aá]cora)\s*[:,\-–]\s*(.+)$", re.I | re.S)
ACCIONES = [("compra", r"\b(?:compr\w*|entr[eéo]\w*|a[nñ]ad\w*|sum[eéo]\w*|aument\w*)\b"),
            ("venta", r"\b(?:vend\w*|vent\w*|sal[ií]\w*|cerr\w*)\b"),
            ("reducción", r"\b(?:reduc\w*|recort\w*|bajo\s+peso)\b"),
            ("mantener", r"\b(?:mantengo|mantener|aguanto|espero|no\s+vendo|sigo\s+con)\b")]


def _frase_accion(accion, ticker):
    return {"compra": "compra de ", "venta": "venta de ", "reducción": "reducción de ", "mantener": "mantener "}[accion] + ticker


def nueva_decision(texto):
    cuerpo = DECISION.match(texto).group(1).strip()
    ticker = _ticker("si " + re.sub(r"^\W*(?:compr|vend|reduc|manten|aguant|sal|cerr|a[nñ]ad|aument)\w*\s+(?:m[aá]s\s+)?", "", cuerpo, flags=re.I))
    if not ticker:
        return "¿De qué acción es la decisión? Ejemplo: «decisión: compro V porque rompió la resistencia de 340»."
    accion = next((nombre for nombre, patron in ACCIONES if re.search(patron, cuerpo, re.I)), None)
    if not accion:
        return "¿Compra, vende, reduce o mantiene " + ticker + "? Ejemplo: «decisión: compro " + ticker + " porque …»."
    m = re.search(r"\b(?:porque|ya\s+que|por\s+que|motivo|raz[oó]n|pues)\b[\s:,]*(.+)$", cuerpo, re.I | re.S)
    motivo = (m.group(1) if m else cuerpo).strip(" .")
    precio = re.search(r"\ba\s+\$?" + NUM + r"\b", cuerpo)
    c = cotizacion(ticker)
    spy = cotizacion("SPY")
    valor = _num(precio.group(1)) if precio else (c["precio"] if c else None)
    with _con() as con:
        cur = con.execute("INSERT INTO decisiones (fecha, ticker, accion, precio, sp500, motivo) VALUES (?,?,?,?,?,?)",
                          (ahora().isoformat(timespec="minutes"), ticker, accion, valor, spy["precio"] if spy else None, motivo))
        did = cur.lastrowid
    return ("📓 Decisión #" + str(did) + " anotada: " + _frase_accion(accion, ticker) + (" a " + _b(valor) if valor else "") +
            ".\nMotivo: «" + motivo + "»\nLe pregunto cómo le fue dentro de 1, 3 y 6 meses, comparado con el S&P 500.")


def ultima_decision(ticker):
    with _con() as con:
        return con.execute("SELECT * FROM decisiones WHERE ticker=? ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()


def _resultado_decision(d, precio):
    if not d["precio"] or not precio:
        return None
    cambio = (precio / d["precio"] - 1) * 100
    return cambio if d["accion"] in ("compra", "mantener") else -cambio      # vender acierta si luego baja


def revisar_decisiones():
    """Revisiones a 1, 3 y 6 meses. Devuelve textos."""
    mensajes = []
    hoy = ahora()
    with _con() as con:
        lista = con.execute("SELECT * FROM decisiones").fetchall()
    for d in lista:
        hechas = set(filter(None, (d["revisadas"] or "").split(",")))
        fecha = datetime.fromisoformat(d["fecha"])
        fecha = fecha if fecha.tzinfo else fecha.replace(tzinfo=hoy.tzinfo)
        dias = (hoy - fecha).days
        pendientes = [r for r in REVISIONES if dias >= r and str(r) not in hechas]
        if not pendientes:
            continue
        r = max(pendientes)
        c, spy = cotizacion(d["ticker"]), cotizacion("SPY")
        if not c:
            continue
        with _con() as con:
            con.execute("UPDATE decisiones SET revisadas=? WHERE id=?", (",".join(sorted(hechas | set(map(str, pendientes)))), d["id"]))
        res = _resultado_decision(d, c["precio"])
        sp = (spy["precio"] / d["sp500"] - 1) * 100 if spy and d["sp500"] else None
        meses = {30: "1 mes", 90: "3 meses", 180: "6 meses"}[r]
        texto = ("📓 <b>Revisión de su decisión #" + str(d["id"]) + "</b> (hace " + meses + ")\n" +
                 _frase_accion(d["accion"], d["ticker"]).capitalize() + " a " + _b(d["precio"]) + " el " + d["fecha"][:10] +
                 ".\nMotivo: «" + d["motivo"] + "»\n\n"
                 "Hoy: " + _b(c["precio"]) + " (" + _pct((c["precio"] / d["precio"] - 1) * 100) + ")")
        if sp is not None:
            texto += " · S&P 500 en el mismo tiempo: " + _pct(sp)
        if res is not None and sp is not None:
            texto += "\n" + ("✅ Su decisión va mejor que el índice." if res > sp else "⚠️ El índice va mejor que su decisión.")
        texto += "\n\n¿Se cumplió su motivo? Respóndame «nota decisión " + str(d["id"]) + ": …» y lo guardo."
        mensajes.append(texto)
    return mensajes


NOTA_DECISION = re.compile(r"^\W*nota\s+(?:de\s+(?:la\s+)?)?decisi[oó]n\s*#?(\d+)\s*[:,\-–]\s*(.+)$", re.I | re.S)


def nota_decision(did, texto):
    with _con() as con:
        d = con.execute("SELECT * FROM decisiones WHERE id=?", (did,)).fetchone()
        if not d:
            return "No encuentro la decisión #" + str(did) + "."
        con.execute("UPDATE decisiones SET motivo=? WHERE id=?", (d["motivo"] + " | Después: " + texto.strip(), did))
    return "📓 Anotado en la decisión #" + str(did) + " (" + d["ticker"] + ")."


def texto_diario():
    with _con() as con:
        lista = con.execute("SELECT * FROM decisiones ORDER BY id DESC").fetchall()
    if not lista:
        return ("Su diario de decisiones está vacío. Anote así: «decisión: compro V porque rompió la resistencia de 340». "
                "Le preguntaré cómo le fue a 1, 3 y 6 meses.")
    spy = cotizacion("SPY")
    lineas = ["📓 Diario de decisiones (" + str(len(lista)) + "):"]
    mejores = peores = 0
    for d in lista[:12]:
        c = cotizacion(d["ticker"])
        res = _resultado_decision(d, c["precio"]) if c else None
        sp = (spy["precio"] / d["sp500"] - 1) * 100 if spy and d["sp500"] else None
        extra = ""
        if res is not None:
            extra = " · resultado " + _pct(res) + (" vs S&P " + _pct(sp) if sp is not None else "")
            if sp is not None:
                mejores += res > sp
                peores += res <= sp
        lineas.append("• #" + str(d["id"]) + " " + d["fecha"][:10] + " " + _frase_accion(d["accion"], d["ticker"]) + " a " +
                      _b(d["precio"]) + extra + "\n   «" + d["motivo"][:140] + "»")
    if mejores + peores:
        lineas.append("\nMejor que el S&P 500: " + str(mejores) + " de " + str(mejores + peores) + " decisiones.")
    return "\n".join(lineas)


def compras_sin_motivo():
    """Lotes nuevos en el informe de XTB sin decisión anotada. La primera vez solo los marca como vistos."""
    try:
        from modulos.portafolio import portafolio, xtb
        eq = portafolio.ajustes().get("equivalencias", {})
        lotes = [l for l in xtb.leer()["lotes"] if l["tipo"] == "BUY"]
    except Exception as exc:
        log.info("No leí el informe de XTB: %s", exc)
        return []
    with _con() as con:
        primera = not con.execute("SELECT 1 FROM decisiones_lotes LIMIT 1").fetchone()
        nuevos = []
        for l in lotes:
            fecha = l["fecha"].isoformat() if isinstance(l["fecha"], datetime) else str(l["fecha"])
            clave = l["ticker"] + "|" + fecha + "|" + str(l["volumen"])
            if con.execute("SELECT 1 FROM decisiones_lotes WHERE clave=?", (clave,)).fetchone():
                continue
            con.execute("INSERT INTO decisiones_lotes VALUES (?,?)", (clave, ahora().isoformat(timespec="minutes")))
            if not primera:
                nuevos.append((xtb.a_yahoo(l["ticker"], eq), fecha[:10]))
    mensajes = []
    for ticker, fecha in nuevos:
        d = ultima_decision(ticker)
        if d and d["fecha"][:10] >= (datetime.fromisoformat(fecha[:10]) - timedelta(days=3)).date().isoformat():
            continue                                           # ya la anotó
        mensajes.append("📓 Vi en su informe de XTB una compra de <b>" + ticker + "</b> (" + fecha + "). "
                        "¿Por qué la compró? Respóndame «decisión: compro " + ticker + " porque …» y en 1, 3 y 6 meses "
                        "revisamos si acertó.")
    return mensajes


# ------------------------------------------------------------------ calendario de resultados y dividendos ---
def _fecha_de(valor):
    if valor is None:
        return None
    if isinstance(valor, (list, tuple)):
        valor = valor[0] if valor else None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.fromisoformat(str(valor)[:10]).date()
    except Exception:
        return None


def calendario():
    """[(fecha, ticker, tipo)] de los próximos 60 días: resultados, ex-dividendo y pago de dividendo."""
    try:
        from modulos.noticias import noticias
        acciones = [t for t in noticias.mis_acciones() if not t.startswith("^")]
    except Exception:
        acciones = []
    hoy = ahora().date()
    eventos = []
    for t in acciones:
        try:
            import yfinance as yf
            cal = yf.Ticker(t).calendar or {}
        except Exception as exc:
            log.info("Sin calendario de %s: %s", t, exc)
            continue
        if hasattr(cal, "to_dict"):                       # versiones viejas devuelven una tabla
            try:
                cal = {k: v[0] if isinstance(v, list) else v for k, v in cal.to_dict().get(0, cal.to_dict()).items()}
            except Exception:
                cal = {}
        for clave, tipo in (("Earnings Date", "resultados"), ("Ex-Dividend Date", "ex-dividendo"),
                            ("Dividend Date", "pago de dividendo")):
            f = _fecha_de(cal.get(clave))
            if f and hoy <= f <= hoy + timedelta(days=60):
                eventos.append((f, t, tipo))
    return sorted(set(eventos))


EXPLICA = {"resultados": "presenta resultados trimestrales (suele mover el precio)",
           "ex-dividendo": "fecha ex-dividendo: para cobrar el dividendo hay que tener la acción ANTES de ese día",
           "pago de dividendo": "paga el dividendo"}


def avisos_calendario():
    hoy = ahora().date()
    mensajes = []
    for f, t, tipo in calendario():
        dias = (f - hoy).days
        if dias not in (0, 2):
            continue
        clave = f.isoformat() + "|" + t + "|" + tipo + "|" + str(dias)
        with _con() as con:
            if con.execute("SELECT 1 FROM calendario_avisos WHERE clave=?", (clave,)).fetchone():
                continue
            con.execute("INSERT INTO calendario_avisos VALUES (?,?)", (clave, ahora().isoformat(timespec="minutes")))
        cuando = "Hoy" if dias == 0 else "En 2 días (" + f.strftime("%d/%m") + ")"
        mensajes.append("📅 " + cuando + ": <b>" + t + "</b> " + EXPLICA[tipo] + ".")
    return mensajes


TITULO_GOOGLE = {"resultados": "📈 Resultados: ", "ex-dividendo": "💵 Ex-dividendo: ", "pago de dividendo": "💵 Pago de dividendo: "}


def calendario_a_google(eventos=None):
    """Pone los resultados y dividendos en Google Calendar (llegan al celular aunque la PC esté apagada).
    Títulos genéricos, sin montos. No duplica; si Yahoo mueve una fecha, cambia el evento; si el usuario lo borra
    desde el celular, no lo vuelve a crear. Devuelve [] (no manda mensajes)."""
    from modulos.calendario import extra_google as eg
    eventos = calendario() if eventos is None else eventos
    vigentes, con_fecha = set(), {}
    for f, t, tipo in eventos:
        clave = "mercado:" + t + "|" + tipo + "|" + f.isoformat()
        vigentes.add(clave)
        con_fecha[(t, tipo)] = f.isoformat()
        if eg.borrado_por_usuario(clave) or any(e["clave"] == clave for e in eg.activos(clave)):
            continue
        try:
            eg.dia_completo(clave, "mercado", TITULO_GOOGLE[tipo] + t, f, EXPLICA[tipo][:1].upper() + EXPLICA[tipo][1:] + ".",
                            avisos_min=(300, 1740) if tipo != "pago de dividendo" else (300,))
            log.info("En Google Calendar: %s %s %s", t, tipo, f)
        except Exception as exc:
            log.info("No pude poner %s %s en Google: %s", t, tipo, exc)
            return []                                      # sin Google ahora: se reintenta mañana / al encender
    hoy = ahora().date().isoformat()
    try:                                                   # acciones que el usuario dijo que vendió del todo
        from modulos.portafolio import cambios
        vendidas = cambios.vendidas() - set(noticias_acciones())
    except Exception:
        vendidas = set()
    for e in eg.activos("mercado:"):                       # fechas que Yahoo movió: se quita la vieja
        t, tipo, fecha = e["clave"].split(":", 1)[1].split("|")
        if fecha >= hoy and e["clave"] not in vigentes and con_fecha.get((t, tipo), fecha) != fecha:
            eg.quitar(e["clave"])
            log.info("Quitado de Google (fecha cambiada): %s", e["clave"])
        elif fecha >= hoy and t in vendidas:
            eg.quitar(e["clave"])
            log.info("Quitado de Google (la vendió): %s", e["clave"])
    return []


def noticias_acciones():
    try:
        from modulos.noticias import noticias
        return noticias.mis_acciones()
    except Exception:
        return {}


def texto_calendario():
    eventos = calendario()
    if not eventos:
        return "No encontré resultados ni dividendos de sus acciones en los próximos 60 días (Yahoo a veces no los publica)."
    lineas = ["📅 Próximos 60 días:"]
    for f, t, tipo in eventos:
        lineas.append("• " + f.strftime("%d/%m") + "  " + t + " — " + tipo)
    try:
        calendario_a_google(eventos)
    except Exception as exc:
        log.info("Calendario a Google falló: %s", exc)
    return "\n".join(lineas) + "\n\nLe aviso 2 días antes y el mismo día, y están en su Google Calendar (calendario «Asistente»)."


# ------------------------------------------------------------------ entrada única (texto, notas de voz, voz) ---
LISTA = re.compile(r"^\W*(?:(?:mis|las|ver|cu[aá]les\s+son\s+mis)\s+)?alertas(?:\s+de\s+precio)?(?:\s+activas)?\W*$", re.I)
BORRA = re.compile(r"^\W*(?:borra|b[oó]rra|elimina|quita|cancela|anula)\w*\s+(?:la\s+)?alerta\s*#?(\d+)\W*$", re.I)
BORRA_SIN_NUMERO = re.compile(r"^\W*(?:por\s+favor\W+)?(?:borra|b[oó]rra|elimina|quita|cancela|anula|ya\s+no\s+quiero)\w*\s+"
                              r"(?:(?:esa|esta|la|mi|su|el|las|mis|todas\s+las|todas\s+mis)\s+)?(?:[uú]ltima\s+)?alertas?\b(.*)$", re.I)
DIARIO = re.compile(r"^\W*(?:mi|el)\s+diario(?:\s+de\s+decisiones)?\W*$|^\W*mis\s+decisiones\W*$", re.I)
CALENDARIO = re.compile(r"\b(?:cu[aá]ndo|pr[oó]xim\w*)\b.*\b(?:resultados|dividendos?|earnings)\b|^\W*calendario(?:\s+de\s+resultados)?\W*$", re.I)


def procesar(texto):
    texto = (texto or "").strip()
    m = NOTA_DECISION.match(texto)
    if m:
        return nota_decision(int(m.group(1)), m.group(2))
    if DECISION.match(texto):
        return nueva_decision(texto)
    m = BORRA.match(texto)
    if m:
        return ("🗑 Alerta #" + m.group(1) + " borrada.") if borrar(int(m.group(1))) else "No encuentro esa alerta activa."
    m = BORRA_SIN_NUMERO.match(texto)
    if m:
        return borrar_por_frase(texto, m.group(1))
    if LISTA.match(texto):
        return texto_lista()
    if DIARIO.match(texto):
        return texto_diario()
    if CALENDARIO.search(texto) and re.search(r"\b(?:mis|sus|de)\b", texto, re.I):
        return texto_calendario()
    if PIDE_ALERTA.match(texto):
        datos = interpretar(texto)
        if isinstance(datos, str):
            return datos
        ya = ya_se_cumple(datos)
        if ya:
            return ya
        return texto_nueva(crear(datos, texto))
    return None
