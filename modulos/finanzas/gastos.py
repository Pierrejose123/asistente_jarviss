"""Finanzas, paso 2: gastos e ingresos por Telegram y voz, con categorias y resumen mensual.

- Base local (tablas 'movimientos' y 'categorias_aprendidas'); fotos de facturas en la misma carpeta de
  comprobantes que las deudas. Nada de montos va a Google.
- Frases que entiende el CODIGO (rapido y exacto):
    "almuerzo 4.50"   "uber 3,20 con diners"   "gaste 15 en el supermercado"   "pague 30 de internet ayer"
    "compre pinceles por 12 con la gold"   "20 en gasolina"   "sueldo 800"   "me pagaron 200 por un logo"
    "cuanto gaste este mes"   "cuanto gaste en comida"   "gastos de la semana"   "borra el ultimo gasto"
  Lo dudoso lo decide la IA (herramienta anotar_gasto); las cuentas siempre las hace el codigo.
- La categoria sale de palabras clave (config/finanzas.json) y de lo que el usuario corrige (aprende).
"""
import re
import unicodedata
from collections import defaultdict
from contextlib import closing
from datetime import date, timedelta

from modulos.comun import db
from modulos.comun.base import CONFIG, ahora, leer_json, registro
from modulos.finanzas.deudas import _comprobante_reciente, dinero, fmt

log = registro("finanzas")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS movimientos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo        TEXT NOT NULL,              -- gasto | ingreso | inversion (depósito a un bróker: no es gasto)
    monto       REAL NOT NULL,
    descripcion TEXT DEFAULT '',
    categoria   TEXT DEFAULT 'Otros',
    medio       TEXT DEFAULT '',            -- Diners, Efectivo... (vacio = sin indicar)
    fecha       TEXT NOT NULL,              -- AAAA-MM-DD
    origen      TEXT DEFAULT 'telegram',    -- telegram | voz | correo
    comprobante TEXT DEFAULT '',
    ref         TEXT DEFAULT '',            -- id del correo del banco (paso 3)
    estado      TEXT DEFAULT 'activo',      -- activo | borrado
    creado      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS gastos_pendientes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    monto       REAL NOT NULL,
    descripcion TEXT NOT NULL,
    medio       TEXT DEFAULT '',
    fecha       TEXT NOT NULL,
    estado      TEXT DEFAULT 'pendiente',    -- pendiente | anotado | descartado
    creado      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS categorias_aprendidas (
    palabra   TEXT PRIMARY KEY,
    categoria TEXT NOT NULL
);
"""
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn").strip()


def ajustes():
    return leer_json("finanzas.json") if (CONFIG / "finanzas.json").exists() else {"medios": {}, "categorias": {"Otros": []}}


def categorias():
    return list(ajustes()["categorias"])


# ------------------------------------------------------------------ categoria y medio ---
def _palabras(descripcion):
    return [w for w in re.findall(r"[a-z0-9]+", _norm(descripcion)) if len(w) >= 3 and w not in
            ("con", "del", "las", "los", "una", "para", "por", "que", "mis", "the")]


def categoria_de(descripcion):
    """(categoria, segura). Primero lo aprendido, luego las palabras clave del archivo."""
    palabras = _palabras(descripcion)
    with closing(_con()) as con:
        for w in palabras:
            f = con.execute("SELECT categoria FROM categorias_aprendidas WHERE palabra = ?", (w,)).fetchone()
            if f:
                return f["categoria"], True
    texto = " " + " ".join(re.findall(r"[a-z0-9]+", _norm(descripcion))) + " "
    for cat, claves in ajustes()["categorias"].items():
        for c in sorted(claves, key=len, reverse=True):
            if " " + _norm(c) + " " in texto:
                return cat, True
    return "Otros", False


def aprender(descripcion, categoria):
    palabras = _palabras(descripcion)
    if not palabras:
        return
    with closing(_con()) as con, con:
        con.execute("INSERT OR REPLACE INTO categorias_aprendidas (palabra, categoria) VALUES (?, ?)", (palabras[0], categoria))


def tipo_ingreso(descripcion):
    """'movilidad' -> 'Movilidad'; 'sueldo de octubre' -> 'Sueldo'; lo demas -> 'Ingreso'."""
    t = _norm(descripcion)
    for nombre, claves in (("Sueldo", ("sueldo", "salario", "quincena")), ("Movilidad", ("movilidad", "viatico")),
                           ("Bono", ("bono", "aguinaldo", "decimo", "utilidades")), ("Comisión", ("comision",)),
                           ("Freelance", ("freelance", "logo", "diseno", "cliente", "proyecto")), ("Horas extra", ("horas extra",))):
        if any(c in t for c in claves):
            return nombre
    return "Ingreso"


def medio_de(texto):
    """Busca la tarjeta o medio en el texto. Devuelve (medio, texto_sin_medio)."""
    t = _norm(texto)
    mejor = None
    for medio, alias in ajustes().get("medios", {}).items():
        for a in sorted(alias + [medio], key=len, reverse=True):
            m = re.search(r"\s*(?:,\s*)?(?:con|en|por|usando|pagado con|pague con)?\s*(?:la |el |mi |tarjeta )*\b" + re.escape(_norm(a))
                          + r"\b", t)
            if m and (not mejor or len(a) > mejor[2]):
                mejor = (medio, m, len(a))
    if not mejor:
        return "", texto
    m = mejor[1]
    return mejor[0], (texto[:m.start()] + " " + texto[m.end():]).strip(" ,")


# ------------------------------------------------------------------ base de datos ---
def anotar(tipo, monto, descripcion, categoria=None, medio="", fecha=None, origen="telegram", ref="", usar_foto=True):
    descripcion = " ".join((descripcion or "").split()).strip(" ,.")[:120]
    if not categoria:
        categoria = categoria_de(descripcion)[0] if tipo == "gasto" else tipo_ingreso(descripcion)
    with closing(_con()) as con, con:
        return con.execute("INSERT INTO movimientos (tipo, monto, descripcion, categoria, medio, fecha, origen, comprobante, ref) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tipo, round(monto, 2), descripcion[:1].upper() + descripcion[1:], categoria, medio,
                            (fecha or ahora().date()).isoformat(), origen, _comprobante_reciente() if usar_foto else "",
                            ref)).lastrowid


def obtener(mid):
    with closing(_con()) as con:
        f = con.execute("SELECT * FROM movimientos WHERE id = ?", (mid,)).fetchone()
    return dict(f) if f else None


def cambiar(mid, **campos):
    with closing(_con()) as con, con:
        con.execute("UPDATE movimientos SET " + ", ".join(k + " = ?" for k in campos) + " WHERE id = ?", (*campos.values(), mid))


def ultimo():
    with closing(_con()) as con:
        f = con.execute("SELECT * FROM movimientos WHERE estado = 'activo' ORDER BY id DESC LIMIT 1").fetchone()
    return dict(f) if f else None


def del_periodo(desde, hasta, tipo=None):
    with closing(_con()) as con:
        filas = con.execute("SELECT * FROM movimientos WHERE estado = 'activo' AND fecha >= ? AND fecha <= ? "
                            + ("AND tipo = ? " if tipo else "") + "ORDER BY fecha, id",
                            (desde.isoformat(), hasta.isoformat()) + ((tipo,) if tipo else ())).fetchall()
    return [dict(f) for f in filas]


def mes(anio, m):
    inicio = date(anio, m, 1)
    fin = date(anio + m // 12, m % 12 + 1, 1) - timedelta(days=1)
    return inicio, fin


def total_categoria_mes(categoria, hoy=None):
    hoy = hoy or ahora().date()
    a, b = mes(hoy.year, hoy.month)
    return sum(x["monto"] for x in del_periodo(a, b, "gasto") if x["categoria"] == categoria)


def recientes(n=10):
    with closing(_con()) as con:
        return [dict(f) for f in con.execute("SELECT * FROM movimientos WHERE estado = 'activo' ORDER BY fecha DESC, id DESC "
                                             "LIMIT ?", (n,))]


def buscar(texto, tipo=None, dias=90):
    """Movimientos activos recientes cuya descripcion o categoria coincide con 'texto' (el mas nuevo primero)."""
    desde = (ahora().date() - timedelta(days=dias)).isoformat()
    palabras = [w for w in re.findall(r"[a-z0-9]+", _norm(texto)) if len(w) >= 3]
    with closing(_con()) as con:
        filas = [dict(f) for f in con.execute("SELECT * FROM movimientos WHERE estado = 'activo' AND fecha >= ? "
                                              "ORDER BY fecha DESC, id DESC", (desde,))]
    salida = []
    for f in filas:
        if tipo and f["tipo"] != tipo:
            continue
        donde = _norm(f["descripcion"] + " " + f["categoria"] + " " + f["medio"])
        if palabras and all(w in donde for w in palabras):
            salida.append(f)
    return salida


def linea(g):
    return ("#" + str(g["id"]) + " " + date.fromisoformat(g["fecha"]).strftime("%d/%m") + " " + g["descripcion"] + " "
            + ("+" if g["tipo"] == "ingreso" else "") + fmt(g["monto"]) + (" · " + g["medio"] if g["medio"] else ""))


# ------------------------------------------------------------------ entender frases ---
MONTO = r"\$?\s?(\d+(?:[.,]\d{1,2})?(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s?(?:d[oó]lares|usd|\$)?"
VERBO_GASTO = r"(?:gast[eé]|pagu[eé]|compr[eé]|me cost[oó]|sali[oó])"
P_GASTO_1 = re.compile(r"^\W*" + VERBO_GASTO + r"\s+" + MONTO + r"\s+(?:en|de|por|del|para)\s+(?:el |la |los |las |un |una )?(.+?)\W*$", re.I)
P_GASTO_2 = re.compile(r"^\W*(?:compr[eé]|pagu[eé])\s+(?:el |la |los |las |un |una )?(.+?)\s+(?:por|en|a)\s+" + MONTO + r"\W*$", re.I)
P_GASTO_3 = re.compile(r"^\W*" + MONTO + r"\s+(?:en|de|del)\s+(?:el |la |los |las |un |una )?(.+?)\W*$", re.I)
P_GASTO_4 = re.compile(r"^\W*([a-zA-ZÀ-ÿ][\wÀ-ÿ ]{1,40}?)\s+" + MONTO + r"\W*$", re.I)
P_INGRESO = re.compile(r"^\W*(?:ingreso|cobr[eé]|me pagaron|recib[ií]|me depositaron|gan[eé]|me lleg[oó] (?:el|mi)?)\s*"
                       r"(?:de |del |por )?(?:(?:el |mi )?(sueldo|salario|pago|bono)\s+(?:de\s+)?)?" + MONTO
                       + r"(?:\s+(?:de|por|del)\s+(?:un |una |el |la |mi )?(.+?))?\W*$", re.I)
TIPOS_INGRESO = r"(sueldo|salario|bono|quincena|movilidad|vi[aá]ticos?|comisi[oó]n|comisiones|aguinaldo|d[eé]cimo(?: tercero| cuarto)?|utilidades|horas extra|freelance|propina|propinas)"
P_SUELDO = re.compile(r"^\W*(?:me (?:pagaron|lleg[oó]|depositaron)\s+(?:la |el |mi |los |las )?|recib[ií]\s+(?:la |el |mi )?|cobr[eé]\s+(?:la |el |mi )?)?"
                      + TIPOS_INGRESO + r"\s+(?:de\s+)?" + MONTO + r"\W*$", re.I)
P_AYER = re.compile(r"\s*,?\s*\b(ayer|anteayer|antier|hoy)\b\s*", re.I)
P_CONSULTA = re.compile(r"cu[aá]nto (?:he )?gast[eé]|mis gastos|gastos (?:de|del|esta)|en qu[eé] (?:he )?gast[eé]|resumen (?:de|del) mes|"
                        r"resumen mensual|c[oó]mo voy (?:este mes|con (?:los |mis )?gastos)", re.I)
P_BORRAR_DESC = re.compile(r"^\W*(?:borra|elimina|quita|anula)(?:r)?\s+(?:el |mi |ese |este )?(gasto|ingreso)\s+(?:de |del |en |por )?"
                           r"(?:el |la |los |las )?(.+?)\W*$", re.I)
P_BORRAR = re.compile(r"^\W*(?:borra|elimina|quita|deshaz|anula)(?:r)?\s+(?:el |mi )?[uú]ltimo (?:gasto|movimiento|ingreso)\W*$", re.I)
NO_DESCRIPCION = re.compile(r"^(?:tengo|tienes|tiene|hay|son|es|era|fue|faltan|falta|quedan|queda|clase|clases|tarea|tareas|"
                            r"semana|semanas|mes|meses|a[nñ]o|a[nñ]os|dia|d[ií]as?|hora|horas|minutos?|segundos?|las|los|nivel|"
                            r"capitulo|cap[ií]tulo|pagina|p[aá]gina|ejercicio|ejercicios|sesion|sesi[oó]n|repeticiones|series|"
                            r"vuelta|vueltas|puesto|lugar|nota|calificaci[oó]n|piso|grupo|aula|me|le|te|se|yo|el|la|un|una|"
                            r"cuantos|cu[aá]ntos|cuanto|cu[aá]nto|que|qu[eé]|como|c[oó]mo|donde|d[oó]nde|cuando|cu[aá]ndo|"
                            r"version|versi[oó]n|top|numero|n[uú]mero|temporada|episodio|parte|modo|ronda|partida|kills|"
                            r"hey|hola|ok|okay|si|s[ií]|no|jarvis)\b", re.I)


def _fecha_de(texto):
    m = P_AYER.search(texto)
    if not m:
        return texto, None
    hoy = ahora().date()
    d = {"ayer": 1, "anteayer": 2, "antier": 2, "hoy": 0}[_norm(m.group(1))]
    return (texto[:m.start()] + " " + texto[m.end():]).strip(), hoy - timedelta(days=d)


def interpretar(texto):
    t = " ".join(texto.strip().split())
    if P_BORRAR.match(t):
        return {"accion": "borrar"}
    m = P_BORRAR_DESC.match(t)
    if m and not re.match(r"^[uú]ltimo\b", m.group(2), re.I):
        return {"accion": "borrar_desc", "tipo": _norm(m.group(1)), "texto": m.group(2)}
    if P_CONSULTA.search(t):
        return {"accion": "consulta", "texto": t}
    t, fecha = _fecha_de(t)
    medio, t = medio_de(t)
    m = P_SUELDO.match(t)
    if m:
        return {"accion": "ingreso", "monto": dinero(m.group(2)), "descripcion": m.group(1), "medio": medio, "fecha": fecha}
    m = P_INGRESO.match(t)
    if m:
        desc = " ".join(x for x in (m.group(1), m.group(3)) if x) or "Ingreso"
        return {"accion": "ingreso", "monto": dinero(m.group(2)), "descripcion": desc, "medio": medio, "fecha": fecha}
    for patron, orden in ((P_GASTO_1, "md"), (P_GASTO_2, "dm"), (P_GASTO_3, "md")):
        m = patron.match(t)
        if m:
            monto, desc = (m.group(1), m.group(2)) if orden == "md" else (m.group(2), m.group(1))
            return {"accion": "gasto", "monto": dinero(monto), "descripcion": desc, "medio": medio, "fecha": fecha}
    m = P_GASTO_4.match(t)
    if m and len(t.split()) <= 6 and not NO_DESCRIPCION.match(m.group(1).strip()):
        desc, monto = m.group(1).strip(), m.group(2)
        cat, segura = categoria_de(desc)
        if segura or medio or "$" in texto or re.search(r"[.,]\d{1,2}$", monto):     # claramente un gasto
            return {"accion": "gasto", "monto": dinero(monto), "descripcion": desc, "medio": medio, "fecha": fecha}
        if len(desc.split()) <= 3 and 0 < dinero(monto) <= 5000:                     # parece gasto: PREGUNTAR
            return {"accion": "dudoso", "monto": dinero(monto), "descripcion": desc, "medio": medio, "fecha": fecha}
    return None


def _periodo(texto):
    """(desde, hasta, nombre) segun la consulta."""
    t, hoy = _norm(texto), ahora().date()
    if "semana" in t:
        if "pasada" in t or "anterior" in t:
            lunes = hoy - timedelta(days=hoy.weekday() + 7)
            return lunes, lunes + timedelta(days=6), "la semana pasada"
        return hoy - timedelta(days=hoy.weekday()), hoy, "esta semana"
    if "hoy" in t:
        return hoy, hoy, "hoy"
    if "ayer" in t:
        return hoy - timedelta(days=1), hoy - timedelta(days=1), "ayer"
    for i, nombre in enumerate(MESES, 1):
        if nombre in t:
            anio = hoy.year if i <= hoy.month else hoy.year - 1
            a, b = mes(anio, i)
            return a, b, nombre
    if "mes pasado" in t or "anterior" in t:
        prev = hoy.replace(day=1) - timedelta(days=1)
        a, b = mes(prev.year, prev.month)
        return a, b, MESES[prev.month - 1]
    a, _ = mes(hoy.year, hoy.month)
    return a, hoy, "este mes"


def consulta(texto):
    desde, hasta, nombre = _periodo(texto)
    t = _norm(texto)
    cat = next((c for c in categorias() if _norm(c).split()[0] in t), None)
    gastos = del_periodo(desde, hasta, "gasto")
    if cat:
        lista = [g for g in gastos if g["categoria"] == cat]
        if not lista:
            return "No tiene gastos en " + cat + " " + nombre + "."
        lineas = ["En " + cat + " gastó " + fmt(sum(g["monto"] for g in lista)) + " " + nombre + " (" + str(len(lista))
                  + " gasto" + ("s" if len(lista) != 1 else "") + "):"]
        lineas += ["• " + date.fromisoformat(g["fecha"]).strftime("%d/%m") + " " + g["descripcion"] + " " + fmt(g["monto"])
                   + (" (" + g["medio"] + ")" if g["medio"] else "") for g in lista[-12:]]
        return "\n".join(lineas)
    return resumen(desde, hasta, nombre)


# ------------------------------------------------------------------ resumenes ---
def _barra(parte, total, ancho=10):
    n = round(parte / total * ancho) if total else 0
    return "▓" * n + "░" * (ancho - n)


def resumen(desde, hasta, nombre="", comparar=True):
    gastos = del_periodo(desde, hasta, "gasto")
    ingresos = del_periodo(desde, hasta, "ingreso")
    total = sum(g["monto"] for g in gastos)
    if not gastos and not ingresos and not del_periodo(desde, hasta, "inversion"):
        return "No tiene gastos registrados " + nombre + ". Anote uno así: «almuerzo 4.50»."
    por_cat = defaultdict(float)
    por_medio = defaultdict(float)
    por_desc = defaultdict(float)
    for g in gastos:
        por_cat[g["categoria"]] += g["monto"]
        por_medio[g["medio"] or "Sin indicar"] += g["monto"]
        por_desc[g["descripcion"]] += g["monto"]
    lineas = ["\U0001F4B8 Gastó " + fmt(total) + " " + nombre + " (" + str(len(gastos)) + " gastos)"]
    if ingresos:
        ent = sum(i["monto"] for i in ingresos)
        ahorro = ent - total
        lineas.append("\U0001F4B5 Ingresos " + fmt(ent) + " → " + ("ahorró " if ahorro >= 0 else "gastó de más ")
                      + fmt(abs(ahorro)) + (" (" + str(round(ahorro / ent * 100)) + " % de lo que entró)" if ent and ahorro > 0 else ""))
    previo = {}
    if comparar and desde.day == 1:
        p = desde - timedelta(days=1)
        pa, pb = mes(p.year, p.month)
        dias = (hasta - desde).days                                     # mismo tramo del mes anterior
        pb = min(pb, pa + timedelta(days=dias))
        for g in del_periodo(pa, pb, "gasto"):
            previo[g["categoria"]] = previo.get(g["categoria"], 0) + g["monto"]
    lineas += ["", "Por categoría:"]
    mayor = max(por_cat.values()) if por_cat else 0
    for c, v in sorted(por_cat.items(), key=lambda x: -x[1]):
        dif = ""
        if previo:
            antes = previo.get(c, 0)
            if antes:
                cambio = (v / antes - 1) * 100
                dif = "  (" + ("↑" if cambio > 0 else "↓") + str(abs(round(cambio))) + " %)" if abs(cambio) >= 10 else ""
            else:
                dif = "  (nuevo)"
        lineas.append(_barra(v, mayor) + " " + c + " " + fmt(v) + " · " + str(round(v / total * 100)) + " %" + dif)
    if len(por_medio) > 1 or "Sin indicar" not in por_medio:
        lineas += ["", "Por tarjeta o medio:"]
        lineas += ["• " + k + ": " + fmt(v) for k, v in sorted(por_medio.items(), key=lambda x: -x[1])]
    top = sorted(por_desc.items(), key=lambda x: -x[1])[:5]
    if len(gastos) >= 5:
        lineas += ["", "En lo que más gastó:"]
        lineas += ["• " + k + ": " + fmt(v) for k, v in top]
    if previo:
        antes = sum(previo.values())
        if antes:
            cambio = (total / antes - 1) * 100
            lineas += ["", "Comparado con el mismo tramo del mes anterior: " + ("↑ " if cambio > 0 else "↓ ")
                       + str(abs(round(cambio))) + " % (" + fmt(antes) + " entonces)."]
    invertido = del_periodo(desde, hasta, "inversion")
    if invertido:
        lineas += ["", "📈 Invertido (no cuenta como gasto): " + fmt(sum(i["monto"] for i in invertido)) + " — "
                   + ", ".join(i["descripcion"] + " " + fmt(i["monto"]) for i in invertido[:4])]
    return "\n".join(lineas)


def resumen_mes_anterior():
    hoy = ahora().date()
    p = hoy.replace(day=1) - timedelta(days=1)
    a, b = mes(p.year, p.month)
    texto = "\U0001F4CA Resumen de " + MESES[p.month - 1] + "\n\n" + resumen(a, b, "en " + MESES[p.month - 1], comparar=False)
    pp = a - timedelta(days=1)
    pa, pb = mes(pp.year, pp.month)
    antes = sum(g["monto"] for g in del_periodo(pa, pb, "gasto"))
    ahora_ = sum(g["monto"] for g in del_periodo(a, b, "gasto"))
    if antes and ahora_:
        cambio = (ahora_ / antes - 1) * 100
        texto += ("\n\nFrente a " + MESES[pp.month - 1] + ": " + ("gastó " + str(round(cambio)) + " % más" if cambio > 0
                  else "gastó " + str(abs(round(cambio))) + " % menos") + ".")
    fijos = repetidos()
    if fijos:
        texto += "\n\n\U0001F501 Pagos que se repiten cada mes (posibles suscripciones):\n" + "\n".join(
            "• " + d + ": " + fmt(v) for d, v in fijos)
    return texto


def repetidos():
    """Descripciones que aparecen en los 2 ultimos meses completos con monto parecido (suscripciones)."""
    hoy = ahora().date()
    m1 = hoy.replace(day=1) - timedelta(days=1)
    m2 = m1.replace(day=1) - timedelta(days=1)
    a1, b1 = mes(m1.year, m1.month)
    a2, b2 = mes(m2.year, m2.month)
    uno = {_norm(g["descripcion"]): g for g in del_periodo(a1, b1, "gasto")}
    dos = {_norm(g["descripcion"]): g for g in del_periodo(a2, b2, "gasto")}
    return [(uno[k]["descripcion"], uno[k]["monto"]) for k in uno if k in dos
            and abs(uno[k]["monto"] - dos[k]["monto"]) <= max(1, 0.1 * dos[k]["monto"])]


# ------------------------------------------------------------------ ejecutar ---
def confirmacion(mid):
    g = obtener(mid)
    if g["tipo"] == "ingreso":
        return "\U0001F4B5 Anotado ingreso de " + fmt(g["monto"]) + " (" + g["descripcion"] + ")" + (" · " + g["medio"] if g["medio"] else "") + "."
    hoy = ahora().date()
    texto = ("\U0001F4B8 Anotado: " + fmt(g["monto"]) + " en " + g["categoria"] + " (" + g["descripcion"] + ")"
             + (" · " + g["medio"] if g["medio"] else "")
             + ("" if g["fecha"] == hoy.isoformat() else " · " + date.fromisoformat(g["fecha"]).strftime("%d/%m")) + ".")
    if not presupuesto_de(g["categoria"]):
        texto += " Este mes en " + g["categoria"] + ": " + fmt(total_categoria_mes(g["categoria"])) + "."
    if g["comprobante"]:
        texto += " Guardé la foto."
    if g["fecha"][:7] == hoy.isoformat()[:7]:
        try:
            from modulos.finanzas import presupuesto
            extra = presupuesto.tras_gasto(g)
            if extra:
                texto += "\n" + extra
        except Exception as exc:
            log.info("Sin datos de presupuesto: %s", exc)
    return texto


def presupuesto_de(categoria):
    try:
        from modulos.finanzas import presupuesto
        return presupuesto.presupuestos().get(categoria)
    except Exception:
        return None


def crear_pendiente(d):
    with closing(_con()) as con, con:
        return con.execute("INSERT INTO gastos_pendientes (monto, descripcion, medio, fecha) VALUES (?, ?, ?, ?)",
                           (d["monto"], d["descripcion"][:120], d.get("medio", ""),
                            (d.get("fecha") or ahora().date()).isoformat())).lastrowid


def pendiente(pid):
    with closing(_con()) as con:
        f = con.execute("SELECT * FROM gastos_pendientes WHERE id = ?", (pid,)).fetchone()
    return dict(f) if f else None


def resolver_pendiente(pid, categoria):
    """El usuario eligio la categoria: se anota el gasto y se aprende la palabra."""
    p = pendiente(pid)
    if not p or p["estado"] != "pendiente":
        return None
    with closing(_con()) as con, con:
        con.execute("UPDATE gastos_pendientes SET estado = 'anotado' WHERE id = ?", (pid,))
    desc, ref = p["descripcion"], ""
    m = re.search(r"\s*\[(gmail:[^\]]+)\]$", desc)              # viene de un correo del banco
    if m:
        desc, ref = desc[:m.start()], m.group(1)
    else:
        aprender(desc, categoria)
    mid = anotar("gasto", p["monto"], desc, categoria, p["medio"], date.fromisoformat(p["fecha"]),
                 "correo" if ref else "telegram", ref, usar_foto=not ref)
    return mid


def descartar_pendiente(pid):
    with closing(_con()) as con, con:
        con.execute("UPDATE gastos_pendientes SET estado = 'descartado' WHERE id = ?", (pid,))


def pregunta_pendiente(pid):
    """(texto, filas_de_botones_en_formato_crudo) para preguntar la categoria."""
    p = pendiente(pid)
    texto = ("🤔 ¿«" + p["descripcion"] + "» es un gasto de " + fmt(p["monto"]) + "?" + (" (" + p["medio"] + ")" if p["medio"] else "")
             + "\nElija la categoría y lo anoto (y aprendo para la próxima):")
    botones = [{"text": c, "callback_data": "gas:pend:" + str(pid) + ":" + str(i)} for i, c in enumerate(categorias())]
    filas = [botones[j:j + 2] for j in range(0, len(botones), 2)]
    filas.append([{"text": "❌ No es un gasto", "callback_data": "gas:pendno:" + str(pid)}])
    return texto, filas


ULTIMO_ANOTADO = []          # el bot lo usa para poner los botones "Cambiar categoria / Deshacer"


def ejecutar(d, origen="telegram"):
    a = d["accion"]
    if a == "consulta":
        return consulta(d["texto"])
    if a == "borrar_desc":
        lista = buscar(d["texto"], "ingreso" if d.get("tipo") == "ingreso" else "gasto")
        if not lista:
            return "No encontré un " + (d.get("tipo") or "gasto") + " reciente de «" + d["texto"] + "»."
        texto = "Encontré: " + linea(lista[0]) + ". Para borrarlo escriba /borrargasto " + str(lista[0]["id"])
        if len(lista) > 1:
            texto += "\nOtros parecidos: " + "; ".join(linea(x) for x in lista[1:4])
        return texto
    if a == "borrar":
        u = ultimo()
        if not u:
            return "No hay movimientos para borrar."
        cambiar(u["id"], estado="borrado")
        return "\U0001F5D1 Borré el último: " + u["descripcion"] + " " + fmt(u["monto"]) + "."
    if a == "dudoso":
        pid = crear_pendiente(d)
        texto, filas = pregunta_pendiente(pid)
        if origen == "voz":                       # por voz: los botones van a Telegram
            try:
                from modulos.comun.base import enviar_telegram
                enviar_telegram(texto, filas)
                return "No estoy seguro de si «" + d["descripcion"] + "» es un gasto. Le pregunté en Telegram, señor."
            except Exception as exc:
                log.info("No pude preguntar en Telegram: %s", exc)
        return texto.split("\n")[0] + " Respóndame con la categoría, por ejemplo «" + d["descripcion"] + " " + ("%g" % d["monto"]) + " en comida»."
    if d["monto"] <= 0 or d["monto"] > 100000:
        return "Ese monto no parece correcto."
    mid = anotar(a, d["monto"], d.get("descripcion", ""), d.get("categoria"), d.get("medio", ""), d.get("fecha"), origen)
    ULTIMO_ANOTADO[:] = [mid]
    return confirmacion(mid)


def procesar(texto, origen="telegram"):
    d = interpretar(texto)
    if not d:
        return None
    try:
        r = ejecutar(d, origen)
        log.info("Gastos: %s -> %s", d["accion"], r[:80])
        return r
    except Exception as exc:
        log.warning("Error en gastos: %s", exc)
        return "No pude registrarlo: " + str(exc)[:100]
