"""Cambios del portafolio que el usuario cuenta con palabras (11-11): «compré Nvidia», «vendí Visa».

El portafolio sale del Excel de XTB. Entre un informe y el siguiente, el usuario puede decir qué compró o vendió y
el asistente lo tiene en cuenta YA: noticias de sus empresas, alertas, calendario de resultados/dividendos y
/portafolio. Cuando llega un informe nuevo de XTB con fecha posterior, esos cambios quedan «confirmados» (el
Excel manda) y dejan de aplicarse.

Todo se entiende en CÓDIGO (sin IA):
  compras:  «compré Nvidia», «compré 3 acciones de AMD a 140», «acabo de comprar Microsoft», «ya tengo Meta»,
            «invertí en Apple», «entré en Palantir», «agrega Tesla a mi portafolio», «compré Nvidia y AMD»
  ventas:   «vendí Visa», «ya no tengo Realty Income», «me deshice de JPM», «saca KOF del portafolio»,
            «cerré mi posición en Amazon», «vendí todas mis acciones de Meta»
  parcial:  «vendí la mitad de Amazon», «vendí 2 acciones de Visa», «reduje Meta»  (la acción se queda)
  mezcla:   «vendí Visa y compré Nvidia»
  después:  «fueron 3 acciones», «a 140» (cantidad/precio del último cambio), «porque …» (va al diario de
            decisiones), «sí» / «no» (confirmar un nombre desconocido o borrar las alertas de lo vendido)
  corregir: «deshaz lo último», «no compré Nvidia», «no vendí Visa», «borra el cambio de AMD»
  consultar:«qué acciones tengo», «mis cambios del portafolio», «¿tengo Visa?»
No se confunde con: gastos («compré pan 3», «compré pinceles por 12 con la gold»), práctica de Cava
(«trade NVDA compra 140»), diario («decisión: compro V porque …»), recordatorios («recuérdame que compre…»).

Por Telegram nunca van montos del portafolio: solo tickers, cantidades que el usuario mismo dijo y porcentajes.
"""
import json
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from modulos.comun import db
from modulos.comun.base import ahora, registro

log = registro("portafolio")
_listo = []
_excel = {"clave": None, "datos": None}
_tabla = {"t": 0.0, "datos": None}

# ------------------------------------------------------------------ nombres de empresas ---
# alias (minúsculas, sin tildes) -> ticker de Yahoo. Además se usan los nombres de su Excel de XTB,
# config/noticias.json ("nombres") y la tabla de Cava.
EMPRESAS = {
    "nvidia": "NVDA", "nvidea": "NVDA", "en vidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT", "amazon": "AMZN",
    "amazon.com": "AMZN", "alphabet": "GOOG", "google": "GOOG", "meta": "META", "meta platforms": "META",
    "facebook": "META", "tesla": "TSLA", "visa": "V", "mastercard": "MA", "master card": "MA", "intel": "INTC",
    "amd": "AMD", "advanced micro devices": "AMD", "netflix": "NFLX", "broadcom": "AVGO", "oracle": "ORCL",
    "palantir": "PLTR", "coca cola": "KO", "coca-cola": "KO", "cocacola": "KO", "coca cola femsa": "KOF",
    "femsa": "KOF", "pepsi": "PEP", "pepsico": "PEP", "berkshire": "BRK-B", "berkshire hathaway": "BRK-B",
    "jpmorgan": "JPM", "jp morgan": "JPM", "j p morgan": "JPM", "jpmorgan chase": "JPM", "bank of america": "BAC",
    "wells fargo": "WFC", "goldman sachs": "GS", "goldman": "GS", "morgan stanley": "MS", "citigroup": "C",
    "citi": "C", "paypal": "PYPL", "salesforce": "CRM", "adobe": "ADBE", "ibm": "IBM", "qualcomm": "QCOM",
    "micron": "MU", "asml": "ASML", "tsmc": "TSM", "taiwan semiconductor": "TSM", "disney": "DIS",
    "walt disney": "DIS", "mcdonalds": "MCD", "mcdonald's": "MCD", "mc donalds": "MCD", "starbucks": "SBUX",
    "nike": "NKE", "walmart": "WMT", "costco": "COST", "home depot": "HD", "procter": "PG",
    "procter & gamble": "PG", "procter and gamble": "PG", "johnson & johnson": "JNJ", "johnson and johnson": "JNJ",
    "pfizer": "PFE", "moderna": "MRNA", "eli lilly": "LLY", "lilly": "LLY", "novo nordisk": "NVO",
    "unitedhealth": "UNH", "abbvie": "ABBV", "merck": "MRK", "exxon": "XOM", "exxonmobil": "XOM",
    "exxon mobil": "XOM", "chevron": "CVX", "realty income": "O", "uber": "UBER", "airbnb": "ABNB",
    "spotify": "SPOT", "shopify": "SHOP", "mercadolibre": "MELI", "mercado libre": "MELI", "nubank": "NU",
    "nu holdings": "NU", "coinbase": "COIN", "alibaba": "BABA", "baidu": "BIDU", "sony": "SONY",
    "toyota": "TM", "boeing": "BA", "caterpillar": "CAT", "verizon": "VZ", "at&t": "T", "comcast": "CMCSA",
    "snowflake": "SNOW", "crowdstrike": "CRWD", "servicenow": "NOW", "super micro": "SMCI",
    "supermicro": "SMCI", "dell": "DELL", "cisco": "CSCO", "booking": "BKNG", "american express": "AXP",
    "amex": "AXP", "coreweave": "CRWV", "arm holdings": "ARM", "rivian": "RIVN", "lucid": "LCID",
    "nio": "NIO", "rocket lab": "RKLB", "ford": "F", "general motors": "GM", "gm": "GM", "ge": "GE",
    "general electric": "GE", "lockheed": "LMT", "lockheed martin": "LMT", "amd ": "AMD",
    "s&p 500": "SPY", "sp500": "SPY", "spy": "SPY", "voo": "VOO", "qqq": "QQQ",
}
# Tickers que también se aceptan escritos en minúscula («compré nvda»): los de 3+ letras de la tabla.
NOMBRE_BONITO = {
    "NVDA": "NVIDIA", "AAPL": "Apple", "MSFT": "Microsoft", "AMZN": "Amazon", "GOOG": "Alphabet", "GOOGL": "Alphabet",
    "META": "Meta Platforms", "TSLA": "Tesla", "V": "Visa", "MA": "Mastercard", "INTC": "Intel", "AMD": "AMD",
    "NFLX": "Netflix", "AVGO": "Broadcom", "ORCL": "Oracle", "PLTR": "Palantir", "KO": "Coca-Cola",
    "KOF": "Coca-Cola Femsa", "PEP": "PepsiCo", "BRK-B": "Berkshire Hathaway", "JPM": "JPMorgan",
    "BAC": "Bank of America", "WFC": "Wells Fargo", "GS": "Goldman Sachs", "MS": "Morgan Stanley", "C": "Citigroup",
    "PYPL": "PayPal", "CRM": "Salesforce", "ADBE": "Adobe", "IBM": "IBM", "QCOM": "Qualcomm", "MU": "Micron",
    "ASML": "ASML", "TSM": "TSMC", "DIS": "Disney", "MCD": "McDonald's", "SBUX": "Starbucks", "NKE": "Nike",
    "WMT": "Walmart", "COST": "Costco", "HD": "Home Depot", "PG": "Procter & Gamble", "JNJ": "Johnson & Johnson",
    "PFE": "Pfizer", "MRNA": "Moderna", "LLY": "Eli Lilly", "NVO": "Novo Nordisk", "UNH": "UnitedHealth",
    "ABBV": "AbbVie", "MRK": "Merck", "XOM": "Exxon Mobil", "CVX": "Chevron", "O": "Realty Income", "UBER": "Uber",
    "ABNB": "Airbnb", "SPOT": "Spotify", "SHOP": "Shopify", "MELI": "MercadoLibre", "NU": "Nu Holdings",
    "COIN": "Coinbase", "BABA": "Alibaba", "BIDU": "Baidu", "SONY": "Sony", "TM": "Toyota", "BA": "Boeing",
    "CAT": "Caterpillar", "VZ": "Verizon", "T": "AT&T", "CMCSA": "Comcast", "SNOW": "Snowflake",
    "CRWD": "CrowdStrike", "NOW": "ServiceNow", "SMCI": "Super Micro", "DELL": "Dell", "CSCO": "Cisco",
    "BKNG": "Booking", "AXP": "American Express", "CRWV": "CoreWeave", "ARM": "Arm Holdings", "RIVN": "Rivian",
    "LCID": "Lucid", "NIO": "NIO", "RKLB": "Rocket Lab", "F": "Ford", "GM": "General Motors", "GE": "GE Aerospace",
    "LMT": "Lockheed Martin", "SPY": "S&P 500 (SPY)", "VOO": "Vanguard S&P 500 (VOO)", "QQQ": "Nasdaq 100 (QQQ)",
}
NO_TICKER = {"NO", "SI", "OK", "EEUU", "USA", "UE", "CEO", "IA", "AI", "PIB", "FED", "BCE", "ETF", "ETFS", "RSI",
             "MACD", "EMA", "SMA", "USD", "EUR", "IPC", "CPI", "PMI", "OPEP", "QE", "ATH", "ADR", "OJO", "TP", "SL",
             "VS", "PD", "EL", "LA", "LO", "LOS", "LAS", "UN", "UNA", "DE", "EN", "XTB", "HOY", "YA", "MI", "MIS",
             "CFD", "CFDS", "Y", "A", "O", "E", "U", "JARVIS", "OYE", "HEY", "OK", "TAMBIEN"}

# ------------------------------------------------------------------ base de datos ---


def _con():
    con = sqlite3.connect(db.ARCHIVO, timeout=30)
    con.row_factory = sqlite3.Row
    if not _listo:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS portafolio_cambios (id INTEGER PRIMARY KEY, ticker TEXT, nombre TEXT,
                accion TEXT, cantidad REAL, fraccion REAL, precio REAL, precio_aprox INTEGER DEFAULT 0,
                creado TEXT, texto TEXT, estado TEXT DEFAULT 'activo', decision INTEGER);
            CREATE TABLE IF NOT EXISTS portafolio_estado (clave TEXT PRIMARY KEY, datos TEXT, t REAL);
        """)
        _listo.append(True)
    return con


def _guardar_estado(clave, datos):
    with _con() as con:
        con.execute("INSERT OR REPLACE INTO portafolio_estado VALUES (?,?,?)", (clave, json.dumps(datos), time.time()))


def _estado(clave, minutos):
    with _con() as con:
        f = con.execute("SELECT * FROM portafolio_estado WHERE clave=?", (clave,)).fetchone()
    if f and time.time() - f["t"] < minutos * 60:
        return json.loads(f["datos"])
    return None


def _borrar_estado(*claves):
    with _con() as con:
        for c in claves:
            con.execute("DELETE FROM portafolio_estado WHERE clave=?", (c,))


def _olvidar_caches():
    """Noticias y /portafolio se recalculan con el cambio."""
    _tabla["datos"] = None
    try:
        from modulos.noticias import noticias
        noticias._estado["acciones"] = None
    except Exception:
        pass
    try:
        from modulos.portafolio import portafolio
        portafolio._cache["datos"] = None
    except Exception:
        pass


# ------------------------------------------------------------------ texto ---
def sin_tildes(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


MULETILLA = re.compile(
    r"^(?:oye|oiga|hey|ey|hola|jarvis|bueno|ok|okay|vale|mira|senor|por\s+favor|porfa|una\s+cosa|fijate\s+que|"
    r"pues|entonces|sabes\s+que|te\s+cuento\s+que|para\s+que\s+sepas(?:\s+que)?|para\s+que\s+lo\s+sepas|quiero\s+que\s+sepas\s+que|"
    r"te\s+aviso\s+que|te\s+informo\s+que|solo\s+(?:para\s+)?avisarte\s+que|"
    r"(?:anota|apunta|registra|guarda|pon|agrega|escribe)(?:me|lo)?\s+(?:en\s+(?:mi\s+|el\s+)?(?:portafolio|cartera)\s+)?que|"
    r"ten\s+en\s+cuenta\s+que|toma\s+nota(?:\s+de\s+que)?|nota|aviso|dato|actualiza(?:cion)?(?:\s+del?\s+portafolio)?)"
    r"(?=\W|$)[\s,.:;!\-]*")
NUMEROS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
           "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20, "treinta": 30,
           "media": 0.5, "medio": 0.5, "cincuenta": 50, "cien": 100}


def normalizar(texto):
    """Minúsculas, sin tildes, sin muletillas («oye Jarvis, anota que…»), «q»→que, «140 con 50»→140.50."""
    t = sin_tildes(texto).replace("¿", " ").replace("¡", " ").replace("’", "'")
    t = re.sub(r"[\"“”«»]", " ", t)
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    t = re.sub(r"(\d+)\s+con\s+(\d{1,2})\b", r"\1.\2", t)
    t = re.sub(r"\bq\b", "que", t)
    t = re.sub(r"\bxq\b|\bpq\b", "porque", t)
    t = re.sub(r"\bacc?iones\b", "acciones", t)
    t = re.sub(r"[ \t\r\n]+", " ", t).strip(" .!?")
    antes = None
    while antes != t:
        antes = t
        t = MULETILLA.sub("", t).strip(" ,.:;!?")
        t = re.sub(r"[\s,]*\b(?:senor|jarvis|gracias|muchas\s+gracias|por\s+favor|porfa|ok|okay|nada\s+mas)$", "", t).strip(" ,.:;!?")
    return t


def _num(palabra):
    if palabra is None:
        return None
    palabra = palabra.strip()
    if palabra in NUMEROS:
        return float(NUMEROS[palabra])
    try:
        return float(palabra.replace(",", "."))
    except ValueError:
        return None


def _bonito(x):
    return ("%.4f" % x).rstrip("0").rstrip(".").replace(".", ",")


# ------------------------------------------------------------------ su Excel de XTB ---
def _leer_excel():
    """El último informe de XTB (cacheado mientras no cambie el archivo). None si no hay."""
    try:
        from modulos.portafolio import xtb
        ruta = xtb.ultimo_archivo()
        if not ruta:
            return None
        clave = (str(ruta), ruta.stat().st_mtime)
        if _excel["clave"] != clave:
            datos = xtb.leer(ruta)
            datos["mtime"] = datetime.fromtimestamp(ruta.stat().st_mtime)
            _excel.update(clave=clave, datos=datos)
        return _excel["datos"]
    except Exception as exc:
        log.info("No leí el Excel de XTB: %s", exc)
        return None


def fecha_informe(datos=None):
    datos = datos if datos is not None else _leer_excel()
    if not datos:
        return None
    f = datos.get("fecha_informe") or datos.get("mtime")
    if not f and datos.get("archivo") and Path(datos["archivo"]).exists():
        f = datetime.fromtimestamp(Path(datos["archivo"]).stat().st_mtime)
    return f.replace(tzinfo=None) if isinstance(f, datetime) else None


def _del_excel(datos=None):
    """{ticker_yahoo: nombre} de las compras abiertas del Excel."""
    datos = datos if datos is not None else _leer_excel()
    res = {}
    if not datos:
        return res
    try:
        from modulos.portafolio import portafolio, xtb
        from modulos.noticias import noticias
        eq = portafolio.ajustes().get("equivalencias", {})
        nombres = {k.upper(): v for k, v in noticias.ajustes().get("nombres", {}).items()}
        for l in datos["lotes"]:
            if l["tipo"] == "BUY":
                y = xtb.a_yahoo(l["ticker"], eq)
                res.setdefault(y, nombres.get(y) or noticias.nombre_corto(l.get("nombre") or "", y))
    except Exception as exc:
        log.info("No pude leer los tickers del Excel: %s", exc)
    return res


# ------------------------------------------------------------------ cambios guardados ---
def conciliar(fecha=None):
    """Lo que ya trae un informe de XTB más nuevo pasa a 'confirmado'. Devuelve cuántos."""
    fecha = fecha if fecha is not None else fecha_informe()
    if not fecha:
        return 0
    limite = fecha.isoformat(timespec="minutes")
    with _con() as con:                    # primero solo mira (no bloquea la base si no hay nada que cambiar)
        if not con.execute("SELECT 1 FROM portafolio_cambios WHERE estado='activo' AND creado < ? LIMIT 1",
                           (limite,)).fetchone():
            return 0
        n = con.execute("UPDATE portafolio_cambios SET estado='confirmado' WHERE estado='activo' AND creado < ?",
                        (limite,)).rowcount
    if n:
        log.info("%d cambios del portafolio ya vienen en el informe de XTB", n)
        _olvidar_caches()
    return n


def activos(fecha=None):
    conciliar(fecha)
    with _con() as con:
        return con.execute("SELECT * FROM portafolio_cambios WHERE estado='activo' ORDER BY id").fetchall()


def ultimo():
    with _con() as con:
        return con.execute("SELECT * FROM portafolio_cambios WHERE estado='activo' ORDER BY id DESC LIMIT 1").fetchone()


def vendidas(dias=60):
    """Tickers vendidos del todo en los últimos días (también los ya confirmados por el Excel)."""
    desde = (datetime.now() - timedelta(days=dias)).isoformat(timespec="minutes")
    with _con() as con:
        filas = con.execute("SELECT ticker, accion FROM portafolio_cambios WHERE estado IN ('activo','confirmado') "
                            "AND creado >= ? ORDER BY id", (desde,)).fetchall()
    final = {}
    for f in filas:
        final[f["ticker"]] = f["accion"]
    return {t for t, a in final.items() if a == "venta"}


def aplicar_a(acciones, fecha=None):
    """Aplica los cambios activos a {ticker: nombre}: suma lo comprado y quita lo vendido del todo."""
    res = dict(acciones)
    for c in activos(fecha):
        if c["accion"] == "compra":
            res.setdefault(c["ticker"], c["nombre"] or c["ticker"])
        elif c["accion"] == "venta":
            res.pop(c["ticker"], None)
    return res


def tenencias():
    """({ticker: nombre} de lo que tiene ahora, fecha del informe)."""
    datos = _leer_excel()
    fecha = fecha_informe(datos)
    return aplicar_a(_del_excel(datos), fecha), fecha


def ajustar_lotes(lotes, fecha, a_yahoo):
    """Para /portafolio: aplica los cambios activos a los lotes del Excel. Devuelve (lotes, notas)."""
    lotes = [dict(l) for l in lotes]
    notas = {"sin_cantidad": [], "cambios": []}
    for c in activos(fecha):
        t = c["ticker"]
        suyos = [l for l in lotes if a_yahoo(l["ticker"]) == t]
        if c["accion"] == "venta":
            lotes = [l for l in lotes if a_yahoo(l["ticker"]) != t]
            notas["cambios"].append("vendió " + t)
        elif c["accion"] == "parcial":
            if c["cantidad"]:
                quitar = c["cantidad"]
                for l in sorted(suyos, key=lambda l: str(l.get("fecha"))):        # primero los lotes más viejos
                    usa = min(quitar, l["volumen"])
                    l["volumen"] -= usa
                    quitar -= usa
                    if quitar <= 1e-9:
                        break
            elif c["fraccion"]:
                for l in suyos:
                    l["volumen"] *= (1 - c["fraccion"])
            lotes = [l for l in lotes if l["volumen"] > 1e-9]
            notas["cambios"].append("vendió parte de " + t)
        elif c["accion"] == "compra":
            if c["cantidad"] and c["precio"]:
                lotes.append({"ticker": t, "tipo": "BUY", "volumen": float(c["cantidad"]), "precio": float(c["precio"]),
                              "fecha": datetime.fromisoformat(c["creado"]), "producto": "", "precio_xtb": None,
                              "posicion": "", "categoria": "STOCK", "nombre": c["nombre"] or "", "manual": True})
                notas["cambios"].append("compró " + _bonito(c["cantidad"]) + (" acción de " if c["cantidad"] == 1 else
                                                                              " acciones de ") + t)
            else:
                notas["sin_cantidad"].append(t)
                notas["cambios"].append("compró " + t + " (sin cantidad)")
    return lotes, notas


# ------------------------------------------------------------------ entender el nombre ---
def _alias():
    """[(alias_sin_tildes, ticker)] del más largo al más corto (se rehace cada minuto)."""
    if _tabla["datos"] is not None and time.time() - _tabla["t"] < 60:
        return _tabla["datos"]
    tabla = {}
    try:
        from modulos.cava import cava
        for nombre, t in cava.NOMBRES.items():
            if not t.startswith("^") and "=" not in t:
                tabla[sin_tildes(nombre)] = t
    except Exception:
        pass
    tabla.update({sin_tildes(k).strip(): v for k, v in EMPRESAS.items()})
    try:
        from modulos.noticias import noticias
        for t, n in noticias.ajustes().get("nombres", {}).items():
            tabla.setdefault(sin_tildes(n), t.upper())
    except Exception:
        pass
    for t, n in _del_excel().items():                      # los nombres de su Excel mandan
        n = sin_tildes(n).replace("-", " ")
        if len(n) >= 3 and n != t.lower():
            tabla[n] = t
            primera = n.split()[0]
            if " " in n and len(primera) >= 5:
                tabla.setdefault(primera, t)
    for t in set(tabla.values()) | set(NOMBRE_BONITO):
        if len(t) >= 3 and t.replace("-", "").isalpha():
            tabla.setdefault(t.lower(), t)                     # «compré nvda»
    for malo in ("hp", "oro", "nu", "c", "f", "t", "o", "ma", "ms", "v", "ge", "gm"):
        tabla.pop(malo, None)
    _tabla.update(t=time.time(), datos=sorted(((a, t) for a, t in tabla.items()), key=lambda x: -len(x[0])))
    return _tabla["datos"]


def nombre_de(ticker):
    excel = _del_excel()
    return excel.get(ticker) or NOMBRE_BONITO.get(ticker) or ticker


def buscar_yahoo(consulta):
    """(ticker, nombre) más probable en Yahoo Finance para un nombre, o None. Solo acciones y ETF."""
    try:
        import yfinance as yf
        quotes = yf.Search(consulta, max_results=6).quotes
    except Exception as exc:
        log.info("Búsqueda en Yahoo falló (%s): %s", consulta, exc)
        return None
    buenas = [q for q in quotes or [] if q.get("quoteType") in ("EQUITY", "ETF") and q.get("symbol")]
    eeuu = [q for q in buenas if q.get("exchange") in ("NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS", "NAS", "NYS")]
    q = (eeuu or buenas or [None])[0]
    if not q:
        return None
    return q["symbol"].upper(), (q.get("shortname") or q.get("longname") or q["symbol"]).strip()


RELLENO = set("""las los unas unos mis mas todas todos todo toda algunas algunos un una par de del en la el lo al a mi
acciones accion titulos titulo participaciones papeles xtb hoy ayer anoche manana otra vez nuevamente tambien ya
portafolio portfolio cartera que tenia tengo tenemos empresa compania mitad parte poco algo por ciento cada c/u
precio dolares dolar usd inc corp nuevas nuevos posicion ahi eso esta este semana lunes martes miercoles jueves
viernes sabado domingo temprano tarde noche pasado recien finalmente cuenta real mas y e su sus se me le senor
jarvis gracias porfa favor media medio dos tres cuatro cinco seis siete ocho nueve diez once doce quince veinte
treinta cincuenta cien xstation plataforma broker app aplicacion""".split())
DEMO = re.compile(r"\b(?:demo|practica|simulad\w*|paper|de\s+prueba)\b")
MEDIO_PAGO = re.compile(r"\b(?:diners|gold|platinum|pichincha|produbanco|tarjeta|efectivo|debito|credito)\b")


def _resolver(pieza, mayusculas, venta=False):
    """De un trozo de frase («3 acciones de AMD a 140») saca el ticker. Devuelve dict o None."""
    pieza = " " + pieza + " "
    hallado = None
    tabla = _alias()
    conocidos = {t for _, t in tabla} | set(NOMBRE_BONITO)
    for alias, t in tabla:
        if re.search(r"(?<![\w&])" + re.escape(alias) + r"(?![\w&])", pieza):
            hallado = (alias, t)
            break
    tokens = re.findall(r"[a-z][a-z.\-]{0,6}", pieza)
    if not hallado:
        for tok in tokens:
            if tok.upper() in mayusculas:
                hallado = (tok, tok.upper())
                break
    resto = pieza
    if hallado:
        resto = re.sub(r"(?<![\w&])" + re.escape(hallado[0]) + r"(?![\w&])", " ", resto)
    resto = re.sub(r"\$?\d+(?:\.\d+)?\s*%?", " ", resto)
    sobra = [w for w in re.findall(r"[a-z&']+", resto) if w not in RELLENO and len(w) > 1]
    sobra = [w for w in sobra if not (len(w) <= 5 and w.upper() in mayusculas)]
    explicita = bool(re.search(r"\bacciones\b|\btitulos?\b|\bparticipaciones\b", pieza))
    if hallado:
        ticker = hallado[1]
        if venta:                                      # «vendí coca cola» y tiene KOF (Coca-Cola Femsa): la suya
            tiene = _del_excel()
            if ticker not in tiene:
                buscado = hallado[0].replace("-", " ")
                suyas = [t for t, n in tiene.items() if buscado in sin_tildes(n).replace("-", " ")]
                if len(suyas) == 1:
                    ticker = suyas[0]
        desconocido = ticker not in conocidos
        return {"ticker": ticker, "seguro": not desconocido, "sobra": sobra, "explicita": explicita}
    if explicita:                                       # «compré acciones de Rocket Lab»: se busca en Yahoo
        m = re.search(r"\b(?:acciones|titulos?|participaciones)\s+(?:de|en)\s+(?:la\s+|el\s+)?([a-z0-9&.\- ]{2,40}?)\s*$",
                      re.sub(r"\s+(?:a|por)\s+\$?\d.*$", "", pieza.strip()))
        if m:
            nombre = " ".join(w for w in m.group(1).split() if w not in RELLENO)
            if len(nombre) >= 2:
                return {"buscar": nombre, "sobra": [], "explicita": True}
    return None


# ------------------------------------------------------------------ entender la frase ---
PRE = r"(?:(?:yo|ya|hoy|ayer|anoche|tambien|recien|finalmente|al\s+final|por\s+fin|hace\s+(?:un\s+)?rato|" \
      r"hace\s+poco|esta\s+(?:manana|tarde|semana)|el\s+(?:lunes|martes|miercoles|jueves|viernes)|en\s+xtb)\s+)*"
V_COMPRA = (r"(?:he\s+comprado|acabo\s+de\s+comprar|termine\s+comprando|ya\s+compre|compre|me\s+compre|adquiri|"
            r"he\s+adquirido|entre\s+(?:en|a)|he\s+entrado\s+(?:en|a)|meti(?:\s+(?:plata|dinero|mas\s+plata|mas\s+dinero|algo))?"
            r"(?:\s+\$?\d+(?:\.\d+)?(?:\s*(?:dolares|usd))?)?\s+en|"
            r"inverti(?:\s+\$?\d+(?:\.\d+)?(?:\s*(?:dolares|usd))?)?\s+en|he\s+invertido\s+en|"
            r"abri\s+(?:una\s+)?posicion\s+(?:en|de)|aumente(?:\s+mi\s+posicion)?\s+(?:en|de)|"
            r"amplie(?:\s+mi\s+posicion)?\s+(?:en|de)|empece\s+a\s+invertir\s+en|me\s+hice\s+con|"
            r"ya\s+tengo|ahora\s+tengo|tambien\s+tengo|tengo(?=\s+\S+\s+acciones\s+de))")
V_VENTA = (r"(?:he\s+vendido|acabo\s+de\s+vender|termine\s+vendiendo|ya\s+vendi|vendi|liquide|he\s+liquidado|"
           r"me\s+deshice\s+de|me\s+he\s+deshecho\s+de|me\s+sali\s+de|sali\s+de|me\s+he\s+salido\s+de|"
           r"cerre(?:\s+(?:mi|la|toda\s+mi|toda\s+la))?\s+posicion\s+(?:en|de)|ya\s+no\s+tengo|no\s+tengo\s+ya|"
           r"ya\s+no\s+estoy\s+en|me\s+quede\s+sin|solte)")
V_PARCIAL = r"(?:reduje|he\s+reducido|recorte|baje)(?:\s+(?:mi\s+)?(?:posicion|peso))?(?:\s+(?:en|de))?"
VERBO = re.compile(r"(?<![\w])" + PRE + r"(?:(?P<c>" + V_COMPRA + r")|(?P<v>" + V_VENTA + r")|(?P<p>" + V_PARCIAL +
                   r"))(?![\w])")
IMP_COMPRA = re.compile(r"^(?:agrega|agregale|anade|anadele|suma|sumale|pon|ponme|mete|meteme|incluye|registra|apunta|anota)"
                        r"(?:me|le)?\s+(.+?)\s+(?:a|en|al)\s+(?:mi\s+|el\s+|la\s+)?(?:portafolio|portfolio|cartera)$")
IMP_VENTA = re.compile(r"^(?:saca|sacame|quita|quitame|borra|borrame|elimina|eliminame|retira)(?:me|le)?\s+(.+?)\s+"
                       r"(?:de|del)\s+(?:mi\s+|el\s+|la\s+)?(?:portafolio|portfolio|cartera)$")
YA_NO_ESTA = re.compile(r"^(.+?)\s+ya\s+no\s+(?:esta|va|forma\s+parte)\s+(?:en|de)\s+(?:mi\s+)?(?:portafolio|cartera)$")
MOTIVO = re.compile(r"\s*,?\s*\b(?:porque|por\s+que|ya\s+que|debido\s+a\s+que|debido\s+a|motivo\s*:?|la\s+razon\s+es)\s+(.+)$")
INTENCION = re.compile(r"\b(?:recuerd\w*|acuerd\w*|avis\w*|alerta\w*|quiero|queria|quisiera|pienso|planeo|voy\s+a|vamos\s+a|"
                       r"deberia|debo|tengo\s+que|me\s+gustaria|conviene|vale\s+la\s+pena|si\s+compro|si\s+vendo|"
                       r"compraria|venderia|comprar\w*\?|vender\w*\?|cuando\s+compre|que\s+compre|que\s+venda|"
                       r"cuanto\s+gane|cuanto\s+perdi|trade|decision\s*:|nota\s+cava|bitacora|diario\s*:)\b")
NO_ANTES = {"que", "si", "cuando", "para", "no", "nunca", "jamas", "quiza", "quizas", "tal"}
PARCIAL_MARCA = re.compile(r"\b(?:la\s+mitad|mitad|una\s+parte|parte|un\s+poco|algo|un\s+tercio|un\s+cuarto|"
                           r"la\s+cuarta\s+parte)\b|\b(\d+(?:\.\d+)?)\s*(?:%|por\s*ciento\b)")
TODO_MARCA = re.compile(r"\b(?:todas|todo|toda|completa|completo|entera|entero|al\s+100)\b")
CANTIDAD = re.compile(r"(?:^|\s)(\d+(?:\.\d+)?|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|quince|"
                      r"veinte|treinta|cincuenta|cien|media)\s+(?:acciones|accion|titulos?|participaciones|papeles)\b")
PRECIO = re.compile(r"\b(?:a|en)\s+(?:un\s+)?(?:precio\s+de\s+)?\$?\s?(\d+(?:\.\d+)?)\s*(?:dolares|usd|\$)?"
                    r"(?:\s+(?:cada\s+una|c/u|por\s+accion|la\s+accion))?(?=\s|$|,)|"
                    r"\bpor\s+\$?\s?(\d+(?:\.\d+)?)\s*(?:dolares|usd|\$)?\s+(?:cada\s+una|c/u|por\s+accion|la\s+accion)")


def _piezas(region):
    """'Nvidia y AMD' -> ['Nvidia', 'AMD']; no parte 'Procter & Gamble' ni 'Johnson and Johnson'."""
    region = re.sub(r"\bjohnson\s+(?:y|and|&)\s+johnson\b", "johnson & johnson", region)
    region = re.sub(r"\bprocter\s+(?:y|and)\s+gamble\b", "procter & gamble", region)
    return [p.strip() for p in re.split(r"\s*(?:,|;|\by\b|\be\b|\bmas\s+(?=[a-z]))\s*", region) if p.strip()]


def interpretar(texto):
    """Lista de cambios entendidos [{accion, ticker|buscar, cantidad, fraccion, precio}] y el motivo, o None."""
    original = texto or ""
    if "?" in original or "¿" in original:
        return None
    t = normalizar(original)
    if not t or INTENCION.search(t) or DEMO.search(t) or MEDIO_PAGO.search(t):
        return None
    mayusculas = {w for w in re.findall(r"\b[A-Z]{2,5}(?:[.\-][A-Z]{1,2})?\b", original) if w not in NO_TICKER}
    motivo = ""
    m = MOTIVO.search(t)
    if m:
        motivo, t = m.group(1).strip(" ."), t[:m.start()].strip(" ,.")
    segmentos = []
    for patron, accion in ((IMP_COMPRA, "compra"), (IMP_VENTA, "venta"), (YA_NO_ESTA, "venta")):
        m = patron.match(t)
        if m:
            segmentos = [(accion, m.group(1), True, False)]
            break
    if not segmentos:
        verbos = list(VERBO.finditer(t))
        if not verbos:
            return None
        if t[:verbos[0].start()].strip():                  # algo antes del primer verbo
            antes = t[:verbos[0].start()].split()
            if antes and antes[-1] in NO_ANTES or len(antes) > 3:
                return None
        for i, v in enumerate(verbos):
            fin = verbos[i + 1].start() if i + 1 < len(verbos) else len(t)
            accion = "compra" if v.group("c") else ("venta" if v.group("v") else "parcial")
            region = t[v.end():fin].strip(" ,.")
            region = re.sub(r"\s*,?\s*\b(?:y|e|luego|despues|pero|ademas|tambien)\s*$", "", region)
            verbo_txt = v.group(0).strip()
            if accion == "compra" and re.match(r"^(?:ya\s+)?(?:compre|me\s+compre)$", verbo_txt) and \
                    re.match(r"^(?:en|algo|cosas|unas?|unos?)\b", region) and not re.search(r"\bacciones\b", region):
                return None                               # «compré en Amazon unos audífonos»
            segmentos.append((accion, region, False, bool(re.search(r"tengo$", verbo_txt))))
    cambios = []
    for accion, region, imperativo, es_estado in segmentos:
        if not region:
            return None
        cant = CANTIDAD.search(region)
        cantidad = _num(cant.group(1)) if cant else None
        pre = PRECIO.search(region)
        precio = float(pre.group(1) or pre.group(2)) if pre else None
        if not pre and re.search(r"\bpor\s+\$?\d", region) and not re.search(r"\bacciones\b", region):
            return None                                   # «compré spotify por 10»: es un gasto
        parcial = PARCIAL_MARCA.search(region)
        fraccion = None
        acc = accion
        if accion in ("venta", "parcial"):
            if parcial and not TODO_MARCA.search(region):
                acc = "parcial"
                frase = parcial.group(0)
                fraccion = {"la mitad": .5, "mitad": .5, "un tercio": 1 / 3, "un cuarto": .25,
                            "la cuarta parte": .25}.get(frase)
                if parcial.group(1):
                    fraccion = min(float(parcial.group(1)) / 100, 1.0)
            elif cantidad and not TODO_MARCA.search(region):
                acc = "parcial"
            elif accion == "parcial" and TODO_MARCA.search(region):
                acc = "venta"
        limpia = PRECIO.sub(" ", region)
        limpia = PARCIAL_MARCA.sub(" ", limpia)
        piezas = _piezas(limpia)
        for pieza in piezas:
            r = _resolver(pieza, mayusculas, venta=acc != "compra")
            if not r:
                if len(piezas) == 1 and not imperativo:
                    return None
                if not re.sub(r"\b(?:" + "|".join(sorted(RELLENO, key=len, reverse=True)) + r")\b", "", pieza).strip():
                    continue                              # trozo de relleno («hoy»)
                return None                               # un trozo que no es una acción: mejor no adivinar
            if r.get("ticker") and r["sobra"] and not r["explicita"] and not imperativo:
                return None                               # «compré unos audífonos en Amazon»: no es una acción
            cambios.append({"accion": acc, **r, "es_estado": es_estado, "cantidad": cantidad if len(piezas) == 1 else None,
                            "fraccion": fraccion, "precio": precio if len(piezas) == 1 else None})
    if not cambios:
        return None
    return {"cambios": cambios, "motivo": motivo, "texto": original.strip()}


# ------------------------------------------------------------------ guardar y responder ---
def _precio_actual(ticker):
    try:
        from modulos.alertas import alertas
        c = alertas.cotizacion(ticker)
        return c["precio"] if c else None
    except Exception:
        return None


def _alertas_de(ticker):
    try:
        from modulos.alertas import alertas
        return [a["id"] for a in alertas.activas() if a["ticker"].upper() == ticker.upper()]
    except Exception:
        return []


def _decision(ticker, accion, precio, motivo):
    try:
        from modulos.alertas import alertas
        verbo = {"compra": "compro", "venta": "vendo", "parcial": "reduzco"}[accion]
        r = alertas.nueva_decision("decisión: " + verbo + " " + ticker + (" a " + ("%g" % precio) if precio else "") +
                                   " porque " + motivo)
        m = re.search(r"#(\d+)", r or "")
        return int(m.group(1)) if m else None
    except Exception as exc:
        log.info("No pude anotar la decisión: %s", exc)
        return None


def guardar(c, texto="", motivo=""):
    """Guarda un cambio ya resuelto. Devuelve el id."""
    precio, aprox = c.get("precio"), 0
    if c["accion"] == "compra" and c.get("cantidad") and not precio:
        precio, aprox = _precio_actual(c["ticker"]), 1
    nombre = c.get("nombre") or nombre_de(c["ticker"])
    with _con() as con:
        cid = con.execute("INSERT INTO portafolio_cambios (ticker, nombre, accion, cantidad, fraccion, precio, precio_aprox, "
                          "creado, texto) VALUES (?,?,?,?,?,?,?,?,?)",
                          (c["ticker"], nombre, c["accion"], c.get("cantidad"), c.get("fraccion"), precio, aprox,
                           datetime.now().isoformat(timespec="seconds"), texto[:300])).lastrowid
    if motivo:
        did = _decision(c["ticker"], c["accion"], c.get("precio"), motivo)
        if did:
            with _con() as con:
                con.execute("UPDATE portafolio_cambios SET decision=? WHERE id=?", (did, cid))
    _olvidar_caches()
    log.info("Cambio del portafolio #%d: %s %s (cant. %s, precio %s)", cid, c["accion"], c["ticker"], c.get("cantidad"),
             precio)
    return cid


def _obtener(cid):
    with _con() as con:
        return con.execute("SELECT * FROM portafolio_cambios WHERE id=?", (cid,)).fetchone()


def _linea_cambio(f):
    nombre = f["nombre"] if f["nombre"] and f["nombre"].upper() != f["ticker"] else ""
    quien = f["ticker"] + (" (" + nombre + ")" if nombre else "")
    extra = ""
    if f["cantidad"]:
        extra += ", " + _bonito(f["cantidad"]) + (" acción" if f["cantidad"] == 1 else " acciones")
    if f["precio"] and not f["precio_aprox"]:
        extra += " a " + _bonito(f["precio"])
    if f["accion"] == "compra":
        return "compró " + quien + extra
    if f["accion"] == "venta":
        return "vendió " + quien
    if f["fraccion"]:
        parte = {0.5: "la mitad", 0.25: "la cuarta parte"}.get(round(f["fraccion"], 2)) or \
            ("%.0f %%" % (f["fraccion"] * 100))
        return "vendió " + parte + " de " + quien
    return "vendió parte de " + quien + extra


MARCA = "✍️ Portafolio:"


def _respuesta(ids, motivo):
    filas = [_obtener(i) for i in ids]
    lineas = [MARCA + " " + "; ".join(_linea_cambio(f) for f in filas) + "."]
    compras = [f for f in filas if f["accion"] == "compra"]
    ventas = [f for f in filas if f["accion"] == "venta"]
    parciales = [f for f in filas if f["accion"] == "parcial"]
    if compras:
        lineas.append("Desde ya sigo " + ("sus noticias" if len(compras) == 1 else "las noticias de " +
                      ", ".join(f["ticker"] for f in compras)) + ", alertas y calendario de resultados.")
    if ventas:
        lineas.append("Dejo de seguir " + ", ".join(f["ticker"] for f in ventas) + " en noticias y calendario.")
    if parciales:
        lineas.append("Como aún le quedan, sigo " + ", ".join(f["ticker"] for f in parciales) + " en noticias y alertas.")
    sin_cant = [f for f in compras if not f["cantidad"]]
    pregunta = ""
    if len(filas) == 1:
        _guardar_estado("detalle", {"id": filas[0]["id"]})
    if sin_cant and len(filas) == 1:
        lineas.append("Para que entre en los porcentajes de /portafolio dígame cuántas fueron (ej. «fueron 3 acciones a "
                      "140»); si no, la tomo de su próximo informe de XTB.")
    elif any(f["precio_aprox"] for f in compras):
        lineas.append("Usé el precio de ahora como precio de compra; si fue otro, dígame «a 140».")
    alertas_ids = []
    for f in ventas:
        alertas_ids += _alertas_de(f["ticker"])
    if alertas_ids:
        _guardar_estado("alertas", {"ids": alertas_ids, "tickers": [f["ticker"] for f in ventas]})
        pregunta = ("Tiene " + str(len(alertas_ids)) + (" alerta" if len(alertas_ids) == 1 else " alertas") + " de " +
                    ", ".join(f["ticker"] for f in ventas) + ": ¿las borro? (sí / no)")
    decididas = [f for f in filas if f["decision"]]
    if decididas:
        lineas.append("📓 Guardé el motivo en su diario de decisiones (#" +
                      ", #".join(str(f["decision"]) for f in decididas) + ").")
    elif len(filas) == 1:
        _guardar_estado("motivo", {"id": filas[0]["id"]})
        lineas.append("Si quiere guardar el motivo en su diario, respóndame «porque …».")
    if pregunta:
        lineas.append(pregunta)
    return "\n".join(lineas)


def registrar(entendido):
    """Guarda lo entendido (o pide confirmar un nombre que solo encontró en Yahoo)."""
    cambios = entendido["cambios"]
    por_buscar = [c for c in cambios if c.get("buscar") or not c.get("seguro", True)]
    if por_buscar:
        c = por_buscar[0]
        consulta = c.get("buscar") or c["ticker"]
        hallado = buscar_yahoo(consulta)
        if not hallado:
            return ("No reconozco «" + consulta + "» como una acción, señor. Dígame su ticker (ej. «compré NVDA») y "
                    "la anoto.")
        c.update(ticker=hallado[0], nombre=hallado[1], seguro=True)
        c.pop("buscar", None)
        _guardar_estado("confirmar", {"entendido": entendido})
        verbo = {"compra": "compró", "venta": "vendió", "parcial": "vendió parte de"}[c["accion"]]
        return ("¿Se refiere a " + hallado[0] + " (" + hallado[1] + ")? Si es así, anoto que " + verbo + " " +
                hallado[0] + ". Respóndame «sí» o «no».")
    ya = []
    if any(c.get("es_estado") for c in cambios):           # «ya tengo Meta»: si ya estaba, no se duplica
        tiene, _ = tenencias()
        ya = [c for c in cambios if c.get("es_estado") and c["accion"] == "compra" and c["ticker"] in tiene]
        cambios = [c for c in cambios if c not in ya]
    if not cambios:
        return "Sí, señor: " + ", ".join(c["ticker"] for c in ya) + " ya " + ("está" if len(ya) == 1 else "están") + \
            " en su portafolio. Si compró más, dígame «compré más " + ya[0]["ticker"] + "»."
    ids = [guardar(c, entendido.get("texto", ""), entendido.get("motivo", "") if len(cambios) == 1 else "")
           for c in cambios]
    return _respuesta(ids, entendido.get("motivo", ""))


# ------------------------------------------------------------------ respuestas cortas y consultas ---
SI = re.compile(r"^(?:si|sip|sii+|claro|correcto|exacto|eso|esa|ese|esa\s+misma|asi\s+es|dale|ok|okay|confirmo|"
                r"afirmativo|de\s+acuerdo|bueno|va|hazlo|borralas?|si\s+(?:es\s+)?(?:esa|ese|eso|correcto|claro|"
                r"borralas?|porfa|por\s+favor|hazlo|dale))(?:\s+(?:senor|jarvis|gracias|por\s+favor|porfa))?$")
NO = re.compile(r"^(?:no|nop|nope|negativo|no\s+es\s+(?:esa|ese|eso)|no\s+es|ninguna|incorrecto|dejalas?|"
                r"no\s+(?:las\s+)?borres|no\s+gracias|mejor\s+no|no\s+(?:senor|jarvis))$")
CANTIDAD_SOLA = re.compile(r"^(?:fueron|son|eran|era|fue|compre|eran\s+unas|unas|como)?\s*"
                           r"(\d+(?:\.\d+)?|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|quince|"
                           r"veinte|treinta|cincuenta|cien|media)\s+(?:acciones|accion|titulos?)"
                           r"(?:\s+(?:a|en|por)\s+\$?(\d+(?:\.\d+)?)\s*(?:dolares|usd|\$)?(?:\s+cada\s+una)?)?$")
PRECIO_SOLO = re.compile(r"^(?:a|las\s+compre\s+a|la\s+compre\s+a|el\s+precio\s+fue(?:\s+de)?|me\s+salieron\s+a|me\s+salio\s+a|"
                         r"pague|fue\s+a|fueron\s+a|precio)\s+\$?(\d+(?:\.\d+)?)\s*(?:dolares|usd|\$)?"
                         r"(?:\s+(?:cada\s+una|c/u|por\s+accion|la\s+accion))?$")
MOTIVO_SOLO = re.compile(r"^(?:(?:la|las|lo|los)\s+(?:compre|vendi)\s+)?(?:porque|por\s+que|ya\s+que|debido\s+a(?:\s+que)?|"
                         r"motivo\s*:|el\s+motivo\s+(?:es|fue)\s*:?|la\s+razon\s+(?:es|fue)\s*:?)\s+(.{3,})$")
DESHAZ = re.compile(r"^(?:deshaz|deshacer|anula|cancela|revierte|borra|elimina|quita)(?:lo)?\s+(?:lo\s+ultimo|eso|ese\s+cambio|"
                    r"el\s+ultimo\s+cambio|ese|lo\s+que\s+(?:anotaste|registraste)|lo\s+anterior)$|"
                    r"^(?:me\s+equivoque|eso\s+no|no\s+era\s+eso|era\s+broma|error)$")
NO_HICE = re.compile(r"^(?:no|nunca)\s+(?:compre|vendi|he\s+comprado|he\s+vendido)\s+(.+)$|"
                     r"^(?:deshaz|anula|cancela|borra|elimina|quita)\s+(?:la\s+|el\s+)?(?:compra|venta|cambio)\s+(?:de\s+|del\s+)?(.+)$|"
                     r"^(?:sigo\s+teniendo|todavia\s+tengo|aun\s+tengo)\s+(.+)$")
LISTA = re.compile(r"^(?:que|cuales)\s+(?:acciones|empresas)\s+tengo(?:\s+(?:ahora|ahorita|hoy|en\s+(?:mi\s+)?(?:portafolio|cartera|xtb)))?$|"
                   r"^(?:mis|ver\s+mis|lista\s+de\s+(?:mis\s+)?)\s*acciones$|^que\s+tengo\s+en\s+(?:mi\s+)?(?:portafolio|cartera|xtb)$|"
                   r"^(?:mis\s+)?cambios\s+(?:del|de\s+mi|en\s+mi|en\s+el)\s+(?:portafolio|cartera)$|"
                   r"^que\s+(?:cambie|cambios\s+hice|he\s+cambiado)\s+en\s+(?:mi\s+)?(?:portafolio|cartera)$|"
                   r"^(?:cuales\s+son\s+)?(?:mis|las)\s+(?:acciones|empresas)(?:\s+que\s+tengo)?(?:\s+ahora)?$")
TENGO = re.compile(r"^(?:todavia\s+|aun\s+|sigo\s+teniendo\s+|ya\s+)?(?:tengo|tenia)\s+(?:acciones\s+de\s+|algo\s+de\s+)?(.+?)"
                   r"(?:\s+en\s+(?:mi\s+)?(?:portafolio|cartera|xtb))?$|^(?:esta|sigue)\s+(.+?)\s+en\s+(?:mi\s+)?(?:portafolio|cartera)$")


def texto_lista():
    tiene, fecha = tenencias()
    lineas = ["📋 Sus acciones" + (" (informe de XTB del " + fecha.strftime("%d/%m") + " + lo que me contó)" if fecha else "") + ":"]
    if tiene:
        lineas += ["• " + t + (" " + n if n and n.upper() != t else "") for t, n in sorted(tiene.items())]
    else:
        lineas.append("No tengo ninguna registrada. Exporte su informe en xStation 5 o dígame «compré …».")
    cambios = activos(fecha)
    if cambios:
        lineas += ["", "✍️ Cambios desde su último informe:"]
        lineas += ["• " + c["creado"][8:10] + "/" + c["creado"][5:7] + " " + _linea_cambio(c) for c in cambios]
        lineas.append("Cuando llegue un informe nuevo de XTB, el informe manda.")
    lineas.append("\nPorcentajes y ganancias: /portafolio")
    return "\n".join(lineas)


def _tengo(nombre_txt, original):
    tiene, _ = tenencias()
    mayus = {w for w in re.findall(r"\b[A-Z]{2,5}\b", original) if w not in NO_TICKER}
    r = _resolver(normalizar(nombre_txt), mayus)
    if not r or not r.get("ticker") or r["sobra"]:
        return None
    t = r["ticker"]
    if t in tiene:
        return "Sí, señor: " + t + (" (" + tiene[t] + ")" if tiene[t] and tiene[t].upper() != t else "") + \
            " está en su portafolio."
    return "No, señor: " + t + " no está en su portafolio. Si la compró, dígame «compré " + t + "»."


def deshacer(cid):
    f = _obtener(cid)
    if not f or f["estado"] != "activo":
        return "No encuentro ese cambio, señor."
    with _con() as con:
        con.execute("UPDATE portafolio_cambios SET estado='deshecho' WHERE id=?", (cid,))
    _borrar_estado("detalle", "motivo", "alertas")
    _olvidar_caches()
    extra = " La decisión #" + str(f["decision"]) + " del diario sigue anotada." if f["decision"] else ""
    return "↩️ Listo, quité el cambio: " + _linea_cambio(f) + "." + extra


def _ultima_respuesta_mia(minutos=15):
    try:
        from modulos.ia import memoria
        previa = memoria.historial(1)
        return bool(previa) and previa[-1]["role"] == "assistant" and previa[-1]["content"].startswith(MARCA)
    except Exception:
        f = ultimo()
        return bool(f) and datetime.now() - datetime.fromisoformat(f["creado"]) < timedelta(minutes=minutos)


def _respuesta_corta(t, original):
    """sí / no / cantidad / precio / motivo justo después de un cambio. None si no aplica."""
    pendiente = _estado("confirmar", 10)
    if pendiente:
        if SI.match(t):
            _borrar_estado("confirmar")
            return registrar(pendiente["entendido"])
        if NO.match(t):
            _borrar_estado("confirmar")
            return "Entendido, no anoto nada. Dígame el ticker exacto (ej. «compré NVDA») y lo registro."
    alertas = _estado("alertas", 15)
    if alertas:
        if SI.match(t):
            _borrar_estado("alertas")
            from modulos.alertas import alertas as al
            n = sum(1 for aid in alertas["ids"] if al.borrar(aid))
            return "🗑 Borré " + str(n) + (" alerta" if n == 1 else " alertas") + " de " + ", ".join(alertas["tickers"]) + "."
        if NO.match(t):
            _borrar_estado("alertas")
            return "De acuerdo, las alertas siguen activas. Las ve con «mis alertas»."
    detalle = _estado("detalle", 20)
    if detalle:
        f = _obtener(detalle["id"])
        m = CANTIDAD_SOLA.match(t)
        p = PRECIO_SOLO.match(t)
        if f and f["estado"] == "activo" and (m or p):
            cantidad = _num(m.group(1)) if m else f["cantidad"]
            precio = float(m.group(2)) if m and m.group(2) else (float(p.group(1)) if p else None)
            aprox = 0
            if precio is None:
                precio = f["precio"] if f["precio"] and not f["precio_aprox"] else None
            if precio is None and cantidad and f["accion"] == "compra":
                precio, aprox = _precio_actual(f["ticker"]), 1
            with _con() as con:
                con.execute("UPDATE portafolio_cambios SET cantidad=?, precio=?, precio_aprox=? WHERE id=?",
                            (cantidad, precio, aprox, f["id"]))
            _olvidar_caches()
            g = _obtener(f["id"])
            texto = MARCA + " corregido: " + _linea_cambio(g) + "."
            if aprox:
                texto += " Usé el precio de ahora como precio de compra; si fue otro, dígame «a 140»."
            elif g["accion"] == "compra" and g["cantidad"] and g["precio"]:
                texto += " Ya entra en los porcentajes de /portafolio."
            return texto
    motivo = _estado("motivo", 30)
    if motivo:
        m = MOTIVO_SOLO.match(t)
        if m:
            f = _obtener(motivo["id"])
            _borrar_estado("motivo")
            if f and not f["decision"]:
                did = _decision(f["ticker"], f["accion"], None if f["precio_aprox"] else f["precio"], m.group(1).strip(" ."))
                if did:
                    with _con() as con:
                        con.execute("UPDATE portafolio_cambios SET decision=? WHERE id=?", (did, f["id"]))
                    return ("📓 Anotado en su diario (decisión #" + str(did) + "): " + _linea_cambio(f) + ". En 1, 3 y 6 "
                            "meses le cuento cómo le fue frente al S&P 500.")
    return None


def procesar(texto):
    """Entrada única desde el cerebro (texto, nota de voz o voz). Devuelve la respuesta o None."""
    original = (texto or "").strip()
    if not original:
        return None
    t = normalizar(original)
    try:
        corta = _respuesta_corta(t, original)
        if corta:
            return corta
        if LISTA.match(t):
            return texto_lista()
        if DESHAZ.match(t) and _ultima_respuesta_mia():
            f = ultimo()
            return deshacer(f["id"]) if f else None
        pregunta = "?" in original or "¿" in original
        m = NO_HICE.match(t)
        if m and not (pregunta and t.startswith(("sigo", "todavia", "aun"))):
            cual = next(g for g in m.groups() if g)
            mayus = {w for w in re.findall(r"\b[A-Z]{2,5}\b", original) if w not in NO_TICKER}
            r = _resolver(cual, mayus)
            if r and r.get("ticker"):
                with _con() as con:
                    f = con.execute("SELECT * FROM portafolio_cambios WHERE estado='activo' AND ticker=? ORDER BY id DESC "
                                    "LIMIT 1", (r["ticker"],)).fetchone()
                if f:
                    return deshacer(f["id"])
                if not t.startswith(("sigo", "todavia", "aun")):
                    return "No tengo ningún cambio reciente de " + r["ticker"] + " que deshacer, señor."
        if pregunta or (t.startswith(("tengo acciones de", "todavia tengo", "aun tengo"))):
            m = TENGO.match(t)
            if m and not re.search(r"\b(?:que|cuantas?|cuantos?|clases?|tareas?|deberes|deber|deudas?|gastos?|agenda|reunion|"
                                   r"examen|cita|tiempo|hambre|frio|sueno|dinero|plata)\b", t):
                r = _tengo(next(g for g in m.groups() if g), original)
                if r:
                    return r
        entendido = interpretar(original)
        if entendido:
            return registrar(entendido)
    except Exception as exc:
        log.warning("Cambios del portafolio fallo: %s", exc)
        return None
    return None


def conciliar_con_ultimo():
    """Tras recoger un informe nuevo de XTB: cuántos cambios contados ya vienen en él."""
    _excel["clave"] = None
    return conciliar()
