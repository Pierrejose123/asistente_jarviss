"""Lee el Excel exportado de XTB (xStation 5 -> Historial -> Exportar).

El archivo real vive SOLO en la PC (carpeta «pesado» de config\\rutas.json, subcarpeta xtb). Trae 3 hojas:
  - Open Positions:   cada compra abierta (lote) con ticker, volumen, precio y fecha de apertura
  - Cash Operations:  dividendos, retenciones, depositos, compras...
  - Closed Positions: ventas ya cerradas con su ganancia o perdida
Se buscan las columnas por su NOMBRE (no por posicion), asi un cambio de XTB no rompe todo.
"""
from datetime import datetime
from pathlib import Path

from modulos.comun.base import PESADO  # noqa: E402

CARPETA = PESADO / "xtb"

# Simbolo de XTB -> simbolo de Yahoo Finance (lo que no este aqui se convierte con las reglas de abajo)
EQUIVALENCIAS = {"GOOGC.US": "GOOG", "BRKB.US": "BRK-B", "BRKA.US": "BRK-A"}
SUFIJOS = {".US": "", ".UK": ".L", ".DE": ".DE", ".FR": ".PA", ".NL": ".AS", ".ES": ".MC", ".IT": ".MI",
           ".PL": ".WA", ".CH": ".SW", ".BE": ".BR", ".PT": ".LS", ".SE": ".ST", ".DK": ".CO", ".NO": ".OL",
           ".FI": ".HE", ".CZ": ".PR"}


def a_yahoo(ticker, extra=None):
    t = (ticker or "").upper().strip()
    tabla = {**EQUIVALENCIAS, **(extra or {})}
    if t in tabla:
        return tabla[t]
    for suf, nuevo in SUFIJOS.items():
        if t.endswith(suf):
            return t[: -len(suf)].replace(".", "-") + nuevo
    return t


def ultimo_archivo(carpeta=CARPETA):
    archivos = sorted(list(carpeta.glob("*.xlsx")) + list(carpeta.glob("*.xlsm")), key=lambda p: p.stat().st_mtime)
    return archivos[-1] if archivos else None


def _tabla(hoja, primera_columna):
    """Devuelve las filas (dict) debajo de la fila de encabezados que empieza con 'primera_columna'."""
    filas = list(hoja.iter_rows(values_only=True))
    for i, fila in enumerate(filas):
        if fila and str(fila[0] or "").strip().lower() == primera_columna.lower() and len([v for v in fila if v]) > 4:
            encabezado = [str(v).strip() if v is not None else "" for v in fila]
            datos = []
            for f in filas[i + 1:]:
                if not f or all(v is None for v in f):
                    continue
                d = {encabezado[j]: f[j] for j in range(min(len(encabezado), len(f))) if encabezado[j]}
                datos.append(d)
            return datos
    return []


def _hoja(libro, *nombres):
    for h in libro.worksheets:
        if h.title.strip().lower() in [n.lower() for n in nombres]:
            return h
    return None


def _num(v):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def diagnostico(ruta=None):
    """Texto con las hojas y encabezados que encuentra (sin datos), para ajustar el lector si XTB cambia."""
    import openpyxl
    import warnings
    ruta = Path(ruta) if ruta else ultimo_archivo()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        libro = openpyxl.load_workbook(ruta, data_only=True)
    lineas = ["Archivo: " + ruta.name]
    for h in libro.worksheets:
        lineas.append("Hoja '" + h.title + "': " + str(h.max_row) + " filas")
        for fila in h.iter_rows(max_row=40, values_only=True):       # solo filas de encabezado (sin datos)
            textos = [str(v) for v in fila if isinstance(v, str)]
            if len(textos) >= 5 and not any(isinstance(v, (int, float)) for v in fila):
                lineas.append("   columnas: " + " | ".join(textos[:25]))
                break
        tipos = {str(f[4]).upper() for f in h.iter_rows(values_only=True)
                 if len(f) > 4 and str(f[4] or "").upper() in ("BUY", "SELL")}
        if tipos:
            lineas.append("   filas de compra encontradas: " + ", ".join(sorted(tipos)))
    return "\n".join(lineas)


def leer(ruta=None):
    """Devuelve {'fecha_informe', 'lotes', 'caja', 'cerradas', 'archivo'}."""
    import openpyxl
    ruta = Path(ruta) if ruta else ultimo_archivo()
    if not ruta or not ruta.exists():
        raise FileNotFoundError("No hay ningun Excel de XTB en " + str(CARPETA))
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")                      # "Workbook contains no default style" de XTB
        # Lectura completa (no read_only): los Excel de XTB declaran mal su tamano y en modo rapido
        # openpyxl solo leeria una parte de las filas.
        libro = openpyxl.load_workbook(ruta, data_only=True)

    lotes, fecha_informe = [], None
    h = _hoja(libro, "Open Positions", "Posiciones abiertas")
    if h:
        for fila in h.iter_rows(max_row=6, values_only=True):
            if fila and isinstance(fila[1] if len(fila) > 1 else None, datetime):
                fecha_informe = fila[1]
        for f in _tabla(h, "Product"):
            tipo = str(f.get("Type") or "").upper()
            if tipo not in ("BUY", "SELL"):              # filas resumen por instrumento: se recalculan
                continue
            volumen, precio = _num(f.get("Volume")), _num(f.get("Open price"))
            if not volumen or not precio:
                continue
            lotes.append({"ticker": str(f.get("Ticker") or "").strip(), "tipo": tipo, "volumen": volumen,
                          "precio": precio, "fecha": f.get("Open time (UTC)"), "producto": f.get("Product") or "",
                          "precio_xtb": _num(f.get("Current price")), "posicion": str(f.get("Instrument/Position") or "")})

    caja = []
    h = _hoja(libro, "Cash Operations", "Operaciones de caja", "Operaciones en efectivo")
    if h:
        for f in _tabla(h, "Type"):
            caja.append({"tipo": str(f.get("Type") or ""), "ticker": str(f.get("Ticker") or ""),
                         "instrumento": str(f.get("Instrument") or ""), "fecha": f.get("Time"),
                         "importe": _num(f.get("Amount")) or 0.0, "comentario": str(f.get("Comment") or "")})

    cerradas = []
    h = _hoja(libro, "Closed Positions", "Posiciones cerradas")
    if h:
        for f in _tabla(h, "Instrument"):
            if not f.get("Ticker"):
                continue
            cerradas.append({"ticker": str(f["Ticker"]), "categoria": str(f.get("Category") or ""),
                             "volumen": _num(f.get("Volume")), "abre": _num(f.get("Open Price")),
                             "cierra": _num(f.get("Close Price")), "fecha_abre": f.get("Open Time (UTC)"),
                             "fecha_cierra": f.get("Close Time (UTC)"), "resultado": _num(f.get("Profit/Loss")) or 0.0,
                             "compra": _num(f.get("Purchase Value")), "venta": _num(f.get("Sale Value"))})

    # Categoria (STOCK / ETF / CFD) de cada ticker: de la caja o de las cerradas
    categorias = {c["ticker"]: c.get("categoria") for c in cerradas}
    if h := _hoja(libro, "Open Positions", "Posiciones abiertas"):
        for f in _tabla(h, "Product"):
            if f.get("Category") and str(f.get("Type") or "").upper() not in ("BUY", "SELL"):
                categorias[str(f.get("Ticker") or "")] = str(f["Category"])
    nombres = {c["ticker"]: c["instrumento"] for c in caja if c["ticker"] and c["instrumento"]}
    if h := _hoja(libro, "Open Positions", "Posiciones abiertas"):
        for f in _tabla(h, "Product"):
            if f.get("Ticker") and str(f.get("Type") or "").upper() not in ("BUY", "SELL") and f.get("Instrument/Position"):
                nombres[str(f["Ticker"])] = str(f["Instrument/Position"])
    for l in lotes:
        l["categoria"] = categorias.get(l["ticker"], "STOCK")
        l["nombre"] = nombres.get(l["ticker"], "")
    return {"fecha_informe": fecha_informe, "lotes": lotes, "caja": caja, "cerradas": cerradas, "archivo": str(ruta)}
