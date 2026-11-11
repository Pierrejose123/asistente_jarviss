"""Ahorros programados (por ejemplo, los dos de Produbanco): para que son, saldo, aporte mensual y meta.

- Tabla 'ahorros'. El aporte mensual se suma al saldo el dia del aporte (saldo ESTIMADO) y se avisa;
  si el banco muestra otro valor, el usuario lo corrige: "ahorro viaje 498".
- Los aportes se descuentan del dinero disponible del mes (presupuesto).
- Frases en codigo: "ahorro viaje 498" / "en el ahorro del viaje tengo 498" / "mis ahorros".
  Crear o cambiar un ahorro con todos sus datos lo hace la IA con la herramienta guardar_ahorro.
"""
import re
import unicodedata
from contextlib import closing
from datetime import date

from modulos.comun import db
from modulos.comun.base import ahora, registro
from modulos.finanzas.deudas import dinero, fmt

log = registro("finanzas")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ahorros (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre      TEXT NOT NULL,
    banco       TEXT DEFAULT '',
    para_que    TEXT DEFAULT '',
    saldo       REAL DEFAULT 0,
    aporte      REAL DEFAULT 0,          -- aporte mensual
    dia_aporte  INTEGER,
    meta        REAL,
    fecha_meta  TEXT,                    -- AAAA-MM-DD
    estado      TEXT DEFAULT 'activo',
    actualizado TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    columnas = {f[1] for f in con.execute("PRAGMA table_info(ahorros)")}
    if "aporte_pct" not in columnas:                       # aporte como % del sueldo (se ajusta solo)
        con.execute("ALTER TABLE ahorros ADD COLUMN aporte_pct REAL")
        con.commit()
    return con


def _raiz(t):
    """'Viajes' -> 'viaje', 'emergencias' -> 'emergencia' (para comparar nombres)."""
    t = _norm(t)
    return t[:-1] if len(t) > 4 and t.endswith("s") else t


def aporte_efectivo(a):
    """Aporte mensual en dolares: fijo, o % del sueldo actual."""
    if a.get("aporte_pct"):
        try:
            from modulos.finanzas import presupuesto
            return round(presupuesto.sueldo() * a["aporte_pct"] / 100, 2)
        except Exception:
            return 0.0
    return a.get("aporte") or 0.0


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn").strip()


def activos():
    with closing(_con()) as con:
        return [dict(f) for f in con.execute("SELECT * FROM ahorros WHERE estado = 'activo' ORDER BY id")]


def buscar(nombre):
    n = _raiz(nombre)
    lista = activos()
    exacto = [a for a in lista if _raiz(a["nombre"]) == n]
    return (exacto or [a for a in lista if n in _raiz(a["nombre"]) or _raiz(a["nombre"]) in n
                       or (a["para_que"] and n in _norm(a["para_que"]))] or [None])[0]


def guardar(nombre, saldo=None, aporte=None, dia_aporte=None, meta=None, fecha_meta=None, para_que=None, banco=None,
            aporte_pct=None):
    """Crea el ahorro o actualiza los datos que vengan."""
    a = buscar(nombre)
    campos = {k: v for k, v in (("saldo", saldo), ("aporte", aporte), ("dia_aporte", dia_aporte), ("meta", meta),
                                ("fecha_meta", fecha_meta), ("para_que", para_que), ("banco", banco),
                                ("aporte_pct", aporte_pct)) if v not in (None, "")}
    if aporte is not None and aporte_pct is None:
        campos["aporte_pct"] = None                          # paso a monto fijo
    with closing(_con()) as con, con:
        if a:
            if campos:
                con.execute("UPDATE ahorros SET " + ", ".join(k + " = ?" for k in campos) + ", actualizado = CURRENT_TIMESTAMP "
                            "WHERE id = ?", (*campos.values(), a["id"]))
            return a["id"], False
        nombre = nombre.strip()[:1].upper() + nombre.strip()[1:60]
        aid = con.execute("INSERT INTO ahorros (nombre) VALUES (?)", (nombre,)).lastrowid
        if campos:
            con.execute("UPDATE ahorros SET " + ", ".join(k + " = ?" for k in campos) + " WHERE id = ?", (*campos.values(), aid))
        return aid, True


def obtener(aid):
    with closing(_con()) as con:
        f = con.execute("SELECT * FROM ahorros WHERE id = ?", (aid,)).fetchone()
    return dict(f) if f else None


def aportes_mensuales():
    return round(sum(aporte_efectivo(a) for a in activos()), 2)


def linea(a, hoy=None):
    hoy = hoy or ahora().date()
    texto = "🐷 " + a["nombre"] + (" (" + a["para_que"] + ")" if a["para_que"] and _norm(a["para_que"]) != _norm(a["nombre"])
                                   and a["meta"] != 0 else "")
    texto += ": " + fmt(a["saldo"] or 0)
    if a["meta"]:
        pct = (a["saldo"] or 0) / a["meta"] * 100
        texto += " de " + fmt(a["meta"]) + " (" + str(round(pct)) + " %)"
    aporte = aporte_efectivo(a)
    if aporte:
        texto += (" · aporta " + fmt(aporte) + "/mes" + (" (" + ("%g" % a["aporte_pct"]) + " % del sueldo)" if a.get("aporte_pct") else "")
                  + (" el " + str(a["dia_aporte"]) if a["dia_aporte"] else ""))
    elif a.get("aporte_pct"):
        texto += " · aporta " + ("%g" % a["aporte_pct"]) + " % del sueldo (dígame su sueldo para calcularlo)"
    if a["meta"] == 0:
        texto += " · sin meta fija (para lo que haga falta)"
        if aporte:
            texto += "; en un año sumaría " + fmt((a["saldo"] or 0) + aporte * 12)
    if a["meta"] and a["fecha_meta"]:
        f = date.fromisoformat(a["fecha_meta"])
        meses = max(0, (f.year - hoy.year) * 12 + f.month - hoy.month)
        falta = a["meta"] - (a["saldo"] or 0)
        if falta <= 0:
            texto += " · ¡meta cumplida!"
        elif meses:
            necesario = falta / meses
            texto += (" · meta " + f.strftime("%m/%Y") + ": necesita " + fmt(necesario) + "/mes"
                      + (" ✅ va bien" if aporte >= necesario - 0.01 else " ⚠️ con su aporte no llega"))
        else:
            texto += " · la fecha de la meta ya llegó (faltan " + fmt(falta) + ")"
    elif a["meta"] and aporte:
        falta = a["meta"] - (a["saldo"] or 0)
        if falta > 0:
            meses = -(-falta // aporte)
            texto += " · llega a la meta en ~" + str(int(meses)) + " meses"
    return texto


def resumen():
    lista = activos()
    if not lista:
        return ("No tengo registrados sus ahorros programados. Cuénteme de cada uno: para qué es, cuánto tiene, "
                "cuánto aporta al mes y qué día, y si tiene una meta (monto y fecha).")
    total = sum(a["saldo"] or 0 for a in lista)
    return ("🐷 Sus ahorros: " + fmt(total) + " en total, aporta " + fmt(aportes_mensuales()) + " al mes\n"
            + "\n".join("• " + linea(a)[2:] for a in lista)
            + "\n\nSi el banco muestra otro saldo, dígame por ejemplo «ahorro " + lista[0]["nombre"].lower() + " 498».")


def aportes_de_hoy(hoy=None):
    """Suma el aporte del dia al saldo (una vez por mes) y devuelve los textos de aviso."""
    hoy = hoy or ahora().date()
    textos = []
    for a in activos():
        aporte = aporte_efectivo(a)
        if not aporte or not a["dia_aporte"]:
            continue
        ultimo = (date(hoy.year + hoy.month // 12, hoy.month % 12 + 1, 1) - date.resolution).day
        if hoy.day != min(a["dia_aporte"], ultimo):
            continue
        clave = hoy.isoformat()[:7] + "|aporte_ahorro|" + str(a["id"])
        if db.aviso_enviado(clave):
            continue
        db.marcar_aviso(clave)
        nuevo = round((a["saldo"] or 0) + aporte, 2)
        guardar(a["nombre"], saldo=nuevo)
        textos.append("🐷 Hoy se debitó su aporte de " + fmt(aporte) + " al ahorro «" + a["nombre"] + "». Saldo estimado: "
                      + fmt(nuevo) + ".\n" + linea(obtener(a["id"])) + "\nSi el banco muestra otro valor, dígame «ahorro "
                      + a["nombre"].lower() + " <monto>».")
    return textos


# ------------------------------------------------------------------ frases ---
MONTO = r"\$?\s?(\d+(?:[.,]\d{1,2})?(?:[.,]\d{3})*(?:[.,]\d{1,2})?)"
P_SALDO = re.compile(r"^\W*(?:mi\s+)?ahorro\s+(?:de(?:l)?\s+|para\s+(?:el\s+|la\s+)?)?(?:mi\s+)?(.+?)\s+(?:tiene\s+|tengo\s+|est[aá] en\s+|es\s+|=\s*)?" + MONTO + r"\W*$", re.I)
P_SALDO_2 = re.compile(r"^\W*en (?:el|mi) ahorro (?:de(?:l)?|para(?: el| la)?)\s+(.+?)\s+(?:tengo|hay|llevo)\s+" + MONTO + r"\W*$", re.I)
P_VER = re.compile(r"^\W*(?:mis ahorros|ahorros|ver ahorros|cu[aá]nto (?:tengo )?(?:en mis ahorros|ahorrado)|c[oó]mo van mis ahorros)\W*$", re.I)


NOMBRE = r"([a-zA-Z\u00c0-\u00ff]+(?:\s+(?:de\s+)?[a-zA-Z\u00c0-\u00ff]+)?)"
P_DECLARA = re.compile(r"\buno\s+(?:para|de)\s+(?:el |la |los |las |un |una )?([a-zA-Z\u00c0-\u00ff]+)", re.I)
P_TENGO = re.compile(r"(?:en\s+)?(?:el|la|mi)\s+(?:ahorro\s+(?:programado\s+)?|cuenta\s+)?(?:de(?:l)?|para(?:\s+el|\s+la|\s+los)?)\s+"
                     r"(?:mi\s+|mis\s+|la\s+|los\s+)?([a-zA-Z\u00c0-\u00ff]+)\s+(?:tengo|hay|llevo|tiene|est[aá]\s+en|va\s+en)\s+" + MONTO, re.I)
P_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:de\s+mi\s+sueldo|del\s+sueldo|de\s+lo\s+que\s+gano)", re.I)
P_DIA = re.compile(r"(?:se\s+(?:debita|descuenta|paga)|aporto|pongo|deposito)\D{0,25}?\bel\s+(?:d[ií]a\s+)?(\d{1,2})\b", re.I)
P_META = re.compile(r"meta\s+(?:del?\s+(?:mi\s+|la\s+)?[a-zA-Z\u00c0-\u00ff]+\s+)?(?:es\s+)?(?:de\s+)?" + MONTO + r"(?:\s+(?:para|en|hasta)\s+(?:el\s+|la\s+)?(?:(\d{1,2})/)?"
                    r"([a-zA-Z\u00c0-\u00ff]+|\d{1,2})(?:\s+de)?(?:\s+|/)(\d{4}))?", re.I)
MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
         "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


def _nombre_ahorro(palabra):
    p = _raiz(palabra)
    for nombre in list(_NOMBRES_VISTOS):                # mismo nombre ya usado en este mensaje
        if _raiz(nombre) == p:
            return nombre
    nombre = {"emergencia": "Emergencias", "viaje": "Viaje", "carro": "Carro", "auto": "Carro", "casa": "Casa",
              "estudio": "Estudios", "universidad": "Estudios"}.get(p, palabra.strip().capitalize())
    _NOMBRES_VISTOS.add(nombre)
    return nombre


_NOMBRES_VISTOS = set()


def interpretar_compuesto(texto):
    """'Tengo dos ahorros, uno para viaje y uno de emergencia. En el de emergencia tengo 428 y en el de viajes 70.
    Saco el 10% de mi sueldo para cada uno' -> lista de cambios por ahorro."""
    _NOMBRES_VISTOS.clear()
    t = " ".join(texto.strip().split())
    referido = re.search(r"\b(?:el|la)\s+de(?:l)?\s+(?:mi\s+|mis\s+|la\s+|los\s+)?([a-zA-Z\u00c0-\u00ff]+)", t, re.I)
    if not referido or not buscar(referido.group(1)):
        referido = re.search(r"\bmeta\s+(?:del?|para(?:\s+el|\s+la)?)\s+(?:mi\s+|la\s+|los\s+)?([a-zA-Z\u00c0-\u00ff]+)", t, re.I)
    if not re.search(r"ahorr", t, re.I) and not (referido and buscar(referido.group(1))) \
            and not (activos() and re.search(r"\b(?:los dos|ambos|ambas|las dos)\b.*\b(?:se\s+)?debit", t, re.I)):
        return None
    cambios = {}
    def clave(palabra):                                    # 'viajes' y 'viaje' son el mismo ahorro
        existente = buscar(palabra)
        return existente["nombre"] if existente else _nombre_ahorro(palabra)

    for m in P_DECLARA.finditer(t):
        cambios.setdefault(clave(m.group(1)), {})
    for m in P_TENGO.finditer(t):
        cambios.setdefault(clave(m.group(1)), {})["saldo"] = dinero(m.group(2))
    for m in re.finditer(r"(?:en\s+)?el\s+de\s+(?:mi\s+|mis\s+|la\s+|los\s+)?([a-zA-Z\u00c0-\u00ff]+)\s+(?:tengo\s+|hay\s+|llevo\s+)?" + MONTO, t, re.I):
        cambios.setdefault(clave(m.group(1)), {}).setdefault("saldo", dinero(m.group(2)))
    pct = P_PCT.search(t)
    if pct:
        valor = float(pct.group(1).replace(",", "."))
        destino = cambios or {a["nombre"]: {} for a in activos()}
        for nombre in destino:
            cambios.setdefault(nombre, {})["aporte_pct"] = valor
    dia = P_DIA.search(t)
    meta = P_META.search(t)
    if dia:                                                 # el dia del debito puede ser de varios a la vez
        mencionados = []
        for m in re.finditer(r"\b(?:de(?:l)?|para)\s+(?:mi\s+|mis\s+|la\s+|los\s+|el\s+)?([a-zA-Z\u00c0-\u00ff]+)", t, re.I):
            a = buscar(m.group(1)) if len(m.group(1)) > 3 else None
            if a and a["nombre"] not in mencionados:
                mencionados.append(a["nombre"])
        for n in cambios:
            if n not in mencionados:
                mencionados.append(n)
        if re.search(r"\b(?:los dos|las dos|ambos|ambas|todos|todas|cada uno|los\s+\w+\s+ahorros)\b", t, re.I):
            mencionados = [x["nombre"] for x in activos()] + [n for n in cambios if not buscar(n)]
        if len(mencionados) > 1:
            for n in mencionados:
                cambios.setdefault(n, {})["dia_aporte"] = int(dia.group(1))
            dia = None                                        # ya aplicado
    if (dia or meta) and len(cambios) <= 1:
        nombre = next(iter(cambios), None)
        if not nombre:
            for m in (re.search(r"ahorro\s+(?:de(?:l)?|para(?:\s+el|\s+la)?)\s+(?:mi\s+|mis\s+|la\s+|los\s+)?([a-zA-Z\u00c0-\u00ff]+)", t, re.I), referido):
                if m and buscar(m.group(1)):
                    nombre = buscar(m.group(1))["nombre"]
                    break
        if nombre:
            if dia:
                cambios.setdefault(nombre, {})["dia_aporte"] = int(dia.group(1))
            if meta:
                cambios.setdefault(nombre, {})["meta"] = dinero(meta.group(1))
                if meta.group(4):
                    mes_txt = meta.group(3)
                    mes = int(mes_txt) if mes_txt.isdigit() else MESES.get(_norm(mes_txt))
                    if mes:
                        import calendar
                        anio = int(meta.group(4))
                        dia_m = int(meta.group(2)) if meta.group(2) else calendar.monthrange(anio, mes)[1]
                        cambios[nombre]["fecha_meta"] = "%04d-%02d-%02d" % (anio, mes, dia_m)
    return cambios or None


SUELDO_EN_TEXTO = re.compile(r"(?:mi\s+)?(?:sueldo|salario)\s+(?:es|son|ser[aá]|de|=)\s+(?:de\s+)?" + MONTO, re.I)
DIA_PAGO_EN_TEXTO = re.compile(r"me\s+(?:pagan|depositan|llega(?:\s+el\s+sueldo)?)\s+(?:hasta\s+|m[aá]ximo\s+)?(?:el\s+)?(?:d[ií]a\s+)?(\d{1,2})\b", re.I)


def sueldo_en_texto(texto):
    """Si el mensaje trae el sueldo o el dia de pago, se guardan. Devuelve el texto de confirmacion o ''."""
    from modulos.finanzas import presupuesto
    partes = []
    m = SUELDO_EN_TEXTO.search(texto)
    if m:
        valor = dinero(m.group(1))
        if 0 < valor < 100000:
            presupuesto.ajuste("sueldo", valor)
            partes.append("sueldo " + fmt(valor))
    d = DIA_PAGO_EN_TEXTO.search(texto)
    if d and 1 <= int(d.group(1)) <= 31:
        presupuesto.ajuste("dia_pago", int(d.group(1)))
        partes.append("le pagan el " + d.group(1))
    return ("💼 También anoté: " + ", ".join(partes) + ".") if partes else ""


def _pregunta(nombres=None):
    """Guarda (o lee) a que ahorros se les pregunto por la meta, para entender la respuesta siguiente."""
    import json
    import time
    from modulos.finanzas import presupuesto
    if nombres is not None:
        presupuesto.ajuste("ahorros_pregunta_meta", json.dumps({"t": time.time(), "nombres": nombres}))
        return nombres
    try:
        d = json.loads(presupuesto.ajuste("ahorros_pregunta_meta") or "{}")
    except ValueError:
        return []
    return d.get("nombres", []) if time.time() - d.get("t", 0) < 3600 else []


SIN_META = re.compile(r"\b(?:no\s+(?:tiene|tienen|hay|tengo)(?:\s+\w+){0,2}\s+meta|sin\s+meta|ninguno|ninguna|no\s+tienen|"
                      r"no\s+tiene|para\s+(?:cualquier|lo\s+que)|por\s+(?:cualquier|si\s+acaso|si\s+las\s+moscas)|"
                      r"cualquier\s+cosa|imprevistos?|no\s+hay\s+fecha|no\s+tengo\s+fecha|solo\s+(?:lo\s+)?ahorro|"
                      r"^\W*no\W*$|^\W*nop?e?\W*$|^\W*ninguna?\W*$)", re.I)


def respuesta_meta(texto):
    """Si se acaba de preguntar por la meta y el usuario dice que no tienen: se guardan 'sin meta fija'."""
    nombres = _pregunta()
    t = " ".join(texto.split())
    general = re.search(r"ahorr", t, re.I) and re.search(r"sin meta|no tienen meta|ninguno tiene meta|no tiene meta", t, re.I)
    if not (nombres or general) or not SIN_META.search(t) or P_META.search(t):
        return None
    if not nombres:
        nombres = [a["nombre"] for a in activos() if a["meta"] is None]
    if not nombres:
        return None
    for n in nombres:
        guardar(n, meta=0, para_que="para lo que haga falta" if re.search(r"cualquier|si acaso|imprevist|lo que", t, re.I) else None)
    _pregunta([])
    plural = len(nombres) > 1
    texto = ("Entendido, señor: " + ("son ahorros" if plural else "es un ahorro") + " sin meta fija, para lo que haga falta. "
             "Ya no le preguntaré por eso; le iré mostrando cuánto " + ("llevan" if plural else "lleva") + " y cuánto "
             + ("suman" if plural else "suma") + " cada mes.\n\n")
    texto += "\n".join("• " + linea(buscar(n))[2:] for n in nombres if buscar(n))
    if any(_raiz(n) == "emergencia" for n in nombres):
        try:
            from modulos.finanzas import perfil
            h = perfil.habitos()
            if h["meses"] and h["total"]:
                a = buscar("emergencia")
                meses = (a["saldo"] or 0) / h["total"]
                texto += ("\n\n💡 Como referencia: su fondo de emergencia cubre ~" + ("%.1f" % meses).replace(".", ",")
                          + " meses de sus gastos normales (" + fmt(h["total"]) + "/mes). Lo habitual es apuntar a 3–6 meses.")
        except Exception:
            pass
    return texto


def aplicar_compuesto(cambios, banco_texto=""):
    lineas, faltan, sin_respuesta = [], [], []
    nota_sueldo = sueldo_en_texto(banco_texto)
    for nombre, datos in cambios.items():
        aid, nuevo = guardar(nombre, saldo=datos.get("saldo"), dia_aporte=datos.get("dia_aporte"), meta=datos.get("meta"),
                             fecha_meta=datos.get("fecha_meta"), aporte_pct=datos.get("aporte_pct"),
                             banco="Produbanco" if "produbanco" in _norm(banco_texto) else None,
                             para_que=None)
        a = obtener(aid)
        lineas.append(("🆕 " if nuevo else "✏️ ") + linea(a)[2:])
        if not a["dia_aporte"] and aporte_efectivo(a) or a.get("aporte_pct") and not a["dia_aporte"]:
            faltan.append("qué día se debita el de " + a["nombre"].lower())
        if a["meta"] is None:
            faltan.append("si el de " + a["nombre"].lower() + " tiene una meta (monto y fecha)")
            sin_respuesta.append(a["nombre"])
    texto = "🐷 Listo, guardé sus ahorros:\n" + "\n".join("• " + l for l in lineas)
    if nota_sueldo:
        texto += "\n" + nota_sueldo
    try:
        from modulos.finanzas import presupuesto
        if any(d.get("aporte_pct") for d in cambios.values()) and not presupuesto.sueldo():
            texto += "\n\nPara calcular el 10 % necesito su sueldo: «mi sueldo es 800 y me pagan el 30»."
    except Exception:
        pass
    if faltan:
        texto += ("\n\nPara seguir su avance, cuénteme " + ", ".join(faltan[:3]) + ". Ej.: «el ahorro de viaje se debita el 30 y "
                  "la meta es 1500 para diciembre 2027». Si no tienen meta, dígamelo y no le pregunto más.")
    _pregunta(sin_respuesta)
    return texto


def interpretar(texto):
    t = " ".join(texto.strip().split())
    if P_VER.match(t):
        return {"accion": "ver"}
    compuesto = interpretar_compuesto(t)
    if compuesto and (len(compuesto) > 1 or P_DECLARA.search(t) or P_PCT.search(t) or P_DIA.search(t) or P_META.search(t)
                      or any(not buscar(n) for n in compuesto) or any("saldo" in d for d in compuesto.values())):
        return {"accion": "compuesto", "cambios": compuesto, "texto": t}
    for p in (P_SALDO_2, P_SALDO):
        m = p.match(t)
        if m and buscar(m.group(1)):
            return {"accion": "saldo", "nombre": m.group(1), "monto": dinero(m.group(2))}
    return None


def ejecutar(d):
    if d["accion"] == "ver":
        return resumen()
    if d["accion"] == "compuesto":
        return aplicar_compuesto(d["cambios"], d.get("texto", ""))
    a = buscar(d["nombre"])
    guardar(a["nombre"], saldo=d["monto"])
    return "Actualizado. " + linea(obtener(a["id"]))


def procesar(texto):
    try:
        r = respuesta_meta(texto)
        if r:
            return r
    except Exception as exc:
        log.warning("Error con la respuesta de meta: %s", exc)
    d = interpretar(texto)
    if not d:
        return None
    try:
        return ejecutar(d)
    except Exception as exc:
        log.warning("Error en ahorros: %s", exc)
        return None
