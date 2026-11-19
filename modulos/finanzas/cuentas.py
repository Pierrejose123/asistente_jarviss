"""Finanzas, paso 7: CUENTAS del banco (13-11). Transferencias enviadas y recibidas, pagos de tarjeta, pagos de servicios,
remesas y pagos a terceros leídos de Gmail (SOLO LECTURA, lectores fijos sin IA) + saldo estimado de cada cuenta.

Saldo: los bancos no mandan el saldo. Se parte de un saldo que da el usuario («saldo produbanco 850») y se suma/resta
cada correo. El día 1 (09:10) pregunta el saldo real de cada cuenta: la diferencia queda como «ajuste» (lo que el banco no
avisó: efectivo, débitos automáticos, apps sin correo). Los aportes a ahorros programados del mismo banco se restan solos.

Qué cuenta como gasto o ingreso (tabla movimientos, la misma de gastos):
  - pago de tarjeta de crédito: sale de la cuenta, NO es gasto (los consumos ya se contaron); su comisión SÍ es gasto
  - pago de servicios: gasto (categoría por palabras) + comisión
  - transferencia a otra persona: pregunta con botones (gasto / pago de deuda / préstamo / entre mis cuentas / no contar)
    y aprende por persona
  - transferencia recibida: «ABONO SUELDOS» = sueldo (si la empresa tiene una deuda abierta con usted, pregunta);
    de otra persona pregunta (ingreso / me pagó una deuda / entre mis cuentas / no contar) y aprende
  - entre sus propias cuentas (el titular se aprende del saludo de cada correo): no es gasto ni ingreso; si el otro banco
    es una de sus cuentas, se anota la entrada estimada y se confirma cuando llega su correo (sin contar dos veces)
Tablas: cuentas, cuenta_movs, cuenta_aprendidas, cuenta_titular, cuenta_vistos.
"""
import re
import unicodedata
from contextlib import closing
from datetime import date, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime

from modulos.comun import db
from modulos.comun.base import ZONA, ahora, registro
from modulos.finanzas import gastos
from modulos.finanzas.deudas import dinero, fmt

log = registro("finanzas")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cuentas (
    nombre      TEXT PRIMARY KEY,
    saldo_base  REAL,
    fecha_base  TEXT                         -- AAAA-MM-DDTHH:MM:SS (hora de Ecuador)
);
CREATE TABLE IF NOT EXISTS cuenta_movs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta      TEXT NOT NULL,
    cuando      TEXT NOT NULL,               -- AAAA-MM-DDTHH:MM:SS
    sentido     TEXT NOT NULL,               -- entrada | salida | neutro
    monto       REAL NOT NULL,
    clase       TEXT NOT NULL,               -- transferencia | pago_tarjeta | pago_servicio | comision | remesa | pago_terceros | ajuste
    decision    TEXT DEFAULT '',             -- gasto | ingreso | sueldo | deuda | prestamo | interna | no_contar | pendiente
    contraparte TEXT DEFAULT '',
    banco_otro  TEXT DEFAULT '',
    descripcion TEXT DEFAULT '',
    ref         TEXT DEFAULT '',             -- gmail:<id> (vacío si es estimado)
    mov         INTEGER,                     -- id en movimientos (gasto/ingreso) si lo hay
    estado      TEXT DEFAULT 'activo',       -- activo | estimado | borrado
    creado      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cuenta_aprendidas (
    clave       TEXT PRIMARY KEY,            -- sentido|contraparte normalizada
    decision    TEXT NOT NULL,
    categoria   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cuenta_titular (palabra TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS cuenta_vistos (ref TEXT PRIMARY KEY, tipo TEXT, cuando TEXT DEFAULT CURRENT_TIMESTAMP);
"""
CUENTAS = ["Pichincha", "Produbanco"]
# Bancos que NO mandan correo cuando le transfieren (revisado 19-11: Pichincha solo avisa lo que sale y los ingresos a la app)
SIN_AVISO_DE_ENTRADAS = {"Pichincha"}
SUELDO = re.compile(r"\b(?:sueldo|sueldos|salario|nomina|rol de pagos?|quincena)\b")


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn").strip()


def _palabras(t):
    return [w for w in re.findall(r"[a-zñ]+", _norm(t)) if len(w) >= 3 and w not in ("del", "las", "los", "cia", "ltda", "s.a")]


def nombres_cuentas():
    return list(gastos.ajustes().get("cuentas_bancarias") or CUENTAS)


def cuenta_de_banco(texto):
    """'BANCO PICHINCHA' / 'Produbanco' / 'DE UNA' → nombre de una de sus cuentas, o '' si es otro banco."""
    n = _norm(texto)
    for c in nombres_cuentas():
        if _norm(c) in n:
            return c
    return ""


def bonito(nombre):
    """'ANDREA ESTEFANIA CISNEROS GUALLICHICO' → 'Andrea Cisneros' (nombre + primer apellido)."""
    p = [w for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñü]+", nombre or "")]
    if not p:
        return (nombre or "").strip()
    if re.search(r"\b(?:cia|ltda|s\.?a\.?s?|corp|empresa|consultores|banco)\b", _norm(nombre)):
        return " ".join(w.capitalize() if len(w) > 3 else w.upper() for w in p[:3])
    elegido = [p[0], p[2]] if len(p) >= 4 else p[:2]
    return " ".join(w.capitalize() for w in elegido)


# ------------------------------------------------------------------ titular (se aprende del saludo) ---
SALUDOS = [r"Estimado/?a?:?\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ ]{6,60}?)\s+(?:Fecha|Te confirmamos|Reciba|Tu |$)",
           r"^(?:Banco Pichincha\s+)?([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ ]{6,60}?)\s+Tu (?:c[ée]dula|identificaci[oó]n|RUC) termina"]


def aprender_titular(plano):
    for patron in SALUDOS:
        m = re.search(patron, plano)
        if m:
            palabras = _palabras(m.group(1))
            if 2 <= len(palabras) <= 6:
                with closing(_con()) as con, con:
                    con.executemany("INSERT OR IGNORE INTO cuenta_titular (palabra) VALUES (?)", [(w,) for w in palabras])
                return palabras
    return []


def es_titular(nombre):
    with closing(_con()) as con:
        titular = {f["palabra"] for f in con.execute("SELECT palabra FROM cuenta_titular")}
    p = set(_palabras(nombre))
    comunes = len(p & titular)
    return bool(p) and comunes >= 2 and comunes >= min(3, len(p))


# ------------------------------------------------------------------ lectores (sin IA) ---
def _m(patron, plano, grupo=1):
    m = re.search(patron, plano, re.I)
    return m.group(grupo).strip() if m else ""


def _plata(t):
    t = re.sub(r"[^\d.,]", "", t or "")
    return dinero(t) if t else 0.0


def leer_produbanco(plano):
    n = _norm(plano)
    if "transaccion: transferencia enviada" in n:
        return {"clase": "transferencia", "sentido": "salida", "monto": _plata(_m(r"Monto:\s*\$?\s*([\d.,]+)", plano)),
                "contraparte": _m(r"Beneficiario:\s*(.+?)\s+Banco Beneficiario:", plano),
                "banco_otro": _m(r"Banco Beneficiario:\s*(.+?)\s+Cuenta Beneficiario", plano),
                "descripcion": _m(r"Descripci[oó]n:\s*(.+?)\s+(?:Canal|Referencia):", plano)}
    if "transaccion: transferencia recibida" in n:
        return {"clase": "transferencia", "sentido": "entrada", "monto": _plata(_m(r"Monto:\s*\$?\s*([\d.,]+)", plano)),
                "contraparte": _m(r"Enviada por:\s*(.+?)\s+Banco Origen:", plano),
                "banco_otro": _m(r"Banco Origen:\s*(.+?)\s+Beneficiario:", plano),
                "descripcion": _m(r"Descripci[oó]n:\s*(.+?)\s+Referencia:", plano)}
    if "pago de tarjeta recibido" in n:
        return {"ignorar": "confirmación del pago a la tarjeta (ya contado con el envío)"}
    if "pago de tarjeta enviada" in n:
        return {"clase": "pago_tarjeta", "sentido": "salida", "monto": _plata(_m(r"Monto:\s*\$?\s*([\d.,]+)", plano)),
                "banco_otro": _m(r"Banco Contacto:\s*(.+?)\s+Tarjeta Contacto", plano), "descripcion": "Pago de tarjeta",
                "comision": _plata(_m(r"tiene un costo de\s*\$?\s*([\d.,]+)", plano))}
    if "transaccion: pago tarjeta de credito" in n:
        return {"clase": "pago_tarjeta", "sentido": "salida",
                "monto": _plata(_m(r"por el monto de\s*(?:USD|\$)?\s*([\d.,]+)", plano)), "banco_otro": "Produbanco",
                "descripcion": "Pago de tarjeta " + _m(r"pago de la tarjeta\s+(.+?)\s+X{4,}", plano).title()}
    return None


def leer_pichincha(plano):
    n = _norm(plano)
    if "recibiste dinero del exterior" in n:
        total = re.findall(r"(\d[\d.,]*)\s*USD", plano.split("Total al receptor")[-1])
        return {"clase": "remesa", "sentido": "entrada", "monto": _plata(total[-1]) if total else 0.0,
                "contraparte": _m(r"exterior!?\s*(.+?)\s+El dinero se acredit", plano), "descripcion": "Remesa del exterior"}
    if "pago a terceros" in n and "acreditacion" in n:
        return {"clase": "pago_terceros", "sentido": "entrada",
                "monto": _plata(_m(r"por el valor de\s*(?:USD|\$)?\s*([\d.,]+)", plano)),
                "contraparte": _m(r"de la empresa\s+(.+?)\s+con la referencia", plano),
                "descripcion": _m(r"referencia:\s*(.+?)\s*\.(?:\s|$)", plano)}
    if "pago de servicios" in n and "empresa:" in n:
        valor = _plata(_m(r"Valor:\s*(?:USD|\$)?\s*([\d.,]+)", plano))
        comision = _plata(_m(r"Comisi[oó]n:\s*(?:USD|\$)?\s*([\d.,]+)", plano))
        total = _plata(_m(r"Valor total:\s*(?:USD|\$)?\s*([\d.,]+)", plano)) or round(valor + comision, 2)
        return {"clase": "pago_servicio", "sentido": "salida", "monto": total, "valor": valor, "comision": comision,
                "contraparte": _m(r"Empresa:\s*(.+?)\s+(?:Contrapartida|Valor):", plano), "descripcion": "Pago de servicio"}
    if "pago tarjeta de credito" in n or "pago de la tarjeta de credito" in n:
        return {"clase": "pago_tarjeta", "sentido": "salida", "monto": _plata(_m(r"Monto:\s*\$?\s*(?:USD\s*)?([\d.,]+)", plano)),
                "banco_otro": _m(r"Banco destino:\s*(.+?)\s+Tarjeta acreditada", plano) or "Pichincha",
                "descripcion": "Pago de tarjeta de crédito"}
    if "nombre del beneficiario" in n:
        return {"clase": "transferencia", "sentido": "salida", "monto": _plata(_m(r"Monto:\s*(?:USD|\$)?\s*([\d.,]+)", plano)),
                "contraparte": _m(r"Nombre del beneficiario:\s*(.+?)\s+(?:Identificaci|Monto|N[úu]mero)", plano),
                "banco_otro": _m(r"Banco destino:\s*(.+?)\s+Cuenta acreditada", plano)}
    if "realizaste una transferencia" in n or "transferencia exitosa" in n:
        nombre = _m(r"Cuenta destino\s+Nombre:\s*(?:N[úu]mero de cuenta:\s*)?(.+?)\s+\*{3,}", plano)
        return {"clase": "transferencia", "sentido": "salida",
                "monto": _plata(_m(r"Monto:\s*(?:Concepto\s+)?(?:USD|\$)?\s*([\d][\d.,]*)", plano)),
                "contraparte": nombre, "banco_otro": _m(r"Banco destino:\s*(.+?)\s+(?:Cuenta|Fecha)", plano) or "Pichincha"}
    return None


LECTORES = {"Produbanco": leer_produbanco, "Pichincha": leer_pichincha}


# ------------------------------------------------------------------ registrar movimientos ---
def _insertar(**c):
    with closing(_con()) as con, con:
        return con.execute("INSERT INTO cuenta_movs (" + ", ".join(c) + ") VALUES (" + ", ".join("?" * len(c)) + ")",
                           list(c.values())).lastrowid


def obtener(cid):
    with closing(_con()) as con:
        f = con.execute("SELECT * FROM cuenta_movs WHERE id = ?", (cid,)).fetchone()
    return dict(f) if f else None


def cambiar(cid, **campos):
    with closing(_con()) as con, con:
        con.execute("UPDATE cuenta_movs SET " + ", ".join(k + " = ?" for k in campos) + " WHERE id = ?", (*campos.values(), cid))


def _estimado_parecido(cuenta, sentido, monto, cuando):
    """Un movimiento estimado (de una transferencia entre sus cuentas) que ahora confirma un correo."""
    c = datetime.fromisoformat(cuando)
    with closing(_con()) as con:
        f = con.execute("SELECT * FROM cuenta_movs WHERE cuenta = ? AND sentido = ? AND estado = 'estimado' "
                        "AND abs(monto - ?) < 0.011 AND cuando >= ? AND cuando <= ? ORDER BY cuando LIMIT 1",
                        (cuenta, sentido, monto, (c - timedelta(days=4)).isoformat(), (c + timedelta(days=4)).isoformat())
                        ).fetchone()
    return dict(f) if f else None


def _aprendido(sentido, contraparte):
    with closing(_con()) as con:
        f = con.execute("SELECT * FROM cuenta_aprendidas WHERE clave = ?", (sentido + "|" + " ".join(_palabras(contraparte)),)
                        ).fetchone()
    return dict(f) if f else None


def aprender(sentido, contraparte, decision, categoria=""):
    if not contraparte:
        return
    with closing(_con()) as con, con:
        con.execute("INSERT OR REPLACE INTO cuenta_aprendidas (clave, decision, categoria) VALUES (?, ?, ?)",
                    (sentido + "|" + " ".join(_palabras(contraparte)), decision, categoria))


def deudas_de(contraparte, sentido_deuda):
    """Deudas abiertas cuya persona aparece en el nombre ('Meraki' ~ 'MERAKIPHARMA CIA LTDA', 'Andrea' ~ 'Andrea Cisneros')."""
    from modulos.finanzas import deudas
    pal = _palabras(contraparte)
    salida = []
    for d in deudas.abiertas(sentido=sentido_deuda):
        dp = [w for w in _palabras(d["persona"]) if w not in ("empresa", "tio", "tia", "mama", "papa")]
        if dp and all(any(w.startswith(x) or x.startswith(w) for w in pal if len(w) >= 4) for x in dp if len(x) >= 4):
            salida.append(d)
    return salida


def registrar(cuenta, datos, cuando, ref, nuevo=True):
    """Guarda un movimiento leído de un correo y decide qué es. Devuelve (id, evento) — evento para avisar o None."""
    sentido, monto, clase = datos["sentido"], datos["monto"], datos["clase"]
    contraparte = datos.get("contraparte", "")
    otra = cuenta_de_banco(datos.get("banco_otro", "")) if datos.get("banco_otro") else ""
    medio = "Cuenta " + cuenta
    dia = date.fromisoformat(cuando[:10])
    base = dict(cuenta=cuenta, cuando=cuando, sentido=sentido, monto=monto, clase=clase, contraparte=contraparte,
                banco_otro=datos.get("banco_otro", ""), descripcion=datos.get("descripcion", "")[:120], ref=ref)
    propia = clase in ("transferencia", "remesa", "pago_terceros") and contraparte and es_titular(contraparte)

    if propia and clase == "transferencia":                       # entre sus cuentas
        previo = _estimado_parecido(cuenta, sentido, monto, cuando)
        if previo:
            cambiar(previo["id"], estado="activo", ref=ref, cuando=cuando)
            return previo["id"], None
        if otra == cuenta:                                         # dentro del mismo banco: no cambia el saldo
            return _insertar(**{**base, "sentido": "neutro", "decision": "interna"}), None
        cid = _insertar(**base, decision="interna")
        if otra:
            _insertar(**{**base, "cuenta": otra, "sentido": "entrada" if sentido == "salida" else "salida",
                         "ref": "", "decision": "interna", "estado": "estimado"})
        return cid, ("interna", cid) if nuevo else None

    if clase == "pago_tarjeta":
        cid = _insertar(**base, decision="no_contar")
        com = _comision(datos, cuenta, cuando, ref, medio, dia, "Transferencia interbancaria")
        return cid, ("tarjeta", cid, com) if nuevo else None

    if clase == "pago_servicio":
        cid = _insertar(**base, decision="gasto")
        previo = _anotado_a_mano(datos["valor"], dia, "gasto")
        if previo:
            gastos.cambiar(previo["id"], ref=ref, medio=previo["medio"] or medio)
            mid = previo["id"]
        else:
            mid = gastos.anotar("gasto", datos["valor"], bonito(contraparte) or "Pago de servicio", None, medio, dia,
                                "correo", ref, usar_foto=False)
        cambiar(cid, mov=mid)
        com = _comision(datos, cuenta, cuando, ref, medio, dia, "pago de " + bonito(contraparte))
        return cid, ("servicio", cid, com) if nuevo else None

    # transferencias con otra persona, remesas, pagos a terceros
    if not nuevo:                                                  # importación inicial: solo para el saldo
        return _insertar(**base, decision="importado"), None
    if sentido == "entrada" and clase == "transferencia":          # alguien que paga SU diferido (modo simple: no es ingreso)
        try:
            from modulos.finanzas import tarjetas
            difs = tarjetas.diferidos_de_persona(contraparte)
        except Exception:
            difs = []
        if difs:
            d = min(difs, key=lambda x: abs(x["cuota"] - monto))
            cid = _insertar(**base, decision="reembolso")
            tarjetas.registrar_reembolso(d, monto, ref, dia)
            return cid, ("reembolso", cid, d["id"])
    if sentido == "entrada" and SUELDO.search(_norm(datos.get("descripcion", ""))) and not deudas_de(contraparte, "me_debe"):
        cid = _insertar(**base, decision="sueldo")
        cambiar(cid, mov=_ingreso(monto, "Sueldo", "Sueldo", medio, dia, ref))
        return cid, ("sueldo", cid)
    sabido = _aprendido(sentido, contraparte)
    if sabido and sabido["decision"] in ("gasto", "ingreso", "interna", "no_contar"):
        cid = _insertar(**base, decision="pendiente")
        aplicar(cid, sabido["decision"], sabido.get("categoria") or None, aprender_=False)
        return cid, ("aprendido", cid)
    cid = _insertar(**base, decision="pendiente")
    return cid, ("preguntar", cid)


def _comision(datos, cuenta, cuando, ref, medio, dia, motivo):
    if not datos.get("comision"):
        return None
    _insertar(cuenta=cuenta, cuando=cuando, sentido="salida" if datos["clase"] != "pago_servicio" else "neutro",
              monto=datos["comision"], clase="comision", decision="gasto", descripcion="Comisión " + motivo[:60],
              ref=ref + "#comision")
    return gastos.anotar("gasto", datos["comision"], "Comisión bancaria (" + motivo[:50] + ")", "Comisiones bancarias", medio,
                         dia, "correo", ref + "#comision", usar_foto=False)


def _anotado_a_mano(monto, dia, tipo, dias=1, categoria=None):
    with closing(gastos._con()) as con:
        filas = [dict(f) for f in con.execute(
            "SELECT * FROM movimientos WHERE estado = 'activo' AND tipo = ? AND ref = '' AND abs(monto - ?) < 0.011 "
            "AND fecha >= ? AND fecha <= ? ORDER BY id DESC", (tipo, monto, (dia - timedelta(days=dias)).isoformat(),
                                                              (dia + timedelta(days=dias)).isoformat()))]
    filas = [f for f in filas if not categoria or _norm(f["categoria"]) == _norm(categoria)]
    return filas[0] if filas else None


def _ingreso(monto, descripcion, categoria, medio, dia, ref):
    previo = _anotado_a_mano(monto, dia, "ingreso", dias=3, categoria=categoria if categoria == "Sueldo" else None)
    if previo:                                                     # ya lo había escrito «sueldo 700»
        gastos.cambiar(previo["id"], ref=ref, medio=previo["medio"] or medio)
        return previo["id"]
    return gastos.anotar("ingreso", monto, descripcion, categoria, medio, dia, "correo", ref, usar_foto=False)


def no_era_reembolso(cid):
    """«No era para el diferido»: se quita el pago del diferido y se vuelve a preguntar qué fue."""
    c = obtener(cid)
    if not c or c["decision"] != "reembolso":
        return None
    from modulos.finanzas import tarjetas
    tarjetas.deshacer_reembolso(c["ref"])
    cambiar(cid, decision="pendiente")
    return texto_evento(("preguntar", cid))


def aplicar(cid, decision, extra=None, aprender_=True):
    """Lo que el usuario eligió con los botones (o lo aprendido). Devuelve el texto de confirmación."""
    c = obtener(cid)
    if not c or c["decision"] not in ("pendiente", "importado"):
        return "Eso ya estaba respondido."
    medio, dia = "Cuenta " + c["cuenta"], date.fromisoformat(c["cuando"][:10])
    quien = bonito(c["contraparte"]) or "?"
    texto = ""
    if decision == "reembolso":                                    # extra = id de un diferido de esa persona
        from modulos.finanzas import tarjetas
        d = next((x for x in tarjetas.activos() if x["id"] == int(extra)), None)
        if not d or not tarjetas.dueno(d):
            return "Ese diferido ya no está."
        persona = tarjetas.dueno(d)["dueno"]
        tarjetas.aprender_alias(c["contraparte"], persona)
        tarjetas.registrar_reembolso(d, c["monto"], c["ref"], dia)
        cambiar(cid, decision="reembolso")
        return ("💳 Anotado: " + quien + " paga el diferido de " + persona + ". No es ingreso. Desde ahora reconozco sola sus "
                "transferencias." + linea_saldo(c["cuenta"]))
    if decision == "gasto" and extra:                              # extra = categoría
        mid = gastos.anotar("gasto", c["monto"], ("Transferencia a " + quien)[:120], extra, medio, dia, "correo", c["ref"],
                            usar_foto=False)
        cambiar(cid, decision="gasto", mov=mid)
        texto = "💸 Anotado como gasto: " + fmt(c["monto"]) + " en " + extra + " (transferencia a " + quien + ")."
    elif decision == "ingreso":
        cat = extra or gastos.tipo_ingreso(c["descripcion"] + " " + c["contraparte"])
        cat = "Ingreso" if cat == "Ingreso" else cat
        mid = _ingreso(c["monto"], ("Recibido de " + quien)[:120], cat if cat != "Ingreso" else None, medio, dia, c["ref"])
        cambiar(cid, decision="ingreso", mov=mid)
        extra = gastos.obtener(mid)["categoria"]
        texto = "💵 Anotado como ingreso: " + fmt(c["monto"]) + " de " + quien + " (" + extra + ")."
    elif decision == "sueldo":
        cambiar(cid, decision="sueldo", mov=_ingreso(c["monto"], "Sueldo", "Sueldo", medio, dia, c["ref"]))
        texto = "💼 Registré su sueldo de " + fmt(c["monto"]) + "."
    elif decision == "deuda":                                      # extra = id de la deuda
        from modulos.finanzas import deudas
        d = deudas.obtener(int(extra))
        if not d:
            return "Esa deuda ya no existe."
        nuevo, sobra = deudas.pagar(d["id"], c["monto"], "Transferencia " + c["cuenta"], dia)
        cambiar(cid, decision="deuda")
        if d["sentido"] == "me_debe":
            texto = "🤝 " + d["persona"] + " le pagó " + fmt(c["monto"]) + ". " + ("Queda debiendo " + fmt(nuevo) + "." if nuevo > 0
                                                                                   else "¡Deuda saldada!")
        else:
            texto = "🤝 Pagó " + fmt(c["monto"]) + " a " + d["persona"] + ". " + ("Le queda debiendo " + fmt(nuevo) + "."
                                                                                if nuevo > 0 else "¡Deuda saldada!")
        if sobra > 0:
            texto += " (Sobraron " + fmt(sobra) + " sobre lo que se debía.)"
        aprender_ = False
    elif decision == "prestamo":
        from modulos.finanzas import deudas
        did = deudas.crear(quien, c["monto"], "me_debe", "Préstamo por transferencia", fecha=dia)
        cambiar(cid, decision="prestamo")
        texto = "📝 Anoté que " + deudas.obtener(did)["persona"] + " le debe " + fmt(c["monto"]) + " (préstamo). /deudas"
        aprender_ = False
    elif decision == "interna":
        cambiar(cid, decision="interna")
        texto = "🔁 Anotado como movimiento entre sus cuentas (no es gasto ni ingreso)."
    elif decision == "no_contar":
        cambiar(cid, decision="no_contar")
        texto = "👌 No lo cuento como gasto ni ingreso; solo cambia el saldo de " + c["cuenta"] + "."
    else:
        return "No entendí esa opción."
    if aprender_ and decision in ("gasto", "ingreso", "interna", "no_contar"):
        aprender(c["sentido"], c["contraparte"], decision, extra if decision == "gasto" else "")
        texto += " La próxima vez con " + quien + " lo hago igual."
    return texto + linea_saldo(c["cuenta"])


# ------------------------------------------------------------------ Gmail ---
BUSQUEDA = ("(from:produbanco.com OR from:pichincha.com) (transferencia OR \"pago de tarjeta\" OR \"pago tarjeta\" OR "
            "\"pago de servicios\" OR \"pago a terceros\" OR \"dinero del exterior\" OR \"tarjetas de credito\" OR "
            "\"tarjeta de credito\")")


def _visto(ref):
    with closing(_con()) as con:
        return con.execute("SELECT 1 FROM cuenta_vistos WHERE ref = ?", (ref,)).fetchone() is not None


def _marcar(ref, tipo):
    with closing(_con()) as con, con:
        con.execute("INSERT OR IGNORE INTO cuenta_vistos (ref, tipo) VALUES (?, ?)", (ref, tipo))


def revisar(srv=None, dias=3, nuevo=True, max_correos=60):
    """Lee los correos de cuenta de los últimos 'dias'. Devuelve [(id_cuenta_mov, evento)] con evento != None."""
    from modulos.finanzas import correos
    srv = srv or correos.servicio()
    res = srv.users().messages().list(userId="me", q=BUSQUEDA + " newer_than:" + str(dias) + "d", maxResults=max_correos).execute()
    eventos = []
    for item in reversed(res.get("messages", [])):
        ref = "gmail:" + item["id"]
        if _visto(ref):
            continue
        try:
            ev = procesar_correo(srv, item["id"], ref, nuevo)
        except Exception as exc:
            log.warning("Cuentas: error con el correo %s: %s", item["id"], exc)
            _marcar(ref, "error")
            continue
        if ev:
            eventos.append(ev)
    return eventos


def procesar_correo(srv, mid, ref, nuevo=True):
    from modulos.finanzas import correos
    msg = srv.users().messages().get(userId="me", id=mid, format="full").execute()
    cab = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    banco = correos.banco_del_remitente(cab.get("from", ""))
    if banco not in LECTORES:                                      # remitente que no es exactamente del banco
        _marcar(ref, "remitente")
        return None
    try:
        cuando = parsedate_to_datetime(cab.get("date")).astimezone(ZONA).replace(tzinfo=None)
    except Exception:
        cuando = ahora().replace(tzinfo=None)
    return procesar_texto(banco, correos._cuerpo(msg["payload"]), cuando, ref, nuevo, parseaddr(cab.get("from", ""))[1])


def procesar_texto(banco, texto, cuando, ref, nuevo=True, remitente=""):
    """Separado de Gmail para poder probarlo. Devuelve (id, evento) o None."""
    if _visto(ref):                                                # el mismo correo nunca se cuenta dos veces
        return None
    plano = " ".join((texto or "").split())
    aprender_titular(plano)
    datos = LECTORES[banco](plano)
    if not datos or datos.get("ignorar"):
        _marcar(ref, "ignorado")
        return None
    if not datos.get("monto"):
        log.warning("Cuentas: no pude leer el monto de un correo de %s", banco)
        _marcar(ref, "ilegible")
        return (None, ("ilegible", banco)) if nuevo else None
    _marcar(ref, datos["clase"])
    cid, evento = registrar(banco, datos, cuando.isoformat(timespec="seconds"), ref, nuevo)
    return (cid, evento) if evento else None


# ------------------------------------------------------------------ saldo ---
def base(cuenta):
    with closing(_con()) as con:
        f = con.execute("SELECT * FROM cuentas WHERE nombre = ?", (cuenta,)).fetchone()
    return dict(f) if f and f["saldo_base"] is not None else None


def _aportes_ahorro(cuenta, desde, hasta):
    """Aportes a ahorros programados del mismo banco entre dos momentos (salen de la cuenta sin correo)."""
    try:
        from modulos.finanzas import ahorros
        lista = [a for a in ahorros.activos() if _norm(cuenta) in _norm(a.get("banco") or "") and a.get("dia_aporte")]
    except Exception:
        return 0.0, 0
    total, veces = 0.0, 0
    d = desde.date()
    while d <= hasta.date():
        for a in lista:
            ultimo = (date(d.year + d.month // 12, d.month % 12 + 1, 1) - timedelta(days=1)).day
            if d.day == min(a["dia_aporte"], ultimo) and datetime(d.year, d.month, d.day, 8, 0) > desde and \
                    datetime(d.year, d.month, d.day, 8, 0) <= hasta:
                total += ahorros.aporte_efectivo(a)
                veces += 1
        d += timedelta(days=1)
    return round(total, 2), veces


def saldo(cuenta, momento=None):
    """(saldo estimado, detalle) o (None, None) si nunca le dijo el saldo."""
    b = base(cuenta)
    if not b:
        return None, None
    hasta = momento or ahora().replace(tzinfo=None)
    with closing(_con()) as con:
        filas = [dict(f) for f in con.execute("SELECT * FROM cuenta_movs WHERE cuenta = ? AND estado IN ('activo', 'estimado') "
                                              "AND sentido != 'neutro' AND clase != 'ajuste' AND cuando > ? AND cuando <= ?",
                                              (cuenta, b["fecha_base"], hasta.isoformat()))]
    entra = sum(f["monto"] for f in filas if f["sentido"] == "entrada")
    sale = sum(f["monto"] for f in filas if f["sentido"] == "salida")
    ahorro, veces = _aportes_ahorro(cuenta, datetime.fromisoformat(b["fecha_base"]), hasta)
    total = round(b["saldo_base"] + entra - sale - ahorro, 2)
    return total, {"base": b["saldo_base"], "desde": b["fecha_base"], "entradas": round(entra, 2), "salidas": round(sale, 2),
                   "ahorros": ahorro, "movs": len(filas)}


def poner_saldo(cuenta, monto, momento=None):
    """El saldo real que dice el usuario. Devuelve (diferencia con el cálculo o None si no había cálculo)."""
    m = (momento or ahora().replace(tzinfo=None)).replace(microsecond=0)
    calculado, _ = saldo(cuenta, m)
    with closing(_con()) as con, con:
        con.execute("INSERT OR REPLACE INTO cuentas (nombre, saldo_base, fecha_base) VALUES (?, ?, ?)",
                    (cuenta, round(monto, 2), m.isoformat()))
    if calculado is None:
        return None
    dif = round(monto - calculado, 2)
    if abs(dif) >= 0.01:
        _insertar(cuenta=cuenta, cuando=m.isoformat(), sentido="entrada" if dif > 0 else "salida", monto=abs(dif),
                  clase="ajuste", decision="ajuste", descripcion="Ajuste: movimientos sin aviso")
    return dif


def linea_saldo(cuenta):
    s, _ = saldo(cuenta)
    return "" if s is None else "\n🏦 Saldo estimado " + cuenta + ": " + fmt(s)


def ajustes_recientes(cuenta, n=3):
    with closing(_con()) as con:
        return [dict(f) for f in con.execute("SELECT * FROM cuenta_movs WHERE cuenta = ? AND clase = 'ajuste' "
                                             "ORDER BY cuando DESC LIMIT ?", (cuenta, n))]


def texto_ajuste(cuenta, dif):
    if dif is None:
        return "✅ Saldo de " + cuenta + " guardado. Desde ahora lo voy sumando y restando con cada correo del banco."
    if abs(dif) < 0.01:
        return "✅ " + cuenta + ": mi cálculo estaba exacto."
    texto = ("✅ " + cuenta + " corregido. " + ("Había " + fmt(dif) + " más" if dif > 0 else "Salieron " + fmt(-dif))
             + " de lo que yo calculaba" + ("" if dif > 0 else " sin aviso del banco (efectivo, débitos automáticos o apps que no "
                                            "mandan correo)") + ".")
    previos = [a for a in ajustes_recientes(cuenta, 3)][1:]
    if previos and dif < 0 and previos[0]["sentido"] == "salida" and abs(previos[0]["monto"] - abs(dif)) <= max(3, 0.2 * abs(dif)):
        texto += (" Es parecido al ajuste anterior (" + fmt(previos[0]["monto"]) + "): puede ser un débito fijo cada mes. "
                  "Si sabe qué es, anótelo como gasto.")
    return texto


def estado():
    lineas = ["🏦 Sus cuentas"]
    for c in nombres_cuentas():
        s, d = saldo(c)
        if s is None:
            lineas.append("• " + c + ": sin saldo inicial. Dígame «saldo " + c.lower() + " 850».")
            continue
        desde = datetime.fromisoformat(d["desde"])
        dias = (ahora().replace(tzinfo=None) - desde).days
        lineas.append("• " + c + ": " + fmt(s) + " (estimado; corregido hace " + (str(dias) + " días" if dias else "hoy") + ")")
        if s < -0.5:
            lineas.append("   ⚠️ Negativo: le entró dinero sin aviso" + (" (el " + c + " no avisa las transferencias "
                          "recibidas)" if c in SIN_AVISO_DE_ENTRADAS else "") + ". Dígame «saldo " + c.lower() + " 320».")
        extra = []
        if d["entradas"]:
            extra.append("+" + fmt(d["entradas"]))
        if d["salidas"]:
            extra.append("−" + fmt(d["salidas"]))
        if d["ahorros"]:
            extra.append("−" + fmt(d["ahorros"]) + " ahorros programados")
        if extra:
            lineas.append("   desde entonces: " + " · ".join(extra))
    pend = pendientes()
    if pend:
        lineas.append("\n⏳ Movimientos sin responder: " + str(len(pend)) + " (toque los botones de cada aviso).")
    lineas.append("\nPara corregir: «saldo pichincha 405, produbanco 236».")
    return "\n".join(lineas)


def revisar_negativos(hoy=None):
    """Un saldo estimado negativo casi siempre significa dinero que entró sin aviso (el Pichincha no avisa las
    transferencias recibidas). Pregunta el saldo real una vez al día por cuenta y deja abierta la respuesta."""
    hoy = (hoy or ahora()).date().isoformat()
    textos = []
    for c in nombres_cuentas():
        s, _ = saldo(c)
        if s is None or s > -0.5:
            continue
        clave = hoy + "|cuenta_negativa|" + c
        if db.aviso_enviado(clave):
            continue
        db.marcar_aviso(clave)
        ESPERA["faltan"] = sorted(set(ESPERA["faltan"] if esperando() else []) | {c})
        ESPERA["desde"] = ESPERA["desde"] if esperando() else ahora()
        motivo = ("el " + c + " no manda correo cuando le transfieren, así que esas entradas no las veo"
                  if c in SIN_AVISO_DE_ENTRADAS else "entró dinero del que no llegó correo")
        textos.append("🏦 Su saldo estimado del " + c + " da " + fmt(s) + ": seguro le entraron transferencias que no "
                      "pude contar (" + motivo + ").\n¿Cuánto tiene ahora en el " + c + "? Respóndame solo el número "
                      "(por ejemplo «320») y lo corrijo.")
    return textos


def pendientes():
    with closing(_con()) as con:
        return [dict(f) for f in con.execute("SELECT * FROM cuenta_movs WHERE decision = 'pendiente' AND estado = 'activo' "
                                             "ORDER BY cuando")]


def recientes(n=8):
    with closing(_con()) as con:
        return [dict(f) for f in con.execute("SELECT * FROM cuenta_movs WHERE estado IN ('activo', 'estimado') AND clase != 'ajuste' "
                                             "ORDER BY cuando DESC LIMIT ?", (n,))]


# ------------------------------------------------------------------ frases ---
P_VER = re.compile(r"^\W*(?:/saldo|mi saldo|mis saldos|saldo de mis cuentas|mis cuentas(?: del banco)?|"
                   r"cu[aá]nto (?:dinero |plata )?tengo(?: en (?:el banco|mis cuentas|la cuenta|pichincha|produbanco))?|"
                   r"cu[aá]nto hay en (?:mis cuentas|el banco|pichincha|produbanco))\W*$", re.I)
P_OK = re.compile(r"^\W*(?:ok|okay|si|s[ií]|est[aá] bien|correcto|exacto|as[ií] es|cuadra|bien)\W*$", re.I)
_NUM = r"\$?\s*(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
ESPERA = {"desde": None, "faltan": []}                             # pregunta del saldo abierta (hasta 24 h)


def _alias():
    salida = []
    for c in nombres_cuentas():
        salida.append((c, _norm(c)))
        if _norm(c) == "produbanco":
            salida.append((c, "produ"))
    return salida


def esperando():
    return bool(ESPERA["desde"]) and ahora() - ESPERA["desde"] < timedelta(hours=24)


def interpretar(texto):
    """{'accion': 'ver'} | {'accion': 'poner', 'saldos': {cuenta: monto}} | {'accion': 'confirmar'} | None."""
    t = " ".join((texto or "").split())
    n = _norm(t)
    if P_VER.match(t):
        return {"accion": "ver"}
    if esperando() and P_OK.match(t):
        return {"accion": "confirmar"}
    if re.search(r"ahorro|tarjeta|platinum|gold|diners|gast|pagu|consum|compr|deb[oe]|prest", n):
        return None
    posiciones = sorted((m.start(), c) for c, a in _alias() for m in re.finditer(r"\b" + re.escape(a) + r"\w*", n))
    if esperando() and not posiciones and len(ESPERA["faltan"]) == 1:      # «236» cuando solo falta una cuenta
        m = re.fullmatch(r"\W*(?:son|tengo|hay)?\s*" + _NUM + r"\s*(?:d[oó]lares|usd)?\W*", n)
        if m:
            return {"accion": "poner", "saldos": {ESPERA["faltan"][0]: dinero(m.group(1))}}
    sin_base = {c for c in nombres_cuentas() if base(c) is None}
    contexto = (esperando() or re.search(r"\bsaldo\b|\btengo\b|\bme quedan?\b", n)
                or (posiciones and {c for _, c in posiciones} <= sin_base and re.fullmatch(r"[\w\s$.,:=]+", n)))
    if not contexto or not posiciones:
        return None
    nums = [(m.start(), dinero(m.group(1))) for m in re.finditer(_NUM, n)]
    saldos, usados = {}, set()
    for i, (pos, cuenta) in enumerate(posiciones):
        fin = posiciones[i + 1][0] if i + 1 < len(posiciones) else len(n)
        despues = [x for x in nums if pos < x[0] < min(fin, pos + len(cuenta) + 22) and x[0] not in usados]
        antes = [x for x in nums if pos - 22 < x[0] < pos and x[0] not in usados and (i == 0 or x[0] > posiciones[i - 1][0])
                 and re.search(r"\ben\s+(?:el\s+|mi\s+)?(?:banco\s+)?(?:cuenta\s+(?:de\s+)?)?$", n[:pos])]
        elegido = despues[0] if despues else (antes[-1] if antes else None)
        if elegido and cuenta not in saldos:
            saldos[cuenta] = elegido[1]
            usados.add(elegido[0])
    return {"accion": "poner", "saldos": saldos} if saldos else None


def ejecutar(d):
    if d["accion"] == "ver":
        return estado()
    if d["accion"] == "confirmar":
        ESPERA.update(desde=None, faltan=[])
        textos = []
        for c in nombres_cuentas():
            s, _ = saldo(c)
            if s is not None:
                poner_saldo(c, s)
                textos.append("✅ " + c + ": " + fmt(s) + " confirmado.")
        return "\n".join(textos) or "Todavía no tengo saldos. Dígame «saldo pichincha 405, produbanco 236»."
    textos = [texto_ajuste(c, poner_saldo(c, m)) + " Saldo: " + fmt(m) + "." for c, m in d["saldos"].items()]
    pendientes_ronda = [c for c in ESPERA["faltan"] if c not in d["saldos"]] if esperando() else []
    faltan = sorted(set(pendientes_ronda) | {c for c in nombres_cuentas() if base(c) is None})
    ESPERA["faltan"] = faltan
    if faltan:
        ESPERA["desde"] = ESPERA["desde"] or ahora()
        textos.append("Ahora dígame el de " + " y ".join(faltan) + " (por ejemplo «" + faltan[0].lower() + " 236»).")
    else:
        ESPERA["desde"] = None
    return "\n".join(textos)


def procesar(texto):
    d = interpretar(texto)
    return ejecutar(d) if d else None


# ------------------------------------------------------------------ textos para avisar ---
def _cuando(c):
    f = datetime.fromisoformat(c["cuando"])
    return f.strftime("%d/%m %H:%M")


def texto_evento(ev):
    """(texto, botones crudos o None) para un evento de registrar()."""
    tipo, cid = ev[0], ev[1]
    if tipo == "ilegible":
        return ("⚠️ Llegó un correo de cuenta de " + str(cid) + " que no pude leer. Si es una transferencia, anótela a mano "
                "y avise a Claude (quizá el banco cambió el formato).", None)
    c = obtener(cid)
    quien = bonito(c["contraparte"])
    if tipo == "interna":
        otra = cuenta_de_banco(c["banco_otro"]) or c["banco_otro"] or "otra cuenta suya"
        origen, destino = (c["cuenta"], otra) if c["sentido"] == "salida" else (otra, c["cuenta"])
        texto = "🔁 Pasó " + fmt(c["monto"]) + " de " + origen + " a " + destino + " (entre sus cuentas, no es gasto)."
        texto += linea_saldo(c["cuenta"])
        if cuenta_de_banco(c["banco_otro"]) not in ("", c["cuenta"]):
            texto += linea_saldo(cuenta_de_banco(c["banco_otro"]))
        return texto, None
    if tipo == "tarjeta":
        com = ev[2] if len(ev) > 2 else None
        return ("💳 Pagó " + fmt(c["monto"]) + " de tarjeta desde " + c["cuenta"] + ". No es gasto nuevo (los consumos ya están "
                "contados)." + ("\n🏦 El banco cobró " + fmt(gastos.obtener(com)["monto"]) + " de comisión: esa sí es gasto."
                                if com else "") + linea_saldo(c["cuenta"]), None)
    if tipo == "servicio":
        g = gastos.obtener(c["mov"])
        com = ev[2] if len(ev) > 2 else None
        return ("🧾 Pagó " + fmt(g["monto"]) + " de " + g["descripcion"] + " desde " + c["cuenta"] + " → " + g["categoria"]
                + (" (+" + fmt(gastos.obtener(com)["monto"]) + " de comisión)" if com else "") + "." + linea_saldo(c["cuenta"]),
                [[{"text": "🏷 Cambiar categoría", "callback_data": "gas:cat:" + str(g["id"])},
                  {"text": "↩️ Deshacer", "callback_data": "gas:del:" + str(g["id"])}]])
    if tipo == "reembolso":
        from modulos.finanzas import tarjetas
        d = next((x for x in tarjetas.activos() if x["id"] == ev[2]), None)
        texto = ("💳 " + quien + " le transfirió " + fmt(c["monto"]) + " (paga su diferido " + (d["descripcion"] if d else "") + "). "
                 "No es ingreso: solo sube el saldo de " + c["cuenta"] + ", y baja igual cuando usted pague la tarjeta.")
        return (texto + linea_saldo(c["cuenta"]),
                [[{"text": "↩️ No era para el diferido", "callback_data": "cta:noreemb:" + str(cid)}]])
    if tipo == "sueldo":
        return ("💼 Llegó su sueldo: " + fmt(c["monto"]) + " de " + quien + " (" + c["cuenta"] + ")." + linea_saldo(c["cuenta"]), None)
    if tipo == "aprendido":
        c = obtener(cid)
        return ("✅ " + ("Transferencia a " if c["sentido"] == "salida" else "Recibió de ") + quien + " " + fmt(c["monto"])
                + ": como la vez anterior, " + {"gasto": "gasto", "ingreso": "ingreso", "interna": "entre sus cuentas",
                                                 "no_contar": "no lo cuento"}.get(c["decision"], c["decision"]) + "."
                + linea_saldo(c["cuenta"]), None)
    # preguntar
    if c["sentido"] == "salida":
        texto = "💸 Transfirió " + fmt(c["monto"]) + " a " + quien + " desde " + c["cuenta"] + " (" + _cuando(c) + "). ¿Qué fue?"
        filas = [[{"text": "🛒 Gasto", "callback_data": "cta:gasto:" + str(cid)},
                  {"text": "💰 Le presté", "callback_data": "cta:prestamo:" + str(cid)}]]
        for d in deudas_de(c["contraparte"], "le_debo")[:2]:
            filas.insert(0, [{"text": "🤝 Pago de mi deuda con " + d["persona"], "callback_data": "cta:deuda:" + str(cid) + ":" + str(d["id"])}])
    else:
        origen = {"remesa": "una remesa del exterior", "pago_terceros": "un pago de empresa"}.get(c["clase"], "una transferencia")
        texto = ("💵 Recibió " + fmt(c["monto"]) + " de " + quien + " en " + c["cuenta"] + " (" + origen + ", " + _cuando(c) + ")"
                 + (" — «" + c["descripcion"] + "»" if c["descripcion"] and c["clase"] != "remesa" else "") + ". ¿Qué fue?")
        filas = [[{"text": "💵 Ingreso", "callback_data": "cta:ingreso:" + str(cid)}]]
        if SUELDO.search(_norm(c["descripcion"])):
            filas.insert(0, [{"text": "💼 Sueldo de este mes", "callback_data": "cta:sueldo:" + str(cid)}])
        for d in deudas_de(c["contraparte"], "me_debe")[:2]:
            filas.insert(0, [{"text": "🤝 Pago de lo que me debe " + d["persona"], "callback_data": "cta:deuda:" + str(cid) + ":" + str(d["id"])}])
        try:                                                       # ¿es alguien que paga un diferido suyo? (se aprende con 1 toque)
            from modulos.finanzas import tarjetas
            for persona, difs in list(tarjetas.duenos_activos().items())[:3]:
                filas.insert(0, [{"text": "💳 Paga el diferido de " + persona, "callback_data": "cta:reembolso:" + str(cid) + ":"
                                  + str(difs[0]["id"])}])
        except Exception:
            pass
    filas.append([{"text": "🔁 Entre mis cuentas", "callback_data": "cta:interna:" + str(cid)},
                  {"text": "🚫 No contar", "callback_data": "cta:no_contar:" + str(cid)}])
    return texto + linea_saldo(c["cuenta"]), filas


def botones_categoria(cid):
    cats = gastos.categorias()
    b = [{"text": x, "callback_data": "cta:cat:" + str(cid) + ":" + str(i)} for i, x in enumerate(cats)]
    return [b[j:j + 2] for j in range(0, len(b), 2)]


def pregunta_saldo():
    """Texto de la pregunta del día 1 (o de la primera vez) y deja abierta la espera de respuesta."""
    ESPERA.update(desde=ahora(), faltan=list(nombres_cuentas()))
    partes, falta = [], []
    for c in nombres_cuentas():
        s, _ = saldo(c)
        (partes if s is not None else falta).append(c + " " + fmt(s) if s is not None else c)
    if partes:
        return ("💰 Revisión del mes: ¿cuánto tiene hoy en sus cuentas? Mi cálculo: " + " · ".join(partes)
                + (" (y no sé " + ", ".join(falta) + ")" if falta else "")
                + ".\nRespóndame «pichincha 405, produbanco 236», o «ok» si está bien.")
    return ("💰 Para llevar el saldo de sus cuentas necesito saber cuánto tiene HOY en cada una (míralo en la app del banco).\n"
            "Respóndame así: «pichincha 405, produbanco 236». Desde ahí lo sumo y resto solo con los correos del banco.")


def sueldo_llego(hoy=None):
    """¿Ya llegó el sueldo este mes por transferencia o anotado? (para no preguntar)."""
    hoy = hoy or ahora().date()
    a, b = gastos.mes(hoy.year, hoy.month)
    return any(_norm(m["categoria"]) == "sueldo" for m in gastos.del_periodo(a, b, "ingreso"))
