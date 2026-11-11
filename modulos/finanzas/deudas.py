"""Finanzas, paso 1: deudas (quien me debe y a quien le debo), pagos, cuotas y comprobantes.

- Todo en la base local (tablas 'deudas', 'deuda_movimientos', 'comprobantes'); las fotos en
  la carpeta privada (rutas.json → pesado\\finanzas\\comprobantes). Nada de montos va a Google (solo "Cobro: Juan").
- Las frases se entienden en CODIGO (rapido y exacto, tambien en modo juego), con muchas formas de decirlo;
  si el codigo no entiende una frase que habla de deudas, la IA la pasa a datos y el codigo valida los montos.
  Varios montos por mes y suma mensual automatica: "la empresa me debe 683.05 de septiembre y 725.10 de octubre,
  y cada mes se suman 726.10" (cuenta por cobrar que crece sola; los pagos se aplican al mes que diga o al mas viejo).
    "Juan me debe 500 por la laptop"        "le preste 50 a Ana"         "le debo 200 a mi tio"
    "Juan me pago 100"  "Juan me abono 50"  "le pague 80 a mi tio"
    "Juan paga 100 cada 15" / "... cada mes el 15"   "Juan me debe 300 para el 30/11"
    "cuanto me debe Juan"  "quien me debe"  "cuanto le debo a mi tio"  "mis deudas"
  Lo demas lo resuelve la IA con las herramientas registrar_deuda / registrar_pago_deuda / ver_deudas.
- Las cuentas las hace el codigo: saldo = cargos - pagos.
"""
import re
import shutil
import unicodedata
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from modulos.comun import db
from modulos.comun.base import RAIZ, ahora, registro

log = registro("finanzas")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS deudas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    persona    TEXT NOT NULL,
    sentido    TEXT NOT NULL,              -- me_debe | le_debo
    concepto   TEXT DEFAULT '',
    limite     TEXT,                       -- fecha limite AAAA-MM-DD (opcional)
    cuota      REAL,                       -- monto de cada cuota (opcional)
    dia_cuota  INTEGER,                    -- dia del mes en que paga (opcional)
    estado     TEXT DEFAULT 'abierta',     -- abierta | saldada | borrada
    creada     TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS deuda_movimientos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deuda       INTEGER NOT NULL,
    tipo        TEXT NOT NULL,             -- cargo | pago
    monto       REAL NOT NULL,
    fecha       TEXT NOT NULL,             -- AAAA-MM-DD
    nota        TEXT DEFAULT '',
    comprobante TEXT DEFAULT '',           -- ruta de la foto en la PC
    creado      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS comprobantes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ruta    TEXT NOT NULL,
    estado  TEXT DEFAULT 'pendiente',      -- pendiente | usado | suelto
    creado  TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

from modulos.comun.base import PESADO  # noqa: E402

CARPETA_DATOS = PESADO / "finanzas" / "comprobantes"


def carpeta_comprobantes():
    c = CARPETA_DATOS if Path(CARPETA_DATOS.drive + "\\").exists() else RAIZ / "datos" / "comprobantes"
    c.mkdir(parents=True, exist_ok=True)
    return c


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    columnas = {c[1] for c in con.execute("PRAGMA table_info(deudas)")}
    for nombre, tipo in (("recurrente", "REAL"), ("dia_recurrente", "INTEGER"), ("ultimo_mes", "TEXT")):
        if nombre not in columnas:                    # suma mensual automática (p. ej. sueldo atrasado de la empresa)
            con.execute("ALTER TABLE deudas ADD COLUMN " + nombre + " " + tipo)
    return con


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn").strip()


def dinero(x):
    """'1.250,50' / '1,250.50' / '12,5' / '$500' -> float."""
    t = str(x).replace("$", "").replace("usd", "").replace(" ", "").strip()
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        ent, _, dec = t.rpartition(",")
        t = ent.replace(",", "") + "." + dec if len(dec) <= 2 else t.replace(",", "")
    elif t.count(".") > 1 or (t.count(".") == 1 and len(t.split(".")[1]) == 3):
        t = t.replace(".", "")                                  # 1.250 = mil doscientos cincuenta
    return round(float(t), 2)


def fmt(x):
    """500 -> '$500'; 12.5 -> '$12,50'."""
    if abs(x - round(x)) < 0.005:
        texto = "{:,.0f}".format(x)
    else:
        texto = "{:,.2f}".format(x)
    return "$" + texto.replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------------------------------------------------------ base de datos ---
def abiertas(persona=None, sentido=None):
    with closing(_con()) as con:
        filas = con.execute("SELECT * FROM deudas WHERE estado = 'abierta' ORDER BY persona, id").fetchall()
    filas = [dict(f) for f in filas]
    if sentido:
        filas = [f for f in filas if f["sentido"] == sentido]
    if persona:
        p = _norm(persona)
        exactas = [f for f in filas if _norm(f["persona"]) == p]
        filas = exactas or [f for f in filas if _norm(f["persona"]).startswith(p) or p.startswith(_norm(f["persona"]))]
    return filas


def movimientos(did):
    with closing(_con()) as con:
        return [dict(m) for m in con.execute("SELECT * FROM deuda_movimientos WHERE deuda = ? ORDER BY fecha, id", (did,))]


def saldo(did):
    ms = movimientos(did)
    return round(sum(m["monto"] for m in ms if m["tipo"] == "cargo") - sum(m["monto"] for m in ms if m["tipo"] == "pago"), 2)


def _nombre_bonito(persona):
    persona = " ".join(persona.split()).strip(" .,:;")
    existentes = {_norm(d["persona"]): d["persona"] for d in abiertas()}
    if _norm(persona) in existentes:
        return existentes[_norm(persona)]
    if persona.lower().startswith(("mi ", "el ", "la ")):
        return persona[:1].lower() + persona[1:]
    return " ".join(w[:1].upper() + w[1:] for w in persona.split())


def _comprobante_reciente():
    """Foto enviada en los ultimos 15 minutos que aun no se uso."""
    limite = (datetime.utcnow() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    with closing(_con()) as con, con:
        f = con.execute("SELECT * FROM comprobantes WHERE estado = 'pendiente' AND creado >= ? ORDER BY id DESC LIMIT 1",
                        (limite,)).fetchone()
        if f:
            con.execute("UPDATE comprobantes SET estado = 'usado' WHERE id = ?", (f["id"],))
            return f["ruta"]
    return ""


def guardar_comprobante(origen):
    """Mueve una foto (descargada por el bot) a la carpeta de comprobantes y la deja pendiente de asociar."""
    destino = carpeta_comprobantes() / (ahora().strftime("%Y-%m-%d_%H%M%S") + Path(origen).suffix.lower())
    shutil.move(str(origen), destino)
    with closing(_con()) as con, con:
        con.execute("INSERT INTO comprobantes (ruta) VALUES (?)", (str(destino),))
    return destino


def crear(persona, monto, sentido="me_debe", concepto="", limite=None, cuota=None, dia_cuota=None, fecha=None):
    persona = _nombre_bonito(persona)
    with closing(_con()) as con, con:
        did = con.execute("INSERT INTO deudas (persona, sentido, concepto, limite, cuota, dia_cuota) VALUES (?, ?, ?, ?, ?, ?)",
                          (persona, sentido, concepto.strip()[:120], limite, cuota, dia_cuota)).lastrowid
        con.execute("INSERT INTO deuda_movimientos (deuda, tipo, monto, fecha, nota, comprobante) VALUES (?, 'cargo', ?, ?, ?, ?)",
                    (did, monto, (fecha or ahora().date()).isoformat(), concepto.strip()[:120], _comprobante_reciente()))
    return did


def agregar_cargo(did, monto, concepto="", fecha=None):
    with closing(_con()) as con, con:
        con.execute("INSERT INTO deuda_movimientos (deuda, tipo, monto, fecha, nota, comprobante) VALUES (?, 'cargo', ?, ?, ?, ?)",
                    (did, monto, (fecha or ahora().date()).isoformat(), concepto.strip()[:120], _comprobante_reciente()))
        con.execute("UPDATE deudas SET estado = 'abierta' WHERE id = ? AND estado = 'saldada'", (did,))


def pagar(did, monto, nota="", fecha=None):
    """Registra un pago. Devuelve (saldo_nuevo, sobrante). Si llega a 0, la deuda queda saldada."""
    actual = saldo(did)
    aplicado = min(monto, actual) if actual > 0 else monto
    with closing(_con()) as con, con:
        con.execute("INSERT INTO deuda_movimientos (deuda, tipo, monto, fecha, nota, comprobante) VALUES (?, 'pago', ?, ?, ?, ?)",
                    (did, aplicado, (fecha or ahora().date()).isoformat(), nota[:120], _comprobante_reciente()))
        nuevo = round(actual - aplicado, 2)
        if nuevo <= 0:
            con.execute("UPDATE deudas SET estado = 'saldada' WHERE id = ?", (did,))
    return nuevo, round(monto - aplicado, 2)


def actualizar(did, **campos):
    with closing(_con()) as con, con:
        con.execute("UPDATE deudas SET " + ", ".join(k + " = ?" for k in campos) + " WHERE id = ?", (*campos.values(), did))


def obtener(did):
    with closing(_con()) as con:
        f = con.execute("SELECT * FROM deudas WHERE id = ?", (did,)).fetchone()
    return dict(f) if f else None


# ------------------------------------------------------------------ textos ---
def _cap(t):
    return t[:1].upper() + t[1:] if t else t


def _fecha_corta(iso):
    d = date.fromisoformat(iso)
    return d.strftime("%d/%m") + ("" if d.year == ahora().year else "/" + str(d.year))


def detalle(d):
    """Texto (sin HTML) de una deuda con su historial."""
    s = saldo(d["id"])
    quien = d["persona"]
    lineas = [(_cap(quien) + " le debe " if d["sentido"] == "me_debe" else "Usted le debe a " + quien + " ") + fmt(s)
              + (" (" + d["concepto"] + ")" if d["concepto"] else "")]
    extra = []
    if d["cuota"] and d["dia_cuota"]:
        extra.append("cuota de " + fmt(d["cuota"]) + " cada " + str(d["dia_cuota"]) + " del mes")
    if d["limite"]:
        extra.append("fecha l\u00edmite " + _fecha_corta(d["limite"]))
    if d.get("recurrente"):
        extra.append("se suman " + fmt(d["recurrente"]) + " cada mes (el " + str(d.get("dia_recurrente") or 1) + ")")
    if extra:
        lineas.append("   " + "; ".join(extra))
    meses = por_mes(d["id"])
    if sum(1 for n, *_ in meses if n and re.search(r"\d{4}$", n)) >= 2:          # cuenta por meses: estado de cada uno
        for nota, cargo, pagado, pendiente in meses:
            lineas.append("   " + (nota or "—") + ": " + fmt(cargo) + ("  ✅ pagado" if pendiente <= 0 else
                          "  (pagado " + fmt(pagado) + ", falta " + fmt(pendiente) + ")" if pagado else "  ⏳ pendiente"))
        pagos = [m for m in movimientos(d["id"]) if m["tipo"] == "pago"]
        for m in pagos:
            lineas.append("   " + _fecha_corta(m["fecha"]) + "  pago −" + fmt(m["monto"]) + ("  " + m["nota"] if m["nota"] else ""))
        return "\n".join(lineas)
    for m in movimientos(d["id"]):
        lineas.append("   " + _fecha_corta(m["fecha"]) + "  " + ("+" if m["tipo"] == "cargo" else "\u2212") + fmt(m["monto"])
                      + ("  " + m["nota"] if m["nota"] and m["tipo"] == "pago" else "")
                      + ("  \U0001F4CE" if m["comprobante"] else ""))
    return "\n".join(lineas)


def resumen(sentido=None):
    me = abiertas(sentido="me_debe")
    yo = abiertas(sentido="le_debo")
    partes = []
    if sentido in (None, "me_debe"):
        if me:
            total = sum(saldo(d["id"]) for d in me)
            partes.append("\U0001F4B0 Le deben " + fmt(total) + ":\n" + "\n".join(
                "\u2022 " + d["persona"] + ": " + fmt(saldo(d["id"])) + (" (" + d["concepto"] + ")" if d["concepto"] else "")
                for d in me))
        elif sentido:
            partes.append("Nadie le debe dinero ahora, se\u00f1or.")
    if sentido in (None, "le_debo"):
        if yo:
            total = sum(saldo(d["id"]) for d in yo)
            partes.append("\U0001F4B8 Usted debe " + fmt(total) + ":\n" + "\n".join(
                "\u2022 A " + d["persona"] + ": " + fmt(saldo(d["id"])) + (" (" + d["concepto"] + ")" if d["concepto"] else "")
                for d in yo))
        elif sentido:
            partes.append("Usted no le debe nada a nadie, se\u00f1or.")
    if not partes:
        return "No tiene deudas registradas, se\u00f1or. Ejemplo: \u00abJuan me debe 500 por la laptop\u00bb."
    if sentido is None and me and yo:
        neto = sum(saldo(d["id"]) for d in me) - sum(saldo(d["id"]) for d in yo)
        partes.append("Balance: " + ("a su favor " if neto >= 0 else "en contra ") + fmt(abs(neto)))
    return "\n\n".join(partes)


# ------------------------------------------------------------------ entender frases ---
# El código entiende la gran mayoría de formas de decirlo (rápido, exacto, también en modo juego).
# Lo que no entiende pero huele a deuda lo pasa a la IA, que solo devuelve datos; el código valida y ejecuta.
MESES = {"enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "abril": 4, "abr": 4, "mayo": 5, "junio": 6,
         "jun": 6, "julio": 7, "jul": 7, "agosto": 8, "ago": 8, "septiembre": 9, "setiembre": 9, "sept": 9, "sep": 9,
         "octubre": 10, "oct": 10, "noviembre": 11, "nov": 11, "diciembre": 12, "dic": 12}
NOMBRE_MES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
              "Noviembre", "Diciembre"]
MES = r"\b(" + "|".join(sorted(MESES, key=len, reverse=True)) + r")\b"
NUM = r"(?<![\d/])\$?\s?(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![\d/])(?:\s?(?:dolares|dolar|usd|\$|lucas|pesos))?"
MONTO = NUM                                                     # compatibilidad con otros módulos
RECURRE = (r"(?:cada mes|todos los meses|mensualmente|mes a mes|por mes|al mes|cada fin de mes|cada inicio de mes|"
           r"de forma mensual|mensual|cada vez que (?:llegue|pase|empiece|entre|termine|acabe|se cumpla) (?:otro|un|el|cada) mes|"
           r"cada (?:nuevo )?mes que (?:pasa|llega|termina)|cuando (?:llegue|empiece|termine|pase) (?:otro|el|cada) mes)")
SUMA = r"(?:se (?:suma|sumen|sumara|agrega|agregue|agregara|aumenta|acumula|anade)|suma|sumale|sumar|agrega|agregale|aumenta|acumula|anade|sube)"
RELLENO = (r"^(?:oye|hey|ey|hola|jarvis|asistente|por favor|porfa|porfavor|mira|bueno|ok|okay|oiga|senor|una cosa|"
           r"anota(?:r|me)?(?: que)?|apunta(?:r|me)?(?: que)?|registra(?:r|me)?(?: que)?|guarda(?:r|me)?(?: que)?|"
           r"recuerda(?:r|me)?(?: que)?|quiero (?:anotar|registrar|que anotes|que registres|que sepas)(?: que)?|"
           r"necesito (?:anotar|registrar|saber)(?: que)?|toma nota(?: de que)?|agrega que|pon que|"
           r"ten en cuenta(?: que)?|sabes que|te cuento que|para que sepas(?: que)?|ojo)\b[\s,:.-]*")
NO_PERSONA = {"yo", "usted", "tu", "el", "ella", "me", "le", "les", "se", "nos", "cuanto", "cuantos", "quien", "quienes",
              "que", "eso", "esto", "esa", "ese", "todo", "nada", "algo", "plata", "dinero", "ya", "alguien", "nadie",
              "mes", "meses", "cada", "total", "lo", "un", "una", "y", "pero", "tambien", "aun", "todavia", "hoy", "ayer",
              "manana", "deuda", "deudas", "saldo", "pago", "pagos", "cuenta", "cuentas", "dolares", "usd", "favor",
              "senor", "jarvis", "si", "no", "como", "cual", "cuales", "donde", "cuando", "debe", "deben", "debo",
              "por", "de", "del", "a", "al", "en", "con", "para", "mis", "mi", "su", "sus", "estos", "estas", "ahora",
              "primero", "luego", "despues", "otro", "otra", "cobrar", "pendiente", "pendientes", "anterior", "pasado",
              "vez", "veces", "dia", "dias", "semana", "ano", "anos", "ya me", "eso me", "tengo", "dime", "decime",
              "muestrame", "ensename", "oye", "sabes", "puedes", "decirme", "dices", "sueldo", "salario", "quincena",
              "bono", "aguinaldo", "decimo", "utilidades", "arriendo", "luz", "agua", "internet", "plata",
              "paquete", "pedido", "favor", "tarea", "examen", "falta", "faltan", "hay", "tienes", "tiene", "estoy",
              "esta", "estan", "mucho", "poco", "lo de", "cobro", "cuenta por cobrar", "es", "son", "fue", "era", "eran",
              "lo", "los", "tanto", "tanta"}
ARTICULOS = ("el ", "la ", "los ", "las ", "mi ", "mis ", "don ", "dona ", "su ")
PISTA = re.compile(r"\b(?:debe|deben|debo|debia|debian|debemos|debiendo|deuda|deudas|adeud\w*|prest\w*|por cobrar|cobrar(?:le)?|cobre|"
                   r"tiene(?:n)? que (?:pagar|devolver)|tengo que (?:pagar|devolver)|pagarle|devolverle|pagarme|devolverme|"
                   r"abon\w*|me pag\w*|le pag\w*|me devolv\w*|le devolv\w*|me cancel\w*|cuentas? por)\b")
VERBO_SUJETO = (r"(?:me|nos)\s+(?:debe|deben|adeuda|adeudan|sigue(?:n)? debiendo|queda(?:n)? debiendo|quedo debiendo|quedaron debiendo|"
                r"hizo (?:una transferencia|un deposito|el pago)|hicieron (?:una transferencia|un deposito|el pago)|pidio|pidieron|esta(?:n)? debiendo|tiene(?:n)? que "
                r"(?:pagar|devolver)|pidio prestado|pidieron prestado|pago|pagaron|abono|abonaron|devolvio|devolvieron|"
                r"dio|dieron|deposito|depositaron|transfirio|transfirieron|mando|mandaron|paso|pasaron|cancelo|cancelaron|"
                r"presto|prestaron|debia|debian)\b|tiene(?:n)? que (?:pagarme|devolverme)\b")


def _limpiar(texto):
    t = _norm(texto)
    t = re.sub(r"[¿?¡!\"“”«»()]", " ", t)
    t = re.sub(r"\b(\d+)\s+con\s+(\d{1,2})\b", r"\1.\2", t)          # "683 con 05"
    t = re.sub(r"\$\s+(\d)", r"$\1", t)
    t = re.sub(r"\b(?:q|k|ke)\b", "que", t)                         # "tengo q pagarle"
    t = re.sub(r"\bxq\b|\bpq\b", "porque", t)
    t = " ".join(t.split())
    anterior = None
    while anterior != t:
        anterior = t
        t = re.sub(RELLENO, "", t).strip(" ,.:;-")
    t = re.sub(r"[\s,]+(?:senor|gracias|porfa|por favor|please|jarvis)\s*\.?$", "", t)
    return t.strip(" ,;")


def _es_persona(p):
    if not p:
        return False
    palabras = p.split()
    if not palabras or palabras[0] in NO_PERSONA and len(palabras) == 1:
        return False
    nucleo = [w for w in palabras if w not in ("el", "la", "los", "las", "mi", "mis", "su", "don", "dona")]
    return bool(nucleo) and not any(w in NO_PERSONA or w in MESES or re.fullmatch(r"\$?\d[\d.,]*", w) for w in nucleo)


def _recortar_persona(p):
    """'la empresa que estoy' -> 'la empresa'; 'juan ya' -> 'juan'."""
    p = " " + p.strip(" ,.;:") + " "
    p = re.split(r"\s(?:que|donde|en la que|en el que|para la que|para el que|con la que|con el que|con quien|"
                 r"la cual|el cual|quien|porque|pues|ya|todavia|aun|tambien|entonces|y|pero|o|por|para|hoy|ayer|"
                 r"desde|hace|el lunes|el martes|el miercoles|el jueves|el viernes|el sabado|el domingo)\s", p)[0]
    palabras = p.split()
    while palabras and palabras[-1] in NO_PERSONA:
        palabras.pop()
    while palabras and (palabras[0] in ("y", "pero", "que", "o", "entonces", "ademas", "tambien", "eso", "ya") or
                        palabras[0] in NO_PERSONA and palabras[0] not in ("el", "la", "los", "las", "mi", "mis", "su")):
        palabras.pop(0)                                    # "cada mes la empresa" -> "la empresa"
    if len(palabras) > 5 or (len(palabras) > 4 and "de" not in palabras):
        palabras = palabras[-3:] if palabras[-3] in ("el", "la", "mi", "los", "las") else palabras[-2:]
    return " ".join(palabras)


def _persona(t):
    """Busca a la persona (o empresa) en cualquier parte de la frase."""
    candidatos = []
    inicio = re.match(r"^((?:el |la |mi |los |las )?[a-z\u00f1]+(?: [a-z\u00f1]+){0,2})\s*:", t)   # "la empresa: septiembre 683…"
    if inicio and _es_persona(_recortar_persona(inicio.group(1))):
        candidatos.append(_recortar_persona(inicio.group(1)))
    # 1) sujeto antes del verbo: "la empresa (que estoy) me debe", "juan ya me pago"
    for m in re.finditer(VERBO_SUJETO, t):
        antes = re.split(r"[,.;:]\s|\s\$?\d[\d.,]*\s|^\$?\d[\d.,]*\s", " " + t[:m.start()])[-1]
        p = _recortar_persona(antes)
        if _es_persona(p):
            candidatos.append(p)
    # 2) objeto: "le debo a mi tio", "le preste 50 a ana", "recibi 100 de juan", "cuanto me debe la empresa"
    m0 = re.match(r"^a\s+((?:el |la |mi |los |las )?[a-z\u00f1]+(?: [a-z\u00f1]+){0,2})\s+(?:les?|ya les?)\s+(?:debo|pague|devolvi|preste)", t)
    if m0 and _es_persona(_recortar_persona(m0.group(1))):          # "a mi tío le debo 200"
        candidatos.append(_recortar_persona(m0.group(1)))
    for m in re.finditer(r"\b(?=(a|al|a la|a los|con|con la|con el|de|del|de la|de los|desde|en)\s+((?:el |la |los |las |mi |mis |don |dona )?"
                         r"[a-zñ][a-zñ0-9]*(?:\s+[a-zñ][a-zñ0-9]*){0,2}))", t):   # (?=…): busca todas, aunque se solapen
        p = _recortar_persona(m.group(2))
        cabeza = t[max(0, m.start() - 60):m.start()]
        if _es_persona(p) and re.search(r"debo|debe|debia|debiendo|prest|pag|abon|devolv|cobr|recib|deposit|transfer|deuda|"
                                        r"dieron|dio|mand|cancel|adeud", cabeza):
            # "de" + nombre solo vale si hay un verbo de dinero cerca y no es "de la cena"
            if m.group(1) in ("de", "del", "de la", "de los", "desde") and not re.search(
                    r"recib\w*|cobr\w*|deuda|me llego|llego|pag\w*|cuanto|saldo|deposit\w*|transfer\w*", cabeza):
                continue
            candidatos.append(p)
    # 3) después del verbo: "cuanto me debe juan", "me debe 500 juan" (se quitan los montos para mirar)
    sin_montos = " ".join(re.sub(NUM, " ", t).split())
    for m in re.finditer(r"(?:me debe|me deben|me adeuda|le debo|les debo|me pago|me pagaron|me pague|me paguen|debe|deuda de|deudas de)\s+"
                         r"((?:el |la |los |las |mi |mis |don |dona )?[a-zñ][a-zñ0-9]*(?:\s+[a-zñ][a-zñ0-9]*){0,2})", sin_montos):
        p = _recortar_persona(re.split(r"\s(?:por|para|de|del|desde|hoy|ayer)\s", " " + m.group(1) + " ")[0])
        if _es_persona(p) and not p.startswith(("a ", "de ")):
            candidatos.append(p)
    if not candidatos:
        return None
    for c in candidatos:                                    # preferir a alguien que ya tiene deuda abierta
        if abiertas(_nombre_bonito(c)):
            return c
    return candidatos[0]


def _mes_cerca(t, ini, fin):
    """Mes justo después ('683 de septiembre', '683 del mes de septiembre') o justo antes ('septiembre: 683')."""
    despues = re.match(r"\s*(?:dolares\s+|usd\s+)?(?:que\s+)?(?:me deben\s+|me debe\s+)?(?:eso\s+)?(?:me deben\s+)?"
                       r"(?:de|del|en|por|para|correspondiente(?:s)? a(?:l)?|del mes de|de el mes de|por el mes de|mes de|"
                       r"el mes de|lo de|el de)?\s*(?:el mes de\s+|mes de\s+)?" + MES, t[fin:])
    if despues:
        return MESES[despues.group(1)]
    antes = re.search(MES + r"\s*(?:del?\s+\d{4}\s*)?[:=-]?\s*(?:son|fueron|es|eran|me deben|me debe|debe|deben|"
                            r"me quedaron debiendo|quedan)?\s*\$?\s*$", t[:ini])
    if antes and ini - antes.start() < 40:
        return MESES[antes.group(1)]
    return None


def _montos(t):
    """[(monto, mes|None, recurrente?)] en orden. Ignora días ('cada 15'), fechas ('30/11') y años."""
    salida = []
    # oraciones (punto o ';' que no sea decimal) y dentro de ellas partes separadas por ',' o ' y '
    oraciones = [(o.start(), o.end()) for o in re.finditer(r"(?:[^.;]|(?<=\d)\.(?=\d))+", t)]
    partes = []
    for oi, (a_, b_) in enumerate(oraciones):
        for p in re.finditer(r"(?:[^,]|(?<=\d),(?=\d))+?(?=,(?!\d)|\sy\s|$)", t[a_:b_]):
            if p.group().strip():
                partes.append((oi, a_ + p.start(), a_ + p.end()))
    def recurre(x):
        return bool(re.search(RECURRE, x) or (re.search(SUMA, x) and re.search(r"\bmes\b", x)))
    for m in re.finditer(NUM, t):
        crudo = m.group(1)
        previo = t[max(0, m.start() - 12):m.start()]
        siguiente = t[m.end():m.end() + 14]
        if re.search(r"(?:cada|\bel|\bdia|\bdias|todos los|hasta el|para el|antes del)\s*$", previo) and \
                re.fullmatch(r"\d{1,2}", crudo):
            continue                                        # "cada 15", "el 30"
        if re.fullmatch(r"(?:19|20)\d\d", crudo) and re.search(MES + r"\s*(?:de|del)?\s*$", t[max(0, m.start() - 16):m.start()]):
            continue                                        # año ("septiembre de 2026")
        if re.match(r"\s*(?:abonos?|pagos?|cuotas?|veces|meses|dias|semanas|anos|personas|tareas|horas|minutos|depositos?|"
                    r"transferencias?|partes|plazos|letras)\b", siguiente):
            continue                                        # "5 abonos": cantidad, no dinero
        if re.fullmatch(r"\d{1,2}", crudo) and re.match(r"\s*(?:de cada mes|del mes|de mes)\b(?!\s+de\s+[a-z])", t[m.end():m.end() + 30]):
            continue                                        # "el 15 de cada mes" (día, no monto)
        try:
            valor = dinero(crudo)
        except ValueError:
            continue
        if valor <= 0:
            continue
        idx = next((i for i, (_, a_, b_) in enumerate(partes) if a_ <= m.start() < b_), None)
        propia = t[partes[idx][1]:partes[idx][2]] if idx is not None else t
        previa = (t[partes[idx - 1][1]:partes[idx - 1][2]] if idx and partes[idx - 1][0] == partes[idx][0] else "")
        mes = _mes_cerca(t, m.start(), m.end())
        recurrente = recurre(propia) or (recurre(previa) and mes is None and
                                         (re.search(SUMA, propia) or len(propia.split()) <= 6))
        salida.append((valor, None if recurrente else mes, recurrente))
    return salida


def _anio_de(mes, hoy=None):
    hoy = hoy or ahora().date()
    return hoy.year if mes <= hoy.month else hoy.year - 1


def _concepto(t):
    m = re.search(r"\bpor\s+(?:el |la |los |las |un |una |unos |unas )?([a-zñ][a-zñ0-9 ]{2,40}?)(?=\s*(?:[,.;]|\s+y\s|\s+cada|"
                  r"\s+para|\s+hasta|\s+el\s+\d|$))", t)
    if m and not re.search(MES + r"|\bmes\b|cobrar|ciento|favor|ahora|eso|si acaso", m.group(1)):
        return m.group(1).strip()
    return ""


def _cuota(texto):
    m = re.search(r"\s*,?\s*(?:y\s+)?(?:me\s+)?(?:paga|pagara|va a pagar|pagare|pago|abona|abonara|da|dara)\s+" + NUM
                  + r"\s+(?:cada|todos los|el|los)\s+(\d{1,2})(?:\s+de cada mes|\s+del mes|\s+de mes)?\b", texto)
    if not m:
        return texto, None, None
    dia = int(m.group(2))
    return texto[:m.start()] + texto[m.end():], dinero(m.group(1)), dia if 1 <= dia <= 31 else None


def _limite(texto):
    m = re.search(r"\s*,?\s*(?:para el|hasta el|antes del|el)\s+(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b", texto)
    if not m:
        return texto, None
    from modulos.tareas.tareas import _fecha
    f, _ = _fecha(m.group(1))
    return texto[:m.start()] + texto[m.end():], (f.isoformat() if f else None)


def _dia_recurrente(t):
    m = re.search(r"(?:el|los|cada)\s+(\d{1,2})\s+(?:de cada mes|del mes|de mes)", t)
    if m and 1 <= int(m.group(1)) <= 28:
        return int(m.group(1))
    return 1


# --- tipos de frase ---
ES_PREGUNTA = re.compile(r"^(?:cuanto|cuanta|cuantos|que|quien|quienes|cual|cuales|a quien|a quienes|dime|dame|muestra|"
                         r"muestrame|ensename|ver|revisa|como (?:va|van|voy|esta|estan)|saldo|estado|detalle|tengo|hay|"
                         r"sabes|me puedes decir|puedes decirme|decime|me dices)\b|\bcuanto\b|\bcuanta\b|\bquien(?:es)?\b|"
                         r"\bsaldo\b|\btotal\b.*\b(?:deben|debo|cobrar)\b")
SENT_ME = re.compile(r"\bme pidi(?:o|eron) .{0,20}prestad|\bque me pague(?:n)?\b|\bme (?:debe|deben|adeuda|adeudan|sigue(?:n)? debiendo|queda(?:n)? debiendo|quedo debiendo|quedaron debiendo|esta(?:n)? debiendo|debia|debian|tiene(?:n)? que "
                     r"(?:pagar|devolver)|falta(?:n)? (?:pagar|devolver))\b|\b(?:le|les) (?:preste|prestamos|di prestado|fie)\b|"
                     r"\bpreste\b|\bpor cobrar\b|\bme pidio prestado|\bme pidieron prestado|\btengo que cobrar(?:le)?\b|"
                     r"\bcobrar(?:le)? (?:a|de)\b|\bfalta(?:n)? (?:por )?cobrar\b|\bdeuda de\b|\bdeben\b|\bme quedo debiendo\b|"
                     r"\bme quedaron debiendo\b|\btiene(?:n)? que (?:pagarme|devolverme)\b")
SENT_YO = re.compile(r"\bme prestaron\b|\b(?:le|les)? ?debo\b|\bme (?:presto|prestaron|fio|fiaron)\b|\btengo que (?:pagarle|devolverle|pagar a|"
                     r"devolver a)\b|\ble tengo que (?:pagar|devolver)\b|\bestoy debiendo\b|\ble quede debiendo\b|"
                     r"\bdeuda con\b|\ba quien(?:es)? le debo\b|\bdebemos\b")
PAGO_ME = re.compile(r"\bme (?:pago|pagaron|abono|abonaron|devolvio|devolvieron|dio|dieron|deposito|depositaron|transfirio|"
                     r"transfirieron|mando|mandaron|paso|pasaron|cancelo|cancelaron|repuso|saldo|liquido|liquidaron)\b|"
                     r"\b(?:recibi|cobre|me llego|llego) (?:el pago|la plata|el dinero|\$?\d|lo de|los|las|el|la)|"
                     r"\bya (?:me )?(?:pago|pagaron)\b|\bme hizo (?:el pago|una transferencia|un deposito)\b|"
                     r"\bme pagaron\b|\bpagaron\b")
PAGO_YO = re.compile(r"\b(?:le |les |ya le |ya les )?(?:pague|abone|devolvi|deposite|transferi|cancele|liquide|saldé|salde)\b|"
                     r"\b(?:le|les) (?:di|mande|pase|hice una transferencia|hice un deposito)\b")
TODO = re.compile(r"\b(?:todo|toda la deuda|todo lo que (?:me )?debia|completo|completa|la totalidad|el total|ya no me debe nada|"
                  r"ya no le debo nada|saldo todo|quedamos a mano|estamos a mano)\b")
VERBOS_BORRAR = r"borra|borrar|borrame|elimina|eliminar|eliminame|quita|quitar|quitame|anula|anular|saca|sacar"
BORRAR = re.compile(r"^(?:" + VERBOS_BORRAR + r")\s+(?:todo\s+)?(?:lo que me debe(?:n)?|lo que le debo a|lo que debo a|"
                    r"lo de|la deuda (?:de|del|de la|con|con la|con el)|las deudas (?:de|del|de la|con)|la cuenta (?:de|del|de la)|"
                    r"el registro de|el cobro (?:a|de)|a)\s+(.+)$")
BORRAR_2 = re.compile(r"^(?:" + VERBOS_BORRAR + r")\s+(?:la deuda|lo que me debe|la cuenta|el registro)\s+(?:que tiene\s+|de\s+)?(.+)$")
DESHACER = re.compile(r"^(?:" + VERBOS_BORRAR + r"|deshaz|deshacer|corrige|olvida)\s+(?:ese|esa|eso|esto|este|"
                      r"esta|lo ultimo|el ultimo|la ultima|lo anterior|lo que (?:acabas de anotar|anotaste)|lo que anote)"
                      r"(?:\s+(?:deuda|registro|anotacion|cobro|pago|abono|monto))?$")
RECUPERAR = re.compile(r"^(?:recupera|recuperar|restaura|restaurar|vuelve a poner|devuelve|regresa)\s+(?:la deuda (?:de|con)|lo que me debe|"
                       r"lo que le debo a|lo de|la cuenta de|a)?\s*(.+)$")
_ULTIMA = {}                                       # lo último que se anotó (para «elimina ese»)
NOMBRE_X = r"((?:el |la |los |las |mi |mis |don |dona )?[a-z\u00f10-9][a-z\u00f10-9&.-]*(?:\s+[a-z\u00f10-9&.-]+){0,3}?)"
RENOMBRAR = [
    re.compile(r"^(?:cambia|cambiar|cambiale|cambiame|renombra|renombrar|corrige|corregir|reemplaza|reemplazar|pon|ponle|"
               r"actualiza)\s+(?:el nombre\s+(?:de|del deudor|de la deuda de|de la cuenta de)\s+)?(?:a\s+)?" + NOMBRE_X +
               r"\s+(?:por|a|como|con el nombre(?: de)?|y ponle|y pon)\s+" + NOMBRE_X + r"$"),
    re.compile(r"^" + NOMBRE_X + r"\s+(?:ahora\s+)?(?:se llama|es|sera)\s+(?:ahora\s+)?" + NOMBRE_X + r"$"),
    re.compile(r"^(?:no es|no era|no se llama)\s+" + NOMBRE_X + r",?\s+(?:es|era|se llama|sino)\s+" + NOMBRE_X + r"$"),
    re.compile(r"^(?:el deudor|la deudora|el nombre)\s+" + NOMBRE_X + r"\s+(?:es|cambia a|pasa a ser|ahora es)\s+" + NOMBRE_X + r"$"),
]


FUERTE = re.compile(r"\b(?:debe|deben|debo|debia|debian|debiendo|deuda|deudas|adeud\w*|prest\w*|por cobrar|cobrarle|"
                    r"tiene(?:n)? que (?:pagarme|devolverme)|tengo que (?:pagarle|devolverle))\b")


def parece_deuda(texto):
    """¿Es una deuda? (para que el lector de gastos no la tome como gasto). «Me pagaron el sueldo» NO lo es."""
    t = _limpiar(texto)
    return bool(FUERTE.search(t)) or interpretar(texto) is not None


def _como_lo_escribio(persona, texto):
    """'mi tio' -> 'mi tío' (el nombre tal como el usuario lo escribió, con tildes)."""
    if not persona:
        return persona
    originales = re.findall(r"[\w\u00c0-\u00ff]+", texto)
    buscadas = persona.split()
    for i in range(len(originales) - len(buscadas) + 1):
        trozo = originales[i:i + len(buscadas)]
        if [_norm(w) for w in trozo] == buscadas:
            return " ".join(w if j == 0 and w.lower() in ("el", "la", "mi", "los", "las", "mis") else w
                            for j, w in enumerate(trozo)).replace(trozo[0], trozo[0].lower() if trozo[0].lower() in
                                                                  ("el", "la", "mi", "los", "las", "mis") else trozo[0], 1)
    return persona


def interpretar(texto):
    """Frase -> dict de acción, o None si no es de deudas (o no se entiende sin la IA)."""
    d = _interpretar(texto)
    if d and d.get("persona"):
        d["persona"] = _como_lo_escribio(d["persona"], texto)
    if d and d.get("nuevo"):                       # el nombre nuevo, exactamente como lo escribió ("Meraki S.A.")
        normal, buscado = _norm(texto), _norm(d["nuevo"]).rstrip(".")
        i = normal.rfind(buscado)
        if i >= 0 and len(normal) == len(texto):
            fin = i + len(buscado)
            fin += 1 if texto[fin:fin + 1] == "." and re.search(r"[A-Za-z]\.[A-Za-z]$", texto[i:fin]) else 0
            d["nuevo"] = texto[i:fin].strip()
        else:
            d["nuevo"] = _como_lo_escribio(d["nuevo"], texto)
    if d:
        d["texto"] = texto
    return d


def _interpretar(texto):
    t = _limpiar(texto)
    if not t:
        return None
    if DESHACER.match(t) and _ULTIMA and (ahora().timestamp() - _ULTIMA.get("cuando", 0)) < 1800:
        return {"accion": "deshacer", "persona": None}
    for patron in (BORRAR, BORRAR_2):
        m = patron.match(t)
        if m:
            p = _recortar_persona(re.sub(r"\b(?:ya|completa|completo|toda|entera)\b", " ", m.group(1)))
            if _es_persona(p):
                return {"accion": "borrar", "persona": p}
    cambio = _interpretar_cambio(t)                # «cambia la deuda de Juan a 400», «súbele 50 a Juan», «septiembre fue 700»…
    if cambio:
        return cambio
    for patron in RENOMBRAR:                       # «cambia Jaspharm por Meraki»: solo si el primero ya tiene deuda
        m = patron.match(t)
        if m:
            viejo, nuevo = _recortar_persona(m.group(1)), m.group(2).strip(" .,")
            if viejo and nuevo and _norm(viejo) != _norm(nuevo) and not re.search(r"\d", nuevo) and \
                    [x for x in _todas(_nombre_bonito(viejo))]:
                return {"accion": "renombrar", "persona": viejo, "nuevo": nuevo}
    m = RECUPERAR.match(t)
    if m and re.search(r"deuda|me debe|le debo|cuenta", t):
        p = _recortar_persona(m.group(1))
        if _es_persona(p):
            return {"accion": "recuperar", "persona": p}
    if not PISTA.search(t) and not PAGO_ME.search(t) and not PAGO_YO.search(t):
        return None
    t, cuota, dia = _cuota(t)
    t, limite = _limite(t)
    montos = _montos(t)
    persona = _persona(t)
    meses_pedidos = [MESES[x] for x in re.findall(MES, t)]
    # --- pagos (antes que las preguntas: "la empresa me pagó septiembre") ---
    pago_me, pago_yo = PAGO_ME.search(t), PAGO_YO.search(t) and not re.search(r"\bme\s+(?:pag|abon|devolv)", t)
    if pago_me and SENT_ME.search(t) and re.search(r"\b\d+\s+(?:abonos?|pagos?|cuotas?|veces|depositos?)\b", t[pago_me.start():]):
        pago_me = None                                      # "me debe 300, ya me pagó 3 cuotas": es la deuda
    if (pago_me or pago_yo) and not ES_PREGUNTA.match(t) and not re.search(r"\bcuanto\b", t):
        if not persona:
            return None
        cargos = [x for x in montos if not x[2]]
        return {"accion": "pago_me" if pago_me else "pago_yo", "persona": persona,
                "monto": cargos[0][0] if cargos else None, "meses": meses_pedidos if not cargos else
                [x[1] for x in cargos if x[1]], "todo": bool(TODO.search(t)) and not cargos,
                "concepto": _concepto(t)} if (cargos or meses_pedidos or TODO.search(t)) else None
    # --- preguntas ---
    if not montos and (ES_PREGUNTA.search(t) or re.match(r"^(?:mis |las |ver |todas las )?deudas\b", t)
                       or re.search(r"\bcuentas? por cobrar\b", t)):
        quien_me = re.search(r"\bquien(?:es)?\s+me\s+(?:debe|deben)|\bcuanto me deben\b|\bpor cobrar\b|\bme deben en total|"
                             r"\bcuanto (?:tengo|hay) (?:que|por) cobrar|\bcuentas? por cobrar|\bquien me debe", t)
        quien_yo = re.search(r"\ba quien(?:es)? les? debo|\bcuanto debo\b|\bcuanto le debo en total|\bmis deudas con|"
                             r"\bque debo\b|\ba quien debo", t)
        if persona:
            sentido = "le_debo" if SENT_YO.search(t) and not SENT_ME.search(t) else "me_debe" if SENT_ME.search(t) else None
            return {"accion": "pregunta_yo" if sentido == "le_debo" else "pregunta_me" if sentido == "me_debe"
                    else "pregunta", "persona": persona}
        if quien_me and not quien_yo:
            return {"accion": "lista_me", "persona": None}
        if quien_yo and not quien_me:
            return {"accion": "lista_yo", "persona": None}
        if re.search(r"\bdeudas?\b|\bdeben\b|\bdebo\b|\bcobrar\b|\bprest", t):
            return {"accion": "lista", "persona": None}
        return None
    # --- deuda nueva (uno o varios montos, por mes, regla mensual) ---
    if not montos or not persona:
        return None
    sentido = "le_debo" if SENT_YO.search(t) and not SENT_ME.search(t) else "me_debe" if SENT_ME.search(t) else None
    if not sentido:
        return None
    cargos = [{"monto": v, "mes": mes} for v, mes, rec in montos if not rec]
    recurrente = next((v for v, _, rec in montos if rec), None)
    # "en total 1408.15" no es otro cargo si coincide con la suma de los meses
    if len(cargos) > 2 and abs(cargos[-1]["monto"] - sum(c["monto"] for c in cargos[:-1])) < 0.02 and not cargos[-1]["mes"]:
        cargos = cargos[:-1]
    return {"accion": "deuda_me" if sentido == "me_debe" else "deuda_yo", "persona": persona, "cargos": cargos,
            "monto": cargos[0]["monto"] if cargos else 0, "recurrente": recurrente,
            "dia_recurrente": _dia_recurrente(t) if recurrente else None, "concepto": _concepto(t),
            "cuota": cuota, "dia_cuota": dia, "limite": limite}


# ------------------------------------------------------------------ la IA como respaldo ---
ESQUEMA_IA = {"type": "object", "properties": {
    "es_deuda": {"type": "boolean"},
    "accion": {"type": "string", "enum": ["nueva", "pago", "pregunta", "lista", "cambiar_saldo", "subir", "bajar", "ninguna"]},
    "sentido": {"type": "string", "enum": ["me_debe", "le_debo", "no_se"]},
    "persona": {"type": "string"},
    "montos": {"type": "array", "items": {"type": "object", "properties": {
        "monto": {"type": "number"}, "mes": {"type": "integer"}}, "required": ["monto", "mes"]}},
    "recurrente_mensual": {"type": "number"},
    "concepto": {"type": "string"}},
    "required": ["es_deuda", "accion", "sentido", "persona", "montos", "recurrente_mensual", "concepto"]}
PIDE_IA = ("Analiza este mensaje del usuario sobre DEUDAS (dinero que le deben o que él debe). Devuelve SOLO datos en JSON:\n"
           "- es_deuda: false si no habla de deudas.\n- accion: nueva (registrar una deuda), pago (alguien pagó o "
           "él pagó), pregunta (consulta sobre una persona), lista (consulta general), cambiar_saldo (corregir: la deuda "
           "pasa a ser un monto exacto), subir (aumentar en un monto), bajar (reducir en un monto, sin que sea un pago), ninguna.\n"
           "- sentido: me_debe (le deben al usuario) o le_debo (el usuario debe).\n- persona: quién (persona o empresa, en "
           "minúsculas, p. ej. 'la empresa', 'juan', 'mi tío'); '' si no se dice.\n"
           "- montos: cada monto que DEUDA con su mes (1-12) si se dice, 0 si no. NO incluyas el monto que se suma "
           "cada mes.\n- recurrente_mensual: monto que se suma automáticamente cada mes (0 si no hay).\n"
           "- concepto: por qué (p. ej. 'la laptop'), '' si no se dice.\nNo inventes números: usa solo los del mensaje."
           "\n\nMENSAJE: ")


def interpretar_con_ia(texto):
    """Para frases que el código no entendió pero hablan de deudas. Los montos se validan contra el texto."""
    import json as _json
    import requests
    from modulos.ia import cerebro
    conf = cerebro.config()
    cuerpo = {"model": conf["modelo"], "messages": [{"role": "user", "content": PIDE_IA + texto}], "stream": False,
              "think": False, "format": ESQUEMA_IA, "keep_alive": conf["keep_alive"],
              "options": {"num_predict": 400, "temperature": 0, **conf.get("opciones", {})}}
    try:
        r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=120)
        if r.status_code == 400:
            cuerpo.pop("think", None)
            r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=120)
        r.raise_for_status()
        datos = _json.loads(re.sub(r"<think>.*?</think>", "", r.json()["message"]["content"], flags=re.S))
    except Exception as exc:
        log.info("IA de deudas no disponible: %s", exc)
        return None
    if not datos.get("es_deuda") or datos.get("accion") in (None, "ninguna"):
        return None
    en_texto = {round(dinero(x), 2) for x in re.findall(r"\d[\d.,]*", _limpiar(texto)) if re.search(r"\d", x)}
    def valido(x):
        try:
            return round(float(x), 2) in en_texto
        except (TypeError, ValueError):
            return False
    persona = _recortar_persona(_norm(datos.get("persona") or ""))
    montos = [{"monto": round(float(m["monto"]), 2), "mes": m["mes"] if 1 <= int(m.get("mes") or 0) <= 12 else None}
              for m in datos.get("montos") or [] if valido(m.get("monto"))]
    recurrente = datos.get("recurrente_mensual") if valido(datos.get("recurrente_mensual")) else None
    sentido = datos.get("sentido") if datos.get("sentido") in ("me_debe", "le_debo") else None
    accion = datos["accion"]
    if accion == "lista":
        return {"accion": {"me_debe": "lista_me", "le_debo": "lista_yo"}.get(sentido, "lista"), "persona": None}
    if not _es_persona(persona):
        return None
    if accion == "pregunta":
        return {"accion": {"me_debe": "pregunta_me", "le_debo": "pregunta_yo"}.get(sentido, "pregunta"), "persona": persona}
    if accion in ("cambiar_saldo", "subir", "bajar") and montos and _todas(_nombre_bonito(persona)):
        return {"accion": "cambiar", "tipo": {"cambiar_saldo": "fijar", "subir": "sumar", "bajar": "restar"}[accion],
                "persona": persona, "monto": montos[0]["monto"], "mes": None, "extra": None}
    if accion == "pago" and montos and sentido:
        return {"accion": "pago_me" if sentido == "me_debe" else "pago_yo", "persona": persona,
                "monto": montos[0]["monto"], "meses": [], "todo": False, "concepto": datos.get("concepto") or ""}
    if accion == "nueva" and sentido and (montos or recurrente):
        return {"accion": "deuda_me" if sentido == "me_debe" else "deuda_yo", "persona": persona,
                "cargos": montos, "monto": montos[0]["monto"] if montos else 0, "recurrente": recurrente,
                "dia_recurrente": 1 if recurrente else None, "concepto": datos.get("concepto") or "",
                "cuota": None, "dia_cuota": None, "limite": None}
    return None


# ------------------------------------------------------------------ cambiar una deuda que ya existe ---
V_CAMBIO = (r"(?:cambia|cambiar|cambiale|cambiame|corrige|corregir|corrigele|actualiza|actualizar|actualizale|modifica|"
            r"modificar|modificale|ajusta|ajustar|ajustale|pon|ponle|ponme|deja|dejale|dejalo|dejala|edita|editar|arregla|"
            r"arreglar|arreglale|fija|fijale|establece|setea)")
OBJ = (r"(?:la deuda|el saldo|el monto|el valor|lo que me debe|lo que me deben|lo que le debo|lo que debo|la cuenta|el total|"
       r"lo que falta|lo pendiente|el pendiente|la plata|el dinero)")
X = r"((?:el |la |los |las |mi |mis |don |dona )?[a-zñ][a-zñ0-9&.-]*(?:\s+[a-zñ0-9&.-]+){0,3}?)"
DE = r"(?:de|del|de la|de los|con|con la|con el|a|al|a la|para|para la|para el)"
N_ = r"\$?\s?(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?:\s?(?:dolares|dolar|usd|\$|lucas|pesos))?"
FECHA_ = r"(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)"
FIN = r"\s*(?:,?\s*(?:no|y no|en vez de|en lugar de)\s+\$?[\d.,]+.*)?$"

CAMBIOS = [
    # --- saldo exacto ---
    ("fijar", re.compile(r"^" + V_CAMBIO + r"\s+(?:" + OBJ + r"\s+)?(?:" + DE + r"\s+)?" + X + r"\s+(?:a|en|por|como|que sean|que sea|"
                         r"a que sean|a que sea|en un total de)\s+" + N_ + FIN)),
    ("fijar_inv", re.compile(r"^" + V_CAMBIO + r"\s+" + OBJ + r"\s+(?:a|en|por)\s+" + N_ + r"\s+" + DE + r"\s+" + X + r"$")),
    ("fijar", re.compile(r"^" + X + r"\s+(?:en realidad|realmente|ahora|en total|al final|finalmente|solo|nada mas|en verdad|"
                         r"de verdad|la verdad)\s+me\s+(?:debe|deben)\s+" + N_ + FIN)),
    ("fijar", re.compile(r"^(?:en realidad|realmente|ahora|en total|al final|finalmente|corrijo|correccion|me equivoque)\s*[,:]?\s+"
                         + X + r"\s+me\s+(?:debe|deben)\s+" + N_ + FIN)),
    ("fijar", re.compile(r"^" + X + r"\s+me\s+(?:debe|deben)\s+" + N_ + r"\s*,?\s+(?:no|y no|no son|no es|en vez de|en lugar de)\s+\$?[\d.,]+.*$")),
    ("fijar", re.compile(r"^" + X + r"\s+no\s+me\s+(?:debe|deben)\s+\$?[\d.,]+\s*,?\s+(?:me debe|me deben|son|sino|es)\s+" + N_ + r".*$")),
    ("fijar", re.compile(r"^(?:lo que me debe|lo que me deben|lo que le debo a|lo que debo a)\s+" + X + r"\s+(?:es|son|queda en|quedo en|"
                         r"seria|deberia ser|tiene que ser|debe ser)\s+(?:de\s+)?" + N_ + FIN)),
    ("fijar", re.compile(r"^(?:el saldo|la deuda|lo que me debe|el total|lo pendiente)\s+" + DE + r"\s+" + X + r"\s+(?:es|son|queda en|"
                         r"quedo en|seria|deberia ser|tiene que ser|debe ser)\s+(?:de\s+)?" + N_ + FIN)),
    ("fijar", re.compile(r"^(?:en realidad|realmente|ahora|al final)\s*,?\s+le\s+debo\s+" + N_ + r"\s+" + DE + r"\s+" + X + r"$")),
    ("fijar", re.compile(r"^(?:correccion|corrijo|me equivoque|era|eran|son|es)\s*[:,]?\s+(?:son\s+|eran\s+|es\s+)?" + N_ + r"\s+(?:no|y no)\s+\$?[\d.,]+$")),
    # --- subir ---
    ("sumar", re.compile(r"^(?:subele|sumale|aumentale|agregale|anadele|cargale|metele|sube|suma|aumenta|agrega|anade|carga|mete)\s+"
                         + N_ + r"\s+(?:mas\s+)?(?:a la deuda de|a la cuenta de|a lo que me debe|a lo que le debo a|a|al|a la|a los)\s+" + X + r"$")),
    ("sumar", re.compile(r"^(?:aumenta|sube|incrementa|amplia)\s+(?:" + OBJ + r")(?:\s+" + DE + r")?\s+" + X + r"\s+(?:en|por|con)\s+" + N_ + r"$")),
    ("sumar", re.compile(r"^" + X + r"\s+(?:me debe|me deben|debe)\s+" + N_ + r"\s+mas(?:\s+de lo que tenia)?$")),
    ("sumar", re.compile(r"^" + X + r"\s+(?:ahora )?me debe\s+(?:otros|otras|ademas|tambien)\s+" + N_ + r"$")),
    # --- bajar ---
    ("restar", re.compile(r"^(?:bajale|restale|descuentale|quitale|rebajale|disminuyele|reducele|bajame|resta|baja|descuenta|quita|rebaja|"
                          r"disminuye|reduce)\s+" + N_ + r"\s+(?:a la deuda de|a la cuenta de|a lo que me debe|de lo que me debe|"
                          r"de la deuda de|a|al|a la|de|del|de la)\s+" + X + r"$")),
    ("restar", re.compile(r"^(?:baja|reduce|disminuye|rebaja|descuenta)\s+(?:" + OBJ + r")(?:\s+" + DE + r")?\s+" + X + r"\s+(?:en|por)\s+" + N_ + r"$")),
    ("restar", re.compile(r"^" + X + r"\s+(?:me debe|me deben|debe)\s+" + N_ + r"\s+menos$")),
    # --- un mes ---
    ("mes", re.compile(r"^(?:" + V_CAMBIO + r"\s+)?(?:el mes de\s+|lo de\s+|el de\s+)?" + MES + r"(?:\s+" + DE + r"\s+" + X + r")?\s+"
                       r"(?:a|en|por|fue|era|es|son|eran|seria|vale|quedo en|fueron|debe ser)\s+(?:de\s+)?" + N_ + FIN)),
    ("mes_inv", re.compile(r"^" + V_CAMBIO + r"\s+" + X + r"\s+(?:el mes de\s+|lo de\s+)?" + MES + r"\s+(?:a|en|por)\s+" + N_ + FIN)),
    ("mes", re.compile(r"^(?:lo de\s+|el mes de\s+)?" + MES + r"\s+(?:no fue|no era|no es)\s+\$?[\d.,]+\s*,?\s+(?:fue|era|es|son|sino)\s+" + N_
                       + r"(?:\s+" + DE + r"\s+" + X + r")?$")),
    # --- suma mensual ---
    ("rec_monto", re.compile(r"^(?:" + V_CAMBIO + r")\s+(?:la suma mensual|lo que se suma(?: cada mes)?|el monto mensual|la cuota mensual|lo mensual|"
                             r"lo de cada mes|la suma de cada mes|el aumento mensual)(?:\s+" + DE + r"\s+" + X + r")?\s+(?:a|en|por)\s+" + N_ + r"$")),
    ("rec_monto", re.compile(r"^(?:ahora\s+)?(?:se suman|se suma|suma|sumale|ponle|que se sumen|que se sume)\s+" + N_
                             + r"\s+(?:cada mes|mensuales|al mes|por mes|mensualmente)(?:\s+(?:a|de|en)\s+" + X + r")?(?:\s+no\s+\$?[\d.,]+)?$")),
    ("rec_quitar", re.compile(r"(?:ya no|deja de|dejes de|que no|no)\s+(?:se\s+)?(?:sume|suma|sumen|sumes|sumar|agregue|agregues|agregar|aumente|"
                              r"aumentes|aumentar)\s*(?:nada\s+)?(?:mas\s+)?(?:cada mes|mensualmente|todos los meses|al mes|mas)?"
                              r"(?:\s+(?:a|de|en)\s+" + X + r")?\s*$|^(?:quita|quitale|elimina|eliminale|para|deten|cancela|apaga|"
                              r"desactiva)\s+(?:la suma mensual|lo que se suma cada mes|el aumento mensual|lo mensual|la suma automatica)"
                              r"(?:\s+" + DE + r"\s+" + X + r")?$")),
    ("rec_dia", re.compile(r"(?:que se sume(?:n)?|sumalo|sumala|que la suma (?:entre|sea)|la suma (?:entre|sea|que sea))\s+(?:el|los)\s+(\d{1,2})"
                           r"(?:\s+de cada mes|\s+del mes)?(?:\s+(?:a|de|en)\s+" + X + r")?$|^" + V_CAMBIO
                           + r"\s+el dia de la suma(?:\s+" + DE + r"\s+" + X + r")?\s+(?:a|al)\s+(?:dia\s+)?(\d{1,2})$")),
    # --- motivo ---
    ("concepto", re.compile(r"^(?:la deuda|lo que me debe|lo que le debo a|lo)\s+(?:de\s+)?" + X + r"\s+(?:es|era|fue)\s+por\s+(.+)$")),
    ("concepto", re.compile(r"^" + V_CAMBIO + r"\s+el (?:concepto|motivo|detalle|por que)\s+" + DE + r"\s+" + X + r"\s+(?:a|por)\s+(.+)$")),
    ("concepto", re.compile(r"^" + X + r"\s+me debe por\s+(.+)$")),
    # --- fecha límite ---
    ("limite", re.compile(r"^(?:la fecha (?:limite|tope|de pago|para pagar)|el plazo)\s+" + DE + r"\s+" + X + r"\s+(?:es|sera|queda|pasa)\s+"
                          r"(?:para\s+)?(?:el\s+)?" + FECHA_ + r"$")),
    ("limite", re.compile(r"^" + V_CAMBIO + r"\s+(?:la fecha(?: limite| tope| de pago)?|el plazo)\s+" + DE + r"\s+" + X + r"\s+(?:a|al|para el|por el)\s+" + FECHA_ + r"$")),
    ("limite", re.compile(r"^" + X + r"\s+(?:me paga|me va a pagar|me pagara|tiene hasta|paga)\s+(?:hasta el|antes del|el|para el)\s+" + FECHA_ + r"$")),
    # --- al revés ---
    ("invertir_yo", re.compile(r"^(?:no\s*,?\s*)?(?:es al reves|al reves|al contrario|es al contrario)?\s*,?\s*(?:soy\s+)?yo\s+(?:le\s+)?debo\s+(?:a\s+)?" + X + r"$")),
    ("invertir_yo", re.compile(r"^(?:no\s*,?\s*)?(?:soy yo el que le debe|yo soy el que le debe|soy yo quien le debe|yo soy quien debe)\s+(?:a\s+)?" + X + r"$")),
    ("invertir_me", re.compile(r"^(?:no\s*,?\s*)?(?:es al reves|al reves|al contrario)?\s*,?\s*" + X + r"\s+me debe a mi$")),
    ("invertir", re.compile(r"^(?:es al reves|al reves|al contrario|esta al reves)(?:\s+(?:lo de|la deuda de|con)\s+" + X + r")?$")),
    # --- corregir un pago ---
    ("pago", re.compile(r"^(?:el ultimo pago|el ultimo abono|el pago|el abono)\s+" + DE + r"\s+" + X + r"\s+(?:fue|era|es|son|fueron)\s+"
                        r"(?:de\s+)?" + N_ + FIN)),
    ("pago", re.compile(r"^" + V_CAMBIO + r"\s+el (?:ultimo )?(?:pago|abono)\s+" + DE + r"\s+" + X + r"\s+(?:a|en|por)\s+" + N_ + FIN)),
    ("pago", re.compile(r"^" + X + r"\s+me (?:pago|abono)\s+" + N_ + r"\s*,?\s+(?:no|y no)\s+\$?[\d.,]+$")),
    ("pago_borrar", re.compile(r"^(?:borra|elimina|quita|anula)\s+el (?:ultimo )?(?:pago|abono)\s+" + DE + r"\s+" + X + r"$")),
]


def _resolver_deuda(persona, filtro=None):
    """La deuda a cambiar: por nombre, o la única que encaja, o la última que se tocó. (deuda|None, mensaje|None)"""
    if persona:
        p = _recortar_persona(persona)
        ds = [x for x in _todas(_nombre_bonito(p)) if x["estado"] != "borrada"]
        if filtro:
            ds = [x for x in ds if filtro(x)] or ds
        if ds:
            return sorted(ds, key=lambda x: (x["estado"] != "abierta", -x["id"]))[0], None
        return None, "No encuentro una deuda de " + _nombre_bonito(p) + ". Vea las que hay con «mis deudas»."
    candidatas = [x for x in abiertas() if not filtro or filtro(x)]
    if len(candidatas) == 1:
        return candidatas[0], None
    if _ULTIMA and (ahora().timestamp() - _ULTIMA.get("cuando", 0)) < 1800:
        d = obtener(_ULTIMA["deuda"])
        if d:
            return d, None
    if not candidatas:
        return None, "No encuentro una deuda que cambiar."
    return None, ("¿De quién? Tiene varias: " + ", ".join(x["persona"] for x in candidatas[:6])
                  + ". Escríbalo con el nombre, por ejemplo: «cambia la deuda de " + candidatas[0]["persona"] + " a 400».")


def _interpretar_cambio(t):
    """«cambia la deuda de Juan a 400», «súbele 50 a Juan», «septiembre fue 700»… -> dict o None."""
    for tipo, patron in CAMBIOS:
        m = patron.search(t)
        if not m:
            continue
        g = [x for x in m.groups()]
        persona, monto, mes, extra = None, None, None, None
        if tipo in ("fijar", "sumar", "restar", "pago"):
            persona = next((x for x in g if x and not re.fullmatch(r"\$?[\d.,]+", x.strip())), None)
            monto = next((x for x in g if x and re.fullmatch(r"\$?[\d.,]+", x.strip())), None)
        elif tipo == "fijar_inv":
            monto, persona, tipo = g[0], g[1], "fijar"
        elif tipo in ("mes", "mes_inv"):
            mes = next((x for x in g if x in MESES), None)
            monto = next((x for x in g if x and re.fullmatch(r"\$?[\d.,]+", x.strip())), None)
            persona = next((x for x in g if x and x not in MESES and not re.fullmatch(r"\$?[\d.,]+", x.strip())), None)
            tipo = "mes"
        elif tipo == "rec_monto":
            monto = next((x for x in g if x and re.fullmatch(r"\$?[\d.,]+", x.strip())), None)
            persona = next((x for x in g if x and not re.fullmatch(r"\$?[\d.,]+", x.strip())), None)
        elif tipo == "rec_dia":
            extra = next((x for x in g if x and re.fullmatch(r"\d{1,2}", x)), None)
            persona = next((x for x in g if x and not re.fullmatch(r"\d{1,2}", x)), None)
        elif tipo in ("concepto", "limite"):
            persona, extra = g[0], g[1]
        else:                                            # rec_quitar, invertir*, pago_borrar
            persona = next((x for x in g if x), None)
        if persona and not _es_persona(_recortar_persona(persona)):
            persona = None
        if tipo in ("fijar", "sumar", "restar", "pago", "mes", "rec_monto") and not monto:
            continue
        if tipo in ("fijar", "sumar", "restar", "concepto", "limite", "invertir_yo", "invertir_me", "pago", "pago_borrar") and persona:
            if not _todas(_nombre_bonito(_recortar_persona(persona))):
                continue                                 # no es un deudor conocido: que lo vea otro módulo
        if tipo in ("mes", "rec_monto", "rec_quitar", "rec_dia") and persona and not _todas(_nombre_bonito(_recortar_persona(persona))):
            continue
        if tipo in ("mes",) and not any(any(mv["tipo"] == "cargo" and re.search(r"\d{4}$", mv["nota"] or "") for mv in movimientos(x["id"]))
                                       for x in abiertas()):
            continue
        if tipo in ("rec_quitar", "rec_dia") and not any(x.get("recurrente") for x in abiertas()):
            continue
        if tipo in ("fijar", "sumar", "restar", "concepto", "limite", "invertir_yo", "invertir_me") and not persona:
            if tipo != "fijar" or not _ULTIMA:
                continue
        return {"accion": "cambiar", "tipo": tipo, "persona": _recortar_persona(persona) if persona else None,
                "monto": dinero(monto) if monto else None, "mes": MESES.get(mes) if mes else None, "extra": extra}
    return None


def ejecutar_cambio(d):
    tipo = d["tipo"]
    filtro = {"mes": lambda x: any(m["tipo"] == "cargo" and re.search(r"\d{4}$", m["nota"] or "") for m in movimientos(x["id"])),
              "rec_monto": lambda x: bool(x.get("recurrente")), "rec_quitar": lambda x: bool(x.get("recurrente")),
              "rec_dia": lambda x: bool(x.get("recurrente")),
              "pago": lambda x: any(m["tipo"] == "pago" for m in movimientos(x["id"])),
              "pago_borrar": lambda x: any(m["tipo"] == "pago" for m in movimientos(x["id"]))}.get(tipo)
    deuda, error = _resolver_deuda(d.get("persona"), filtro)
    if error:
        return error
    did, quien = deuda["id"], deuda["persona"]
    antes = saldo(did)

    def cierre(texto):
        actualizar(did, estado="abierta" if saldo(did) > 0 or obtener(did).get("recurrente") else "saldada")
        try:
            subir_google(did)
        except Exception:
            pass
        _ULTIMA.clear()
        _ULTIMA.update(deuda=did, tipo="cambio", cuando=ahora().timestamp(), movimientos=[])
        s = saldo(did)
        return texto + " " + (_cap(quien) + " le debe " if obtener(did)["sentido"] == "me_debe" else "Usted le debe a " + quien + " ") + fmt(max(s, 0)) + "."

    if tipo in ("fijar", "sumar", "restar"):
        objetivo = d["monto"] if tipo == "fijar" else antes + d["monto"] if tipo == "sumar" else antes - d["monto"]
        diferencia = round(objetivo - antes, 2)
        if abs(diferencia) < 0.005:
            return "No cambió nada: " + quien + " ya está en " + fmt(antes) + "."
        with closing(_con()) as con, con:
            con.execute("INSERT INTO deuda_movimientos (deuda, tipo, monto, fecha, nota, comprobante) VALUES (?, ?, ?, ?, ?, '')",
                        (did, "cargo" if diferencia > 0 else "pago", abs(diferencia), ahora().date().isoformat(),
                         "Ajuste (" + ("sube" if diferencia > 0 else "baja") + " " + fmt(abs(diferencia)) + ")"))
        return cierre("✏️ Listo: " + ("subí " if diferencia > 0 else "bajé ") + fmt(abs(diferencia)) + " (estaba en " + fmt(antes) + ").")
    if tipo == "mes":
        etiqueta = _etiqueta_mes(d["mes"], _anio_de(d["mes"]))
        with closing(_con()) as con, con:
            fila = con.execute("SELECT id, monto FROM deuda_movimientos WHERE deuda = ? AND tipo = 'cargo' AND nota = ?",
                               (did, etiqueta)).fetchone()
            if fila:
                con.execute("UPDATE deuda_movimientos SET monto = ? WHERE id = ?", (d["monto"], fila["id"]))
            else:
                con.execute("INSERT INTO deuda_movimientos (deuda, tipo, monto, fecha, nota, comprobante) VALUES (?, 'cargo', ?, ?, ?, '')",
                            (did, d["monto"], date(_anio_de(d["mes"]), d["mes"], 1).isoformat(), etiqueta))
        return cierre("✏️ " + etiqueta + (": de " + fmt(fila["monto"]) + " a " if fila else " agregado: ") + fmt(d["monto"]) + ".")
    if tipo == "rec_monto":
        cambios = {"recurrente": d["monto"]}
        if not deuda.get("ultimo_mes"):
            hoy = ahora().date()
            cambios.update(dia_recurrente=1, ultimo_mes=(date(hoy.year, hoy.month, 1) - timedelta(days=1)).strftime("%Y-%m"))
        actualizar(did, **cambios)
        return cierre("🔁 Ahora le sumo " + fmt(d["monto"]) + " cada mes a " + quien + ".")
    if tipo == "rec_quitar":
        if not deuda.get("recurrente"):
            return quien + " no tenía suma mensual."
        actualizar(did, recurrente=None)
        return cierre("⏹ Ya no le sumo nada cada mes a " + quien + ".")
    if tipo == "rec_dia":
        dia = int(d["extra"])
        if not 1 <= dia <= 28:
            return "Elija un día entre el 1 y el 28."
        actualizar(did, dia_recurrente=dia)
        return cierre("🔁 La suma mensual de " + quien + " entra ahora el día " + str(dia) + ".")
    if tipo == "concepto":
        actualizar(did, concepto=d["extra"].strip()[:80])
        return cierre("✏️ Anoté el motivo: " + d["extra"].strip()[:80] + ".")
    if tipo == "limite":
        from modulos.tareas.tareas import _fecha
        f, _ = _fecha(d["extra"])
        if not f:
            return "No entendí la fecha. Escríbala así: 30/11."
        actualizar(did, limite=f.isoformat())
        return cierre("📅 Fecha límite de " + quien + ": " + _fecha_corta(f.isoformat()) + "; le aviso antes.")
    if tipo.startswith("invertir"):
        nuevo = {"invertir_yo": "le_debo", "invertir_me": "me_debe"}.get(tipo) or (
            "le_debo" if deuda["sentido"] == "me_debe" else "me_debe")
        if nuevo == deuda["sentido"]:
            return "Ya estaba así: " + ("usted le debe a " + quien if nuevo == "le_debo" else quien + " le debe a usted") + "."
        actualizar(did, sentido=nuevo)
        return cierre("🔄 Corregido: ahora " + ("usted le debe a " + quien if nuevo == "le_debo" else quien + " le debe a usted") + ".")
    if tipo in ("pago", "pago_borrar"):
        pagos = [m for m in movimientos(did) if m["tipo"] == "pago"]
        if not pagos:
            return quien + " no tiene pagos registrados."
        ultimo = pagos[-1]
        with closing(_con()) as con, con:
            if tipo == "pago_borrar":
                con.execute("DELETE FROM deuda_movimientos WHERE id = ?", (ultimo["id"],))
            else:
                con.execute("UPDATE deuda_movimientos SET monto = ? WHERE id = ?", (d["monto"], ultimo["id"]))
        return cierre("✏️ " + ("Quité el último pago (" + fmt(ultimo["monto"]) + ")." if tipo == "pago_borrar" else
                              "El último pago ahora es " + fmt(d["monto"]) + " (era " + fmt(ultimo["monto"]) + ")."))
    return None


# ------------------------------------------------------------------ ejecutar ---
def _etiqueta_mes(mes, anio):
    return NOMBRE_MES[mes] + " " + str(anio)


def _mes_siguiente(anio, mes):
    return (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def por_mes(did):
    """Estado de cada mes cargado: [(etiqueta, cargo, pagado, pendiente)]. Los pagos con mes van a ese mes; el resto,
    al más antiguo primero."""
    ms = movimientos(did)
    meses = [{"nota": m["nota"], "cargo": m["monto"], "pagado": 0.0} for m in ms if m["tipo"] == "cargo"]
    libre = 0.0
    for p in [m for m in ms if m["tipo"] == "pago"]:
        destino = next((x for x in meses if p["nota"] and x["nota"] and _norm(x["nota"]) in _norm(p["nota"])), None)
        if destino:
            aplica = min(p["monto"], destino["cargo"] - destino["pagado"])
            destino["pagado"] += aplica
            libre += p["monto"] - aplica
        else:
            libre += p["monto"]
    for x in meses:
        aplica = min(libre, x["cargo"] - x["pagado"])
        x["pagado"] += aplica
        libre -= aplica
    return [(x["nota"], x["cargo"], round(x["pagado"], 2), round(x["cargo"] - x["pagado"], 2)) for x in meses]


def ejecutar(d):
    """Ejecuta la acción entendida y devuelve la respuesta (texto plano)."""
    a = d["accion"]
    if a == "lista":
        return resumen()
    if a == "lista_me":
        return resumen("me_debe")
    if a == "lista_yo":
        return resumen("le_debo")
    if a in ("pregunta_me", "pregunta_yo", "pregunta"):
        sentido = {"pregunta_me": "me_debe", "pregunta_yo": "le_debo"}.get(a)
        ds = abiertas(d["persona"], sentido)
        if not ds:
            nombre = _nombre_bonito(d["persona"])
            return ("No tengo registrado que usted le deba algo a " + nombre + "." if sentido == "le_debo"
                    else "No tengo registrado que " + nombre + " le deba algo.")
        return "\n\n".join(detalle(x) for x in ds)
    if a == "borrar":
        ds = abiertas(d["persona"])
        if not ds:
            return "No encuentro una deuda abierta de " + _nombre_bonito(d["persona"]) + ". Vea las que hay con «mis deudas»."
        total = sum(saldo(x["id"]) for x in ds)
        for x in ds:
            actualizar(x["id"], estado="borrada")
            try:
                quitar_google(x["id"])
            except Exception:
                pass
        _ULTIMA.clear()
        return ("🗑 Borré la deuda de " + ds[0]["persona"] + " (" + fmt(total) + ").\n"
                "Si fue un error: «recupera la deuda de " + ds[0]["persona"] + "».")
    if a == "cambiar":
        return ejecutar_cambio(d)
    if a == "renombrar":
        viejas = _todas(_nombre_bonito(d["persona"]))
        if not viejas:
            return "No encuentro una deuda de " + _nombre_bonito(d["persona"]) + "."
        nuevo = d["nuevo"].strip()
        nuevo = nuevo[:1].upper() + nuevo[1:] if not re.match(r"(?:el|la|los|las|mi|mis) ", nuevo.lower()) else nuevo
        with closing(_con()) as con, con:
            for x in viejas:
                con.execute("UPDATE deudas SET persona = ? WHERE id = ?", (nuevo, x["id"]))
        for x in viejas:
            try:
                subir_google(x["id"])                  # el recordatorio de Google con el nombre nuevo
            except Exception:
                pass
        total = sum(saldo(x["id"]) for x in viejas if x["estado"] == "abierta")
        return ("✏️ Listo: «" + viejas[0]["persona"] + "» ahora se llama «" + nuevo + "»"
                + (" (" + str(len(viejas)) + " cuentas)" if len(viejas) > 1 else "") + ". "
                + (_cap(nuevo) + (" le debe " if viejas[0]["sentido"] == "me_debe" else ": usted le debe ") + fmt(total) + "."
                   if total else ""))
    if a == "recuperar":
        nombre = _nombre_bonito(d["persona"])
        borradas = [x for x in _todas(nombre, incluir_borradas=True) if x["estado"] == "borrada"]
        if not borradas:
            return "No encuentro una deuda borrada de " + nombre + "."
        x = max(borradas, key=lambda y: y["id"])
        actualizar(x["id"], estado="abierta" if saldo(x["id"]) > 0 else "saldada")
        try:
            subir_google(x["id"])
        except Exception:
            pass
        return "♻️ Recuperé la deuda de " + x["persona"] + ": " + fmt(saldo(x["id"])) + "."
    if a == "deshacer":
        u = dict(_ULTIMA)
        _ULTIMA.clear()
        deuda = obtener(u["deuda"])
        if not deuda:
            return "No encuentro qué deshacer."
        if u["tipo"] == "nueva":
            actualizar(deuda["id"], estado="borrada")
            try:
                quitar_google(deuda["id"])
            except Exception:
                pass
            return ("🗑 Listo, borré lo que acababa de anotar: la deuda de " + deuda["persona"] + ".\n"
                    "Si fue un error: «recupera la deuda de " + deuda["persona"] + "».")
        with closing(_con()) as con, con:
            for mid in u.get("movimientos", []):
                con.execute("DELETE FROM deuda_movimientos WHERE id = ?", (mid,))
        actualizar(deuda["id"], estado="abierta" if saldo(deuda["id"]) > 0 else "saldada")
        return ("↩️ Deshice lo último (" + ("el pago" if u["tipo"] == "pago" else "lo que sumé") + "). "
                + _cap(deuda["persona"]) + (" le debe " if deuda["sentido"] == "me_debe" else ": usted le debe ")
                + fmt(saldo(deuda["id"])) + ".")
    if a == "plan":
        ds = abiertas(d["persona"])
        if not ds:
            return "No encuentro una deuda abierta de " + _nombre_bonito(d["persona"]) + ". Primero dígame cuánto debe."
        actualizar(ds[-1]["id"], cuota=d["cuota"], dia_cuota=d["dia_cuota"])
        return ("Anotado: " + ds[-1]["persona"] + " paga " + fmt(d["cuota"]) + " cada " + str(d["dia_cuota"])
                + " del mes. Le aviso ese día y si se atrasa.")

    sentido = "me_debe" if a in ("deuda_me", "prestamo", "pago_me") else "le_debo"
    if a in ("pago_me", "pago_yo"):
        ds = abiertas(d["persona"], sentido)
        if not ds:
            return ("No tengo una deuda abierta de " + _nombre_bonito(d["persona"]) + ". Si es nueva, dígame cuánto debe."
                    if sentido == "me_debe" else "No tengo registrado que le deba a " + _nombre_bonito(d["persona"]) + ".")
        deuda = min(ds, key=lambda x: x["id"])                     # la más antigua primero
        meses = d.get("meses") or []
        monto, nota = d.get("monto"), d.get("concepto", "")
        if not monto and meses:                                     # "me pagó septiembre": el pendiente de ese mes
            estado = por_mes(deuda["id"])
            elegidos = [(n, p) for n, _, _, p in estado if n and any(NOMBRE_MES[x].lower() in n.lower() for x in meses) and p > 0]
            if not elegidos:
                return "No encuentro pendiente de " + ", ".join(NOMBRE_MES[x].lower() for x in meses) + " en la cuenta de " + deuda["persona"] + "."
            monto = round(sum(p for _, p in elegidos), 2)
            nota = " y ".join(n for n, _ in elegidos)
        elif meses:
            nota = " y ".join(_etiqueta_mes(x, _anio_de(x)) for x in meses)
        if not monto and d.get("todo"):
            monto = saldo(deuda["id"])
        if not monto:
            return "¿Cuánto le pagó? Escríbalo así: «" + deuda["persona"] + " me pagó 100»."
        nuevo, sobra = pagar(deuda["id"], monto, nota)
        _ULTIMA.clear()
        _ULTIMA.update(deuda=deuda["id"], tipo="pago", cuando=ahora().timestamp(),
                       movimientos=[movimientos(deuda["id"])[-1]["id"]])
        quien = deuda["persona"]
        if nuevo <= 0 and not deuda.get("recurrente"):
            try:
                quitar_google(deuda["id"])
            except Exception as exc:
                log.info("No se quito de Google: %s", exc)
            texto = ("\U0001F389 " + quien + " terminó de pagarle" if sentido == "me_debe" else "\U0001F389 Terminó de pagarle a " + quien)
            texto += (" (" + deuda["concepto"] + ")" if deuda["concepto"] else "") + ". Cuenta saldada."
            if sobra > 0:
                texto += " Ojo: el pago fue " + fmt(sobra) + " mayor que la deuda."
        else:
            if nuevo <= 0:                                          # cuenta con suma mensual: sigue abierta
                actualizar(deuda["id"], estado="abierta")
            texto = ("Anotado el pago de " + fmt(monto) + (" (" + nota + ")" if nota else "") + ". "
                     + (_cap(quien) + " ahora le debe " if sentido == "me_debe" else "Ahora le debe a " + quien + " ") + fmt(max(nuevo, 0)) + ".")
        return texto + (" Guardé la captura." if movimientos(deuda["id"])[-1]["comprobante"] else "")

    # deuda nueva o más deuda (uno o varios montos, con o sin mes, con o sin suma mensual)
    persona = _nombre_bonito(d["persona"])
    cargos = d.get("cargos") or ([{"monto": d["monto"], "mes": None}] if d.get("monto") else [])
    ds = abiertas(persona, sentido)
    if ds and not (d.get("concepto") and ds[0]["concepto"] and _norm(d["concepto"]) != _norm(ds[0]["concepto"])):
        did = ds[0]["id"]
        texto = "Actualizado. "
    else:
        did = None
        texto = "Anotado. "
    agregados = []
    for c in cargos:
        nota = _etiqueta_mes(c["mes"], _anio_de(c["mes"])) if c.get("mes") else (d.get("concepto") or "")
        if did and c.get("mes") and any(m["tipo"] == "cargo" and _norm(m["nota"]) == _norm(nota) for m in movimientos(did)):
            continue                                                # ese mes ya estaba anotado
        if did is None:
            fecha = date(_anio_de(c["mes"]), c["mes"], 1) if c.get("mes") else None
            did = crear(persona, c["monto"], sentido, d.get("concepto", ""), d.get("limite"), d.get("cuota"),
                        d.get("dia_cuota"), fecha)
            with closing(_con()) as con, con:
                con.execute("UPDATE deuda_movimientos SET nota = ? WHERE deuda = ? AND tipo = 'cargo'", (nota, did))
        else:
            agregar_cargo(did, c["monto"], nota, date(_anio_de(c["mes"]), c["mes"], 1) if c.get("mes") else None)
        agregados.append((nota, c["monto"]))
    if did is None and d.get("recurrente"):                         # solo la regla mensual, sin montos atrasados
        did = crear(persona, 0, sentido, d.get("concepto", ""))
        with closing(_con()) as con, con:
            con.execute("DELETE FROM deuda_movimientos WHERE deuda = ? AND monto = 0", (did,))
    if did is None:
        return "No entendí el monto. Escríbalo así: «Juan me debe 500»."
    _ULTIMA.clear()
    _ULTIMA.update(deuda=did, tipo="nueva" if texto.startswith("Anotado") else "cargo", cuando=ahora().timestamp(),
                   movimientos=[m["id"] for m in movimientos(did)[-len(agregados):]] if agregados else [])
    cambios = {k: v for k, v in (("limite", d.get("limite")), ("cuota", d.get("cuota")), ("dia_cuota", d.get("dia_cuota"))) if v}
    if d.get("recurrente"):
        meses_cargados = [c["mes"] for c in cargos if c.get("mes")]
        if meses_cargados:
            ultimo = max(date(_anio_de(x), x, 1) for x in meses_cargados)
        else:
            hoy = ahora().date()
            ultimo = date(hoy.year, hoy.month, 1) - timedelta(days=1)
        cambios.update(recurrente=d["recurrente"], dia_recurrente=d.get("dia_recurrente") or 1,
                       ultimo_mes=ultimo.strftime("%Y-%m"))
    if cambios:
        actualizar(did, **cambios)
    deuda = obtener(did)
    if len(agregados) > 1:
        texto += "Sumé " + ", ".join(n.lower().split()[0] + " " + fmt(v) if n else fmt(v) for n, v in agregados) + ". "
    elif agregados and texto.startswith("Actualizado"):
        texto += "Sumé " + fmt(agregados[0][1]) + (" (" + agregados[0][0] + ")" if agregados[0][0] else "") + ". "
    texto += (_cap(persona) + " le debe " if sentido == "me_debe" else "Usted le debe a " + persona + " ") + fmt(saldo(did))
    texto += (" (" + deuda["concepto"] + ")" if deuda["concepto"] else "") + "."
    if deuda.get("recurrente"):
        a_, m_ = _mes_siguiente(*map(int, deuda["ultimo_mes"].split("-")))
        a2, m2 = _mes_siguiente(a_, m_)
        texto += ("\n🔁 Cada mes le sumo " + fmt(deuda["recurrente"]) + ": el " + str(deuda["dia_recurrente"]) + " de "
                  + NOMBRE_MES[m2].lower() + " entra " + NOMBRE_MES[m_].lower() + " y le aviso.")
    if deuda["cuota"] and deuda["dia_cuota"]:
        texto += " Cuota: " + fmt(deuda["cuota"]) + " cada " + str(deuda["dia_cuota"]) + "; le aviso ese día."
    elif deuda["limite"]:
        texto += " Fecha límite: " + _fecha_corta(deuda["limite"]) + "; le aviso antes."
    if movimientos(did) and movimientos(did)[-1]["comprobante"]:
        texto += " Guardé la captura."
    abonos = re.search(r"\b(\d+)\s+(abonos?|pagos?|cuotas?)\b", _limpiar(d.get("texto", "")))
    if abonos:
        texto += ("\nAnoté " + fmt(saldo(did)) + " como lo que falta. Si quiere el historial de los " + abonos.group(1) + " "
                  + abonos.group(2) + ", escríbalos así: «" + persona + " me abonó 200».")
    try:
        subir_google(did)
    except Exception as exc:
        log.info("Deuda %s sin Google: %s", did, exc)
    return texto


def aplicar_recurrentes(hoy=None):
    """Suma el monto mensual de cada cuenta con regla (por cada mes terminado que falte). Devuelve avisos."""
    hoy = hoy or ahora().date()
    avisos = []
    for d in abiertas() + [x for x in _todas("") if x["estado"] == "saldada" and x.get("recurrente")]:
        if not d.get("recurrente") or not d.get("ultimo_mes"):
            continue
        anio, mes = map(int, d["ultimo_mes"].split("-"))
        sumados = []
        while True:
            a_, m_ = _mes_siguiente(anio, mes)                       # mes a cobrar
            cobra_a, cobra_m = _mes_siguiente(a_, m_)                # se suma al empezar el mes siguiente
            if date(cobra_a, cobra_m, min(d["dia_recurrente"] or 1, 28)) > hoy:
                break
            agregar_cargo(d["id"], d["recurrente"], _etiqueta_mes(m_, a_), date(cobra_a, cobra_m, 1))
            anio, mes = a_, m_
            sumados.append(NOMBRE_MES[m_].lower())
        if sumados:
            actualizar(d["id"], ultimo_mes="%04d-%02d" % (anio, mes), estado="abierta")
            avisos.append(("recurrente", d["id"], "➕ Sumé " + fmt(d["recurrente"] * len(sumados)) + " de "
                           + " y ".join(sumados) + " a la cuenta de " + d["persona"] + ". "
                           + ("Ahora le debe " if d["sentido"] == "me_debe" else "Ahora usted le debe ")
                           + fmt(saldo(d["id"])) + "."))
    return avisos


PISTA_IA = re.compile(r"\b(?:debe|deben|debo|deuda|adeud\w*|prest\w*|por cobrar|cobrar|abon\w*|me pag\w*|le pag\w*)\b")


def procesar(texto):
    """Para el cerebro: si la frase es de deudas, la resuelve el código (o la IA si el código no la entiende)."""
    d = interpretar(texto)
    limpio = _limpiar(texto)
    nombra_deudor = re.search(r"\d", limpio) and any(
        re.search(r"(?<!\w)" + re.escape(_norm(x["persona"])) + r"(?!\w)", limpio) for x in abiertas())
    if not d and (PISTA_IA.search(limpio) and re.search(r"\d|mes|todo|quien|cuanto", limpio) or nombra_deudor):
        d = interpretar_con_ia(texto)
        if d:
            log.info("Deudas entendidas por la IA: %s", d)
    if not d:
        return None
    try:
        r = ejecutar(d)
        log.info("Deudas: %s -> %s", d["accion"], r[:80])
        return r
    except Exception as exc:
        log.warning("Error en deudas: %s", exc)
        return "No pude registrarlo: " + str(exc)[:100]


# ------------------------------------------------------------------ avisos ---
def avisos_de_hoy(hoy=None):
    """Lista de textos para hoy: cuotas que tocan, atrasos (3 dias despues) y fechas limite."""
    hoy = hoy or ahora().date()
    textos = aplicar_recurrentes(hoy)                 # suma mensual automática (una vez por mes, al empezar el mes)
    for d in abiertas():
        s = saldo(d["id"])
        if s <= 0:
            continue
        quien = d["persona"]
        cobra = d["sentido"] == "me_debe"
        if d["dia_cuota"]:
            dia = min(d["dia_cuota"], (date(hoy.year + hoy.month // 12, hoy.month % 12 + 1, 1) - timedelta(days=1)).day)
            vence = date(hoy.year, hoy.month, dia)
            pagos_mes = [m for m in movimientos(d["id"]) if m["tipo"] == "pago" and m["fecha"][:7] == hoy.isoformat()[:7]]
            if hoy == vence and not pagos_mes:
                textos.append(("cuota", d["id"], ("\U0001F4C5 Hoy " + quien + " deber\u00eda pagarle " if cobra
                               else "\U0001F4C5 Hoy le toca pagar a " + quien + " ") + fmt(min(d["cuota"] or s, s))
                               + " (saldo " + fmt(s) + ")."))
            if hoy == vence + timedelta(days=3) and not pagos_mes:
                textos.append(("atraso", d["id"], "\u23F0 " + (quien + " va 3 d\u00edas atrasado con su cuota" if cobra
                               else "Va 3 d\u00edas atrasado con la cuota a " + quien) + " (saldo " + fmt(s) + ")."))
        if d["limite"]:
            lim = date.fromisoformat(d["limite"])
            if hoy == lim - timedelta(days=1):
                textos.append(("limite", d["id"], "\U0001F4C5 Ma\u00f1ana vence la deuda de " + quien + " (saldo " + fmt(s) + ")."))
            elif hoy == lim:
                textos.append(("limite", d["id"], "\U0001F4C5 Hoy vence la deuda de " + quien + " (saldo " + fmt(s) + ")."))
            elif hoy == lim + timedelta(days=3):
                textos.append(("atraso", d["id"], "\u23F0 La deuda de " + quien + " venci\u00f3 hace 3 d\u00edas (saldo " + fmt(s) + ")."))
    return textos


def mensaje_cobro(did):
    """Borrador amable para cobrar (el usuario decide si lo envia)."""
    d = obtener(did)
    s = saldo(did)
    concepto = d["concepto"] or ""
    if concepto.lower().startswith("el "):
        concepto = "del " + concepto[3:]
    elif concepto:
        concepto = "de " + concepto
    return ("Hola " + d["persona"].split()[0].capitalize() + ", \u00bfc\u00f3mo est\u00e1s? Te escribo por lo pendiente"
            + (" " + concepto if concepto else "") + ": quedan " + fmt(s)
            + ". \u00bfCu\u00e1ndo crees que me puedas pagar? Gracias.")


def comprobantes_de(persona):
    rutas = []
    for d in abiertas(persona) + [x for x in _todas(persona) if x["estado"] == "saldada"]:
        rutas += [(d["persona"], m) for m in movimientos(d["id"]) if m["comprobante"] and Path(m["comprobante"]).exists()]
    return rutas


def _todas(persona, incluir_borradas=False):
    p = _norm(persona)
    with closing(_con()) as con:
        filas = [dict(f) for f in con.execute("SELECT * FROM deudas" + ("" if incluir_borradas else " WHERE estado != 'borrada'"))]
    return [f for f in filas if _norm(f["persona"]).startswith(p)]


# ------------------------------------------------------------------ Google Calendar (sin montos) ---
def subir_google(did):
    """Recordatorio en Google Calendar SIN montos: 'Cobro: Juan' (mensual si hay cuota, o en la fecha limite)."""
    d = obtener(did)
    if not d or not (d["dia_cuota"] or d["limite"]):
        return
    from modulos.calendario import google_cal as gc
    srv = gc.servicio(interactivo=False)
    cal_id = gc.id_calendario(srv)
    titulo = ("\U0001F4B0 Cobro: " if d["sentido"] == "me_debe" else "\U0001F4B8 Pago a: ") + d["persona"]
    if d["dia_cuota"]:
        hoy = ahora().date()
        dia = date(hoy.year, hoy.month, min(d["dia_cuota"], 28))
        if dia < hoy:
            dia = date(hoy.year + (hoy.month // 12), hoy.month % 12 + 1, min(d["dia_cuota"], 28))
        regla = ["RRULE:FREQ=MONTHLY;BYMONTHDAY=" + str(d["dia_cuota"])]
    else:
        dia, regla = date.fromisoformat(d["limite"]), None
    cuerpo = {"summary": titulo, "description": "Deuda #" + str(did) + " del asistente (detalle en la PC).",
              "start": {"date": dia.isoformat()}, "end": {"date": (dia + timedelta(days=1)).isoformat()},
              "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 900}]},
              "transparency": "transparent", "colorId": "5",
              "extendedProperties": {"private": {"asistente_clave": "deuda:" + str(did)}}}
    if regla:
        cuerpo["recurrence"] = regla
    clave = "deuda:" + str(did)
    fila = db.obtener_evento(clave)
    if fila and fila["google_id"] and fila["estado"] != "borrado":
        srv.events().update(calendarId=cal_id, eventId=fila["google_id"], body=cuerpo).execute()
        gid = fila["google_id"]
    else:
        gid = srv.events().insert(calendarId=cal_id, body=cuerpo).execute()["id"]
    db.guardar_evento(clave, "deuda", titulo, gid, "")


def quitar_google(did):
    fila = db.obtener_evento("deuda:" + str(did))
    if not fila or not fila["google_id"] or fila["estado"] == "borrado":
        return
    from modulos.calendario import google_cal as gc
    srv = gc.servicio(interactivo=False)
    try:
        srv.events().delete(calendarId=gc.id_calendario(srv), eventId=fila["google_id"]).execute()
    except Exception as exc:
        log.info("No se pudo borrar en Google: %s", exc)
    db.marcar_estado("deuda:" + str(did), "borrado")
