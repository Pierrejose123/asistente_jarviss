"""Finanzas, paso 8: TARJETAS de crédito (13-11). Diferidos, cuotas por mes, fechas máximas de pago y «¿me alcanza?».

Fuentes (Gmail SOLO LECTURA, lectores fijos sin IA):
  - Estados de cuenta en PDF (sin contraseña): Pichincha («Estados de Cuenta de Tarjeta») y
    Produbanco («Estado de Cuenta Produbanco»). De ahí salen la fecha máxima de pago, total, mínimo y la lista de
    diferidos con su cuota del mes, saldo pendiente y «(n/N)». El estado de cuenta MANDA: reemplaza lo anterior de esa tarjeta.
  - Correo de Pichincha «Tu diferido fue realizado con éxito»: diferido provisional hasta el próximo estado de cuenta.
  - Diners: estado de cuenta en PDF («Estado de cuenta Diners Club»; líneas «(n/N) cuota saldo») y confirmación de
    pago «Agradecemos su pago» (monto y pendiente).
  Qué correos buscar (remitentes y asuntos de cada banco) va en config/bancos.json, que es PRIVADO (no se publica);
  el formato está en config/bancos.ejemplo.json. Sin ese archivo no se buscan estados de cuenta en Gmail.
  - A mano (cualquier tarjeta): «diferí la laptop de 900 a 6 meses con diners».
Cómo cuenta: la COMPRA es un gasto una sola vez (el día que se hizo, ya lo anota correos.py). Las CUOTAS no son gastos
nuevos: son compromisos de cada mes. Se usan para «mis diferidos», el aviso de endeudamiento (cuotas > 30 % del sueldo)
y la pregunta «¿me alcanza comprar X de 900 a 6 meses?» (sueldo − ahorros − gasto normal − cuotas − cuota nueva, mes a mes).
Diferidos de OTRA persona (13-11, MODO SIMPLE elegido por el usuario): «el diferido 12 es de Juan» → no cuentan en sus
cuotas, % del sueldo ni «¿me alcanza?». NO se sigue si la persona pagó: sus transferencias no son ingreso ni se preguntan
(solo suben el saldo de la cuenta, que es dinero real). El dueño sigue al diferido aunque cambie el estado de cuenta.
(cuenta_dueno/diferido_reembolsos quedan por si algún día se quiere el seguimiento completo, pero no se muestran.)
El asistente informa, no decide. Tablas: diferidos, tarjeta_estados, tarjeta_factores, tarjeta_pagos, diferido_duenos,
diferido_reembolsos.
"""
import base64
import io
import re
import sys
import unicodedata
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))          # para poder correrlo como script (--probar)

from modulos.comun import db
from modulos.comun.base import ahora, registro
from modulos.finanzas import gastos
from modulos.finanzas.deudas import dinero, fmt

log = registro("finanzas")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS diferidos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tarjeta      TEXT NOT NULL,
    descripcion  TEXT DEFAULT '',
    fecha_compra TEXT DEFAULT '',
    cuota        REAL NOT NULL,             -- valor de cada cuota
    total_cuotas INTEGER NOT NULL,
    pagadas      INTEGER NOT NULL DEFAULT 0, -- cuotas ya facturadas al mes de referencia
    mes_ref      TEXT NOT NULL,             -- AAAA-MM del estado de cuenta (o de la compra) en que se contó 'pagadas'
    saldo        REAL,                      -- lo que falta por facturar
    origen       TEXT DEFAULT 'manual',     -- estado | correo | manual
    ref          TEXT DEFAULT '',
    estado       TEXT DEFAULT 'activo',     -- activo | reemplazado | terminado | borrado
    creado       TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tarjeta_estados (
    ref          TEXT PRIMARY KEY,
    tarjeta      TEXT NOT NULL,
    emision      TEXT,
    fecha_max    TEXT,
    total        REAL,
    minimo       REAL,
    saldo_diferido REAL,
    diferidos    INTEGER DEFAULT 0,
    aviso        TEXT DEFAULT '',
    creado       TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tarjeta_factores (plazo INTEGER PRIMARY KEY, factor REAL NOT NULL, banco TEXT, actualizado TEXT);
CREATE TABLE IF NOT EXISTS diferido_duenos (
    clave     TEXT PRIMARY KEY,            -- tarjeta|fecha de compra|número de cuotas
    dueno     TEXT NOT NULL,
    base      INTEGER NOT NULL DEFAULT 0,  -- cuotas facturadas ANTES de que fuera de esa persona
    cuota     REAL,
    desde     TEXT
);
CREATE TABLE IF NOT EXISTS dueno_alias (
    nombre    TEXT PRIMARY KEY,            -- nombre como lo manda el banco, normalizado ('juan carlos vera lopez')
    dueno     TEXT NOT NULL                -- como lo dijo el usuario ('mi hermano', 'Juan')
);
CREATE TABLE IF NOT EXISTS diferido_reembolsos (
    ref       TEXT PRIMARY KEY,
    clave     TEXT NOT NULL,
    dueno     TEXT NOT NULL,
    fecha     TEXT NOT NULL,
    monto     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tarjeta_pagos (
    ref       TEXT PRIMARY KEY,
    tarjeta   TEXT NOT NULL,
    fecha     TEXT NOT NULL,
    monto     REAL NOT NULL,
    pendiente REAL,                        -- lo que el banco dice que queda por pagar
    creado    TEXT DEFAULT CURRENT_TIMESTAMP
);
"""
MESES_ABR = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SEP": 9, "SET": 9, "OCT": 10,
             "NOV": 11, "DIC": 12}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre",
         "diciembre"]
TARJETA_DE_BANCO = {"Pichincha": "Pichincha Platinum", "Produbanco": "Produbanco Gold", "Diners": "Diners"}
LIMITE_CUOTAS = 30          # % del sueldo
COLCHON = 10                # % del sueldo que conviene que quede libre cada mes


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn").strip()


def _mes(d):
    return d.strftime("%Y-%m") if isinstance(d, (date, datetime)) else str(d)[:7]


def _sumar_meses(mes, n):
    a, m = int(mes[:4]), int(mes[5:7]) - 1 + n
    return "%04d-%02d" % (a + m // 12, m % 12 + 1)


def nombre_mes(mes):
    return MESES[int(mes[5:7]) - 1] + (" " + mes[:4] if mes[:4] != str(ahora().year) else "")


# ------------------------------------------------------------------ lectores de estados de cuenta ---
def _fecha_texto(t):
    """'18 NOV 2026' → date."""
    m = re.search(r"(\d{1,2})\s+([A-Z]{3})\s+(\d{4})", t or "")
    if m and m.group(2).upper() in MESES_ABR:
        return date(int(m.group(3)), MESES_ABR[m.group(2).upper()], int(m.group(1)))
    return None


def _plata(t):
    t = re.sub(r"[^\d.,]", "", t or "")
    return dinero(t) if t else None


def leer_estado_pichincha(texto):
    plano = " ".join(texto.split())
    emision = _fecha_texto(re.search(r"FECHA DE EMISI[ÓO]N:?\s*(\d{1,2}\s+[A-Z]{3}\s+\d{4})", plano).group(1)) \
        if re.search(r"FECHA DE EMISI[ÓO]N:?\s*(\d{1,2}\s+[A-Z]{3}\s+\d{4})", plano) else None
    m = re.search(r"FECHA M[ÁA]XIMA DE PAGO\s+(?:ATENCI[ÓO]N\s+)?(\d{1,2}\s+[A-Z]{3}\s+\d{4})", plano)
    fecha_max = _fecha_texto(m.group(1)) if m else None
    total = _plata((re.search(r"TOTAL A PAGAR USD\s*([\d.,]+)", plano) or [None, ""])[1])
    minimo = _plata((re.search(r"PAGO M[ÍI]NIMO\s*([\d.,]+)", plano) or [None, ""])[1])
    saldo_dif = _plata((re.search(r"([\d.,]+)\s*SALDO DIFERIDO A FACTURAR", plano) or [None, ""])[1])
    lineas = []
    for l in texto.splitlines():
        m = re.match(r"^\s*(\d{2}/\d{2})\s+\d+\s+(.+?)\s+DIFERIDO\s+([\d.,]+)(?:\s+([\d.,]+))?\s*\((\d{1,2})/(\d{1,2})\)", l)
        if m:
            lineas.append({"fecha": m.group(1), "descripcion": m.group(2), "a": dinero(m.group(3)),
                           "b": dinero(m.group(4)) if m.group(4) else None, "n": int(m.group(5)), "N": int(m.group(6))})
            continue
        m = re.match(r"^\s*(\d{2}/\d{2})\s+\d+\s+(.+?)\s+DIFERIDO\s+([\d.,]+)\s*\(FINAL\)", l, re.I)
        if m:
            lineas.append({"fecha": m.group(1), "descripcion": m.group(2), "a": dinero(m.group(3)), "b": None, "n": 0, "N": 0,
                           "final": True})
    return armar(lineas, emision, fecha_max, total, minimo, saldo_dif, "Pichincha Platinum")


def armar(lineas, emision, fecha_max, total, minimo, saldo_dif, tarjeta, saldo_con_otros=False):
    """Columnas «Valores | Diferido (n/N)»: el 1.º número es la cuota del mes y el 2.º el saldo que falta.
    Se comprueba con «saldo diferido a facturar»; si no cuadra, el saldo se estima con cuota × cuotas restantes."""
    con_saldo = [x for x in lineas if x["b"] is not None]
    suma_b = sum(x["b"] for x in con_saldo)
    cuadra = saldo_dif is not None and con_saldo and (abs(suma_b - saldo_dif) <= max(1, 0.02 * saldo_dif)
                                                       or (saldo_con_otros and suma_b <= saldo_dif + 1))
    difs = []
    for x in lineas:
        if x.get("final"):
            difs.append({"descripcion": _limpio(x["descripcion"]), "fecha_compra": x["fecha"], "cuota": x["a"], "total_cuotas": 1,
                         "pagadas": 1, "saldo": 0.0, "final": True})
            continue
        restantes = x["N"] - x["n"]
        saldo = x["b"] if (cuadra and x["b"] is not None) else round(x["a"] * restantes, 2)
        difs.append({"descripcion": _limpio(x["descripcion"]), "fecha_compra": x["fecha"], "cuota": x["a"],
                     "total_cuotas": x["N"], "pagadas": x["n"], "saldo": saldo})
    aviso = "" if cuadra or not con_saldo or saldo_dif is None else "los saldos de los diferidos no suman lo que dice el banco"
    return {"tarjeta": tarjeta, "emision": emision, "fecha_max": fecha_max, "total": total, "minimo": minimo,
            "saldo_diferido": saldo_dif, "diferidos": difs, "aviso": aviso}


def _limpio(d):
    d = re.sub(r"\s+", " ", d or "").strip()
    d = re.sub(r"^DIF\s+CON\s+", "Diferido ", d, flags=re.I)
    return d.title().replace("Bp", "BP")[:60]


def leer_estado_diners(texto):
    plano = " ".join(texto.split())
    m = re.search(r"(\d{1,2})/([A-Z]{3})/(\d{4})", plano)
    emision = date(int(m.group(3)), MESES_ABR[m.group(2)], int(m.group(1))) if m and m.group(2) in MESES_ABR else None
    if not emision:
        m = re.search(r"\bAL\s+(\d{1,2}\s+[A-Z]{3}\s+\d{4})", plano)
        emision = _fecha_texto(m.group(1)) if m else None
    fechas = re.findall(r"Fecha m[áa]xima de pago:?\s*(\d{1,2}\s+[A-Z]{3}\s+\d{4})", plano, re.I)
    fecha_max = _fecha_texto(fechas[-1]) if fechas else None      # la del «Resumen» (la 1.ª etiqueta va con el período)
    total = _plata((re.search(r"([\d.,]+)\s*Total a pagar:", plano, re.I) or [None, ""])[1])
    minimo = _plata((re.search(r"([\d.,]+)\s*M[íi]nimo a pagar:", plano, re.I) or [None, ""])[1])
    saldo_dif = _plata((re.search(r"([\d.,]+)\s*Saldos y diferidos pendientes", plano, re.I) or [None, ""])[1])
    lineas = []
    for l in texto.splitlines():
        m = re.match(r"^\s*(\d{2}/\d{2})\s+\d+\s+(.+?)\s+\((\d{1,2})/(\d{1,2})\)\s+([\d.,]+)(?:\s+([\d.,]+))?", l)
        if m:
            lineas.append({"fecha": m.group(1), "descripcion": m.group(2), "a": dinero(m.group(5)),
                           "b": dinero(m.group(6)) if m.group(6) else None, "n": int(m.group(3)), "N": int(m.group(4))})
            continue
        m = re.match(r"^\s*(\d{2}/\d{2})\s+\d+\s+(.+?)\s+\(FINAL\)\s+([\d.,]+)", l, re.I)
        if m:
            lineas.append({"fecha": m.group(1), "descripcion": m.group(2), "a": dinero(m.group(3)), "b": None, "n": 0, "N": 0,
                           "final": True})
    r = armar(lineas, emision, fecha_max, total, minimo, saldo_dif, "Diners", saldo_con_otros=True)
    m = re.search(r"Plazo\s+((?:\d{1,2}\s+)+)Factor\s+((?:[\d.,]+\s*%\s*)+)", plano)
    if m:
        plazos = [int(x) for x in m.group(1).split()]
        factores = [dinero(x) for x in re.findall(r"([\d.,]+)\s*%", m.group(2))]
        r["factores"] = dict(zip(plazos, factores))
    return r


def leer_pago_diners(texto):
    """«Agradecemos su pago»: monto recibido, fecha y lo que queda pendiente."""
    plano = " ".join((texto or "").split())
    if "gracias por el pago" not in _norm(plano) and "gracias por tu pago" not in _norm(plano):
        return None
    monto = _plata((re.search(r"Monto recibido:?\s*\$?\s*([\d.,]+)", plano, re.I) or [None, ""])[1])
    m = re.search(r"Fecha de pago:?\s*(\d{2})/(\d{2})/(\d{4})", plano, re.I)
    fecha = date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
    pendiente = _plata((re.search(r"valor pendiente de pago es\s*\$?\s*([\d.,]+)", plano, re.I) or [None, ""])[1])
    return {"monto": monto, "fecha": fecha, "pendiente": pendiente} if monto else None


def guardar_pago(tarjeta, d, ref):
    with closing(_con()) as con, con:
        return con.execute("INSERT OR IGNORE INTO tarjeta_pagos (ref, tarjeta, fecha, monto, pendiente) VALUES (?, ?, ?, ?, ?)",
                           (ref, tarjeta, (d["fecha"] or ahora().date()).isoformat(), d["monto"], d["pendiente"])).rowcount


def _fecha_mdy(t):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", t or "")
    if not m:
        return None
    a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(c, a, b)                      # Produbanco escribe mes/día/año
    except ValueError:
        return date(c, b, a)


def leer_estado_produbanco(texto):
    plano = " ".join(texto.split())
    emision = _fecha_mdy((re.search(r"Fecha De Emisi[óo]n\s*:\s*(\d{2}/\d{2}/\d{4})", plano, re.I) or [None, ""])[1])
    fecha_max = _fecha_mdy((re.search(r"Fecha M[áa]x\.? de Pago\s*:\s*(\d{2}/\d{2}/\d{4})", plano, re.I) or [None, ""])[1])
    total = _plata((re.search(r"Total a Pagar\s*:\s*([\d.,]+)", plano, re.I) or [None, ""])[1])
    minimo = _plata((re.search(r"Pagos? M[íi]nimo\s*:\s*([\d.,]+)", plano, re.I) or [None, ""])[1])
    m = re.search(r"\bDiferido\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", plano)
    usado = _plata(m.group(2)) if m else None
    lineas = []
    for l in texto.splitlines():
        if not re.search(r"\bDIF", l, re.I) or "SALDO" in l.upper():
            continue
        m = re.match(r"^\s*(\d{2}/\d{2}/\d{4})\s+\d+\s+(.+?)\s+(?:DIF\w*\.?)\s+.*?([\d.,]+)\s*\+?.*?\(?(\d{1,2})\s*/\s*(\d{1,2})\)?\s*$", l)
        if m:
            lineas.append({"fecha": m.group(1)[:5], "descripcion": m.group(2), "a": dinero(m.group(3)), "b": None,
                           "n": int(m.group(4)), "N": int(m.group(5))})
    r = armar(lineas, emision, fecha_max, total, minimo, usado, "Produbanco Gold")
    if usado and not lineas:
        r["aviso"] = "tiene diferidos (" + fmt(usado) + ") pero no pude leer su detalle"
    r["factores"] = {int(p): dinero(f) for p, f in re.findall(r"(\d{1,2})\s+meses\s+([\d.,]+)\s*%", plano)}
    return r


def leer_correo_diferido(texto):
    """Pichincha «Tu diferido fue realizado con éxito»."""
    plano = " ".join((texto or "").split())
    if "diferido fue realizado" not in _norm(plano):
        return None
    valor = _plata((re.search(r"Valor diferido\s*\$?\s*([\d.,]+)", plano) or [None, ""])[1])
    plazo = re.search(r"Plazo\s+(\d{1,2})\b", plano)
    cuota = _plata((re.search(r"Cuotas a pagar\s+Valor\s*\$?\s*([\d.,]+)", plano) or [None, ""])[1])
    interes = _plata((re.search(r"Inter[ée]s generado\s*\$?\s*([\d.,]+)", plano) or [None, ""])[1])
    if not (valor and plazo):
        return None
    n = int(plazo.group(1))
    return {"valor": valor, "plazo": n, "cuota": cuota or round((valor + (interes or 0)) / n, 2), "interes": interes or 0.0}


# ------------------------------------------------------------------ guardar ---
def guardar_estado(r, ref):
    """Reemplaza los diferidos de esa tarjeta por los del estado de cuenta. Devuelve el resumen guardado o None si ya estaba."""
    with closing(_con()) as con:
        if con.execute("SELECT 1 FROM tarjeta_estados WHERE ref = ?", (ref,)).fetchone():
            return None
        ultimo = con.execute("SELECT emision FROM tarjeta_estados WHERE tarjeta = ? ORDER BY emision DESC LIMIT 1",
                             (r["tarjeta"],)).fetchone()
    nuevo = not ultimo or not r["emision"] or not ultimo["emision"] or r["emision"].isoformat() >= ultimo["emision"]
    mes_ref = _mes(r["emision"] or ahora().date())
    with closing(_con()) as con, con:
        con.execute("INSERT INTO tarjeta_estados (ref, tarjeta, emision, fecha_max, total, minimo, saldo_diferido, diferidos, aviso) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ref, r["tarjeta"], r["emision"].isoformat() if r["emision"] else None,
                     r["fecha_max"].isoformat() if r["fecha_max"] else None, r["total"], r["minimo"], r["saldo_diferido"],
                     len(r["diferidos"]), r["aviso"]))
        if nuevo:                                              # un estado viejo no pisa uno más nuevo
            emi = r["emision"].isoformat() if r["emision"] else "9999"
            con.execute("UPDATE diferidos SET estado = 'reemplazado' WHERE tarjeta = ? AND estado = 'activo' "
                        "AND (origen = 'estado' OR creado < ?)", (r["tarjeta"], emi))
            for d in r["diferidos"]:
                if d.get("final"):
                    continue
                con.execute("INSERT INTO diferidos (tarjeta, descripcion, fecha_compra, cuota, total_cuotas, pagadas, mes_ref, saldo, "
                            "origen, ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'estado', ?)",
                            (r["tarjeta"], d["descripcion"], d["fecha_compra"], d["cuota"], d["total_cuotas"], d["pagadas"],
                             mes_ref, d["saldo"], ref))
            for plazo, f in (r.get("factores") or {}).items():
                con.execute("INSERT OR REPLACE INTO tarjeta_factores (plazo, factor, banco, actualizado) VALUES (?, ?, ?, ?)",
                            (plazo, f, r["tarjeta"], ahora().date().isoformat()))
    if nuevo:
        _reubicar_duenos(r["tarjeta"])
    return r


def clave(d):
    return d["tarjeta"] + "|" + (d.get("fecha_compra") or "") + "|" + str(d["total_cuotas"])


def _reubicar_duenos(tarjeta):
    """Un diferido provisional (a mano o del correo) que ya sale en el estado de cuenta cambia de fecha: el dueño se pasa
    al diferido del estado con el mismo número de cuotas y casi la misma cuota."""
    vivos = [d for d in activos() if d["tarjeta"] == tarjeta]
    claves = {clave(d) for d in vivos}
    with closing(_con()) as con, con:
        for o in [dict(f) for f in con.execute("SELECT * FROM diferido_duenos WHERE clave LIKE ?", (tarjeta + "|%",))]:
            if o["clave"] in claves:
                continue
            n = int(o["clave"].rsplit("|", 1)[1])
            candidatos = [d for d in vivos if d["total_cuotas"] == n and o["cuota"] and abs(d["cuota"] - o["cuota"]) <= max(1, 0.05 * o["cuota"])
                          and not con.execute("SELECT 1 FROM diferido_duenos WHERE clave = ?", (clave(d),)).fetchone()]
            if len(candidatos) == 1:
                nueva = clave(candidatos[0])
                con.execute("UPDATE diferido_duenos SET clave = ? WHERE clave = ?", (nueva, o["clave"]))
                con.execute("UPDATE diferido_reembolsos SET clave = ? WHERE clave = ?", (nueva, o["clave"]))


def nuevo_diferido(tarjeta, descripcion, cuota, total_cuotas, origen="manual", ref="", fecha=None):
    """Una compra diferida que todavía no sale en un estado de cuenta (la 1.ª cuota se cobra el mes siguiente)."""
    f = fecha or ahora().date()
    with closing(_con()) as con, con:
        return con.execute("INSERT INTO diferidos (tarjeta, descripcion, fecha_compra, cuota, total_cuotas, pagadas, mes_ref, saldo, "
                           "origen, ref) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                           (tarjeta, descripcion[:60], f.strftime("%d/%m"), round(cuota, 2), int(total_cuotas), _mes(f),
                            round(cuota * total_cuotas, 2), origen, ref)).lastrowid


def activos():
    with closing(_con()) as con:
        return [dict(f) for f in con.execute("SELECT * FROM diferidos WHERE estado = 'activo' ORDER BY tarjeta, id")]


def ultimo_mes(d):
    """Mes en que se factura la última cuota."""
    return _sumar_meses(d["mes_ref"], d["total_cuotas"] - d["pagadas"])


def dueno(d):
    """{'dueno','base','cuota','desde'} si el diferido es de otra persona; None si es suyo."""
    with closing(_con()) as con:
        f = con.execute("SELECT * FROM diferido_duenos WHERE clave = ?", (clave(d),)).fetchone()
    return dict(f) if f else None


def marcar_dueno(did, persona):
    """persona=None → vuelve a ser suyo. Devuelve el diferido o None."""
    d = next((x for x in activos() if x["id"] == did), None)
    if not d:
        return None
    with closing(_con()) as con, con:
        if persona:
            base = max(0, d["pagadas"] - 1)                       # la cuota de este estado ya la debe esa persona
            con.execute("INSERT OR REPLACE INTO diferido_duenos (clave, dueno, base, cuota, desde) VALUES (?, ?, ?, ?, ?)",
                        (clave(d), persona, base, d["cuota"], ahora().date().isoformat()))
        else:
            con.execute("DELETE FROM diferido_duenos WHERE clave = ?", (clave(d),))
    return d


def cuenta_dueno(d):
    """Lo que la otra persona lleva pagado y lo que debe de las cuotas ya facturadas."""
    o = dueno(d)
    if not o:
        return None
    facturadas = max(0, d["pagadas"] - o["base"])
    with closing(_con()) as con:
        pagado = con.execute("SELECT coalesce(sum(monto), 0) AS s FROM diferido_reembolsos WHERE clave = ?", (clave(d),)).fetchone()["s"]
    debe = round(facturadas * d["cuota"] - pagado, 2)
    return {"dueno": o["dueno"], "facturadas": facturadas, "pagado": round(pagado, 2), "debe": debe,
            "restante": round((d["total_cuotas"] - d["pagadas"]) * d["cuota"], 2)}


def _coincide(persona, nombre):
    pal = [w for w in re.findall(r"[a-zñ]+", _norm(nombre)) if len(w) >= 3]
    pp = [w for w in re.findall(r"[a-zñ]+", _norm(persona)) if len(w) >= 3]
    return bool(pp) and all(any(w.startswith(x) or x.startswith(w) for w in pal if len(w) >= 4 or w == x) for x in pp)


def _alias(nombre):
    with closing(_con()) as con:
        f = con.execute("SELECT dueno FROM dueno_alias WHERE nombre = ?", (" ".join(re.findall(r"[a-zñ]+", _norm(nombre))),)).fetchone()
    return f["dueno"] if f else None


def aprender_alias(nombre_banco, persona):
    """«Esta transferencia de JUAN CARLOS VERA es para el diferido de mi hermano» → desde ahora se reconoce sola."""
    with closing(_con()) as con, con:
        con.execute("INSERT OR REPLACE INTO dueno_alias (nombre, dueno) VALUES (?, ?)",
                    (" ".join(re.findall(r"[a-zñ]+", _norm(nombre_banco))), persona))


def diferidos_de_persona(nombre):
    """Diferidos activos de quien transfiere: por el nombre que dio el usuario ('Juan' ~ 'JUAN CARLOS PEREZ') o por un nombre
    del banco ya aprendido ('JUAN CARLOS VERA' = 'mi hermano')."""
    alias = _alias(nombre)
    vivos = [d for d in activos() if dueno(d) and ultimo_mes(d) >= _mes(ahora().date())]
    if alias:
        return [d for d in vivos if _norm(dueno(d)["dueno"]) == _norm(alias)]
    return [d for d in vivos if _coincide(dueno(d)["dueno"], nombre)]


def duenos_activos():
    """{persona: [diferidos]} de los diferidos que pagan otras personas (para ofrecer el botón «Paga el diferido de …»)."""
    salida = {}
    for d in activos():
        o = dueno(d)
        if o and ultimo_mes(d) >= _mes(ahora().date()):
            salida.setdefault(o["dueno"], []).append(d)
    return salida


def registrar_reembolso(d, monto, ref, fecha=None):
    with closing(_con()) as con, con:
        con.execute("INSERT OR IGNORE INTO diferido_reembolsos (ref, clave, dueno, fecha, monto) VALUES (?, ?, ?, ?, ?)",
                    (ref, clave(d), dueno(d)["dueno"], (fecha or ahora().date()).isoformat(), monto))


def deshacer_reembolso(ref):
    with closing(_con()) as con, con:
        return con.execute("DELETE FROM diferido_reembolsos WHERE ref = ?", (ref,)).rowcount


def cuotas_del_mes(mes, lista=None, incluir_otros=False):
    """Suma de cuotas que se facturan ese mes (AAAA-MM) y el detalle. Sin los diferidos de otras personas (salvo que se pida)."""
    detalle = []
    for d in lista if lista is not None else activos():
        if not incluir_otros and dueno(d):
            continue
        if d["mes_ref"] < mes <= ultimo_mes(d):
            detalle.append(d)
    return round(sum(d["cuota"] for d in detalle), 2), detalle


def proximos_meses(n=6, desde=None):
    mes = _mes(desde or ahora().date())
    return [_sumar_meses(mes, i) for i in range(1, n + 1)]


# ------------------------------------------------------------------ Gmail ---
def _config_bancos():
    """config/bancos.json (privado): qué correos de cada banco buscar en Gmail. Ver config/bancos.ejemplo.json."""
    from modulos.comun.base import leer_json
    try:
        return leer_json("bancos.json")
    except Exception:
        return {}


_BANCOS = _config_bancos()
BUSQUEDA_ESTADOS = (_BANCOS.get("busqueda_estados") or "").strip()
BUSQUEDA_PAGOS = (_BANCOS.get("busqueda_pagos") or "").strip()
BUSQUEDA_DIFERIDO = (_BANCOS.get("busqueda_diferido") or "").strip()
REMITENTES_ESTADO = {k.lower(): v for k, v in (_BANCOS.get("remitentes_estado") or {}).items()}   # dominio EXACTO


def _buscar(srv, q, extra, maximo):
    """Mensajes de Gmail para esa búsqueda; si no está configurada, ninguno (nunca buscar con q vacío)."""
    if not q:
        return []
    return srv.users().messages().list(userId="me", q=q + " " + extra, maxResults=maximo).execute().get("messages", [])


def banco_estado(remitente):
    from email.utils import parseaddr
    from modulos.finanzas import correos
    dominio = parseaddr(remitente)[1].split("@")[-1].lower()
    return REMITENTES_ESTADO.get(dominio) or correos.banco_del_remitente(remitente)


def _partes(p):
    yield p
    for x in p.get("parts", []) or []:
        yield from _partes(x)


def texto_pdf(datos):
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(datos))
    if r.is_encrypted:
        raise ValueError("el PDF tiene contraseña")
    return "\n".join((p.extract_text() or "") for p in r.pages)


def revisar(srv=None, dias=45):
    """Estados de cuenta nuevos y correos de diferido. Devuelve [eventos] para avisar."""
    from modulos.finanzas import correos
    srv = srv or correos.servicio()
    eventos = []
    for item in reversed(_buscar(srv, BUSQUEDA_ESTADOS, "newer_than:" + str(dias) + "d", 10)):
        ref = "gmail:" + item["id"]
        with closing(_con()) as con:
            if con.execute("SELECT 1 FROM tarjeta_estados WHERE ref = ?", (ref,)).fetchone():
                continue
        try:
            msg = srv.users().messages().get(userId="me", id=item["id"], format="full").execute()
            cab = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            banco = banco_estado(cab.get("from", ""))
            if banco not in ("Pichincha", "Produbanco", "Diners"):
                continue
            pdf = next((x for x in _partes(msg["payload"]) if (x.get("filename") or "").lower().endswith(".pdf")
                        and (x.get("body") or {}).get("attachmentId")), None)
            if not pdf:
                continue
            a = srv.users().messages().attachments().get(userId="me", messageId=item["id"], id=pdf["body"]["attachmentId"]).execute()
            texto = texto_pdf(base64.urlsafe_b64decode(a["data"]))
            r = {"Pichincha": leer_estado_pichincha, "Produbanco": leer_estado_produbanco, "Diners": leer_estado_diners}[banco](texto)
            if not r["fecha_max"] and not r["diferidos"]:
                log.warning("Estado de cuenta de %s sin datos legibles", banco)
                continue
            if guardar_estado(r, ref):
                eventos.append(("estado", r))
        except Exception as exc:
            log.warning("Tarjetas: no pude leer el estado de cuenta %s: %s", item["id"], exc)
    for item in _buscar(srv, BUSQUEDA_PAGOS, "newer_than:" + str(dias) + "d", 10):
        ref = "gmail:" + item["id"]
        with closing(_con()) as con:
            if con.execute("SELECT 1 FROM tarjeta_pagos WHERE ref = ?", (ref,)).fetchone():
                continue
        try:
            msg = srv.users().messages().get(userId="me", id=item["id"], format="full").execute()
            cab = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            if correos.banco_del_remitente(cab.get("from", "")) != "Diners":
                continue
            d = leer_pago_diners(correos._cuerpo(msg["payload"]))
            if d:
                guardar_pago("Diners", d, ref)
        except Exception as exc:
            log.warning("Tarjetas: no pude leer el pago de Diners %s: %s", item["id"], exc)
    for item in _buscar(srv, BUSQUEDA_DIFERIDO, "newer_than:10d", 5):
        ref = "gmail:" + item["id"]
        with closing(_con()) as con:
            if con.execute("SELECT 1 FROM diferidos WHERE ref = ?", (ref,)).fetchone():
                continue
        try:
            msg = srv.users().messages().get(userId="me", id=item["id"], format="full").execute()
            cab = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            if correos.banco_del_remitente(cab.get("from", "")) != "Pichincha":
                continue
            ev = procesar_correo_diferido(correos._cuerpo(msg["payload"]), ref)
            if ev:
                eventos.append(ev)
        except Exception as exc:
            log.warning("Tarjetas: no pude leer el correo de diferido %s: %s", item["id"], exc)
    return eventos


def procesar_correo_diferido(texto, ref):
    d = leer_correo_diferido(texto)
    if not d:
        return None
    desc = "Compra diferida"
    with closing(gastos._con()) as con:                       # la compra que se difirió (mismo monto, últimos 45 días)
        f = con.execute("SELECT descripcion FROM movimientos WHERE estado = 'activo' AND tipo = 'gasto' AND medio = ? "
                        "AND abs(monto - ?) < 0.011 AND fecha >= ? ORDER BY fecha DESC LIMIT 1",
                        ("Pichincha Platinum", d["valor"], (ahora().date() - timedelta(days=45)).isoformat())).fetchone()
    if f:
        desc = f["descripcion"]
    did = nuevo_diferido("Pichincha Platinum", desc, d["cuota"], d["plazo"], "correo", ref)
    return ("diferido", did, d)


# ------------------------------------------------------------------ cálculos: me alcanza ---
def gasto_normal(meses=3, hoy=None):
    """Promedio mensual de gastos de los últimos meses completos, sin compras grandes sueltas (> 30 % del sueldo)."""
    from modulos.finanzas import presupuesto
    hoy = hoy or ahora().date()
    tope = (presupuesto.sueldo() or 0) * 0.3 or float("inf")
    totales = []
    p = hoy.replace(day=1)
    for _ in range(meses):
        p = (p - timedelta(days=1)).replace(day=1)
        a, b = gastos.mes(p.year, p.month)
        lista = gastos.del_periodo(a, b, "gasto")
        if lista:
            totales.append(sum(g["monto"] for g in lista if g["monto"] <= tope))
    return round(sum(totales) / len(totales), 2) if totales else None, len(totales)


def factor(plazo):
    with closing(_con()) as con:
        f = con.execute("SELECT factor FROM tarjeta_factores WHERE plazo = ?", (plazo,)).fetchone()
    return f["factor"] if f else None


def me_alcanza(monto, plazo, con_interes=None, hoy=None):
    """Simula una compra diferida. Devuelve dict con el veredicto y el detalle mes a mes."""
    from modulos.finanzas import ahorros, presupuesto
    hoy = hoy or ahora().date()
    sueldo = presupuesto.sueldo()
    f = factor(plazo) if con_interes is not False else None
    total = round(monto * (1 + f / 100), 2) if f else monto
    cuota = round(total / plazo, 2)
    normal, meses_vistos = gasto_normal(hoy=hoy)
    ahorro = ahorros.aportes_mensuales()
    filas, peor = [], None
    for mes in proximos_meses(plazo, hoy):
        actuales, _ = cuotas_del_mes(mes)
        libre = round(sueldo - ahorro - (normal or 0) - actuales - cuota, 2)
        filas.append({"mes": mes, "cuotas": actuales, "libre": libre})
        if peor is None or libre < peor["libre"]:
            peor = filas[-1]
    maximo_cuotas = max((x["cuotas"] for x in filas), default=0) + cuota
    pct = round(maximo_cuotas / sueldo * 100) if sueldo else None
    if not sueldo:
        veredicto = "sin_sueldo"
    elif peor["libre"] < 0:
        veredicto = "no"
    elif peor["libre"] < sueldo * COLCHON / 100 or (pct or 0) > LIMITE_CUOTAS:
        veredicto = "justo"
    else:
        veredicto = "si"
    return {"monto": monto, "plazo": plazo, "total": total, "cuota": cuota, "factor": f, "sueldo": sueldo, "ahorro": ahorro,
            "normal": normal, "meses_vistos": meses_vistos, "filas": filas, "peor": peor, "pct_cuotas": pct,
            "veredicto": veredicto}


def texto_alcanza(r, que=""):
    cosa = (que + " de " if que else "Una compra de ") + fmt(r["monto"])
    if r["veredicto"] == "sin_sueldo":
        return "Para calcularlo necesito su sueldo. Dígame por ejemplo «mi sueldo es 700 y me pagan el 10»."
    if r["normal"] is None:
        nota_normal = " (todavía no tengo meses completos de gastos: no resté su gasto normal, el cálculo es optimista)"
    else:
        nota_normal = ""
    lineas = [cosa + " a " + str(r["plazo"]) + " meses: cuota de " + fmt(r["cuota"]) + "/mes"
              + (" (con interés estimado del banco, total " + fmt(r["total"]) + ")" if r["factor"] else " (sin contar intereses)")]
    icono = {"si": "✅ Sí le alcanza.", "justo": "⚠️ Le alcanza, pero justo.", "no": "❌ No le alcanza."}[r["veredicto"]]
    peor = r["peor"]
    if r["veredicto"] == "no":
        lineas.append(icono + " En " + nombre_mes(peor["mes"]) + " le faltarían " + fmt(-peor["libre"]) + ".")
    else:
        lineas.append(icono + " En el mes más apretado (" + nombre_mes(peor["mes"]) + ") le quedarían " + fmt(peor["libre"]) + " libres.")
    if r["pct_cuotas"] is not None and r["pct_cuotas"] > LIMITE_CUOTAS:
        lineas.append("🚩 Sus cuotas llegarían al " + str(r["pct_cuotas"]) + " % de su sueldo (lo prudente es no pasar del "
                      + str(LIMITE_CUOTAS) + " %).")
    lineas.append("\nCómo lo calculé (por mes): sueldo " + fmt(r["sueldo"]) + " − ahorros " + fmt(r["ahorro"])
                  + " − gasto normal " + fmt(r["normal"] or 0) + nota_normal + " − cuotas que ya tiene − cuota nueva.")
    lineas.append("\n".join("• " + nombre_mes(x["mes"]) + ": cuotas actuales " + fmt(x["cuotas"]) + " → libre " + fmt(x["libre"])
                            for x in r["filas"][:12]))
    lineas.append("\nSolo le informo: la decisión es suya.")
    return "\n".join(lineas)


# ------------------------------------------------------------------ textos ---
def texto_diferidos(hoy=None):
    hoy = hoy or ahora().date()
    lista = [d for d in activos() if ultimo_mes(d) > _mes(hoy)]
    if not lista:
        return ("No tengo diferidos activos. Los leo de los estados de cuenta de Pichincha y Produbanco; para Diners dígame "
                "«diferí la laptop de 900 a 6 meses con diners».")
    otros = [d for d in lista if dueno(d)]
    lista = [d for d in lista if not dueno(d)]
    lineas = ["💳 Sus diferidos"] if lista else ["💳 No tiene diferidos propios."]
    for d in lista:
        restantes = d["total_cuotas"] - d["pagadas"]
        lineas.append("#" + str(d["id"]) + " " + d["descripcion"] + " (" + d["tarjeta"] + "): " + fmt(d["cuota"]) + "/mes"
                      + (", va en la " + str(d["pagadas"]) + " de " + str(d["total_cuotas"]) if d["pagadas"] else "")
                      + ", faltan " + str(restantes)
                      + " cuota" + ("s" if restantes != 1 else "") + " → hasta " + nombre_mes(ultimo_mes(d))
                      + (" · pendiente " + fmt(d["saldo"]) if d["saldo"] else "") + (" (provisional)" if d["origen"] != "estado" else ""))
    lineas.append("\nCuotas por mes:")
    for mes in proximos_meses(6, hoy):
        total, det = cuotas_del_mes(mes, lista)
        if total:
            lineas.append("• " + nombre_mes(mes) + ": " + fmt(total) + " (" + str(len(det)) + ")")
    libre = [m for m in proximos_meses(36, hoy) if not cuotas_del_mes(m, lista)[0]]
    if libre and lista:
        lineas.append("Queda libre de cuotas desde " + nombre_mes(libre[0]) + ".")
    if otros:
        lineas.append("\n👥 Los paga otra persona (no cuentan en sus cuotas):")
        for d in otros:
            lineas.append("#" + str(d["id"]) + " " + d["descripcion"] + " (" + d["tarjeta"] + ") → " + dueno(d)["dueno"] + ": "
                          + fmt(d["cuota"]) + "/mes hasta " + nombre_mes(ultimo_mes(d)))
    lineas.append("\nSi uno no es suyo: «el diferido #" + str((lista or otros)[0]["id"]) + " es de Juan» (y «… es mío» para deshacerlo).")
    from modulos.finanzas import presupuesto
    s = presupuesto.sueldo()
    proximo = cuotas_del_mes(proximos_meses(1, hoy)[0], lista)[0]
    if s and proximo:
        pct = round(proximo / s * 100)
        lineas.append(("🚩 " if pct > LIMITE_CUOTAS else "") + "El próximo mes las cuotas son el " + str(pct) + " % de su sueldo"
                      + (" (lo prudente es no pasar del " + str(LIMITE_CUOTAS) + " %): mejor no diferir más por ahora."
                         if pct > LIMITE_CUOTAS else "."))
    return "\n".join(lineas)


def texto_estado(r):
    lineas = ["🧾 Llegó el estado de cuenta de " + r["tarjeta"] + "."]
    if r["fecha_max"]:
        lineas.append("Pagar hasta el " + r["fecha_max"].strftime("%d/%m") + ": total " + fmt(r["total"] or 0)
                      + (" (mínimo " + fmt(r["minimo"]) + ")" if r["minimo"] else "") + ".")
    vivos = [d for d in r["diferidos"] if not d.get("final")]
    finales = [d for d in r["diferidos"] if d.get("final")]
    if vivos:
        lineas.append("Diferidos: " + str(len(vivos)) + ", cuotas de este mes " + fmt(sum(d["cuota"] for d in vivos))
                      + (" · pendiente " + fmt(r["saldo_diferido"]) if r["saldo_diferido"] else "") + ". /diferidos")
    if finales:
        lineas.append("🎉 Terminó de pagar: " + ", ".join(d["descripcion"] for d in finales) + ".")
    ajenos = [x for x in activos() if x["tarjeta"] == r["tarjeta"] and dueno(x) and x["mes_ref"] == _mes(r["emision"] or ahora().date())]
    if ajenos:
        lineas.append("👥 El total incluye " + fmt(sum(x["cuota"] for x in ajenos)) + " de diferidos que pagan otras personas ("
                      + ", ".join(dueno(x)["dueno"] for x in ajenos) + ").")
    if r["aviso"]:
        lineas.append("⚠️ Ojo: " + r["aviso"] + ". Avise a Claude con el estado de cuenta.")
    return "\n".join(lineas)


def texto_diferido_nuevo(did, d):
    x = next(y for y in activos() if y["id"] == did)
    return ("💳 Difirió " + fmt(d["valor"]) + " (" + x["descripcion"] + ") a " + str(d["plazo"]) + " meses: " + fmt(x["cuota"])
            + "/mes hasta " + nombre_mes(ultimo_mes(x)) + (" (interés " + fmt(d["interes"]) + ")" if d.get("interes") else "")
            + ".\nLa compra ya está contada como gasto; las cuotas quedan como compromiso de cada mes. /diferidos")


def pagos_por_vencer(hoy=None, dias=3):
    """Estados con fecha máxima en los próximos 'dias' (o hoy) que no se pagaron todavía. [(estado, pagado)]"""
    hoy = hoy or ahora().date()
    with closing(_con()) as con:
        filas = [dict(f) for f in con.execute("SELECT * FROM tarjeta_estados WHERE fecha_max >= ? AND fecha_max <= ? ORDER BY fecha_max",
                                              (hoy.isoformat(), (hoy + timedelta(days=dias)).isoformat()))]
    salida = []
    for e in filas:
        pagado = pagado_desde(e["tarjeta"], e["emision"])
        if e["total"] and pagado >= e["total"] - 0.01:
            continue
        salida.append((e, pagado))
    return salida


def pagado_desde(tarjeta, emision):
    """Lo pagado a esa tarjeta desde la emisión: pagos vistos en sus cuentas (cuentas.py) o confirmados por el banco
    (Diners «Agradecemos su pago»); se toma el mayor para no contar dos veces el mismo pago."""
    banco = _norm(tarjeta.split()[0])
    de_cuentas = 0.0
    try:
        from modulos.finanzas import cuentas
        with closing(cuentas._con()) as con:
            filas = con.execute("SELECT monto, banco_otro FROM cuenta_movs WHERE clase = 'pago_tarjeta' AND estado = 'activo' "
                                "AND cuando >= ?", ((emision or "0000") + "T00:00:00",)).fetchall()
        de_cuentas = round(sum(f["monto"] for f in filas if banco in _norm(f["banco_otro"])), 2)
    except Exception:
        pass
    with closing(_con()) as con:
        f = con.execute("SELECT coalesce(sum(monto), 0) AS s FROM tarjeta_pagos WHERE tarjeta = ? AND fecha >= ?",
                        (tarjeta, emision or "0000")).fetchone()
    return max(de_cuentas, round(f["s"], 2))


def pagos_recientes(tarjeta, desde):
    """Pagos de esa tarjeta desde una fecha: [{'fecha','monto','origen'}] (para el panel y la IA)."""
    banco = _norm(tarjeta.split()[0])
    salida = []
    try:
        from modulos.finanzas import cuentas
        with closing(cuentas._con()) as con:
            for f in con.execute("SELECT cuando, monto, banco_otro, cuenta FROM cuenta_movs WHERE clase = 'pago_tarjeta' "
                                 "AND estado = 'activo' AND cuando >= ? ORDER BY cuando", ((desde or "0000") + "T00:00:00",)):
                if banco in _norm(f["banco_otro"]):
                    salida.append({"fecha": f["cuando"][:10], "monto": f["monto"], "origen": "desde " + f["cuenta"]})
    except Exception:
        pass
    if not salida:
        with closing(_con()) as con:
            salida = [{"fecha": f["fecha"], "monto": f["monto"], "origen": "confirmado por el banco"} for f in
                      con.execute("SELECT * FROM tarjeta_pagos WHERE tarjeta = ? AND fecha >= ? ORDER BY fecha", (tarjeta, desde or "0000"))]
    return salida


def texto_por_vencer(e, pagado, hoy=None):
    hoy = hoy or ahora().date()
    f = date.fromisoformat(e["fecha_max"])
    cuando = "HOY" if f == hoy else ("mañana" if (f - hoy).days == 1 else "el " + f.strftime("%d/%m"))
    texto = "💳 " + e["tarjeta"] + ": la fecha máxima de pago es " + cuando + ". Total " + fmt(e["total"] or 0)
    texto += (" (mínimo " + fmt(e["minimo"]) + ")" if e["minimo"] else "") + "."
    if pagado:
        texto += " Ya vi pagos por " + fmt(pagado) + "; faltarían " + fmt(max(0, (e["total"] or 0) - pagado)) + "."
    return texto + " Pagar solo el mínimo genera intereses."


# ------------------------------------------------------------------ frases ---
_N = r"\$?\s*(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(?:d[oó]lares|usd)?"
P_VER = re.compile(r"^\W*(?:/diferidos|mis diferidos|mis cuotas|(?:mis\s+)?compras diferidas|cu[aá]nto pago (?:de|en) cuotas|"
                   r"qu[eé] (?:diferidos|cuotas) tengo|hasta cu[aá]ndo (?:pago|tengo que pagar) (?:las|mis) cuotas)\W*$", re.I)
# «/tarjetas» y «mis tarjetas» ya son las tarjetas de estudio de la biblioteca: aquí siempre «de crédito» o «pagar».
P_TARJETAS = re.compile(r"^\W*(?:/credito|mis tarjetas de cr[eé]dito|tarjetas de cr[eé]dito|cu[aá]nto debo (?:de|en) (?:las |mis )?tarjetas|"
                        r"cu[aá]ndo (?:tengo que |debo )?pag(?:ar|o) (?:la|las|mis) tarjetas?(?: de cr[eé]dito)?|"
                        r"fechas? (?:m[aá]xima )?de pago(?: de (?:mis )?tarjetas?)?)\W*$", re.I)
P_ALCANZA = re.compile(r"(?:me alcanza|puedo|podr[ií]a|deber[ií]a|conviene|si difiero|quiero comprar(?:me)?|si compro|alcanza)"
                       r".*?" + _N + r".*?\ba\s+(\d{1,2})\s+(?:meses|cuotas)", re.I)
P_ALCANZA_2 = re.compile(r"(?:me alcanza|puedo|si difiero|quiero comprar(?:me)?|si compro|diferir).*?\ba\s+(\d{1,2})\s+(?:meses|cuotas)"
                         r".*?" + _N, re.I)
P_DIFERI = re.compile(r"^\W*(?:difer[ií]|compr[eé])\s+(?:la |el |los |las |un |una |mi )?(.+?)\s+(?:de|por|en)\s+" + _N
                      + r"\s+a\s+(\d{1,2})\s+(?:meses|cuotas)(?:\s+(?:con|en)\s+(?:la |mi )?(diners|pichincha|produbanco|platinum|gold))?\W*$", re.I)


def _tarjeta_de(t):
    n = _norm(t or "")
    if "diners" in n:
        return "Diners"
    if "pichincha" in n or "platinum" in n:
        return "Pichincha Platinum"
    if "produbanco" in n or "gold" in n:
        return "Produbanco Gold"
    return "Diners"


def _que(texto):
    m = re.search(r"(?:comprar(?:me)?|compro|difiero)\s+(?:un |una |el |la |unos |unas )?([a-zA-ZÀ-ÿ][\wÀ-ÿ ]{1,30}?)\s+(?:de|por|en|a)\b",
                  texto, re.I)
    return m.group(1).strip() if m else ""


# Varios mensajes seguidos («el #12 es de Juan» … «y el 15» … «el de lg tampoco» … «listo»): sesión de 10 minutos.
SESION = {"hasta": None, "persona": None, "marcados": [], "pendientes": []}
CIERRE = re.compile(r"^\W*(?:listo|ya|ya est[aá]|eso es todo|es todo|nada m[aá]s|ninguno(?: m[aá]s)?|no,? (?:ninguno|nada|eso es todo|m[aá]s no)|"
                    r"(?:ya )?termin[eé]|solo esos?|son todos|eso nom[aá]s|nada|no hay m[aá]s|ya no|cancela(?:r)?|ol[vb]id[aá]lo|d[eé]jalo(?: as[ií])?)\W*$", re.I)
_NO_PERSONA = {"mio", "mia", "mios", "mias", "tambien", "tampoco", "igual", "el", "la", "los", "las", "de", "otra", "otro", "persona",
               "alguien", "ese", "esos", "este", "estos", "diferido", "diferidos", "nadie", "yo", "mi"}
P_PERSONA = re.compile(r"(?:\bes|\bson|\blo paga|\blos paga|\bpertenece(?:n)?(?: a)?|\bes para|\bson para|\bpaga)\s+(?:de\s+)?"
                       r"((?:mi\s+)?[a-zA-ZÀ-ÿ]+(?:\s+[a-zA-ZÀ-ÿ]+)?)\W*$", re.I)


def _en_sesion():
    return bool(SESION["hasta"]) and ahora() < SESION["hasta"]


def _clausulas(texto):
    partes = re.split(r"[\n;]+|(?<=[.!?])\s+", texto)
    return [p.strip() for p in partes if p.strip()]


def _ids_en(texto, vivos):
    ids = {d["id"] for d in vivos}
    salida = []
    for m in re.finditer(r"#?\s?(?<![\d.,$])(\d{1,5})(?!\d|[.,]\d)(?!\s*(?:meses|cuotas|d[oó]lares|usd|%))", texto, re.I):
        n = int(m.group(1))
        if n in ids and n not in salida:
            salida.append(n)
    return salida


def _clausula(cl, vivos, sesion, persona_previa=None):
    n = _norm(cl)
    con_diferido = "diferido" in n
    corto = re.match(r"^\W*(?:y\s+|tambi[eé]n\s+|ah,?\s+|adem[aá]s\s+)?(?:el|los|la|las)?\s*(?:#?\s?\d{1,5}(?:\s*(?:,|y|e)\s*(?:el\s+)?#?\s?\d{1,5})*)",
                     cl, re.I) and re.search(r"\d", cl)
    if not con_diferido and not (sesion and (corto or SESION["pendientes"] or
                                             re.search(r"tambi[eé]n|tampoco|\bes de\b|\bson de\b|lo paga|los paga|m[ií]os?\b", n))):
        return None
    ids = _ids_en(cl, vivos)
    if not ids:
        m = re.search(r"\bde(?:l)?\s+(?:la\s+|el\s+)?(.+?)\s+(?:no\s+|tambi[eé]n|tampoco|es\b|son\b|lo\s+paga|los\s+paga|igual)", cl, re.I)
        if m:
            ids = [d["id"] for d in _buscar_diferido(None, m.group(1))]
    persona = None
    m = P_PERSONA.search(cl)
    if m and not set(_norm(m.group(1)).split()) & _NO_PERSONA - {"mi"} and _norm(m.group(1)).split()[-1] not in _NO_PERSONA:
        persona = m.group(1).strip()
        persona = ("mi " + persona[3:].strip().lower()) if persona.lower().startswith("mi ") else persona.title()
    mio = bool(re.search(r"\b(?:es|son)\s+m[ií]os?\b|\blos?\s+pago\s+yo\b|\bvuelve(?:n)?\s+a\s+ser\s+m[ií]os?\b", n)) and \
        not re.search(r"\b(?:no|tampoco)\s+(?:es|son)\s+m[ií]os?\b", n)
    if not ids:
        suelto = re.fullmatch(r"\W*(?:de\s+)?(?:mi\s+)?[a-zA-ZÀ-ÿ]+(?:\s+[a-zA-ZÀ-ÿ]+)?\W*", cl) and not set(n.split()) & {
            "gracias", "ok", "okay", "si", "no", "vale", "bueno", "dale", "perfecto", "hola", "jarvis", "espera", "ahora"}
        if sesion and SESION["pendientes"] and (persona or suelto):
            if not persona:                                   # respuesta a «¿de quién es?»: «de mi hermano», «Juan»
                persona = re.sub(r"^\W*(?:de\s+)?", "", cl).strip(" .!?")
                persona = ("mi " + persona[3:].strip().lower()) if persona.lower().startswith("mi ") else persona.title()
            return {"ids": list(SESION["pendientes"]), "persona": persona, "mio": False}
        return {"ids": [], "persona": persona, "mio": mio, "no_encontrado": cl} if con_diferido else None
    if mio:
        return {"ids": ids, "persona": None, "mio": True}
    previa = persona_previa or SESION["persona"]
    if not persona and (sesion or re.search(r"tambi[eé]n|tampoco|igual|lo mismo", n)) and previa:
        persona = previa
    return {"ids": ids, "persona": persona, "mio": False, "falta_persona": not persona}


def interpretar_duenos(texto):
    t = (texto or "").strip()
    sesion = _en_sesion()
    if sesion and CIERRE.match(t):
        return {"accion": "duenos_fin"}
    if "diferido" not in _norm(t) and not sesion:
        return None
    vivos = activos()
    acciones, previa, hablando = [], None, sesion
    for cl in _clausulas(t):                                 # en un mensaje largo, cada línea sigue el hilo de la anterior
        a = _clausula(cl, vivos, hablando, previa)
        if a:
            acciones.append(a)
            hablando = True
            previa = a.get("persona") or previa
    if not acciones:
        return None
    if all(a.get("no_encontrado") is not None and not a["ids"] for a in acciones) and not re.search(
            r"no\s+(?:es|son)\s+m[ií]o|\bes de\b|\bson de\b|lo paga|los paga|m[ií]os?\b", _norm(t)):
        return None                                           # habla de diferidos pero no de quién es («mis diferidos»…)
    return {"accion": "duenos", "acciones": acciones}


def ejecutar_duenos(d):
    if d["accion"] == "duenos_fin":
        hechos = SESION["marcados"]
        SESION.update(hasta=None, persona=None, marcados=[], pendientes=[])
        if not hechos:
            return "👌 Listo, no cambié nada."
        return ("✅ Listo. Quedaron así:\n" + "\n".join("• " + h for h in hechos)
                + "\n\nYa no cuentan en sus cuotas ni en «¿me alcanza?». Lo que esa persona le transfiera no es ingreso: "
                "solo sube el saldo de su cuenta. /diferidos")
    lineas, pendientes = [], []
    for a in d["acciones"]:
        if not a["ids"]:
            lineas.append("🤔 No encontré el diferido de «" + a.get("no_encontrado", "")[:60] + "». Use el número de /diferidos.")
            continue
        if a.get("falta_persona"):
            pendientes += a["ids"]
            continue
        for did in a["ids"]:
            x = marcar_dueno(did, None if a["mio"] else a["persona"])
            if not x:
                continue
            if a["mio"]:
                linea = "#" + str(did) + " " + x["descripcion"] + " → suyo"
            else:
                linea = ("#" + str(did) + " " + x["descripcion"] + " (" + fmt(x["cuota"]) + "/mes hasta " + nombre_mes(ultimo_mes(x))
                         + ") → lo paga " + a["persona"])
                SESION["persona"] = a["persona"]
            lineas.append(("👌 " if a["mio"] else "👥 ") + linea)
            SESION["marcados"] = [m for m in SESION["marcados"] if not m.startswith("#" + str(did) + " ")] + [linea]
    SESION["hasta"] = ahora() + timedelta(minutes=10)
    SESION["pendientes"] = pendientes
    if pendientes:
        vivos = {x["id"]: x for x in activos()}
        lineas.append("¿De quién " + ("es el " if len(pendientes) == 1 else "son los ") + ", ".join(
            "#" + str(i) + " " + vivos[i]["descripcion"] for i in pendientes if i in vivos) + "? Dígame el nombre (ej.: «de Juan»).")
    else:
        propios = [x for x in activos() if not dueno(x) and ultimo_mes(x) > _mes(ahora().date())]
        lineas.append("\n¿Algún otro que no sea suyo? Mándeme el número (o varios: «#12, #15 y #18 son de Juan») o «listo»."
                      + ("\nSiguen como suyos: " + ", ".join("#" + str(x["id"]) + " " + x["descripcion"] for x in propios[:8])
                         if propios else ""))
    return "\n".join(lineas)


def _buscar_diferido(num, texto):
    vivos = activos()
    if num:
        return [d for d in vivos if d["id"] == int(num)]
    pal = [w for w in re.findall(r"[a-zñ0-9]+", _norm(texto)) if len(w) >= 2]
    return [d for d in vivos if pal and all(w in _norm(d["descripcion"]) for w in pal)]


def interpretar(texto):
    d = interpretar_duenos(texto)                       # antes que nada: de quién es cada diferido (varios mensajes seguidos)
    if d:
        return d
    t = " ".join((texto or "").split())
    if P_VER.match(t):
        return {"accion": "ver"}
    if P_TARJETAS.match(t):
        return {"accion": "tarjetas"}
    m = P_DIFERI.match(t)
    if m:
        return {"accion": "diferi", "que": m.group(1), "monto": dinero(m.group(2)), "plazo": int(m.group(3)),
                "tarjeta": _tarjeta_de(m.group(4))}
    if re.search(r"\b(?:meses|cuotas)\b", t, re.I) and re.search(r"alcanza|puedo|podr[ií]a|conviene|difiero|diferir|si compro|"
                                                              r"quiero comprar", t, re.I):
        m = P_ALCANZA.search(t)
        if m:
            monto, plazo = dinero(m.group(1)), int(m.group(2))
        else:
            m = P_ALCANZA_2.search(t)
            if not m:
                return None
            plazo, monto = int(m.group(1)), dinero(m.group(2))
        if 1 <= plazo <= 48 and 1 <= monto <= 100000:
            return {"accion": "alcanza", "monto": monto, "plazo": plazo, "que": _que(t),
                    "sin_interes": bool(re.search(r"sin inter[eé]s", t, re.I))}
    return None


def ejecutar(d):
    if d["accion"] in ("duenos", "duenos_fin"):
        return ejecutar_duenos(d)
    if d["accion"] == "dueno":
        if not d["lista"]:
            return "No encontré ese diferido. Mire los números con /diferidos (ej.: «el diferido #12 es de Juan»)."
        if len(d["lista"]) > 1:
            return ("Encontré varios: " + "; ".join("#" + str(x["id"]) + " " + x["descripcion"] + " (" + x["tarjeta"] + ")"
                                                  for x in d["lista"][:5]) + ". Dígame el número.")
        x = marcar_dueno(d["lista"][0]["id"], d["persona"])
        if not d["persona"]:
            return "👌 El diferido " + x["descripcion"] + " vuelve a ser suyo: cuenta en sus cuotas y en «¿me alcanza?»."
        return ("👥 Anotado: el diferido " + x["descripcion"] + " (" + x["tarjeta"] + ", " + fmt(x["cuota"]) + "/mes hasta "
                + nombre_mes(ultimo_mes(x)) + ") lo paga " + d["persona"] + ".\nYa no cuenta en sus cuotas ni en «¿me alcanza?».")
    if d["accion"] == "ver":
        return texto_diferidos()
    if d["accion"] == "tarjetas":
        return texto_tarjetas()
    if d["accion"] == "diferi":
        did = nuevo_diferido(d["tarjeta"], d["que"].capitalize(), d["monto"] / d["plazo"], d["plazo"])
        x = next(y for y in activos() if y["id"] == did)
        return ("📝 Anoté el diferido: " + d["que"] + " " + fmt(d["monto"]) + " a " + str(d["plazo"]) + " meses con " + d["tarjeta"]
                + " → " + fmt(x["cuota"]) + "/mes hasta " + nombre_mes(ultimo_mes(x)) + " (sin intereses; si el banco cobra, "
                "el estado de cuenta lo corrige)." + ("" if d["tarjeta"] == "Diners" else " Cuando llegue el estado de cuenta, "
                                                       "lo reemplazo por el dato del banco."))
    if d["accion"] == "alcanza":
        return texto_alcanza(me_alcanza(d["monto"], d["plazo"], False if d.get("sin_interes") else None), d.get("que", ""))
    return None


def texto_tarjetas(hoy=None):
    """/credito: por tarjeta, cuánto y hasta cuándo pagar, lo pagado (con cada pago) y sus diferidos."""
    hoy = hoy or ahora().date()
    datos = {x["tarjeta"]: x for x in resumen_tarjetas(hoy)}
    lineas = ["💳 Sus tarjetas de crédito"]
    for nombre in ("Pichincha Platinum", "Produbanco Gold", "Diners"):
        t = datos.get(nombre)
        if not t or not t["fecha_max"]:
            lineas.append("\n• " + nombre + ": todavía no leí su estado de cuenta (llega por correo cada mes).")
            if not t:
                continue
        else:
            f = date.fromisoformat(t["fecha_max"])
            lineas.append("\n• " + nombre + ": pagar hasta el " + f.strftime("%d/%m") + " · total " + fmt(t["total"])
                          + (" · mínimo " + fmt(t["minimo"]) if t["minimo"] else ""))
            lineas.append("   " + ("✅ Pagada" if t["pagada"] else ("Pagado " + fmt(t["pagado"]) + ", falta " + fmt(t["falta"])
                                                                   if t["pagado"] else "Pendiente: " + fmt(t["falta"]))))
            for p in t["pagos"][:4]:
                lineas.append("   💸 " + date.fromisoformat(p["fecha"]).strftime("%d/%m") + " " + fmt(p["monto"]) + " (" + p["origen"] + ")")
        if t["diferidos"]:
            propios = [d for d in t["diferidos"] if not d["otro"]]
            ajenos = [d for d in t["diferidos"] if d["otro"]]
            if propios:
                lineas.append("   Diferidos: " + str(len(propios)) + " · " + fmt(sum(d["cuota"] for d in propios)) + "/mes")
            for d in ajenos:
                lineas.append("   👥 " + d["descripcion"] + " " + fmt(d["cuota"]) + "/mes lo paga " + d["otro"]["dueno"])
    lineas.append("\nDetalle de cuotas: /diferidos")
    return "\n".join(lineas)


def procesar(texto):
    d = interpretar(texto)
    return ejecutar(d) if d else None


# ------------------------------------------------------------------ panel y contexto de la IA ---
def ultimos_estados():
    with closing(_con()) as con:
        return {f["tarjeta"]: dict(f) for f in con.execute(
            "SELECT * FROM tarjeta_estados t WHERE emision = (SELECT max(emision) FROM tarjeta_estados WHERE tarjeta = t.tarjeta)")}


def resumen_tarjetas(hoy=None):
    """Por tarjeta: último estado, lo pagado, lo que falta y sus diferidos. [dict] (Pichincha, Produbanco, Diners)."""
    hoy = hoy or ahora().date()
    estados = ultimos_estados()
    difs = [d for d in activos() if ultimo_mes(d) > _mes(hoy)]
    salida = []
    for nombre in ("Pichincha Platinum", "Produbanco Gold", "Diners"):
        e = estados.get(nombre)
        mios = [d for d in difs if d["tarjeta"] == nombre]
        if not e and not mios:
            continue
        pagado = pagado_desde(nombre, e["emision"]) if e else 0.0
        total = (e or {}).get("total") or 0
        salida.append({
            "tarjeta": nombre, "fecha_max": (e or {}).get("fecha_max"), "total": total, "minimo": (e or {}).get("minimo"),
            "pagado": pagado, "falta": round(max(0, total - pagado), 2), "pagada": bool(total) and pagado >= total - 0.01,
            "pagos": pagos_recientes(nombre, e["emision"]) if e else [],
            "diferidos": [{"id": d["id"], "descripcion": d["descripcion"], "cuota": d["cuota"], "pagadas": d["pagadas"],
                           "total_cuotas": d["total_cuotas"], "faltan": d["total_cuotas"] - d["pagadas"], "hasta": ultimo_mes(d),
                           "hasta_texto": nombre_mes(ultimo_mes(d)), "saldo": d["saldo"], "provisional": d["origen"] != "estado",
                           "otro": {"dueno": dueno(d)["dueno"]} if dueno(d) else None}
                          for d in mios],
            "cuota_proximo_mes": cuotas_del_mes(proximos_meses(1, hoy)[0], mios)[0]})
    return salida


def datos_panel(hoy=None):
    hoy = hoy or ahora().date()
    from modulos.finanzas import presupuesto
    s = presupuesto.sueldo()
    meses = [{"mes": m, "nombre": nombre_mes(m), "total": cuotas_del_mes(m)[0]} for m in proximos_meses(6, hoy)]
    proximo = meses[0]["total"] if meses else 0
    return {"tarjetas": resumen_tarjetas(hoy), "cuotas_meses": meses,
            "pct_sueldo": round(proximo / s * 100) if s and proximo else None, "limite": LIMITE_CUOTAS}


def contexto_ia(hoy=None):
    """Una línea por tarjeta con lo que importa para conversar (va dentro de perfil.contexto_ia)."""
    hoy = hoy or ahora().date()
    partes = []
    for t in resumen_tarjetas(hoy):
        txt = t["tarjeta"] + ": "
        if t["fecha_max"]:
            txt += ("pagada (" + fmt(t["pagado"]) + ")" if t["pagada"] else "pagar " + fmt(t["falta"]) + " hasta el "
                    + date.fromisoformat(t["fecha_max"]).strftime("%d/%m") + (" (mínimo " + fmt(t["minimo"]) + ")" if t["minimo"] else "")
                    + (", ya pagó " + fmt(t["pagado"]) if t["pagado"] else ""))
        if t["diferidos"]:
            txt += "; diferidos: " + ", ".join(d["descripcion"] + " " + fmt(d["cuota"]) + "/mes hasta " + d["hasta_texto"]
                                              + (" (lo paga " + d["otro"]["dueno"] + ": no cuenta en sus cuotas)"
                                                 if d["otro"] else "") for d in t["diferidos"])
        partes.append(txt)
    if not partes:
        return ""
    meses = [m for m in datos_panel(hoy)["cuotas_meses"] if m["total"]]
    if meses:
        partes.append("Cuotas por mes: " + ", ".join(m["nombre"] + " " + fmt(m["total"]) for m in meses[:6])
                      + " (la compra diferida ya se contó como gasto el día que se hizo; las cuotas son compromisos)")
    return "TARJETAS — " + " | ".join(partes)


ULTIMA_REVISION = {"t": 0.0}


def revisar_si_hace_falta(minutos=30):
    """Para /credito y /diferidos: si no se revisó Gmail hace rato, revisa ahora. Devuelve los eventos nuevos."""
    import time
    if time.time() - ULTIMA_REVISION["t"] < minutos * 60:
        return []
    ULTIMA_REVISION["t"] = time.time()
    return revisar()


def diagnostico():
    """python modulos\\finanzas\\tarjetas.py --probar : qué estados de cuenta y pagos encuentra en Gmail (solo lectura)."""
    from modulos.finanzas import correos
    srv = correos.servicio()
    for titulo, q in (("ESTADOS DE CUENTA", BUSQUEDA_ESTADOS), ("PAGOS DINERS", BUSQUEDA_PAGOS), ("DIFERIDOS", BUSQUEDA_DIFERIDO)):
        res = _buscar(srv, q, "newer_than:60d", 10)
        print("\n## " + titulo + ": " + str(len(res)))
        for item in res:
            msg = srv.users().messages().get(userId="me", id=item["id"], format="full").execute()
            cab = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            banco = banco_estado(cab.get("from", ""))
            linea = "- " + cab.get("date", "")[:16] + " | " + cab.get("from", "")[:50] + " | banco: " + str(banco)
            if titulo == "ESTADOS DE CUENTA" and banco in ("Pichincha", "Produbanco", "Diners"):
                pdf = next((x for x in _partes(msg["payload"]) if (x.get("filename") or "").lower().endswith(".pdf")
                            and (x.get("body") or {}).get("attachmentId")), None)
                if not pdf:
                    linea += " | SIN PDF"
                else:
                    try:
                        a = srv.users().messages().attachments().get(userId="me", messageId=item["id"], id=pdf["body"]["attachmentId"]).execute()
                        texto = texto_pdf(base64.urlsafe_b64decode(a["data"]))
                        r = {"Pichincha": leer_estado_pichincha, "Produbanco": leer_estado_produbanco, "Diners": leer_estado_diners}[banco](texto)
                        linea += (" | emisión " + str(r["emision"]) + " · pagar hasta " + str(r["fecha_max"]) + " · total "
                                  + str(r["total"]) + " · diferidos " + str(len(r["diferidos"])) + (" · AVISO: " + r["aviso"] if r["aviso"] else ""))
                    except Exception as exc:
                        linea += " | ERROR: " + str(exc)[:80]
            with closing(_con()) as con:
                if con.execute("SELECT 1 FROM tarjeta_estados WHERE ref = ? UNION SELECT 1 FROM tarjeta_pagos WHERE ref = ?",
                               ("gmail:" + item["id"], "gmail:" + item["id"])).fetchone():
                    linea += " | ya guardado"
            print(linea)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--probar" in sys.argv:
        diagnostico()
    if "--revisar" in sys.argv:
        print(revisar())
