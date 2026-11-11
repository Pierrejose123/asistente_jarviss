"""Fase 2, punto 3: portafolio de XTB calculado en CODIGO (la IA no hace cuentas).

- Posiciones: del ultimo Excel de XTB en la carpeta privada (rutas.json → pesado\\xtb) (solo en la PC).
- Precios: Yahoo Finance (yfinance, con retraso; sirve para informarse, no para operar rapido).
- Por Telegram solo PORCENTAJES. Los montos solo se ven en la PC:
      .\\.venv\\Scripts\\python.exe modulos\\portafolio\\portafolio.py
- El asistente informa; no decide compras ni ventas.
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from modulos.comun.base import CONFIG, leer_json, registro  # noqa: E402
from modulos.portafolio import xtb  # noqa: E402

log = registro("portafolio")
REFERENCIA = "SPY"                       # S&P 500
_cache = {"t": 0, "datos": None}


def ajustes():
    base = {"moneda": "USD", "equivalencias": {}, "comparar_con_sp500": True, "carpetas_descargas": [str(Path.home() / "Downloads")]}
    if (CONFIG / "portafolio.json").exists():
        base.update(leer_json("portafolio.json"))
    return base


# ------------------------------------------------------------------ precios ---
def _precios(simbolos, desde):
    """Historial diario de cierres desde 'desde' (+1 ano para el maximo de 52 semanas)."""
    import warnings
    import yfinance as yf
    inicio = min(desde, datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")

    def bajar(lista):
        # threads=False: con hilos, la cache interna de yfinance da "database is locked"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tabla = yf.download(lista, start=inicio, auto_adjust=False, progress=False,
                                group_by="ticker", threads=False)
        salida = {}
        for s in lista:
            try:
                col = tabla[s]["Close"] if len(lista) > 1 else tabla["Close"]
                col = col.squeeze() if hasattr(col, "squeeze") else col
                col = col.dropna()
                if len(col):
                    salida[s] = col
            except Exception:
                continue
        return salida

    lista = sorted(set(simbolos))
    series = bajar(lista)
    for s in [x for x in lista if x not in series]:          # reintento uno por uno
        time.sleep(1)
        series.update(bajar([s]))
    faltan = [x for x in lista if x not in series]
    if faltan:
        log.warning("Sin precio de Yahoo para: %s", ", ".join(faltan))
    return series


def _moneda(simbolo):
    try:
        import yfinance as yf
        return yf.Ticker(simbolo).fast_info.get("currency") or "USD"
    except Exception:
        return "USD"


def _factor(moneda, destino, series_fx):
    """Factor para pasar un precio de 'moneda' a la moneda de la cuenta."""
    if moneda == destino:
        return 1.0
    escala = 0.01 if moneda in ("GBp", "GBX") else 1.0
    base = "GBP" if moneda in ("GBp", "GBX") else moneda
    if base == destino:
        return escala
    par = base + destino + "=X"
    if par in series_fx and len(series_fx[par]):
        return escala * float(series_fx[par].iloc[-1])
    return escala


def _cierre_en(serie, fecha):
    """Cierre del dia de 'fecha' o del dia habil anterior/siguiente mas cercano."""
    if serie is None or not len(serie):
        return None
    f = fecha.replace(tzinfo=None) if hasattr(fecha, "tzinfo") else fecha
    idx = serie.index.tz_localize(None) if getattr(serie.index, "tz", None) is not None else serie.index
    previos = serie[idx <= f]
    return float(previos.iloc[-1]) if len(previos) else float(serie.iloc[0])


# ------------------------------------------------------------------ calculo ---
def calcular(ruta=None, usar_cache=True):
    """Devuelve un dict con todo el portafolio calculado. Cachea 10 min."""
    if usar_cache and _cache["datos"] and time.time() - _cache["t"] < 600 and not ruta:
        return _cache["datos"]
    cfg = ajustes()
    datos = xtb.leer(ruta)
    lotes = [l for l in datos["lotes"] if l["tipo"] == "BUY"]
    manuales = {"sin_cantidad": [], "cambios": []}
    try:                                   # lo que el usuario contó desde el último informe («compré…», «vendí…»)
        from modulos.portafolio import cambios
        fecha_inf = datos["fecha_informe"] or datetime.fromtimestamp(Path(datos["archivo"]).stat().st_mtime)
        lotes, manuales = cambios.ajustar_lotes(lotes, fecha_inf, lambda t: xtb.a_yahoo(t, cfg["equivalencias"]))
    except Exception as exc:
        log.info("Sin cambios manuales: %s", exc)
    if not lotes:
        log.warning("Sin posiciones abiertas. Diagnostico:\n%s", xtb.diagnostico(datos["archivo"]))
        raise ValueError("El informe no tiene posiciones abiertas (ver logs/portafolio.log).")
    yahoo = {l["ticker"]: xtb.a_yahoo(l["ticker"], cfg["equivalencias"]) for l in lotes}
    primera = min(l["fecha"] for l in lotes if isinstance(l["fecha"], datetime))

    fuente = "Yahoo Finance"
    try:
        series = _precios(list(yahoo.values()) + [REFERENCIA], primera)
        monedas = {s: _moneda(s) for s in set(yahoo.values()) if not s.isalpha() or "." in s}   # solo las no-US
        bases = {("GBP" if m in ("GBp", "GBX") else m) for m in monedas.values()}
        pares = {b + cfg["moneda"] + "=X" for b in bases if b != cfg["moneda"]}
        if pares:
            series.update(_precios(list(pares), datetime.now() - timedelta(days=10)))
    except Exception as exc:
        log.warning("Sin precios de Yahoo: %s", exc)
        series, monedas = {}, {}
    if not series:
        fuente = "precios del informe de XTB"

    posiciones = {}
    for l in lotes:
        p = posiciones.setdefault(l["ticker"], {"ticker": l["ticker"], "yahoo": yahoo[l["ticker"]], "acciones": 0.0,
                                                "costo": 0.0, "lotes": [], "categoria": l.get("categoria", "STOCK"),
                                                "nombre": l.get("nombre", "")})
        p["acciones"] += l["volumen"]
        p["costo"] += l["volumen"] * l["precio"]
        p["lotes"].append(l)

    spy = series.get(REFERENCIA)
    ref_hoy = float(spy.iloc[-1]) if spy is not None and len(spy) else None
    total_valor = total_costo = total_ayer = total_ref = 0.0
    for p in posiciones.values():
        s = series.get(p["yahoo"])
        factor = _factor(monedas.get(p["yahoo"], "USD"), cfg["moneda"], series)
        if s is not None and len(s):
            precio = float(s.iloc[-1]) * factor
            ayer = float(s.iloc[-2]) * factor if len(s) > 1 else precio
            ultimo_ano = s[s.index >= s.index[-1] - timedelta(days=365)]
            p["max52"], p["min52"] = float(ultimo_ano.max()) * factor, float(ultimo_ano.min()) * factor
            p["media50"] = float(s.iloc[-50:].mean()) * factor if len(s) >= 50 else None
            p["media200"] = float(s.iloc[-200:].mean()) * factor if len(s) >= 200 else None
            p["fecha_precio"] = s.index[-1]
        else:
            precio = next((l["precio_xtb"] for l in p["lotes"] if l.get("precio_xtb")), p["costo"] / p["acciones"])
            ayer = precio
            p.update(max52=None, min52=None, media50=None, media200=None, fecha_precio=None)
        p["precio"], p["promedio"] = precio, p["costo"] / p["acciones"]
        p["valor"] = p["acciones"] * precio
        p["ganancia"] = p["valor"] - p["costo"]
        p["ganancia_pct"] = p["ganancia"] / p["costo"] * 100 if p["costo"] else 0
        p["hoy_pct"] = (precio / ayer - 1) * 100 if ayer else 0
        # Si hubiera puesto lo mismo en el S&P 500 en las mismas fechas
        if ref_hoy:
            p["ref_valor"] = sum(l["volumen"] * l["precio"] / _cierre_en(spy, l["fecha"]) * ref_hoy for l in p["lotes"])
            total_ref += p["ref_valor"]
        total_valor += p["valor"]
        total_costo += p["costo"]
        total_ayer += p["acciones"] * ayer

    sin_precio = [p["yahoo"] for p in posiciones.values() if p.get("fecha_precio") is None]
    for p in posiciones.values():
        p["peso"] = p["valor"] / total_valor * 100 if total_valor else 0
        p["dist_max52"] = (p["precio"] / p["max52"] - 1) * 100 if p.get("max52") else None

    hace_un_ano = datetime.now() - timedelta(days=365)
    div = [c for c in datos["caja"] if c["tipo"].lower() in ("dividend", "withholding tax", "dividendo",
                                                             "retencion de impuestos", "retención de impuestos")
           and isinstance(c["fecha"], datetime) and c["fecha"] >= hace_un_ano]
    dividendos = sum(c["importe"] for c in div)
    realizadas = [c for c in datos["cerradas"] if isinstance(c["fecha_cierra"], datetime) and c["fecha_cierra"] >= hace_un_ano]
    real_res = sum(c["resultado"] for c in realizadas)
    real_base = sum((c["compra"] or (c["volumen"] or 0) * (c["abre"] or 0)) for c in realizadas
                    if c["categoria"] != "CFD") or 0

    res = {
        "posiciones": sorted(posiciones.values(), key=lambda p: -p["valor"]),
        "valor": total_valor, "costo": total_costo, "ganancia": total_valor - total_costo,
        "ganancia_pct": (total_valor / total_costo - 1) * 100 if total_costo else 0,
        "hoy_pct": (total_valor / total_ayer - 1) * 100 if total_ayer else 0,
        "ref_pct": (total_ref / total_costo - 1) * 100 if total_ref and total_costo else None,
        "ref_hoy_pct": (float(spy.iloc[-1]) / float(spy.iloc[-2]) - 1) * 100 if spy is not None and len(spy) > 1 else None,
        "dividendos_12m": dividendos, "dividendos_pct": dividendos / total_costo * 100 if total_costo else 0,
        "realizado_12m": real_res, "realizado_pct": real_res / real_base * 100 if real_base else None,
        "fecha_informe": datos["fecha_informe"], "fuente": fuente, "archivo": datos["archivo"],
        "calculado": datetime.now(), "sin_precio": sin_precio if series else [], "manuales": manuales,
    }
    _cache.update(t=time.time(), datos=res)
    return res


# ------------------------------------------------------------------ textos ---
def _s(x, dec=1):
    return ("+" if x >= 0 else "\u2212") + ("%." + str(dec) + "f") % abs(x) + " %"


def senales(p):
    """Observaciones objetivas de una posicion (no son recomendaciones). Lista de (clave, texto corto)."""
    notas = []
    if p.get("dist_max52") is not None and p["dist_max52"] > -3:
        notas.append(("max", "cerca de su m\u00e1ximo anual (" + _s(p["dist_max52"]) + ")"))
    if p.get("min52") and p["precio"] <= p["min52"] * 1.03:
        notas.append(("min", "cerca de su m\u00ednimo anual"))
    if p.get("media200") and p["precio"] < p["media200"]:
        notas.append(("media", "debajo de su media de 200 d\u00edas"))
    if p["peso"] >= 30:
        notas.append(("peso", "pesa " + "%.0f" % p["peso"] + " % del portafolio"))
    if abs(p["hoy_pct"]) >= 4:
        notas.append(("hoy", "se movi\u00f3 " + _s(p["hoy_pct"]) + " hoy"))
    return notas


# Explicacion sencilla de cada senal (para que el mensaje se entienda sin saber de bolsa)
EXPLICA = {
    "media": ("est\u00e1n por debajo de su <b>precio promedio de los \u00faltimos 10 meses</b> (la \u00abmedia de 200 d\u00edas\u00bb). "
              "Quiere decir que en los \u00faltimos meses vienen m\u00e1s bajas que antes. No significa que vayan a seguir "
              "bajando; es algo para mirar con calma."),
    "max": ("est\u00e1n cerca de su <b>precio m\u00e1s alto del \u00faltimo a\u00f1o</b>. Es un buen momento para recordar en qu\u00e9 "
            "punto pensaba tomar ganancias, si es que lo ten\u00eda."),
    "min": ("est\u00e1n cerca de su <b>precio m\u00e1s bajo del \u00faltimo a\u00f1o</b>. Conviene revisar si sigue confiando en "
            "la raz\u00f3n por la que las compr\u00f3."),
    "peso": ("ocupan una parte grande de su dinero invertido. Si a esa empresa le va mal, se nota mucho en todo el "
             "portafolio (es lo que llaman <b>concentraci\u00f3n</b>)."),
    "hoy": "tuvieron un <b>movimiento fuerte hoy</b> (4 % o m\u00e1s). Puede deberse a una noticia o a sus resultados.",
}


def _c(x, dec=1):
    """Porcentaje con signo y coma decimal: +4,4 %."""
    return _s(x, dec).replace(".", ",")


def _nombre(p):
    from html import escape
    corto = re.sub(r"\s+(?:SAB de CV|Corp|Inc|Corporation|Incorporated)\b\.?", "", p["nombre"]).strip()   # «Realty Income» intacto
    return "<b>" + escape(p["yahoo"]) + "</b>" + (" (" + escape(corto) + ")" if corto and corto.upper() != p["yahoo"] else "")


def texto_telegram(r):
    """Resumen en PORCENTAJES (sin montos) para Telegram, en HTML, explicado en palabras simples."""
    from html import escape
    pos = r["posiciones"]
    mayor = max(pos, key=lambda p: p["peso"])
    mejor = max(pos, key=lambda p: p["ganancia_pct"])
    peor = min(pos, key=lambda p: p["ganancia_pct"])
    gana = r["ganancia_pct"] >= 0

    resumen = ("Va " + ("<b>ganando " if gana else "<b>perdiendo ") + _c(abs(r["ganancia_pct"])).lstrip("+") + "</b> sobre lo que "
               "invirti\u00f3 en las acciones que tiene ahora. ")
    if abs(r["hoy_pct"]) < 0.3:
        resumen += "Hoy casi no se movi\u00f3 (" + _c(r["hoy_pct"], 2) + "). "
    else:
        resumen += "Hoy " + ("subi\u00f3 " if r["hoy_pct"] > 0 else "baj\u00f3 ") + _c(abs(r["hoy_pct"]), 2).lstrip("+") + ". "
    resumen += ("Su acci\u00f3n m\u00e1s grande es " + escape(mayor["yahoo"]) + " (" + "%.0f" % mayor["peso"] + " % del total); "
                "la que mejor va es " + escape(mejor["yahoo"]) + " (" + _c(mejor["ganancia_pct"]) + ")")
    resumen += (" y la que peor va es " + escape(peor["yahoo"]) + " (" + _c(peor["ganancia_pct"]) + ")." if peor is not mejor
                and peor["ganancia_pct"] < 0 else ".")

    lineas = ["\U0001F4CA <b>Su portafolio</b> <i>(" + r["calculado"].strftime("%d/%m %H:%M") + ", " + escape(r["fuente"]) + ")</i>",
              "", "\U0001F4DD <b>En pocas palabras</b>", resumen]

    if r["ref_pct"] is not None and ajustes().get("comparar_con_sp500", True):
        dif = r["ganancia_pct"] - r["ref_pct"]
        lineas += ["", "\U0001F4CF <b>Comparaci\u00f3n de referencia</b>",
                   "Usted no tiene nada en el S&amp;P 500: se usa como <b>regla para medir</b>. Es un fondo con las 500 "
                   "empresas m\u00e1s grandes de EE. UU., la opci\u00f3n m\u00e1s simple que existe. Si el mismo dinero lo "
                   "hubiera puesto ah\u00ed en las mismas fechas, ir\u00eda " + _c(r["ref_pct"]) + ". "
                   + ("<b>Sus elecciones le van ganando</b> por " if dif >= 0 else "<b>Por ahora el \u00edndice va mejor</b> por ")
                   + ("%.1f" % abs(dif)).replace(".", ",") + " puntos."]
    lineas += ["", "\U0001F4B5 <b>Dividendos</b>",
               "En los \u00faltimos 12 meses sus empresas le pagaron " + _c(r["dividendos_pct"], 2).lstrip("+")
               + " de lo invertido (dinero que reparten a sus accionistas, ya descontado el impuesto)."]

    lineas += ["", "\U0001F4CB <b>Sus acciones</b>", "<i>cu\u00e1nto pesa en su portafolio \u00b7 cu\u00e1nto gana o pierde \u00b7 c\u00f3mo le fue hoy</i>"]
    for p in pos:
        lineas.append("\u2022 " + _nombre(p) + "\n   " + "%.0f" % p["peso"] + " % \u00b7 " + _c(p["ganancia_pct"])
                      + " \u00b7 hoy " + _c(p["hoy_pct"]))

    grupos = {}
    for p in pos:
        for clave, _ in senales(p):
            grupos.setdefault(clave, []).append(p["yahoo"])
    if grupos:
        lineas += ["", "\U0001F50E <b>Para tener en cuenta</b>"]
        for clave in ("peso", "hoy", "max", "min", "media"):
            if clave in grupos:
                quienes = grupos[clave]
                lista = (", ".join(quienes[:-1]) + " y " + quienes[-1]) if len(quienes) > 1 else quienes[0]
                texto = EXPLICA[clave]
                if len(quienes) == 1:                      # singular
                    texto = (texto.replace("est\u00e1n", "est\u00e1").replace("vienen", "viene").replace("vayan", "vaya")
                             .replace("las compr\u00f3", "la compr\u00f3").replace("ocupan", "ocupa")
                             .replace("tuvieron", "tuvo"))
                lineas.append("\u2022 <b>" + escape(lista) + "</b> " + texto)
    man = r.get("manuales") or {}
    if man.get("cambios"):
        lineas += ["", "\u270D\uFE0F <b>Cambios que me cont\u00f3</b> <i>(hasta su pr\u00f3ximo informe de XTB)</i>",
                   escape("; ".join(man["cambios"])) + "."]
        if man.get("sin_cantidad"):
            lineas.append("Sin cantidad no entran en los porcentajes: " + escape(", ".join(man["sin_cantidad"])) +
                          ". D\u00edgame \u00abfueron 3 acciones a 140\u00bb justo despu\u00e9s de contarme la compra.")
    if r.get("sin_precio"):
        lineas += ["", "\u2139\uFE0F Sin precio actual para " + escape(", ".join(r["sin_precio"])) + ": uso el del informe de XTB."]
    if r["fecha_informe"]:
        dias = (datetime.now() - r["fecha_informe"]).days
        if dias >= 7:
            lineas += ["", "\u26A0\uFE0F Su informe de XTB tiene " + str(dias) + " d\u00edas: si compr\u00f3 o vendi\u00f3 algo, "
                       "exporte uno nuevo o d\u00edgamelo (\u00abcompr\u00e9 NVDA\u00bb, \u00abvend\u00ed V\u00bb)."]
    lineas += ["", "<i>Esto es informaci\u00f3n, no una recomendaci\u00f3n. Las decisiones son suyas.</i>"]
    return "\n".join(lineas)


def texto_ia(r):
    """Resumen compacto (porcentajes) para que la IA pueda comentarlo sin hacer cuentas."""
    partes = ["Portafolio: ganancia " + _s(r["ganancia_pct"]) + ", hoy " + _s(r["hoy_pct"], 2)]
    if r["ref_pct"] is not None:
        partes.append("S&P 500 en las mismas fechas " + _s(r["ref_pct"]))
    for p in r["posiciones"]:
        partes.append(p["yahoo"] + ": peso " + "%.0f" % p["peso"] + " %, ganancia " + _s(p["ganancia_pct"])
                      + ", hoy " + _s(p["hoy_pct"]) + ("; " + "; ".join(t for _, t in senales(p)) if senales(p) else ""))
    man = r.get("manuales") or {}
    if man.get("cambios"):
        partes.append("Cambios que el usuario contó desde su último informe de XTB: " + "; ".join(man["cambios"]))
    return ". ".join(partes) + "."


# ------------------------------------------------------------------ informes nuevos ---
PATRON_XTB = re.compile(r"^[A-Z]{3}_\d{5,}_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.xlsx$")


def recoger_informes():
    """Si hay un Excel recien exportado de XTB en Descargas, lo mueve a la carpeta privada.
    Devuelve la ruta nueva o None."""
    import shutil
    movido = None
    for carpeta in ajustes()["carpetas_descargas"]:
        c = Path(carpeta)
        if not c.exists():
            continue
        for f in c.glob("*.xlsx"):
            if PATRON_XTB.match(f.name):
                xtb.CARPETA.mkdir(parents=True, exist_ok=True)
                destino = xtb.CARPETA / ("xtb_operaciones_" + datetime.now().strftime("%Y-%m-%d_%H%M") + ".xlsx")
                shutil.move(str(f), destino)
                log.info("Informe de XTB movido a la carpeta privada: %s", destino.name)
                movido = destino
    if movido:
        _cache["datos"] = None
    return movido


# ------------------------------------------------------------------ uso en la PC ---
if __name__ == "__main__":
    if "--diagnostico" in sys.argv:
        print(xtb.diagnostico())
        raise SystemExit
    r = calcular(usar_cache=False)
    print("Archivo:", r["archivo"], "| precios:", r["fuente"])
    print("Valor: %.2f  Costo: %.2f  Ganancia: %.2f (%s)  Hoy: %s" % (r["valor"], r["costo"], r["ganancia"],
                                                                      _s(r["ganancia_pct"]), _s(r["hoy_pct"], 2)))
    if r["ref_pct"] is not None:
        print("Mismo dinero en el S&P 500 en las mismas fechas: %s" % _s(r["ref_pct"]))
    print("Dividendos netos 12 meses: %.2f   Ventas cerradas 12 meses: %.2f" % (r["dividendos_12m"], r["realizado_12m"]))
    print("\n%-8s %9s %9s %9s %10s %9s %6s %9s" % ("Ticker", "Acciones", "Promedio", "Precio", "Valor", "Ganancia", "Peso", "Hoy"))
    for p in r["posiciones"]:
        print("%-8s %9.4f %9.2f %9.2f %10.2f %9s %5.1f%% %9s" % (p["yahoo"], p["acciones"], p["promedio"], p["precio"],
                                                                p["valor"], _s(p["ganancia_pct"]), p["peso"], _s(p["hoy_pct"], 2)))
        if senales(p):
            print("         -> " + "; ".join(t for _, t in senales(p)))
    print("\nAsi se vera en Telegram (sin montos):\n")
    print(re.sub(r"<[^>]+>", "", texto_telegram(r)).replace("&amp;", "&").replace("&#x27;", "'"))
