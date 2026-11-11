"""El asistente aprende los habitos de dinero del usuario (todo calculado en CODIGO, mes a mes).

- historial(): evolucion de los ultimos meses (gastos, ingresos, ahorro, categoria principal).
- habitos(): promedio mensual por categoria y monto tipico por comercio (de los meses anteriores).
- revisar_consumo(): ante un consumo del BANCO, detecta lo raro (cobro doble, monto muy alto, comercio nuevo caro,
  otra moneda) y devuelve una pregunta "¿Fue usted?".
- contexto_ia(): resumen financiero para que la IA lo tenga presente en cada conversacion.
- semana(): mensaje de los domingos (lo bueno, lo que vigilar y una sugerencia).
"""
import statistics
from collections import defaultdict
from datetime import date, timedelta

from modulos.comun.base import ahora, registro
from modulos.finanzas import gastos
from modulos.finanzas.deudas import fmt

log = registro("finanzas")


def _meses_atras(n, hoy=None):
    """Lista de (anio, mes) de los n meses anteriores al actual (el mas reciente primero)."""
    hoy = hoy or ahora().date()
    a, m, salida = hoy.year, hoy.month, []
    for _ in range(n):
        m -= 1
        if m == 0:
            a, m = a - 1, 12
        salida.append((a, m))
    return salida


def _datos_mes(anio, mes):
    a, b = gastos.mes(anio, mes)
    g = [x for x in gastos.del_periodo(a, b, "gasto") if x["monto"] > 0]
    i = gastos.del_periodo(a, b, "ingreso")
    por_cat = defaultdict(float)
    for x in g:
        por_cat[x["categoria"]] += x["monto"]
    return {"gastos": round(sum(x["monto"] for x in g), 2), "ingresos": round(sum(x["monto"] for x in i), 2),
            "por_cat": dict(por_cat), "n": len(g)}


def historial(n=6, hoy=None):
    hoy = hoy or ahora().date()
    filas = []
    for anio, mes in [(hoy.year, hoy.month)] + _meses_atras(n - 1, hoy):
        d = _datos_mes(anio, mes)
        if d["n"] or d["ingresos"]:
            filas.append((anio, mes, d))
    if not filas:
        return "Aún no hay meses registrados."
    lineas = ["📅 Su dinero mes a mes", ""]
    previo = None
    for anio, mes, d in reversed(filas):
        nombre = gastos.MESES[mes - 1].capitalize() + ((" " + str(anio)) if anio != hoy.year else "")
        actual = (anio, mes) == (hoy.year, hoy.month)
        texto = "• " + nombre + (" (en curso)" if actual else "") + ": gastó " + fmt(d["gastos"])
        if previo and previo["gastos"] and not actual:
            cambio = (d["gastos"] / previo["gastos"] - 1) * 100
            texto += " (igual que el mes anterior)" if abs(cambio) < 1 else " (" + ("↑" if cambio > 0 else "↓") + str(abs(round(cambio))) + " %)"
        if d["ingresos"]:
            ahorro = d["ingresos"] - d["gastos"]
            texto += " · entró " + fmt(d["ingresos"]) + " · " + ("ahorró " if ahorro >= 0 else "faltó ") + fmt(abs(ahorro))
        if d["por_cat"]:
            top = max(d["por_cat"].items(), key=lambda x: x[1])
            texto += "\n   donde más: " + top[0] + " " + fmt(top[1])
        lineas.append(texto)
        previo = d
    h = habitos(hoy)
    if h["meses"]:
        lineas += ["", "Su promedio (" + str(h["meses"]) + " mes" + ("es" if h["meses"] > 1 else "") + " completos): "
                   + fmt(h["total"]) + " al mes"]
        lineas += ["   " + c + ": " + fmt(v) for c, v in sorted(h["por_cat"].items(), key=lambda x: -x[1])[:6]]
    return "\n".join(lineas)


def habitos(hoy=None, meses=6):
    """Promedios de los meses COMPLETOS anteriores que tengan datos."""
    datos = [_datos_mes(a, m) for a, m in _meses_atras(meses, hoy)]
    datos = [d for d in datos if d["n"] >= 3]
    por_cat = defaultdict(list)
    for d in datos:
        for c, v in d["por_cat"].items():
            por_cat[c].append(v)
    n = len(datos)
    return {"meses": n, "total": round(sum(d["gastos"] for d in datos) / n, 2) if n else 0,
            "por_cat": {c: round(sum(v) / n, 2) for c, v in por_cat.items()} if n else {}}


def _historial_comercio(desc, excluir_id, dias=180):
    hoy = ahora().date()
    n = gastos._norm(desc)
    return [x for x in gastos.del_periodo(hoy - timedelta(days=dias), hoy, "gasto")
            if gastos._norm(x["descripcion"]) == n and x["id"] != excluir_id and x["monto"] > 0]


def revisar_consumo(mid):
    """Para consumos del banco: devuelve el motivo de duda (texto) o None si parece normal."""
    g = gastos.obtener(mid)
    if not g or g["tipo"] != "gasto" or g["monto"] <= 0:
        return None
    dia = date.fromisoformat(g["fecha"])
    mismos = _historial_comercio(g["descripcion"], mid)
    dobles = [x for x in mismos if abs(x["monto"] - g["monto"]) < 0.01 and abs((date.fromisoformat(x["fecha"]) - dia).days) <= 1]
    if dobles:
        return "se cobró dos veces lo mismo (" + fmt(g["monto"]) + " en " + g["descripcion"] + ")"
    if "(" in g["descripcion"] and any(m in g["descripcion"] for m in ("EUR", "COP", "PEN", "GBP", "MXN", "BRL")):
        otras = [x for x in gastos.del_periodo(dia - timedelta(days=365), dia, "gasto")
                 if x["id"] != mid and any(m in x["descripcion"] for m in ("EUR ", "COP ", "PEN ", "GBP ", "MXN ", "BRL "))]
        if not otras:
            return "es una compra en otra moneda y no suele hacer compras así"
    if len(mismos) >= 3:
        tipico = statistics.median(x["monto"] for x in mismos)
        if g["monto"] > max(3 * tipico, tipico + 30):
            return "en " + g["descripcion"] + " suele gastar unos " + fmt(tipico) + " y este es de " + fmt(g["monto"])
    else:
        h = habitos()
        prom = h["por_cat"].get(g["categoria"], 0)
        if not mismos and g["monto"] >= 80 and (not prom or g["monto"] > 1.5 * prom):
            return "es un comercio nuevo para usted y el monto es alto (" + fmt(g["monto"]) + ")"
    return None


def texto_pregunta(mid, motivo):
    g = gastos.obtener(mid)
    return ("🔍 ¿Fue usted? Llegó un consumo de " + fmt(g["monto"]) + " en " + g["descripcion"] + " (" + g["medio"] + "): "
            + motivo + ".")


def texto_no_reconocido(mid):
    g = gastos.obtener(mid)
    return ("🚨 Marqué el consumo de " + fmt(g["monto"]) + " en " + g["descripcion"] + " como NO reconocido (no cuenta en sus gastos).\n\n"
            "Qué hacer ahora:\n1. Llame a " + g["medio"].split()[0] + " al número que está en el reverso de su tarjeta "
            "(o desde la app oficial) y pida bloquearla y desconocer el consumo.\n2. No responda correos, mensajes ni llamadas "
            "que le pidan claves o códigos: el banco nunca los pide.\n3. Revise los últimos movimientos en la app del banco.")


# ------------------------------------------------------------------ para la IA ---
def contexto_ia():
    """Texto compacto con la situacion financiera actual (va en las instrucciones de la IA, solo en la PC)."""
    from modulos.finanzas import ahorros, deudas, presupuesto
    hoy = ahora().date()
    partes = []
    total, detalle = presupuesto.ingresos_mes(hoy)
    gastado = presupuesto.gastado_mes(hoy)
    if presupuesto.sueldo():
        partes.append("Sueldo " + fmt(presupuesto.sueldo()) + "/mes" + (", le pagan el " + str(presupuesto.dia_pago())
                                                                         if presupuesto.dia_pago() else ""))
    if total:
        partes.append("Este mes: ingresos " + fmt(total) + ", gastado " + fmt(gastado) + " (" + str(round(gastado / total * 100))
                      + " %) con el " + str(presupuesto.avance_del_mes(hoy)) + " % del mes transcurrido")
    else:
        partes.append("Este mes gastado " + fmt(gastado))
    a_mes = hoy.replace(day=1)
    invertido = gastos.del_periodo(a_mes, hoy, "inversion")
    if invertido:
        partes.append("Este mes INVIRTIÓ " + fmt(sum(i["monto"] for i in invertido)) + " (" + ", ".join(
            i["descripcion"] + " " + fmt(i["monto"]) for i in invertido[:4]) + "): es inversión, NO cuenta como gasto "
            "ni en el presupuesto")
    tops = presupuesto.presupuestos()
    if tops:
        partes.append("Presupuestos: " + ", ".join(c + " " + fmt(presupuesto.gastado_mes(hoy, c)) + "/" + fmt(v) for c, v in tops.items()))
    lista = ahorros.activos()
    if lista:
        partes.append("Ahorros programados: " + "; ".join(ahorros.linea(a)[2:] for a in lista))
    h = habitos(hoy)
    if h["meses"]:
        partes.append("Promedio mensual de gastos " + fmt(h["total"]) + " (" + ", ".join(
            c + " " + fmt(v) for c, v in sorted(h["por_cat"].items(), key=lambda x: -x[1])[:5]) + ")")
    me = sum(deudas.saldo(d["id"]) for d in deudas.abiertas(sentido="me_debe"))
    yo = sum(deudas.saldo(d["id"]) for d in deudas.abiertas(sentido="le_debo"))
    if me or yo:
        partes.append("Deudas: le deben " + fmt(me) + ", él debe " + fmt(yo))
    return ". ".join(partes) + "."


GUIA_DINERO = ("GUIA DE DINERO (para aconsejar al usuario con sus numeros reales de arriba): usa la regla 50/30/20 como "
               "referencia (necesidades/gustos/ahorro); recomienda un fondo de emergencia de 3 a 6 meses de gastos; pagar "
               "SIEMPRE el total de las tarjetas para no pagar intereses; antes de una compra grande, comparar con lo que le "
               "queda del mes y sus presupuestos; avisarle con tacto si va gastando mas rapido de lo que avanza el mes. "
               "Si algo no cuadra con sus habitos, preguntale. No recomiendes acciones ni inversiones concretas, ni "
               "productos financieros; no inventes cifras: si un dato no esta, dilo.")


# ------------------------------------------------------------------ domingo ---
def semana(hoy=None):
    from modulos.finanzas import ahorros, presupuesto
    hoy = hoy or ahora().date()
    lunes = hoy - timedelta(days=hoy.weekday())
    sem = [x for x in gastos.del_periodo(lunes, hoy, "gasto") if x["monto"] > 0]
    total = sum(x["monto"] for x in sem)
    lineas = ["📈 Su semana financiera", "", "Esta semana gastó " + fmt(total) + " en " + str(len(sem)) + " gastos."]
    por_cat = defaultdict(float)
    for x in sem:
        por_cat[x["categoria"]] += x["monto"]
    if por_cat:
        top = max(por_cat.items(), key=lambda x: x[1])
        lineas.append("Donde más: " + top[0] + " (" + fmt(top[1]) + ").")
    bien, vigilar = [], []
    tot, _ = presupuesto.ingresos_mes(hoy)
    if tot:
        pct = presupuesto.gastado_mes(hoy) / tot * 100
        paso = presupuesto.avance_del_mes(hoy)
        (bien if pct <= paso else vigilar).append("lleva " + str(round(pct)) + " % de su dinero del mes con el " + str(paso)
                                                  + " % del mes" + (" — va a buen ritmo" if pct <= paso else " — va más rápido que el mes"))
    for c, tope in presupuesto.presupuestos().items():
        pct = presupuesto.gastado_mes(hoy, c) / tope * 100
        if pct >= 80:
            vigilar.append(c + " va en " + str(round(pct)) + " % de su presupuesto")
    h = habitos(hoy)
    for c, v in por_cat.items():
        semanal = h["por_cat"].get(c, 0) / 4.3
        if semanal and v > 1.8 * semanal and v - semanal > 15:
            vigilar.append("en " + c + " gastó " + fmt(v) + ", más del doble de lo normal por semana (" + fmt(semanal) + ")")
    for a in ahorros.activos():
        if a["meta"] and (a["saldo"] or 0) >= a["meta"]:
            bien.append("¡su ahorro «" + a["nombre"] + "» llegó a la meta!")
    if bien:
        lineas += ["", "✅ Bien:"] + ["• " + b for b in bien]
    if vigilar:
        lineas += ["", "👀 Para vigilar:"] + ["• " + v for v in vigilar]
    if not presupuesto.presupuestos():
        lineas += ["", "💡 Sugerencia: póngase presupuestos («sugiéreme un presupuesto») para que le avise antes de pasarse."]
    elif vigilar:
        lineas += ["", "💡 Sugerencia: esta semana intente compensar en lo que más se pasó; cada dólar que no gaste puede ir a su ahorro."]
    else:
        lineas += ["", "💡 Sugerencia: si le sobra al final del mes, súmelo a uno de sus ahorros."]
    return "\n".join(lineas)
