"""Finanzas, paso 3: consumos con tarjeta leidos de Gmail (SOLO LECTURA) -> gastos automaticos.

Bancos: Diners Club, Banco Pichincha (Platinum) y Produbanco (Gold). Cada uno tiene su lector fijo (regex):
la IA NO lee los correos ni sigue nada de lo que digan. Solo se aceptan correos cuyo remitente es del banco.

- Permiso de Google: gmail.readonly (no puede enviar, borrar ni modificar). Token en credenciales/token_gmail.json,
  creado con:  .\\.venv\\Scripts\\python.exe modulos\\finanzas\\conectar_gmail.py
- No duplica: cada correo se guarda con su id (movimientos.ref). Si el usuario ya lo anoto a mano (mismo monto,
  mismo dia o el siguiente), se une a ese registro y solo se le agrega la tarjeta.
- Avances de efectivo: no se anotan solos (se pregunta), para no contar dos veces.
"""
import base64
import re
import unicodedata
from contextlib import closing
from datetime import date, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape

from modulos.comun import db
from modulos.comun.base import RAIZ, ZONA, ahora, registro
from modulos.finanzas import gastos
from modulos.finanzas.deudas import dinero, fmt

log = registro("finanzas")
TOKEN = RAIZ / "credenciales" / "token_gmail.json"
SECRETO = RAIZ / "credenciales" / "client_secret.json"
PERMISOS = ["https://www.googleapis.com/auth/gmail.readonly"]
BUSQUEDA = ('("Realizaste una compra con tu Diners" OR "Has realizado un consumo" OR '
            '"Consumo Tarjeta de Crédito Produbanco" OR "consumo con tu Tarjeta de Crédito" OR '
            '"reverso de un consumo" OR "Reverso Consumo" OR "anulación de consumo" OR "anulación de compra" OR '
            '"devolución de consumo" OR "devolución de compra" OR "reembolso de consumo")')
REVERSO = re.compile(r"\b(?:reverso|reversion|reversado|anulacion|anulado|anulada|devolucion|reembolso|extorno)\b")
MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
MEDIOS = {"Diners": "Diners", "Pichincha": "Pichincha Platinum", "Produbanco": "Produbanco Gold"}


class SinPermiso(Exception):
    pass


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


def texto_de_html(html):
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", html or "")
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|td|th|li|h\d|table)>", "\n", t)
    t = unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    lineas = [" ".join(l.split()) for l in t.splitlines()]
    return "\n".join(l for l in lineas if l)


# ------------------------------------------------------------------ lectores por banco ---
def _monto(t):
    return dinero(re.sub(r"[A-Za-z$]", "", t).strip())


def _moneda(t):
    m = re.search(r"\b(USD|EUR|COP|PEN|MXN|GBP|BRL|CLP|ARS|CAD|JPY)\b", t or "", re.I)
    return m.group(1).upper() if m else "USD"


_tasas = {}


def a_usd(monto, moneda, dia):
    """Convierte a dolares con el cierre de ese dia (Yahoo Finance). Devuelve (monto_usd, tasa) o (None, None)."""
    if moneda == "USD":
        return monto, 1.0
    clave = (moneda, dia.isoformat())
    if clave not in _tasas:
        try:
            import warnings
            import yfinance as yf
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tabla = yf.download(moneda + "USD=X", start=(dia - timedelta(days=6)).isoformat(),
                                    end=(dia + timedelta(days=1)).isoformat(), progress=False, auto_adjust=False)
            serie = tabla["Close"].squeeze().dropna()
            _tasas[clave] = float(serie.iloc[-1]) if len(serie) else None
        except Exception as exc:
            log.info("Sin tasa %s: %s", moneda, exc)
            _tasas[clave] = None
    tasa = _tasas[clave]
    return (round(monto * tasa, 2), tasa) if tasa else (None, None)


def _armar(anio, mes, dia, h=0, mi=0):
    """datetime valido o None. Si dia/mes no cuadran, prueba invertidos (formato mes/dia)."""
    for a, m, d in ((anio, mes, dia), (anio, dia, mes)):
        try:
            return datetime(int(a), int(m), int(d), int(h or 0), int(mi or 0))
        except ValueError:
            continue
    return None


def _fecha_iso(t):
    t = t or ""
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T]+(\d{1,2}):(\d{2}))?", t)
    if m:
        f = _armar(m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
        if f:
            return f
    m = re.search(r"(\d{1,2})[/ -]+(?:de\s+)?([A-Za-z\u00c0-\u00ff]+)[/ -]+(?:de(?:l)?\s+)?(\d{4})(?:\D+(\d{1,2}):(\d{2}))?", t)
    if m and _norm(m.group(2)) in MESES:
        f = _armar(m.group(3), MESES[_norm(m.group(2))], m.group(1), m.group(4), m.group(5))
        if f:
            return f
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})(?:\D+(\d{1,2}):(\d{2}))?", t)
    if m:
        anio = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
        f = _armar(anio, m.group(2), m.group(1), m.group(4), m.group(5))
        if f:
            return f
    return None


def leer_diners(texto):
    if "diners" not in _norm(texto) or "realizaste una compra" not in _norm(texto):
        return None
    plano = " ".join(texto.split())
    m = re.search(r"Fecha\s+(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})\s+Establecimiento\s+(.+?)\s+Valor\s+([\d.,]+)", plano, re.I)
    if not m:                                   # encabezados en una fila y valores en la siguiente
        m = re.search(r"Fecha\s+Establecimiento\s+Valor\s+(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})\s+(.+?)\s+([\d.,]+)(?:\s|$)", plano, re.I)
    if not m:
        return None
    return {"banco": "Diners", "fecha": _fecha_iso(m.group(1)), "comercio": m.group(2), "monto": _monto(m.group(3))}


def leer_pichincha(texto):
    n = _norm(texto)
    if "realizado un consumo" not in n:
        return None
    plano = " ".join(texto.split())
    valor = re.search(r"Valor\s+((?:[A-Z]{3}|\$)?\s*[\d.,]+)", plano, re.I)
    comercio = re.search(r"Establecimiento\s+(.+?)\s+(?:Tarjeta usada|Fecha)\b", plano, re.I)
    fecha = re.search(r"Fecha\s+(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})", plano, re.I)
    if not (valor and comercio):
        return None
    return {"banco": "Pichincha", "fecha": _fecha_iso(fecha.group(1)) if fecha else None,
            "comercio": comercio.group(1), "monto": _monto(valor.group(1)), "moneda": _moneda(valor.group(1))}


def leer_produbanco(texto):
    n = _norm(texto)
    if "produbanco" not in n or "consumo" not in n:
        return None
    plano = " ".join(texto.split())
    valor = re.search(r"Valor:\s*((?:[A-Z]{3}|\$)?\s*[\d.,]+)", plano, re.I)
    comercio = re.search(r"Establecimiento:\s*(.+?)(?:\s+Atentamente|\s+Fecha|\s+Valor:|\s+Esta transacci|\s+Si no realizaste|"
                         r"\s+Por favor|$)", plano, re.I)
    fecha = re.search(r"Fecha y Hora:\s*([^\s]+(?:\s+\d{1,2}:\d{2})?)", plano, re.I)
    if not (valor and comercio):
        return None
    cargo = re.search(r"cargo por el valor de\s*\$?\s*([\d.,]+)\s*(?:por concepto de\s+(.+?))?(?:\s+Si no realizaste|\.|$)",
                      plano, re.I)
    return {"banco": "Produbanco", "fecha": _fecha_iso(fecha.group(1)) if fecha else None,
            "comercio": comercio.group(1), "monto": _monto(valor.group(1)), "moneda": _moneda(valor.group(1)),
            "cargo": _monto(cargo.group(1)) if cargo else None,
            "cargo_motivo": (cargo.group(2) or "cargo del banco").strip() if cargo else ""}


def leer_generico(texto):
    """Para reversos de bancos cuyo formato aún no conocemos: 'Valor' y 'Establecimiento'/'Comercio'."""
    plano = " ".join(texto.split())
    valor = re.search(r"(?:Valor|Monto|Importe)\s*:?\s*((?:[A-Z]{3}|\$)?\s*[\d.,]+)", plano, re.I)
    comercio = re.search(r"(?:Establecimiento|Comercio)\s*:?\s*(.+?)(?:\s+(?:Atentamente|Fecha|Valor|Monto|Tarjeta)\b|$)", plano, re.I)
    fecha = re.search(r"Fecha(?:\s+y\s+Hora)?\s*:?\s*([^\s]+(?:\s+\d{1,2}:\d{2})?)", plano, re.I)
    if not (valor and comercio):
        return None
    return {"fecha": _fecha_iso(fecha.group(1)) if fecha else None, "comercio": comercio.group(1),
            "monto": _monto(valor.group(1)), "moneda": _moneda(valor.group(1))}


LECTORES = {"Diners": leer_diners, "Pichincha": leer_pichincha, "Produbanco": leer_produbanco}


def es_reverso(asunto, texto):
    """¿Es un correo de reverso, anulación o devolución de un consumo (no un consumo nuevo)?"""
    cabeza = _norm(asunto) + " " + _norm(" ".join((texto or "").split())[:600])
    return bool(REVERSO.search(cabeza)) and not re.search(r"estado de cuenta", _norm(asunto))


def fecha_confiable(leida, fecha_correo):
    """La fecha del texto puede venir como mes/día (Produbanco: '11/04/2026' = 4 de noviembre).
    Si no cuadra con el día en que llegó el correo (±2 días), se prueba al revés y si no, la del correo."""
    if leida:
        if abs((leida.date() - fecha_correo.date()).days) <= 2:
            return leida
        try:
            invertida = leida.replace(month=leida.day, day=leida.month)
            if abs((invertida.date() - fecha_correo.date()).days) <= 2:
                return invertida
        except ValueError:
            pass
    return fecha_correo


def limpiar_comercio(c):
    c = re.sub(r"\s+", " ", c or "").strip(" .-*")
    c = re.sub(r"^(?:https?\s+|www\s+)", "", c, flags=re.I)                 # "HTTPS TIENDA EJEMPLO"
    palabras = []
    for w in c.split():
        palabras.append(w if (re.search(r"\d", w) or len(w) <= 3 and w.isupper() and w not in ("EL", "LA", "DE", "DEL", "LOS"))
                        else w.capitalize())
    return " ".join(palabras)[:60] or "Consumo con tarjeta"


INVERSION_PREDETERMINADA = ["xtb", "interactive brokers", "ibkr", "etoro", "hapi", "trading 212", "trading212", "degiro",
                            "plus500", "admiral markets", "admirals", "naga", "binance", "tastytrade", "webull"]


def es_inversion(comercio):
    """Depósito a un bróker (XTB…): es dinero del usuario que pasa a invertirse, NO un gasto.
    Lista editable en config/finanzas.json -> comercios_inversion."""
    lista = gastos.ajustes().get("comercios_inversion") or INVERSION_PREDETERMINADA
    n = " " + re.sub(r"[^a-z0-9]+", " ", _norm(comercio)) + " "
    return any(" " + re.sub(r"[^a-z0-9]+", " ", _norm(x)).strip() + " " in n for x in lista)


def anotar_cargo(datos, comercio, medio, fecha, ref):
    """Cargo extra del banco (p. ej. 1,96 por consumo en el exterior > 100 USD): gasto aparte."""
    if not datos.get("cargo"):
        return None
    with closing(gastos._con()) as con:
        if con.execute("SELECT 1 FROM movimientos WHERE ref = ?", (ref + "#cargo",)).fetchone():
            return None
    motivo = datos.get("cargo_motivo") or "cargo del banco"
    motivo = "consumo en el exterior" if "exterior" in _norm(motivo) else motivo[:40]
    return gastos.anotar("gasto", datos["cargo"], "Cargo banco por " + motivo + " (" + comercio.split(" (")[0] + ")",
                         "Comisiones bancarias", medio, fecha, "correo", ref + "#cargo", usar_foto=False)


def es_avance(comercio):
    return bool(re.search(r"avance de efectivo|retiro|cajero|cash advance", _norm(comercio)))


# ------------------------------------------------------------------ Gmail (solo lectura) ---
def servicio(interactivo=False):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    cred = Credentials.from_authorized_user_file(str(TOKEN), PERMISOS) if TOKEN.exists() else None
    if cred and cred.expired and cred.refresh_token:
        try:
            cred.refresh(Request())
            TOKEN.write_text(cred.to_json(), encoding="utf-8")
        except RefreshError:
            cred = None
    if not cred or not cred.valid:
        if not interactivo:
            raise SinPermiso("Gmail pide volver a autorizar")
        from google_auth_oauthlib.flow import InstalledAppFlow
        cred = InstalledAppFlow.from_client_secrets_file(str(SECRETO), PERMISOS).run_local_server(port=0)
        TOKEN.write_text(cred.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=cred, cache_discovery=False)


def _cuerpo(payload):
    """Texto del correo (prefiere HTML convertido a texto)."""
    partes, html, plano = [payload], "", ""
    while partes:
        p = partes.pop()
        partes += p.get("parts", []) or []
        datos = (p.get("body") or {}).get("data")
        if not datos:
            continue
        contenido = base64.urlsafe_b64decode(datos + "=" * (-len(datos) % 4)).decode("utf-8", "replace")
        if p.get("mimeType") == "text/html":
            html += contenido
        elif p.get("mimeType") == "text/plain":
            plano += contenido
    return texto_de_html(html) if html else plano


def banco_del_remitente(remitente):
    """Solo dominios EXACTOS de cada banco (o sus subdominios): 'estafa-pichincha.xyz' no pasa.
    La lista esta en config/finanzas.json -> remitentes_bancos (si un banco cambia de dominio, se agrega ahi)."""
    dominio = parseaddr(remitente)[1].split("@")[-1].lower().strip()
    lista = gastos.ajustes().get("remitentes_bancos") or {"Diners": ["dinersclub.com.ec"], "Pichincha": ["pichincha.com"],
                                                          "Produbanco": ["produbanco.com"]}
    for banco, dominios in lista.items():
        if any(dominio == d or dominio.endswith("." + d) for d in dominios):
            return banco
    return None


VERSION = 2                                       # subir al mejorar un lector: reintenta los ilegibles
ULTIMA = {"encontrados": 0, "vistos": 0}      # para informar en /correos
IGNORADOS = []          # remitentes con texto de banco pero dominio desconocido (para /correos)


def _ya_procesado(ref):
    with closing(gastos._con()) as con:
        return con.execute("SELECT 1 FROM movimientos WHERE ref = ?", (ref,)).fetchone() is not None or \
            con.execute("SELECT 1 FROM gastos_pendientes WHERE descripcion LIKE ?", ("%[" + ref + "]",)).fetchone() is not None


def _anotado_a_mano(monto, dia):
    """Gasto escrito por el usuario (sin correo) con el mismo monto ese dia o el anterior/siguiente."""
    with closing(gastos._con()) as con:
        f = con.execute("SELECT * FROM movimientos WHERE estado = 'activo' AND tipo = 'gasto' AND ref = '' AND origen != 'correo' "
                        "AND abs(monto - ?) < 0.011 AND fecha >= ? AND fecha <= ? ORDER BY id DESC LIMIT 1",
                        (monto, (dia - timedelta(days=1)).isoformat(), (dia + timedelta(days=1)).isoformat())).fetchone()
    return dict(f) if f else None


def revisar(dias=3, max_correos=40):
    """Lee los correos de consumo de los ultimos 'dias'. Devuelve lista de eventos:
    ('nuevo', id_movimiento) | ('unido', id_movimiento) | ('avance', id_pendiente) | ('ilegible', asunto)."""
    srv = servicio()
    reintentar_ilegibles()
    res = srv.users().messages().list(userId="me", q=BUSQUEDA + " newer_than:" + str(dias) + "d",
                                      maxResults=max_correos).execute()
    eventos = []
    ULTIMA.update(encontrados=len(res.get("messages", [])), vistos=0)
    for item in reversed(res.get("messages", [])):                         # del mas viejo al mas nuevo
        ref = "gmail:" + item["id"]
        if _ya_procesado(ref):
            ULTIMA["vistos"] += 1
            continue
        try:
            evento = _procesar_uno(srv, item, ref)
        except Exception as exc:                                           # un correo raro no detiene a los demas
            log.warning("Error con el correo %s: %s", item["id"], exc)
            _marcar_ilegible(ref)
            evento = ("ilegible", "error al leerlo: " + str(exc)[:60])
        if evento:
            eventos.append(evento)
    log.info("Correos de consumo revisados: %d encontrados, %d eventos", ULTIMA["encontrados"], len(eventos))
    return eventos


def reintentar_ilegibles():
    """Cuando mejora un lector (VERSION), los correos que antes no se pudieron leer se vuelven a intentar
    y se repite la importacion de 45 dias (sin duplicar: cada correo ya procesado se salta)."""
    clave = "correos|lectores_v" + str(VERSION)
    if db.aviso_enviado(clave):
        return
    with closing(gastos._con()) as con, con:
        con.execute("DELETE FROM movimientos WHERE descripcion = 'correo ilegible' AND origen = 'correo'")
        con.execute("DELETE FROM avisos_enviados WHERE clave = 'correos|importacion'")
    db.marcar_aviso(clave)
    log.info("Lectores v%d: se reintentan los correos ilegibles", VERSION)


def _marcar_ilegible(ref):
    with closing(gastos._con()) as con, con:
        if not con.execute("SELECT 1 FROM movimientos WHERE ref = ?", (ref,)).fetchone():
            con.execute("INSERT INTO movimientos (tipo, monto, descripcion, fecha, origen, ref, estado) "
                        "VALUES ('gasto', 0, 'correo ilegible', ?, 'correo', ?, 'borrado')", (ahora().date().isoformat(), ref))


def _procesar_uno(srv, item, ref):
    """Procesa un correo. Devuelve un evento (tipo, dato) o None si se ignora."""
    if True:
        msg = srv.users().messages().get(userId="me", id=item["id"], format="full").execute()
        cab = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        banco = banco_del_remitente(cab.get("from", ""))
        if not banco:                                                      # no es del banco: ignorar
            log.info("Correo ignorado (remitente no es de un banco): %s", parseaddr(cab.get("from", ""))[1])
            dom = parseaddr(cab.get("from", ""))[1].split("@")[-1]
            if dom and dom not in IGNORADOS:
                IGNORADOS.append(dom)
            return None
        texto = _cuerpo(msg["payload"])
        try:
            fecha_correo = parsedate_to_datetime(cab.get("date")).astimezone(ZONA).replace(tzinfo=None)
        except Exception:
            fecha_correo = ahora().replace(tzinfo=None)
        if es_reverso(cab.get("subject", ""), texto):                     # anulación / devolución: resta, no suma
            return procesar_reverso(banco, texto, cab.get("subject", ""), ref, fecha_correo)
        datos = LECTORES[banco](texto)
        if not datos or not datos.get("monto"):
            log.warning("No pude leer un correo de %s: %s", banco, cab.get("subject", "")[:60])
            _marcar_ilegible(ref)                                          # marca para no reintentar
            return ("ilegible", banco + ": " + cab.get("subject", "")[:60])
        fecha = fecha_confiable(datos.get("fecha"), fecha_correo)
        comercio = limpiar_comercio(datos["comercio"])
        medio = MEDIOS[banco]
        moneda = datos.get("moneda", "USD")
        if moneda != "USD":                                               # compra en otra moneda
            original = datos["monto"]
            usd, tasa = a_usd(original, moneda, fecha.date())
            comercio = comercio + " (" + moneda + " " + fmt(original).replace("$", "") + ")"
            if usd is None:                                               # sin tasa: que el usuario lo anote en dolares
                _marcar_ilegible(ref)
                return ("moneda", "Compra de " + moneda + " " + fmt(original).replace("$", "") + " en " + comercio.split(" (")[0]
                        + " con " + medio + ": no pude obtener el tipo de cambio. An\u00f3tela en d\u00f3lares, por ejemplo \u00ab"
                        + comercio.split(" (")[0].lower() + " 41.20 con " + banco.lower() + "\u00bb.")
            datos["monto"] = usd
        if es_avance(comercio):
            pid = gastos.crear_pendiente({"monto": datos["monto"], "descripcion": comercio + " [" + ref + "]",
                                          "medio": medio, "fecha": fecha.date()})
            return ("avance", pid)
        cargo_id = anotar_cargo(datos, comercio, medio, fecha.date(), ref)
        inversion = es_inversion(comercio)
        previo = _anotado_a_mano(datos["monto"], fecha.date())
        if previo:
            gastos.cambiar(previo["id"], ref=ref, medio=previo["medio"] or medio,
                           **({"tipo": "inversion", "categoria": "Inversión"} if inversion else {}))
            return ("inversion" if inversion else "unido", (previo["id"], cargo_id) if inversion else previo["id"])
        if inversion:
            mid = gastos.anotar("inversion", datos["monto"], comercio, "Inversión", medio, fecha.date(), "correo", ref,
                                usar_foto=False)
            return ("inversion", (mid, cargo_id))
        mid = gastos.anotar("gasto", datos["monto"], comercio, None, medio, fecha.date(), "correo", ref, usar_foto=False)
        return ("nuevo", mid) if not cargo_id else ("nuevo_con_cargo", (mid, cargo_id))


# ------------------------------------------------------------------ reversos, anulaciones y devoluciones ---
def _parecido_comercio(a, b):
    """0 a 1: palabras del comercio en común ('DLC*UBER RIDES' ~ 'Dlc*uber Rides', 'PTP - DL -DIDI RIDE' ~ 'Didi')."""
    pa = {w for w in re.findall(r"[a-z]{3,}", _norm(a)) if w not in ("ptp", "dlc", "www", "com", "the")}
    pb = {w for w in re.findall(r"[a-z]{3,}", _norm(b)) if w not in ("ptp", "dlc", "www", "com", "the")}
    return len(pa & pb) / max(1, min(len(pa), len(pb))) if pa and pb else 0.0


def buscar_consumo(monto, comercio, medio, dia, excluir_ref=""):
    """El consumo que se reversa: mismo monto (o mayor, si es parcial) en los 30 días anteriores.
    Devuelve (movimiento, 'total'|'parcial') o (None, None)."""
    with closing(gastos._con()) as con:
        filas = [dict(f) for f in con.execute(
            "SELECT * FROM movimientos WHERE estado = 'activo' AND tipo = 'gasto' AND ref != ? AND fecha >= ? AND fecha <= ? "
            "ORDER BY fecha DESC, id DESC", (excluir_ref, (dia - timedelta(days=30)).isoformat(),
                                             (dia + timedelta(days=1)).isoformat()))]
    def puntos(f):
        return (_parecido_comercio(f["descripcion"], comercio) + (0.3 if f["medio"] == medio else 0)
                - abs((dia - date.fromisoformat(f["fecha"])).days) / 100)
    exactos = [f for f in filas if abs(f["monto"] - monto) < 0.011 and
               (f["medio"] in ("", medio) or _parecido_comercio(f["descripcion"], comercio) >= 0.5)]
    if exactos:
        return max(exactos, key=puntos), "total"
    parciales = [f for f in filas if f["monto"] > monto + 0.01 and f["medio"] in ("", medio)
                 and _parecido_comercio(f["descripcion"], comercio) >= 0.5]
    if parciales:
        return max(parciales, key=puntos), "parcial"
    return None, None


def procesar_reverso(banco, texto, asunto, ref, fecha_correo):
    """Un reverso/anulación: deja de contar el consumo (o lo rebaja si es parcial). Devuelve un evento."""
    datos = LECTORES.get(banco, leer_generico)(texto) or leer_generico(texto)
    if not datos or not datos.get("monto"):
        log.info("Reverso de %s sin monto legible: %s", banco, asunto[:60])
        _marcar_ilegible(ref)
        return ("ilegible", banco + " (reverso): " + asunto[:50])
    fecha = fecha_confiable(datos.get("fecha"), fecha_correo).date()
    comercio = limpiar_comercio(datos["comercio"])
    medio = MEDIOS.get(banco, "")
    monto = datos["monto"]
    if datos.get("moneda", "USD") != "USD":
        monto = a_usd(monto, datos["moneda"], fecha)[0] or monto
    consumo, tipo = buscar_consumo(monto, comercio, medio, fecha, ref)
    if consumo and tipo == "total":
        gastos.cambiar(consumo["id"], estado="anulado")
    elif consumo:
        gastos.cambiar(consumo["id"], monto=round(consumo["monto"] - monto, 2),
                       descripcion=(consumo["descripcion"] + " (−" + fmt(monto).replace("$", "") + " reverso)")[:120])
    with closing(gastos._con()) as con, con:                 # el reverso queda registrado, pero NO cuenta
        con.execute("INSERT INTO movimientos (tipo, monto, descripcion, categoria, medio, fecha, origen, ref, estado) "
                    "VALUES ('gasto', ?, ?, 'Reverso', ?, ?, 'correo', ?, 'reverso')",
                    (monto, ("Reverso de " + comercio + (" (#" + str(consumo["id"]) + ")" if consumo else ""))[:120],
                     medio, fecha.isoformat(), ref))
    log.info("Reverso %s %.2f %s -> %s", banco, monto, comercio, (tipo, consumo["id"]) if consumo else "sin consumo")
    return ("reverso", {"monto": monto, "comercio": comercio, "medio": medio, "fecha": fecha.isoformat(),
                        "consumo": consumo["id"] if consumo else None, "tipo": tipo,
                        "restante": round(consumo["monto"] - monto, 2) if tipo == "parcial" else None})


def texto_reverso(d):
    cuando = date.fromisoformat(d["fecha"]).strftime("%d/%m")
    base = "↩️ " + (d["medio"] or "El banco") + " reversó " + fmt(d["monto"]) + " de " + d["comercio"] + " (" + cuando + ")."
    if d["tipo"] == "total":
        return base + "\nQuité ese consumo de sus gastos y del presupuesto."
    if d["tipo"] == "parcial":
        return base + "\nEra parte de un consumo mayor: lo dejé en " + fmt(d["restante"]) + "."
    return (base + "\nNo encontré ese consumo en sus gastos (quizá fue un cobro de verificación de la app o es de "
            "hace más de 30 días). No cambié nada.")


def corregir_reversos_pasados(srv=None, dias=3650):
    """Una sola vez (v2): relee TODOS los correos ya importados y arregla: reversos que se sumaron como gasto,
    fechas leídas al revés (mes/día, aunque hayan quedado meses atrás), comercios con texto de más,
    depósitos a brókers (→ inversión) y cargos del banco que no se anotaron.
    Devuelve dict con lo corregido o None si ya se hizo."""
    clave = "correos|reparar_v2"
    if db.aviso_enviado(clave):
        return None
    srv = srv or servicio()
    with closing(gastos._con()) as con:
        filas = [dict(f) for f in con.execute("SELECT * FROM movimientos WHERE origen = 'correo' AND ref LIKE 'gmail:%' "
                                              "AND ref NOT LIKE '%#%' AND estado = 'activo' AND fecha >= ? ORDER BY fecha, id",
                                              ((ahora().date() - timedelta(days=dias)).isoformat(),))]
    reversos, fechas, total = 0, 0, 0.0
    inversiones, cargos, nombres = [], [], 0
    leidos = []
    for f in filas:                               # 1) leer cada correo y arreglar fechas mes/día
        try:
            msg = srv.users().messages().get(userId="me", id=f["ref"][6:], format="full").execute()
        except Exception as exc:
            log.info("No pude releer %s: %s", f["ref"], exc)
            continue
        cab = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        try:
            fecha_correo = parsedate_to_datetime(cab.get("date")).astimezone(ZONA).replace(tzinfo=None)
        except Exception:
            continue
        texto = _cuerpo(msg["payload"])
        if es_reverso(cab.get("subject", ""), texto):
            leidos.append((f, cab, texto, fecha_correo))
            continue
        cambios = {}
        if abs((date.fromisoformat(f["fecha"]) - fecha_correo.date()).days) > 2:
            cambios["fecha"] = fecha_confiable(datetime.fromisoformat(f["fecha"]), fecha_correo).date().isoformat()
            fechas += 1
        banco = banco_del_remitente(cab.get("from", ""))
        datos = LECTORES[banco](texto) if banco else None
        if datos:
            comercio = limpiar_comercio(datos["comercio"])
            if datos.get("moneda", "USD") == "USD" and comercio != f["descripcion"] and \
                    re.search(r"esta transacci|si no realizaste|por favor", _norm(f["descripcion"])):
                cambios["descripcion"] = comercio
                nombres += 1
            if f["tipo"] == "gasto" and es_inversion(comercio):
                cambios.update(tipo="inversion", categoria="Inversión")
                inversiones.append((comercio, f["monto"]))
            dia = date.fromisoformat(cambios.get("fecha", f["fecha"]))
            cid = anotar_cargo(datos, comercio, f["medio"] or MEDIOS.get(banco, ""), dia, f["ref"])
            if cid:
                cargos.append(gastos.obtener(cid)["monto"])
        if cambios:
            gastos.cambiar(f["id"], **cambios)
    for f, cab, texto, fecha_correo in leidos:    # 2) los reversos que se habían sumado como gasto
        gastos.cambiar(f["id"], estado="borrado", ref=f["ref"] + "#viejo")
        banco = banco_del_remitente(cab.get("from", "")) or "Produbanco"
        evento = procesar_reverso(banco, texto, cab.get("subject", ""), f["ref"], fecha_correo)
        if evento[0] == "reverso":
            reversos += 1
            total += evento[1]["monto"]
    db.marcar_aviso(clave)
    log.info("Reparación v2: %d reversos (%.2f), %d fechas, %d nombres, %d inversiones, %d cargos",
             reversos, total, fechas, nombres, len(inversiones), len(cargos))
    return {"reversos": reversos, "total_reversos": round(total, 2), "fechas": fechas, "nombres": nombres,
            "inversiones": inversiones, "cargos": cargos}


def texto_reparacion(r):
    if not r or not any([r["reversos"], r["fechas"], r["nombres"], r["inversiones"], r["cargos"]]):
        return None
    lineas = ["🧹 Revisé todos sus correos del banco ya importados:"]
    if r["reversos"]:
        lineas.append("• " + str(r["reversos"]) + " reversos se habían contado como gastos (" + fmt(r["total_reversos"])
                      + "). Los quité y anulé los consumos originales.")
    if r["fechas"]:
        lineas.append("• Corregí la fecha de " + str(r["fechas"]) + " consumos (venían como mes/día).")
    if r["nombres"]:
        lineas.append("• Limpié el nombre de " + str(r["nombres"]) + " comercios.")
    for comercio, monto in r["inversiones"]:
        lineas.append("• " + fmt(monto) + " en " + comercio + " ahora es INVERSIÓN, no gasto.")
    if r["cargos"]:
        lineas.append("• Anoté " + str(len(r["cargos"])) + " cargos del banco que faltaban (" + fmt(sum(r["cargos"]))
                      + ", Comisiones bancarias).")
    lineas.append("Sus gastos y presupuesto ya están al día: /gastos")
    return "\n".join(lineas)


def texto_nuevo(mid):
    g = gastos.obtener(mid)
    segura = gastos.categoria_de(g["descripcion"])[1]
    return ("\U0001F4B3 Registré " + fmt(g["monto"]) + " en " + g["descripcion"] + " (" + g["medio"] + ")"
            + (" · " + date.fromisoformat(g["fecha"]).strftime("%d/%m") if g["fecha"] != ahora().date().isoformat() else "")
            + "\nCategoría: " + g["categoria"] + ("" if segura else " (no la conozco: cámbiela y la aprendo)")
            + ". " + ("Este mes" if g["fecha"][:7] == ahora().date().isoformat()[:7] else "En ese mes") + " en " + g["categoria"]
            + ": " + fmt(gastos.total_categoria_mes(g["categoria"], date.fromisoformat(g["fecha"]))) + ".")


def texto_inversion(mid, cargo_id=None):
    g = gastos.obtener(mid)
    texto = ("📈 Registré una INVERSIÓN de " + fmt(g["monto"]) + " en " + g["descripcion"] + " (" + g["medio"] + ")"
             + (" · " + date.fromisoformat(g["fecha"]).strftime("%d/%m") if g["fecha"] != ahora().date().isoformat() else "")
             + ".\nNo cuenta como gasto ni en su presupuesto: es dinero suyo que pasó a su cuenta de inversión.")
    return texto + ("\n" + texto_cargo(cargo_id) if cargo_id else "")


def texto_cargo(cargo_id):
    c = gastos.obtener(cargo_id)
    return ("🏦 El banco además cobró " + fmt(c["monto"]) + " de " + c["descripcion"].replace("Cargo banco por ", "cargo por ")
            + ". Ese sí lo anoté como gasto (Comisiones bancarias).")


def texto_unido(mid):
    g = gastos.obtener(mid)
    return ("\U0001F517 Llegó el correo del banco por " + fmt(g["monto"]) + ": ya lo tenía anotado («" + g["descripcion"]
            + "»), solo le agregué la tarjeta " + g["medio"] + ".")


def texto_avance(pid):
    p = gastos.pendiente(pid)
    desc = re.sub(r"\s*\[gmail:[^\]]+\]$", "", p["descripcion"])
    texto = ("\U0001F3E7 " + desc + " de " + fmt(p["monto"]) + " con " + p["medio"] + ".\nEs efectivo que sacó de la tarjeta: "
             "si luego anota en qué lo gastó, se contaría dos veces. ¿Lo cuento como gasto? Elija la categoría o ❌:")
    _, filas = gastos.pregunta_pendiente(pid)
    return texto, filas
