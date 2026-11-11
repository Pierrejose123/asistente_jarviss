"""Finanzas, paso 4: sueldo, ingresos extra, cuanto del sueldo se va gastando y presupuestos por categoria.

- "Dinero del mes" = sueldo fijo configurado + ingresos extra registrados ese mes (movilidad, bonos, freelance...).
  El sueldo que llega tambien se registra como ingreso (categoria Sueldo) pero NO se suma dos veces.
- Avisos (una vez por mes cada uno): 50/75/90/100 % del dinero del mes; 80/100 % de cada presupuesto.
- Todo se calcula en CODIGO. Frases:
    "mi sueldo es 800 y me pagan el 30"   "gano 800 al mes"   "me pagan el 15"
    "presupuesto comida 150"   "maximo 40 en ocio"   "quita el presupuesto de ocio"
    "como voy con mi presupuesto"   "cuanto me queda"   "cuanto me queda en comida"   "sugiereme un presupuesto"
"""
import re
import unicodedata
from contextlib import closing
from datetime import date, timedelta

from modulos.comun import db
from modulos.comun.base import ahora, registro
from modulos.finanzas import gastos
from modulos.finanzas.deudas import dinero, fmt

log = registro("finanzas")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS finanzas_ajustes (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
CREATE TABLE IF NOT EXISTS presupuestos (
    categoria TEXT PRIMARY KEY,
    monto     REAL NOT NULL
);
"""
# Reparto sugerido si aun no hay historial (fraccion del sueldo; suma 0.80 -> 20 % para ahorro)
REPARTO_BASE = {"Comida": 0.13, "Supermercado": 0.14, "Transporte": 0.10, "Hogar y servicios": 0.13,
                "Suscripciones": 0.03, "Salud y gimnasio": 0.05, "Diseño y estudio": 0.05, "Ocio y juegos": 0.07,
                "Ropa": 0.04, "Regalos": 0.02, "Otros": 0.04}
UMBRALES_TOTAL = (50, 75, 90, 100)
UMBRALES_CATEGORIA = (80, 100)


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn").strip()


def ajuste(clave, valor=None):
    with closing(_con()) as con, con:
        if valor is not None:
            con.execute("INSERT OR REPLACE INTO finanzas_ajustes (clave, valor) VALUES (?, ?)", (clave, str(valor)))
            return valor
        f = con.execute("SELECT valor FROM finanzas_ajustes WHERE clave = ?", (clave,)).fetchone()
    return f["valor"] if f else None


def sueldo():
    v = ajuste("sueldo")
    return float(v) if v else 0.0


def dia_pago():
    v = ajuste("dia_pago")
    return int(v) if v else None


def presupuestos():
    with closing(_con()) as con:
        return {f["categoria"]: f["monto"] for f in con.execute("SELECT * FROM presupuestos ORDER BY monto DESC")}


def poner_presupuesto(categoria, monto):
    with closing(_con()) as con, con:
        if monto and monto > 0:
            con.execute("INSERT OR REPLACE INTO presupuestos (categoria, monto) VALUES (?, ?)", (categoria, round(monto, 2)))
        else:
            con.execute("DELETE FROM presupuestos WHERE categoria = ?", (categoria,))


# ------------------------------------------------------------------ calculos del mes ---
def _mes(hoy=None):
    hoy = hoy or ahora().date()
    a, b = gastos.mes(hoy.year, hoy.month)
    return hoy, a, b


def ingresos_mes(hoy=None):
    """(total, detalle) del dinero del mes: sueldo fijo + extras registrados (sin contar el sueldo dos veces)."""
    hoy, a, b = _mes(hoy)
    extras = [m for m in gastos.del_periodo(a, b, "ingreso") if _norm(m["categoria"]) != "sueldo"]
    detalle = []
    if sueldo():
        detalle.append(("Sueldo", sueldo()))
    por_tipo = {}
    for m in extras:
        por_tipo[m["categoria"] if m["categoria"] != "Ingreso" else m["descripcion"]] = \
            por_tipo.get(m["categoria"] if m["categoria"] != "Ingreso" else m["descripcion"], 0) + m["monto"]
    detalle += sorted(por_tipo.items(), key=lambda x: -x[1])
    return round(sum(v for _, v in detalle), 2), detalle


def disponible_mes(hoy=None):
    """Dinero del mes menos los aportes a ahorros programados (ese dinero ya tiene destino)."""
    total, _ = ingresos_mes(hoy)
    try:
        from modulos.finanzas import ahorros
        aportes = ahorros.aportes_mensuales()
    except Exception:
        aportes = 0
    return round(max(0.0, total - aportes), 2) if total else 0.0, aportes


def gastado_mes(hoy=None, categoria=None):
    hoy, a, b = _mes(hoy)
    return round(sum(g["monto"] for g in gastos.del_periodo(a, min(b, hoy), "gasto")
                     if not categoria or g["categoria"] == categoria), 2)


def avance_del_mes(hoy=None):
    """Que porcentaje del mes ya paso (1 de noviembre = 3 %, 15 = 50 %...)."""
    hoy, a, b = _mes(hoy)
    return round(hoy.day / b.day * 100)


def _barra(pct, ancho=10):
    n = max(0, min(ancho, round(pct / 100 * ancho)))
    return "▓" * n + "░" * (ancho - n)


def linea_sueldo(hoy=None):
    """Resumen corto: cuanto del dinero del mes se lleva gastado vs cuanto del mes paso."""
    hoy, a, b = _mes(hoy)
    total, _ = disponible_mes(hoy)
    gastado = gastado_mes(hoy)
    if not total:
        return ""
    pct = gastado / total * 100
    paso = avance_del_mes(hoy)
    queda = total - gastado
    dias = (b - hoy).days + 1
    texto = ("💼 Lleva " + str(round(pct)) + " % de su dinero del mes gastado (" + fmt(gastado) + " de " + fmt(total)
             + "); va el " + str(paso) + " % del mes.")
    if queda > 0:
        texto += " Le quedan " + fmt(queda) + " (≈ " + fmt(queda / dias) + " por día)."
    else:
        texto += " Ya gastó " + fmt(-queda) + " más de lo que entró este mes."
    if pct > paso + 15 and queda > 0:
        texto += " Va más rápido que el mes: con calma."
    return texto


def linea_categoria(categoria, hoy=None):
    tope = presupuestos().get(categoria)
    if not tope:
        return ""
    usado = gastado_mes(hoy, categoria)
    pct = usado / tope * 100
    return ("📊 Presupuesto de " + categoria + ": " + fmt(usado) + " de " + fmt(tope) + " (" + str(round(pct)) + " %)"
            + (" · le quedan " + fmt(tope - usado) if usado < tope else " · se pasó por " + fmt(usado - tope)))


def alertas_nuevas(categoria=None, hoy=None):
    """Avisos de umbral que se cruzaron y aun no se enviaron este mes."""
    hoy, a, b = _mes(hoy)
    clave_mes = hoy.isoformat()[:7]
    salida = []
    total, _ = disponible_mes(hoy)
    if total:
        pct = gastado_mes(hoy) / total * 100
        for u in UMBRALES_TOTAL:
            clave = clave_mes + "|sueldo|" + str(u)
            if pct >= u and not db.aviso_enviado(clave):
                db.marcar_aviso(clave)
                if u == max(x for x in UMBRALES_TOTAL if pct >= x):        # solo el umbral mas alto alcanzado
                    salida.append("⚠️ Ya gastó el " + str(u) + " % de su dinero del mes (" + fmt(gastado_mes(hoy)) + " de "
                                  + fmt(total) + ") y va el " + str(avance_del_mes(hoy)) + " % del mes."
                                  if u < 100 else "🚨 Gastó todo su dinero del mes (" + fmt(gastado_mes(hoy)) + " de " + fmt(total) + ").")
    for cat, tope in presupuestos().items():
        if categoria and cat != categoria:
            continue
        pct = gastado_mes(hoy, cat) / tope * 100
        for u in UMBRALES_CATEGORIA:
            clave = clave_mes + "|presupuesto|" + cat + "|" + str(u)
            if pct >= u and not db.aviso_enviado(clave):
                db.marcar_aviso(clave)
                if u == max(x for x in UMBRALES_CATEGORIA if pct >= x):
                    salida.append(("⚠️ Llegó al 80 % de su presupuesto de " + cat if u == 80 else
                                   "🚨 Se pasó de su presupuesto de " + cat) + " (" + fmt(gastado_mes(hoy, cat)) + " de " + fmt(tope) + ").")
    return salida


def tras_gasto(g):
    """Lineas que se agregan a la confirmacion de un gasto."""
    if g["tipo"] != "gasto":
        return ""
    lineas = [x for x in (linea_categoria(g["categoria"]), linea_sueldo()) if x]
    lineas += alertas_nuevas(g["categoria"])
    return "\n".join(lineas)


def estado(categoria=None, hoy=None):
    hoy, a, b = _mes(hoy)
    total, detalle = ingresos_mes(hoy)
    if categoria:
        l = linea_categoria(categoria, hoy)
        return l or ("No tiene presupuesto para " + categoria + ". En " + categoria + " lleva " + fmt(gastado_mes(hoy, categoria))
                     + " este mes. Póngale uno: «presupuesto " + categoria.lower() + " 100».")
    lineas = ["💼 " + gastos.MESES[hoy.month - 1].capitalize() + " (va el " + str(avance_del_mes(hoy)) + " % del mes)"]
    if total:
        lineas.append("Ingresos: " + fmt(total) + " (" + ", ".join(k.lower() + " " + fmt(v) for k, v in detalle) + ")")
        disponible, aportes = disponible_mes(hoy)
        if aportes:
            lineas.append("Menos ahorro programado " + fmt(aportes) + " → disponible para gastar " + fmt(disponible))
        lineas.append(linea_sueldo(hoy))
    else:
        lineas.append("Aún no me dijo su sueldo. Escriba por ejemplo: «mi sueldo es 800 y me pagan el 30».")
        lineas.append("Gastado este mes: " + fmt(gastado_mes(hoy)))
    tops = presupuestos()
    if tops:
        lineas += ["", "📊 Presupuestos"]
        for cat, tope in tops.items():
            usado = gastado_mes(hoy, cat)
            pct = usado / tope * 100
            lineas.append(_barra(pct) + " " + cat + ": " + fmt(usado) + " de " + fmt(tope) + " (" + str(round(pct)) + " %)"
                          + (" 🚨" if pct >= 100 else " ⚠️" if pct >= 80 else ""))
        sin = [c for c in gastos.categorias() if c not in tops and gastado_mes(hoy, c) > 0]
        if sin:
            lineas.append("Sin presupuesto: " + ", ".join(c + " " + fmt(gastado_mes(hoy, c)) for c in sin))
        total = disponible_mes(hoy)[0] or total
        libre = total - sum(tops.values()) if total else 0
        if total:
            lineas.append("Presupuestado: " + fmt(sum(tops.values())) + " de " + fmt(total)
                          + (" → libre para ahorrar " + fmt(libre) + " (" + str(round(libre / total * 100)) + " %)" if libre > 0
                             else " → ¡presupuestó más de lo que gana!"))
    else:
        lineas += ["", "Aún no tiene presupuestos. Escriba «sugiéreme un presupuesto» o «presupuesto comida 150»."]
    return "\n".join(l for l in lineas if l is not None)


# ------------------------------------------------------------------ sugerencia ---
def sugerir():
    """{categoria: monto} segun lo que gasta (promedio mensual de lo registrado) y su sueldo (deja 20 % de ahorro)."""
    total, _ = ingresos_mes()
    base = total or sueldo()
    hoy = ahora().date()
    with closing(gastos._con()) as con:
        f = con.execute("SELECT MIN(fecha) AS desde FROM movimientos WHERE estado = 'activo' AND tipo = 'gasto' AND monto > 0").fetchone()
    desde = date.fromisoformat(f["desde"]) if f and f["desde"] else hoy
    dias = max(1, (hoy - desde).days + 1)
    historial = {}
    if dias >= 20:
        for g in gastos.del_periodo(desde, hoy, "gasto"):
            historial[g["categoria"]] = historial.get(g["categoria"], 0) + g["monto"] * 30 / dias
    if not base and not historial:
        return {}, "Necesito su sueldo o algunos gastos registrados para sugerir."
    objetivo = base * 0.80 if base else sum(historial.values())
    if historial:
        propuesta = {c: v for c, v in historial.items() if v >= 3}
        suma = sum(propuesta.values())
        if base and suma > objetivo:                                # gasta mas del 80 %: recortar en proporcion
            propuesta = {c: v * objetivo / suma for c, v in propuesta.items()}
        nota = ("Basado en lo que gastó en los últimos " + str(dias) + " días"
                + (", ajustado para que le quede un 20 % de ahorro." if base and suma > objetivo else "."))
    else:
        propuesta = {c: base * p for c, p in REPARTO_BASE.items()}
        nota = "Aún tengo pocos gastos suyos: uso un reparto típico que deja un 20 % para ahorro."
    propuesta = {c: max(5, round(v / 5) * 5) for c, v in propuesta.items()}         # redondeo a 5
    return dict(sorted(propuesta.items(), key=lambda x: -x[1])), nota


def texto_sugerencia(propuesta, nota):
    total, _ = ingresos_mes()
    base = total or sueldo()
    lineas = ["💡 Presupuesto sugerido por mes", nota, ""]
    lineas += ["• " + c + ": " + fmt(v) for c, v in propuesta.items()]
    suma = sum(propuesta.values())
    lineas.append("")
    lineas.append("Total: " + fmt(suma) + ((" de " + fmt(base) + " → ahorro " + fmt(base - suma) + " (" + str(round((base - suma) / base * 100))
                                            + " %)") if base else ""))
    lineas.append("Puede aplicarlo con el botón y luego ajustar cualquiera: «presupuesto comida 120».")
    return "\n".join(lineas)


# ------------------------------------------------------------------ entender frases ---
MONTO = r"\$?\s?(\d+(?:[.,]\d{1,2})?(?:[.,]\d{3})*(?:[.,]\d{1,2})?)"
P_SUELDO = re.compile(r"^\W*(?:mi sueldo (?:es|son|sera|será)|gano|me pagan|cobro|mi salario (?:es|son))\s+(?:de\s+)?" + MONTO
                      + r"(?:\s*(?:d[oó]lares)?\s*(?:al mes|mensual(?:es)?|cada mes))?(?:\s*,?\s*y?\s*(?:me (?:lo )?pagan|cobro|me llega|me depositan)\s+(?:hasta\s+)?(?:el\s+|los\s+)?(?:d[ií]a\s+)?(\d{1,2})(?:\s+de\s+cada\s+mes)?)?\W*$", re.I)
P_DIA_PAGO = re.compile(r"^\W*(?:me pagan|cobro|me llega el sueldo|me depositan(?: el sueldo)?)\s+(?:el\s+sueldo\s+)?(?:hasta\s+)?(?:el\s+|los\s+)?(?:d[ií]a\s+)?(\d{1,2})(?:\s+de cada mes)?\W*$", re.I)
P_PRESUPUESTO = re.compile(r"^\W*(?:pon(?:me|er)?\s+(?:un\s+)?)?presupuesto\s+(?:de\s+|para\s+|en\s+)?(?:la |el |los |las )?(.+?)\s+(?:de\s+|en\s+)?" + MONTO + r"\W*$", re.I)
P_PRESUPUESTO_2 = re.compile(r"^\W*(?:pon(?:me|er)?\s+)?" + MONTO + r"\s+(?:de\s+)?presupuesto\s+(?:para|de|en)\s+(?:la |el )?(.+?)\W*$", re.I)
P_MAXIMO = re.compile(r"^\W*(?:quiero gastar\s+)?(?:m[aá]ximo|como m[aá]ximo|no m[aá]s de)\s+" + MONTO + r"\s+(?:en|para|de)\s+(?:la |el |los |las )?(.+?)(?:\s+al mes)?\W*$", re.I)
P_QUITAR = re.compile(r"^\W*(?:quita|borra|elimina)(?:r)?\s+(?:el\s+)?presupuesto\s+(?:de|del|para)\s+(?:la |el )?(.+?)\W*$", re.I)
P_ESTADO = re.compile(r"c[oó]mo voy con (?:mi |el |mis )?(?:presupuesto|sueldo|plata|dinero)|cu[aá]nto me queda|mi presupuesto|"
                      r"mis presupuestos|cu[aá]nto (?:llevo|he) gastado de mi sueldo|estado del mes", re.I)
P_SUGERIR = re.compile(r"sug[ie]+[eé]?r[ea]?(?:me)?\s+(?:un\s+)?presupuesto|arma(?:me)?\s+(?:un\s+)?presupuesto|"
                       r"recomi[eé]ndame\s+(?:un\s+)?presupuesto|haz(?:me)?\s+(?:un\s+)?presupuesto", re.I)


def categoria_por_nombre(texto):
    t = _norm(texto)
    for c in gastos.categorias():
        n = _norm(c)
        if t == n or t in n.split() or n.split()[0] == t.split()[0] or t.rstrip("s") == n.split()[0].rstrip("s"):
            return c
    cat, segura = gastos.categoria_de(texto)
    return cat if segura else None


def interpretar(texto):
    t = " ".join(texto.strip().split())
    if P_SUGERIR.search(t):
        return {"accion": "sugerir"}
    m = P_SUELDO.match(t)
    if m:
        return {"accion": "sueldo", "monto": dinero(m.group(1)), "dia": int(m.group(2)) if m.group(2) else None}
    m = P_DIA_PAGO.match(t)
    if m:
        return {"accion": "dia_pago", "dia": int(m.group(1))}
    m = P_QUITAR.match(t)
    if m:
        cat = categoria_por_nombre(m.group(1))
        return {"accion": "quitar", "categoria": cat, "texto": m.group(1)}
    for patron, orden in ((P_PRESUPUESTO, "cm"), (P_PRESUPUESTO_2, "mc"), (P_MAXIMO, "mc")):
        m = patron.match(t)
        if m:
            nombre, monto = (m.group(1), m.group(2)) if orden == "cm" else (m.group(2), m.group(1))
            return {"accion": "presupuesto", "categoria": categoria_por_nombre(nombre), "texto": nombre, "monto": dinero(monto)}
    if P_ESTADO.search(t):
        resto = re.sub(r".*(?:queda|voy)\s+(?:en|con)\s+(?:la |el )?", "", t) if re.search(r"(?:queda|voy)\s+(?:en|con)\s+(?!mi |el presupuesto|mis )", t) else ""
        return {"accion": "estado", "categoria": categoria_por_nombre(resto) if resto else None}
    return None


def ejecutar(d):
    a = d["accion"]
    if a == "sueldo":
        if not 0 < d["monto"] < 100000:
            return "Ese sueldo no parece correcto."
        ajuste("sueldo", d["monto"])
        if d.get("dia"):
            ajuste("dia_pago", d["dia"])
        texto = "💼 Anotado: su sueldo es " + fmt(d["monto"]) + " al mes"
        texto += (", le pagan el " + str(dia_pago()) + ". Ese día le pregunto si llegó." if dia_pago() else
                  ". ¿Qué día le pagan? Escriba por ejemplo «me pagan el 30».")
        return texto + "\nLos extras (movilidad, bonos) anótelos cuando lleguen: «me pagaron movilidad 40»."
    if a == "dia_pago":
        if not 1 <= d["dia"] <= 31:
            return "Ese día no existe."
        ajuste("dia_pago", d["dia"])
        return "Anotado: le pagan el " + str(d["dia"]) + " de cada mes. Ese día le pregunto si llegó el sueldo."
    if a == "presupuesto":
        if not d.get("categoria"):
            return ("No sé a qué categoría corresponde «" + d["texto"] + "». Use una de estas: " + ", ".join(gastos.categorias()) + ".")
        poner_presupuesto(d["categoria"], d["monto"])
        usado = gastado_mes(None, d["categoria"])
        return ("📊 Listo: presupuesto de " + d["categoria"] + " de " + fmt(d["monto"]) + " al mes."
                + (" Este mes ya lleva " + fmt(usado) + " (" + str(round(usado / d["monto"] * 100)) + " %)." if usado else "")
                + " Le aviso al llegar al 80 % y si se pasa.")
    if a == "quitar":
        if not d.get("categoria"):
            return "No encontré ese presupuesto."
        poner_presupuesto(d["categoria"], 0)
        return "Quité el presupuesto de " + d["categoria"] + "."
    if a == "estado":
        return estado(d.get("categoria"))
    if a == "sugerir":
        propuesta, nota = sugerir()
        return texto_sugerencia(propuesta, nota) if propuesta else nota
    return None


def procesar(texto):
    d = interpretar(texto)
    if not d:
        return None
    try:
        return ejecutar(d)
    except Exception as exc:
        log.warning("Error en presupuesto: %s", exc)
        return "No pude hacerlo: " + str(exc)[:100]


# ------------------------------------------------------------------ dia de pago ---
def toca_preguntar_sueldo(hoy=None):
    hoy = hoy or ahora().date()
    dia = dia_pago()
    if not dia or not sueldo():
        return False
    _, _, fin = _mes(hoy)
    return hoy.day == min(dia, fin.day)
