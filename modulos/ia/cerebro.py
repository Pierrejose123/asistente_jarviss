"""Fase 2, paso 1: conversacion fluida por Telegram con la IA local (Ollama + tool calling).

La IA entiende lo que escribes y elige una "herramienta"; el CODIGO ejecuta la accion real
con los datos reales. Reglas:
  - Crear tareas, consultar el dia y marcar como hecha: se hacen directo (es una orden tuya).
  - Borrar: NUNCA directo; el bot pide confirmacion con botones.
  - Cuentas: siempre con la calculadora (la IA no hace aritmetica de memoria).
"""
import ast
import json
import operator
import re
from html import unescape

from datetime import datetime, timedelta

import requests

from modulos.comun.base import CONFIG, DIAS, DIAS_BONITO, NOMBRE, PERFIL, ahora, leer_json, registro
from modulos.ia import memoria
from modulos.tareas import tareas

log = registro("ia")
DIAS_LISTA = DIAS


def config():
    base = {"modelo": "qwen3.5:9b", "ollama": "http://127.0.0.1:11434", "keep_alive": "10m", "memoria": 12}
    if (CONFIG / "ia.json").exists():
        base.update(leer_json("ia.json"))
    base["opciones"] = {}
    try:                                     # modo juego/diseno: modelo chico solo en el procesador
        from modulos.comun import modos
        modelo, opciones, keep = modos.modelo_y_opciones(base["modelo"])
        if modelo != base["modelo"]:
            base.update(modelo=modelo, opciones=opciones, keep_alive=keep, modo_ligero=True)
    except Exception as exc:
        log.info("No pude revisar el modo juego/diseno: %s", exc)
    return base


HERRAMIENTAS = [
    {"type": "function", "function": {
        "name": "crear_tarea",
        "description": "Anota una tarea, deber, entrega o recordatorio con su fecha. Usala cuando el usuario pida anotar, "
                       "recordar o agendar algo que debe hacer.",
        "parameters": {"type": "object", "properties": {
            "descripcion": {"type": "string", "description": "Que hay que hacer, corto. Ej: 'afiche de color'"},
            "fecha": {"type": "string", "description": "hoy, manana, pasado manana, lunes..domingo o DD/MM"},
            "materia": {"type": "string", "description": "Materia de clase si la menciona (ej. 'grafica digital'), si no vacio"},
            "hora": {"type": "string", "description": "HH:MM si la menciona, si no vacio"}},
            "required": ["descripcion", "fecha"]}}},
    {"type": "function", "function": {
        "name": "crear_evento",
        "description": "Agenda una actividad CON HORA (reunion, estudio, gimnasio, cita, llamada), una vez o repetida "
                       "cada semana. Se guarda en el asistente y en Google Calendar con aviso previo. "
                       "Si hay choque con otra actividad, NO se crea: pregunta al usuario y, si confirma, repite con forzar=true.",
        "parameters": {"type": "object", "properties": {
            "titulo": {"type": "string", "description": "Nombre corto. Ej: 'Reunion con cliente'"},
            "fecha": {"type": "string", "description": "Primera fecha en DD/MM (usa el calendario del sistema). Vacio si se repite desde hoy"},
            "hora_inicio": {"type": "string", "description": "HH:MM en 24 horas, ej. 15:00"},
            "hora_fin": {"type": "string", "description": "HH:MM en 24 horas; vacio si no la dijo"},
            "duracion_minutos": {"type": "integer", "description": "Si no hay hora_fin; por defecto 60"},
            "repetir": {"type": "array", "items": {"type": "string"},
                        "description": "Dias si se repite cada semana: lunes, martes, miercoles, jueves, viernes, sabado, domingo"},
            "hasta": {"type": "string", "description": "DD/MM ultima fecha si se repite; vacio = 6 meses"},
            "aviso_minutos": {"type": "integer", "description": "Minutos antes para avisar; por defecto 15"},
            "forzar": {"type": "boolean", "description": "true solo si el usuario confirmo crearlo pese al choque"}},
            "required": ["titulo", "hora_inicio"]}}},
    {"type": "function", "function": {
        "name": "editar_evento",
        "description": "Cambia una actividad con hora YA EXISTENTE (por su numero): hora, dias, fecha, titulo o aviso. "
                       "Usala para 'cambia', 'mueve' o 'pasa a otra hora'. Nunca crees una nueva para cambiar una existente.",
        "parameters": {"type": "object", "properties": {
            "numero": {"type": "integer"},
            "titulo": {"type": "string"},
            "fecha": {"type": "string", "description": "DD/MM (solo actividades de una vez)"},
            "hora_inicio": {"type": "string", "description": "HH:MM 24 h"},
            "hora_fin": {"type": "string", "description": "HH:MM 24 h; si cambias solo el inicio se conserva la duracion"},
            "repetir": {"type": "array", "items": {"type": "string"}},
            "aviso_minutos": {"type": "integer"},
            "forzar": {"type": "boolean"}},
            "required": ["numero"]}}},
    {"type": "function", "function": {
        "name": "ver_actividades", "description": "Lista las actividades con hora agendadas (unicas y repetidas) con su numero.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "borrar_evento",
        "description": "Pide borrar una actividad con hora por su numero. No la borra: el sistema pedira confirmacion.",
        "parameters": {"type": "object", "properties": {"numero": {"type": "integer"}}, "required": ["numero"]}}},
    {"type": "function", "function": {
        "name": "ver_dia",
        "description": "Consulta clases, entregas y avisos de un dia (hoy, manana, un dia de la semana o DD/MM).",
        "parameters": {"type": "object", "properties": {"fecha": {"type": "string"}}, "required": ["fecha"]}}},
    {"type": "function", "function": {
        "name": "ver_semana",
        "description": "Consulta la semana completa (lunes a domingo): clases, entregas y avisos de cada dia. "
                       "Usala para preguntas sobre la semana o varios dias.",
        "parameters": {"type": "object", "properties": {
            "cual": {"type": "string", "enum": ["esta", "siguiente"], "description": "esta semana o la siguiente"}},
            "required": ["cual"]}}},
    {"type": "function", "function": {
        "name": "ver_tareas", "description": "Lista todas las tareas pendientes con su numero.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "marcar_hecha", "description": "Marca como terminada una tarea pendiente por su numero.",
        "parameters": {"type": "object", "properties": {"numero": {"type": "integer"}}, "required": ["numero"]}}},
    {"type": "function", "function": {
        "name": "borrar_tarea",
        "description": "Pide borrar una tarea por su numero. No la borra: el sistema pedira confirmacion al usuario.",
        "parameters": {"type": "object", "properties": {"numero": {"type": "integer"}}, "required": ["numero"]}}},
    {"type": "function", "function": {
        "name": "recordar",
        "description": "Guarda en la memoria permanente un dato util sobre el usuario: preferencias, gustos, correcciones, "
                       "datos estables de su vida o trabajo. Usala por iniciativa propia cuando el usuario cuente algo asi "
                       "(ej. 'tengo 32 GB de RAM', 'mi procesador es i5 14600KF', 'prefiero estudiar de noche'). "
                       "NO guardes contrasenas, montos de dinero ni datos sensibles.",
        "parameters": {"type": "object", "properties": {
            "dato": {"type": "string", "description": "Una frase corta en tercera persona. Ej: 'Prefiere estudiar de noche'"}},
            "required": ["dato"]}}},
    {"type": "function", "function": {
        "name": "actualizar_recuerdo",
        "description": "Reescribe un recuerdo que ya existe para completarlo o corregirlo. Usala EN LUGAR de 'recordar' "
                       "cuando el dato nuevo trata del mismo tema que un recuerdo de la lista (ej. mas datos de su PC -> "
                       "actualiza el recuerdo de la PC). 'dato' es el texto completo final, uniendo lo viejo y lo nuevo.",
        "parameters": {"type": "object", "properties": {
            "numero": {"type": "integer"}, "dato": {"type": "string"}}, "required": ["numero", "dato"]}}},
    {"type": "function", "function": {
        "name": "olvidar_recuerdo", "description": "Borra un dato de la memoria permanente por su numero (cuando el usuario lo pida o ya no sea cierto).",
        "parameters": {"type": "object", "properties": {"numero": {"type": "integer"}}, "required": ["numero"]}}},
    {"type": "function", "function": {
        "name": "anotar_deuda",
        "description": "Registra dinero que alguien le debe al usuario o que el usuario debe, o un pago de esa deuda. "
                       "tipo: me_debe (alguien le debe o le presto), le_debo (el usuario debe), me_pago (le pagaron/abonaron), "
                       "le_pague (el usuario pago). El codigo calcula el saldo.",
        "parameters": {"type": "object", "properties": {
            "persona": {"type": "string"}, "monto": {"type": "number"},
            "tipo": {"type": "string", "enum": ["me_debe", "le_debo", "me_pago", "le_pague"]},
            "concepto": {"type": "string", "description": "Por que (opcional), ej. 'la laptop'"}},
            "required": ["persona", "monto", "tipo"]}}},
    {"type": "function", "function": {
        "name": "anotar_gasto",
        "description": "Registra un gasto o un ingreso de dinero del usuario (no deudas). El codigo pone la categoria y suma.",
        "parameters": {"type": "object", "properties": {
            "tipo": {"type": "string", "enum": ["gasto", "ingreso"]}, "monto": {"type": "number"},
            "descripcion": {"type": "string", "description": "En que gasto o de donde vino, corto. Ej: 'almuerzo'"},
            "medio": {"type": "string", "description": "Tarjeta o medio si lo dijo: Diners, Pichincha, Produbanco, efectivo, debito"},
            "fecha": {"type": "string", "description": "hoy, ayer o DD/MM; vacio = hoy"}},
            "required": ["tipo", "monto", "descripcion"]}}},
    {"type": "function", "function": {
        "name": "ver_gastos",
        "description": "Resumen de gastos e ingresos (calculado en codigo). periodo: 'este mes', 'esta semana', "
                       "'mes pasado', 'octubre'... Puede incluir una categoria, ej. 'comida este mes'.",
        "parameters": {"type": "object", "properties": {"periodo": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "guardar_ahorro",
        "description": "Crea o actualiza un ahorro programado del usuario (ej. sus 2 de Produbanco): nombre corto, para que es, "
                       "saldo actual, aporte mensual, dia del aporte, meta y fecha de la meta. Solo pon los datos que dijo.",
        "parameters": {"type": "object", "properties": {
            "nombre": {"type": "string", "description": "Nombre corto, ej. 'Viaje', 'Emergencias'"},
            "para_que": {"type": "string"}, "banco": {"type": "string"},
            "saldo": {"type": "number"}, "aporte_mensual": {"type": "number"},
            "dia_aporte": {"type": "integer"}, "meta": {"type": "number"},
            "fecha_meta": {"type": "string", "description": "MM/AAAA o DD/MM/AAAA"}},
            "required": ["nombre"]}}},
    {"type": "function", "function": {
        "name": "ver_ahorros_historial",
        "description": "Ahorros programados del usuario y la evolucion de su dinero mes a mes (calculado en codigo).",
        "parameters": {"type": "object", "properties": {"que": {"type": "string", "enum": ["ahorros", "historial"]}}}}},
    {"type": "function", "function": {
        "name": "ver_presupuesto",
        "description": "Cuanto del sueldo/ingresos del mes lleva gastado el usuario, cuanto le queda y como van sus "
                       "presupuestos por categoria (calculado en codigo). categoria opcional.",
        "parameters": {"type": "object", "properties": {"categoria": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "ver_deudas",
        "description": "Saldo y pagos de las deudas (quien le debe al usuario y a quien le debe el). persona opcional.",
        "parameters": {"type": "object", "properties": {"persona": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "ver_portafolio",
        "description": "Estado del portafolio de acciones del usuario en XTB (en porcentajes, calculado en codigo): "
                       "ganancia, peso de cada accion, movimiento de hoy, comparacion con el S&P 500 y observaciones. "
                       "Usala cuando pregunte por sus acciones o inversiones. Solo informa: nunca digas que compre o venda.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "leer_noticia",
        "description": "Investiga una noticia o tema de actualidad: lee el articulo guardado (si existe) Y busca en "
                       "internet. Usala SIN PREGUNTAR siempre que el usuario pregunte algo de noticias, empresas, economia, "
                       "politica, leyes, multas, mercados o el mundo. 'cual' es el numero del resumen (ej. '3') o la "
                       "pregunta con sus nombres propios (ej. 'multas Apple Amazon Union Europea').",
        "parameters": {"type": "object", "properties": {"cual": {"type": "string"}}, "required": ["cual"]}}},
    {"type": "function", "function": {
        "name": "calcular",
        "description": "Calculadora exacta. Usala SIEMPRE para cualquier cuenta. Ej: '1250*0.15', '(30+45)/2'.",
        "parameters": {"type": "object", "properties": {"expresion": {"type": "string"}}, "required": ["expresion"]}}},
]


# En modo juego/diseno el modelo chico se confunde con muchas herramientas: solo las basicas.
LIGERAS = {"crear_tarea", "crear_evento", "ver_dia", "ver_tareas", "marcar_hecha", "borrar_tarea", "calcular"}


# ------------------------------------------------------------------ calculadora segura ---
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def _evaluar(nodo):
    if isinstance(nodo, ast.Expression):
        return _evaluar(nodo.body)
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)):
        return nodo.value
    if isinstance(nodo, ast.BinOp) and type(nodo.op) in _OPS:
        if isinstance(nodo.op, ast.Pow) and abs(_evaluar(nodo.right)) > 100:
            raise ValueError("exponente demasiado grande")
        return _OPS[type(nodo.op)](_evaluar(nodo.left), _evaluar(nodo.right))
    if isinstance(nodo, ast.UnaryOp) and type(nodo.op) in _OPS:
        return _OPS[type(nodo.op)](_evaluar(nodo.operand))
    raise ValueError("expresion no permitida")


def calcular(expresion):
    expr = expresion.replace(",", ".").replace("x", "*").replace("×", "*").replace("%", "/100")
    valor = _evaluar(ast.parse(expr, mode="eval"))
    return round(valor, 6) if isinstance(valor, float) else valor


# ------------------------------------------------------------------ herramientas ---
def _fecha(texto):
    partes = (texto or "").strip().split()
    if not partes:
        return None
    if len(partes) >= 2:
        f, n = tareas._fecha(partes[0], partes[1])
        if n == 2:
            return f
    return tareas._fecha(partes[-1])[0]


def _sin_html(texto):
    return unescape(re.sub(r"<[^>]+>", "", texto))


def _hora(texto):
    t = (texto or "").lower().replace(" ", "").replace(".", "").replace("h", ":").rstrip(":")
    pm, am = t.endswith("pm"), t.endswith("am")
    t = t.replace("pm", "").replace("am", "")
    if not t:
        return None
    partes = t.split(":")
    h, m = int(partes[0]), int(partes[1] or 0) if len(partes) > 1 and partes[1] else 0
    if pm and h < 12:
        h += 12
    if am and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return "%02d:%02d" % (h, m)


def _dias(lista):
    from modulos.tareas.tareas import _sin_tildes
    if isinstance(lista, str):
        lista = [lista]
    salida = []
    for x in lista or []:
        x = _sin_tildes(str(x)).strip()
        if "fin" in x and "semana" in x:
            salida += ["sabado", "domingo"]
        elif "entre semana" in x or "laborable" in x:
            salida += ["lunes", "martes", "miercoles", "jueves", "viernes"]
        elif "todos" in x or "diario" in x or "cada dia" in x:
            salida += list(DIAS_LISTA)
        else:
            salida += [d for d in DIAS_LISTA if d in x]
    return ",".join(d for d in DIAS_LISTA if d in salida)


def crear_evento(args):
    from modulos.agenda import eventos
    inicio = _hora(args.get("hora_inicio"))
    if not inicio:
        return "Falta la hora de inicio (HH:MM). Pidela al usuario."
    dias = _dias(args.get("repetir"))
    f = _fecha(args.get("fecha")) if args.get("fecha") else None
    if not f:
        if not dias:
            return "Falta la fecha. Pidela al usuario."
        f = ahora().date()
    fin = _hora(args.get("hora_fin"))
    if not fin:
        t = datetime.strptime(inicio, "%H:%M") + timedelta(minutes=int(args.get("duracion_minutos") or 60))
        fin = t.strftime("%H:%M")
    hasta = _fecha(args.get("hasta")).isoformat() if args.get("hasta") and _fecha(args.get("hasta")) else None
    if not args.get("forzar"):
        cruces = eventos.choques(f, inicio, fin, dias, hasta)
        if cruces:
            return ("NO creado: se cruza con " + "; ".join(cruces) + ". Pregunta al usuario si igual lo agenda "
                    "(entonces repite con forzar=true) o prefiere otra hora.")
    eid = eventos.crear(args.get("titulo", "Actividad").strip()[:80], f, inicio, fin, dias, hasta,
                        int(args.get("aviso_minutos") or 15))
    try:
        eventos.subir(eid)
        extra = " Tambien quedo en Google Calendar con aviso previo."
    except Exception as exc:
        log.warning("Actividad %s sin subir a Google: %s", eid, exc)
        extra = " (No se pudo subir a Google Calendar ahora.)"
    return "Agendado: " + eventos.descripcion(eventos.obtener(eid)) + "." + extra


def editar_evento(args):
    from modulos.agenda import eventos
    e = eventos.obtener(int(args.get("numero", 0)))
    if not e or e["estado"] != "activo":
        return "No existe una actividad activa con ese numero."
    cambios = {}
    if args.get("titulo"):
        cambios["titulo"] = args["titulo"].strip()[:80]
    if args.get("hora_inicio"):
        ini = _hora(args["hora_inicio"])
        if not ini:
            return "No entendi la hora de inicio."
        cambios["inicio"] = ini
        if not args.get("hora_fin"):
            dur = (datetime.strptime(e["fin"], "%H:%M") - datetime.strptime(e["inicio"], "%H:%M")).seconds // 60
            cambios["fin"] = (datetime.strptime(ini, "%H:%M") + timedelta(minutes=dur or 60)).strftime("%H:%M")
    if args.get("hora_fin"):
        fin = _hora(args["hora_fin"])
        if fin:
            cambios["fin"] = fin
    if args.get("repetir"):
        dias = _dias(args["repetir"])
        if dias:
            cambios["dias"] = dias
    if args.get("fecha"):
        f = _fecha(args["fecha"])
        if f:
            cambios["fecha"] = f.isoformat()
    if args.get("aviso_minutos") is not None:
        cambios["aviso_min"] = int(args["aviso_minutos"])
    if not cambios:
        return "No se indico ningun cambio."
    nuevo = dict(e, **cambios)
    if not args.get("forzar"):
        from datetime import date as _date
        dia = max(_date.fromisoformat(nuevo["fecha"]), ahora().date())
        cruces = eventos.choques(dia, nuevo["inicio"], nuevo["fin"], nuevo["dias"], nuevo["hasta"], ignorar_id=e["id"])
        if cruces:
            return "NO cambiado: se cruza con " + "; ".join(cruces) + ". Pregunta al usuario (si confirma, forzar=true)."
    eventos.actualizar(e["id"], **cambios)
    try:
        eventos.subir(e["id"])
        extra = " Actualizado tambien en Google Calendar."
    except Exception as exc:
        log.warning("No se actualizo en Google: %s", exc)
        extra = " (No se pudo actualizar Google Calendar ahora.)"
    return "Cambiado: " + eventos.descripcion(eventos.obtener(e["id"])) + "." + extra


def semana(cual="esta"):
    """Resumen compacto de lunes a domingo, con datos reales."""
    from modulos.clases.agenda import clases_efectivas
    from modulos.habitos import habitos
    hoy = ahora()
    lunes = hoy - timedelta(days=hoy.weekday()) + timedelta(days=7 if cual == "siguiente" else 0)
    lineas = ["Semana del " + lunes.strftime("%d/%m") + " al " + (lunes + timedelta(days=6)).strftime("%d/%m") + ":"]
    for i in range(7):
        d = lunes + timedelta(days=i)
        partes = []
        clases = [c for c in clases_efectivas(d) if c["nota"] != "cancelada"]
        if clases:
            partes.append("clases: " + ", ".join(c["inicio"] + " " + c["materia"] for c in clases))
        entregas = tareas.para_fecha(d.date().isoformat())
        if entregas:
            partes.append("entregas: " + ", ".join("#" + str(t["id"]) + " " + t["titulo"] for t in entregas))
        from modulos.agenda import eventos
        for e in eventos.del_dia(d):
            partes.append(e["inicio"] + " " + e["titulo"])
        if habitos.toca_hoy(d):
            partes.append(habitos.nombre().lower() + " " + habitos.config()["hora"])
        lineas.append("- " + DIAS_BONITO[d.weekday()] + " " + d.strftime("%d/%m") + ": " + ("; ".join(partes) or "libre"))
    return "\n".join(lineas)


def ejecutar(nombre, args, ver_dia):
    """Ejecuta una herramienta. Devuelve (resultado_para_la_IA, accion_pendiente_o_None)."""
    try:
        if nombre == "crear_tarea":
            frase = " ".join(x for x in [args.get("materia") or "", args.get("descripcion", ""),
                                          args.get("fecha", ""), args.get("hora") or ""] if x)
            datos = tareas.interpretar(frase)
            if isinstance(datos, str):
                return "No pude anotarla: falta " + datos.replace("sin ", "") + ". Pide el dato al usuario.", None
            tid = tareas.crear(**datos)
            try:
                tareas.subir(tid)
                extra = " Tambien quedo en Google Calendar."
            except Exception as exc:
                log.warning("Tarea %s sin subir a Google: %s", tid, exc)
                extra = " (No se pudo subir a Google Calendar ahora.)"
            return "Tarea #" + str(tid) + " anotada: " + _sin_html(tareas.linea(tareas.obtener(tid))) + "." + extra, None
        if nombre == "ver_dia":
            f = _fecha(args.get("fecha"))
            if not f:
                return "No entendi la fecha.", None
            dia = ahora().replace(year=f.year, month=f.month, day=f.day)
            return _sin_html(ver_dia(dia, "Plan del " + DIAS_BONITO[f.weekday()])), None
        if nombre == "crear_evento":
            return crear_evento(args), None
        if nombre == "editar_evento":
            return editar_evento(args), None
        if nombre == "ver_actividades":
            from modulos.agenda import eventos
            lista = eventos.activos()
            return ("\n".join(eventos.descripcion(e) for e in lista) if lista else "No hay actividades agendadas."), None
        if nombre == "borrar_evento":
            from modulos.agenda import eventos
            e = eventos.obtener(int(args.get("numero", 0)))
            if not e or e["estado"] != "activo":
                return "No existe una actividad con ese numero.", None
            return "Se pidio confirmacion al usuario para borrar la actividad #" + str(e["id"]) + ".", ("borrar_evento", e["id"])
        if nombre == "ver_semana":
            return semana(args.get("cual", "esta")), None
        if nombre == "ver_tareas":
            lista = tareas.pendientes()
            return ("\n".join(_sin_html(tareas.linea(t)) for t in lista) if lista else "No hay tareas pendientes."), None
        if nombre in ("marcar_hecha", "borrar_tarea"):
            t = tareas.obtener(int(args.get("numero", 0)))
            if not t or t["estado"] != "pendiente":
                return "No existe una tarea pendiente con ese numero.", None
            if nombre == "borrar_tarea":
                return "Se pidio confirmacion al usuario para borrar la tarea #" + str(t["id"]) + ".", ("borrar", t["id"])
            tareas.cambiar_estado(t["id"], "hecha")
            try:
                tareas.subir(t["id"], hecha=True)
            except Exception as exc:
                log.warning("No se actualizo en Google: %s", exc)
            return "Tarea #" + str(t["id"]) + " (" + t["titulo"] + ") marcada como hecha. Quedan " + str(len(tareas.pendientes())) + " pendientes.", None
        if nombre == "recordar":
            return guardar_dato(args.get("dato", "")), None
        if nombre == "actualizar_recuerdo":
            ok = memoria.actualizar(int(args.get("numero", 0)), args.get("dato", ""))
            return ("Recuerdo actualizado." if ok else "No existe ese recuerdo."), None
        if nombre == "olvidar_recuerdo":
            ok = memoria.olvidar(int(args.get("numero", 0)))
            return ("Recuerdo borrado." if ok else "No existe ese recuerdo."), None
        if nombre == "guardar_ahorro":
            from modulos.finanzas import ahorros
            fm = (args.get("fecha_meta") or "").strip()
            fecha_meta = None
            m = re.match(r"^(?:(\d{1,2})/)?(\d{1,2})/(\d{4})$", fm)
            if m:
                import calendar as _cal
                anio, mes = int(m.group(3)), int(m.group(2))
                dia = int(m.group(1)) if m.group(1) else _cal.monthrange(anio, mes)[1]
                fecha_meta = "%04d-%02d-%02d" % (anio, mes, dia)
            aid, nuevo = ahorros.guardar(args["nombre"], args.get("saldo"), args.get("aporte_mensual"), args.get("dia_aporte"),
                                         args.get("meta"), fecha_meta, args.get("para_que"), args.get("banco"))
            return ("Ahorro " + ("creado" if nuevo else "actualizado") + ": " + ahorros.linea(ahorros.obtener(aid))[2:]), None
        if nombre == "ver_ahorros_historial":
            from modulos.finanzas import ahorros, perfil
            return (perfil.historial() if args.get("que") == "historial" else ahorros.resumen()), None
        if nombre == "ver_presupuesto":
            from modulos.finanzas import presupuesto
            cat = presupuesto.categoria_por_nombre(args["categoria"]) if args.get("categoria") else None
            return presupuesto.estado(cat), None
        if nombre in ("anotar_gasto", "ver_gastos"):
            from modulos.finanzas import gastos
            if nombre == "ver_gastos":
                return gastos.consulta(args.get("periodo") or "este mes"), None
            medio, _ = gastos.medio_de(args.get("medio") or "")
            f = _fecha(args.get("fecha")) if args.get("fecha") else None
            return gastos.ejecutar({"accion": args.get("tipo", "gasto"), "monto": float(args.get("monto") or 0),
                                    "descripcion": args.get("descripcion", ""), "medio": medio, "fecha": f}), None
        if nombre in ("anotar_deuda", "ver_deudas"):
            from modulos.finanzas import deudas
            if nombre == "ver_deudas":
                if args.get("persona"):
                    ds = deudas.abiertas(args["persona"])
                    return ("\n\n".join(deudas.detalle(x) for x in ds) if ds else "No hay deudas abiertas de esa persona."), None
                return deudas.resumen(), None
            accion = {"me_debe": "deuda_me", "le_debo": "deuda_yo", "me_pago": "pago_me", "le_pague": "pago_yo"}.get(args.get("tipo"))
            if not accion or not args.get("persona") or not args.get("monto"):
                return "Faltan datos (persona, monto o tipo). Pidelos al usuario.", None
            return deudas.ejecutar({"accion": accion, "persona": args["persona"], "monto": float(args["monto"]),
                                    "concepto": args.get("concepto") or ""}), None
        if nombre == "ver_portafolio":
            from modulos.portafolio import portafolio
            return portafolio.texto_ia(portafolio.calcular()), None
        if nombre == "leer_noticia":
            from modulos.noticias import noticias
            return noticias.para_herramienta(args.get("cual", "")), None
        if nombre == "calcular":
            return "Resultado exacto: " + str(calcular(args.get("expresion", ""))), None
    except Exception as exc:
        log.warning("Herramienta %s fallo: %s", nombre, exc)
        return "La accion fallo: " + str(exc)[:120], None
    return "Herramienta desconocida.", None


# ------------------------------------------------------------------ conversacion ---
def _calendario():
    hoy = ahora()
    lunes = hoy - timedelta(days=hoy.weekday())
    filas = []
    for semana_n, nombre in ((0, "Esta semana"), (1, "Semana siguiente")):
        dias = [lunes + timedelta(days=7 * semana_n + i) for i in range(7)]
        filas.append(nombre + ": " + ", ".join(DIAS_BONITO[d.weekday()] + " " + d.strftime("%d/%m") for d in dias))
    return " ".join(filas)


def _agenda_real():
    """Datos reales que se inyectan en CADA mensaje: la IA no necesita adivinar nada."""
    partes = [semana("esta"), semana("siguiente")]
    pend = tareas.pendientes()
    partes.append("Tareas pendientes: " + ("; ".join("#" + str(t["id"]) + " " + t["titulo"] + " (" + t["materia"]
                                                       + ", entrega " + t["entrega"] + ")" for t in pend) if pend else "ninguna"))
    try:
        from modulos.agenda import eventos
        acts = eventos.activos()
        partes.append("Actividades agendadas: " + ("; ".join(eventos.descripcion(e) for e in acts) if acts else "ninguna"))
    except Exception:
        pass
    return "\n".join(partes)


def _sistema():
    hoy = ahora()
    texto = ("Eres JARVIS, el asistente personal de " + NOMBRE + (" (" + PERFIL + ")" if PERFIL else "") + ": elegante, sereno, eficiente, con humor seco sutil. "
             "Tratalo de usted y llamalo solo 'senor'. Responde SIEMPRE en espanol. "
             "Conversacion: 1 a 3 frases. Agenda: detalla dia por dia (dia, hora y nombre), sin resumir ni agrupar. "
             "FORMATO (Telegram, texto plano): frases cortas y una linea en blanco entre ideas. Para listas, un elemento "
             "por linea empezando con '\u2022 '. Para la agenda, el dia en su propia linea (ej. 'Martes 20/10:') y debajo "
             "sus elementos con '\u2022 '. Nunca uses asteriscos, almohadillas ni markdown. "
             "Hoy es " + DIAS_BONITO[hoy.weekday()] + " " + hoy.strftime("%d/%m/%Y") + ", hora " + hoy.strftime("%H:%M")
             + " (hora local). Calendario de referencia (usalo para convertir 'el martes de la proxima semana' etc. "
             "a DD/MM, no calcules de memoria): " + _calendario() + ".\n\n"
             "LO QUE SABES DEL USUARIO (memoria permanente, con numero):\n"
             + "\n".join("#" + str(r["id"]) + " " + r["dato"] for r in memoria.recuerdos()) + "\n\n"
             "AGENDA REAL DEL USUARIO (unica fuente de verdad; lo que no aparece aqui NO existe):\n"
             + _agenda_real() + "\n\n"
             "REGLAS: Responde preguntas de agenda, clases y tareas SOLO con la agenda real de arriba o con las "
             "herramientas. JAMAS inventes clases, materias, horarios ni tareas. Si algo no esta, di que no lo tienes registrado. "
             "Si el usuario te corrige, revisa la agenda real y responde con el dato correcto. "
             "Tareas/entregas sin hora: crear_tarea. Actividades con hora NUEVAS: crear_evento. "
             "Para CAMBIAR o mover una actividad que ya existe usa editar_evento con su numero (de 'Actividades agendadas'); "
             "nunca crees un duplicado. Si ves dos actividades repetidas, avisale al usuario y ofrece borrar la sobrante. "
             "Cuentas: herramienta calcular. Preguntas generales: responde tu sin herramientas. "
             "Tras usar una herramienta, confirma en una frase lo que se hizo. "
             "Si el usuario pide borrar algo, llama directo a borrar_tarea o borrar_evento (el sistema le muestra botones); "
             "no le preguntes tu si esta seguro. "
             "MEMORIA: cuando el usuario cuente una preferencia, un dato estable o te corrija algo importante, usa 'recordar' "
             "sin pedir permiso. ANTES revisa la lista: si ya hay un recuerdo del mismo tema, usa 'actualizar_recuerdo' "
             "(une lo viejo y lo nuevo en un solo texto) en vez de crear otro. Si un recuerdo ya no es cierto, corrigelo "
             "con 'actualizar_recuerdo'. Si el usuario pide juntar dos recuerdos, actualiza uno y borra el otro con 'olvidar_recuerdo'. "
             "Si el usuario olvida algo que esta en la memoria o en la agenda, recuerdaselo con amabilidad.")
    try:
        from modulos.finanzas import perfil
        texto += "\n\nFINANZAS DEL USUARIO (datos reales, calculados en codigo): " + perfil.contexto_ia() + "\n" + perfil.GUIA_DINERO
    except Exception as exc:
        log.info("Sin contexto financiero: %s", exc)
    return texto.replace("senor", "se\u00f1or").replace("disenador", "dise\u00f1ador").replace("diseno", "dise\u00f1o")


def _llamar(mensajes, conf, con_herramientas=True):
    cuerpo = {"model": conf["modelo"], "messages": mensajes, "stream": False, "think": False,
              "keep_alive": conf["keep_alive"],
              "options": {"num_predict": 500, "temperature": 0.3, **conf.get("opciones", {})}}
    if con_herramientas:
        cuerpo["tools"] = ([h for h in HERRAMIENTAS if h["function"]["name"] in LIGERAS]
                           if conf.get("modo_ligero") else HERRAMIENTAS)
    r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=180)
    if r.status_code == 400 and "think" in r.text:
        cuerpo.pop("think")
        r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=180)
    r.raise_for_status()
    return r.json()["message"]


# Solo frases donde el asistente dice que EL hizo algo ahora ("anote", "he agendado", "Listo, anotado").
# No cuenta "ya tenia registrado" (eso es informar, no actuar).
_PRET = (r"agend\u00e9|anot\u00e9|cambi\u00e9|mov\u00ed|reprogram\u00e9|registr\u00e9|borr\u00e9|elimin\u00e9|marqu\u00e9|"
         r"actualic\u00e9|cre\u00e9|guard\u00e9|un\u00ed|junt\u00e9|apunt\u00e9|program\u00e9|a\u00f1ad\u00ed|agregu\u00e9|tom\u00e9 nota|"
         r"le anoto|lo anoto|se lo anoto|le agendo|lo agendo|queda anotad[oa]|queda agendad[oa]")
_PART = r"(?:agend|anot|cambi|mov|reprogram|registr|borr|elimin|marc|actualiz|cre|guard|apunt|program|a[nñ]ad|agreg)(?:ad|id)[oa]s?"
AFIRMA_ACCION = re.compile(r"(?<!\bno )\b(?:" + _PRET + r")\b|(?<!\bno )\b(?:he|hemos|ha quedado|queda|qued[oó]|ya est[aá])\s+(?:sido\s+)?" + _PART +
                           r"\b|^\W*(?:listo\W+)?(?:se[nñ]or\W+)?" + _PART + r"\b|\blo recordar[eé]\b", re.I)
PIDE_TAREA = re.compile(r"^\W*(?:por favor\W+)?(?:recu[eé]rdame|recordarme|an[oó]ta(?:me)?|apunta(?:me)?|tengo que|debo|"
                        r"agr[eé]ga(?:me)?|a[nñ]ade)\b(?:\s+que)?\s+", re.I)
CORTESIA = re.compile(r"^\W*(?:muchas\s+)?(?:gracias|ok|okay|vale|listo|perfecto|bien|genial|excelente|no|nada|"
                      r"no gracias|eso es todo|nada m[aá]s|de acuerdo|entendido)\W*$", re.I)
PIDE_ACCION = re.compile(r"\b(?:borra|b\u00f3rra\w*|elimina\w*|quita\w*|anota\w*|ap\u00fanta\w*|apunta\w*|agenda\w*|"
                         r"recu\u00e9rda\w*|recuerda\w*|recordarme|cr\u00e9a\w*|crea|pon(?:me|lo|la)?|cambia\w*|"
                         r"mueve\w*|marca\w*|termin\u00e9|ya hice)\b", re.I)
HABLA_DE_MEMORIA = re.compile(r"memoria|recuerd|recordar|guard|registr|en cuenta", re.I)
# Preguntas del asistente que piden un DATO (dia, hora, numero...). "¿Desea algo mas?" no cuenta.
PREGUNTA_DATO = re.compile(r"qu[eé] d[ií]a|qu[eé] hora|cu[aá]ndo|qu[eé] fecha|cu[aá]l|qu[eé] n[uú]mero|"
                           r"para qu[eé]|a qu[eé]|lo agendo|lo anoto|confirm", re.I)


def _tarea_directa(texto, ver_dia):
    """'Recuerdame comprar pinceles el lunes' -> crea la tarea desde el codigo si el modelo no lo hizo."""
    m = PIDE_TAREA.search(texto)
    if not m:
        return None
    resto = re.sub(r"[.!?\u00bf\u00a1,]", " ", texto[m.end():])
    datos = tareas.interpretar(resto)
    if isinstance(datos, str):
        return None
    f = datos["entrega"]
    resultado, _ = ejecutar("crear_tarea", {"materia": datos["materia"] if datos["materia"] != "General" else "",
                                            "descripcion": datos["titulo"], "fecha": f[8:10] + "/" + f[5:7],
                                            "hora": datos["hora"]}, ver_dia)
    ULTIMAS.append("crear_tarea")
    log.info("Tarea creada por respaldo: %s", resultado[:80])
    if not resultado.startswith("Tarea #"):
        return None
    cuando = tareas.fecha_bonita(f)
    cuando = ("el " if cuando[:1].isupper() or cuando.split()[0] in DIAS else "") + cuando
    return ("Listo, se\u00f1or. Anot\u00e9 \u00ab" + datos["titulo"] + "\u00bb para " + cuando +
            ("" if "Google" not in resultado or "No se pudo" in resultado else ", tambi\u00e9n en Google Calendar") + ".")


ULTIMAS = []      # herramientas usadas en la ultima respuesta (la voz las copia a Telegram)

VOZ = ("CANAL: VOZ. Tu respuesta se leera en voz alta por los parlantes de la PC. Responde en 1 a 3 frases "
       "naturales y habladas: sin vinetas, sin listas, sin numeros de recuerdo, sin emojis ni simbolos. "
       "Para la agenda, cuentalo de forma hablada y breve (ej. 'Manana tiene Multimedia a las ocho y estudio a las siete'). "
       "Si algo necesita confirmacion (borrar), di que le envias los botones a Telegram.")


def _rondas(mensajes, conf, ver_dia, pendientes):
    """Ejecuta herramientas hasta que la IA responda con texto. Devuelve (mensaje, cuantas_herramientas)."""
    usadas = 0
    for _ in range(4):                                   # como maximo 4 rondas de herramientas
        msg = _llamar(mensajes, conf)
        llamadas = msg.get("tool_calls") or []
        if not llamadas:
            return msg, usadas
        mensajes.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": llamadas})
        for ll in llamadas:
            fn = ll.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            resultado, pendiente = ejecutar(fn.get("name", ""), args, ver_dia)
            ULTIMAS.append(fn.get("name", ""))
            usadas += 1
            log.info("IA uso %s %s -> %s", fn.get("name"), args, resultado[:80])
            if pendiente:
                pendientes.append(pendiente)
            mensajes.append({"role": "tool", "content": resultado, "tool_name": fn.get("name", "")})
        if any(ll.get("function", {}).get("name") == "leer_noticia" for ll in llamadas):
            # Tras leer un texto de internet, la IA solo responde: no puede ejecutar nada mas (proteccion)
            return _llamar(mensajes, {**conf, "opciones": {**conf.get("opciones", {}), "num_predict": 1200}},
                           con_herramientas=False), usadas
    return _llamar(mensajes, conf, con_herramientas=False), usadas


# ------------------------------------------------------------------ memoria inteligente ---
def _simple(instruccion):
    """Pregunta corta al modelo, sin herramientas ni agenda. Devuelve solo el texto."""
    try:
        msg = _llamar([{"role": "user", "content": instruccion}], config(), con_herramientas=False)
        return re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
    except Exception as exc:
        log.info("Pregunta simple fallo: %s", exc)
        return ""


def _limpio(dato):
    return re.sub(r"^el usuario cont[oó]:\s*", "", dato.strip(), flags=re.I)


def _unir_textos(a, b):
    junto = _simple("Une estos dos datos sobre el usuario en UNA sola frase corta, en tercera persona, sin perder "
                    "ningun dato y sin repetir. Responde solo con la frase.\nA: " + _limpio(a) + "\nB: " + _limpio(b))
    junto = _ordenar(junto).replace("\n", " ").strip('" ')
    if len(junto) < 10 or len(junto) > 300:
        junto = _limpio(a).rstrip(". ") + "; " + _limpio(b)
    return junto


def guardar_dato(dato):
    """Guarda un dato; si ya hay un recuerdo del mismo tema, lo completa en vez de duplicar."""
    dato = " ".join(dato.split())
    if not dato:
        return "No habia nada que guardar."
    lista = memoria.recuerdos()
    resp = _simple("Lista de recuerdos:\n" + "\n".join(str(r["id"]) + ") " + r["dato"] for r in lista) +
                   "\n\nDato nuevo: " + _limpio(dato) +
                   "\n\nEl dato nuevo trata del MISMO tema que alguno de la lista (ej. ambos sobre su computadora)? "
                   "Responde SOLO con el numero de ese recuerdo, o 0 si es un tema nuevo.")
    m = re.search(r"\d+", resp)
    ids = {r["id"]: r["dato"] for r in lista}
    if m and int(m.group()) in ids:
        rid = int(m.group())
        memoria.actualizar(rid, _unir_textos(ids[rid], dato))
        return "Lo agregu\u00e9 a mi memoria, completando el recuerdo #" + str(rid) + "."
    rid = memoria.recordar(_limpio(dato))
    return "Lo guard\u00e9 en mi memoria (#" + str(rid) + ")."


UNIR = re.compile(r"\b(junt|un[eiaí]|unir|fusion|combin)\w*\b\D*?#?(\d+)\D+?#?(\d+)", re.I)


def _unir_pedido(texto):
    """'junta el recuerdo 8 con el 6' -> se hace directo en codigo (no depende del modelo)."""
    m = UNIR.search(texto)
    if not m or re.search(r"tarea|actividad|evento|clase", texto, re.I):
        return None
    ids = {r["id"]: r["dato"] for r in memoria.recuerdos()}
    origen, destino = int(m.group(2)), int(m.group(3))
    if origen not in ids or destino not in ids or origen == destino:
        return None
    nuevo = _unir_textos(ids[destino], ids[origen])
    memoria.actualizar(destino, nuevo)
    memoria.olvidar(origen)
    return ("Listo, se\u00f1or. Un\u00ed el #" + str(origen) + " dentro del #" + str(destino) + ":\n\n\u2022 #"
            + str(destino) + " " + nuevo)


# ------------------------------------------------------------------ rescate de acciones ---
ESQUEMA_ACCION = {"type": "object", "properties": {
    "accion": {"type": "string", "enum": ["crear_tarea", "recordatorio_con_hora", "borrar_tarea", "borrar_actividad",
                                          "marcar_hecha", "recordar_dato", "ninguna"]},
    "descripcion": {"type": "string"}, "fecha": {"type": "string"}, "hora": {"type": "string"},
    "numero": {"type": "integer"}, "dato": {"type": "string"}},
    "required": ["accion", "descripcion", "fecha", "hora", "numero", "dato"]}


def _json(instruccion, esquema, conf):
    cuerpo = {"model": conf["modelo"], "messages": [{"role": "user", "content": instruccion}], "stream": False,
              "think": False, "format": esquema, "keep_alive": conf["keep_alive"],
              "options": {"num_predict": 200, "temperature": 0, **conf.get("opciones", {})}}
    r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=120)
    if r.status_code == 400:
        cuerpo.pop("think", None)
        cuerpo["format"] = "json"
        r = requests.post(conf["ollama"] + "/api/chat", json=cuerpo, timeout=120)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def _cuando(ddmm):
    f = _fecha(ddmm)
    if not f:
        return "el " + (ddmm or "d\u00eda indicado")
    b = tareas.fecha_bonita(f.isoformat())
    return b if b in ("hoy", "ma\u00f1ana") else "el " + b


def _dicho(texto, charla):
    """Lo que el usuario dijo en este mensaje (y antes, si el asistente le estaba preguntando), para no inventar datos."""
    partes = [texto]
    i = len(charla) - 1
    while i >= 1 and charla[i]["role"] == "assistant" and charla[i]["content"].rstrip().endswith("?") \
            and charla[i - 1]["role"] == "user" and len(partes) < 3:     # solo si venimos respondiendo preguntas
        partes.insert(0, charla[i - 1]["content"])
        i -= 2
    return " ".join(partes).lower()


def _hora_dicha(hora, dicho):
    h = _hora(hora)
    if not h:
        return False
    n = int(h[:2])
    candidatos = {str(n), str(n % 12 or 12), h, h.lstrip("0")}
    if re.search(r"mediod[ií]a|medianoche", dicho):
        return True
    return any(re.search(r"(?<![\d:])" + re.escape(c) + r"(?![\d])", dicho) for c in candidatos)


DIA_DICHO = re.compile(r"\b(hoy|ma[nñ]ana|pasado|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|semana|"
                       r"m[aá]s tarde|esta (?:tarde|noche)|\d{1,2}[/-]\d{1,2}|\d{1,2} de \w+)\b")


def _rescate(texto, conf, ver_dia, pendientes, canal):
    """El modelo no uso herramientas: se le pide SOLO decidir la accion en JSON y el codigo la ejecuta.
    Devuelve el texto de respuesta, o None si el usuario no pidio ninguna accion."""
    from modulos.agenda import eventos
    charla = memoria.historial(6)
    lista_t = "\n".join("#" + str(t["id"]) + " " + t["titulo"] + " (entrega " + t["entrega"] + ")" for t in tareas.pendientes()) or "(ninguna)"
    lista_e = "\n".join(eventos.descripcion(e) for e in eventos.activos()) or "(ninguna)"
    instruccion = (
        "Hoy es " + DIAS_BONITO[ahora().weekday()] + " " + ahora().strftime("%d/%m/%Y %H:%M") + ".\n"
        + _calendario() + "\n\nTAREAS PENDIENTES:\n" + lista_t + "\n\nACTIVIDADES CON HORA:\n" + lista_e
        + "\n\nCONVERSACION RECIENTE:\n" + "\n".join(("El usuario: " if m["role"] == "user" else "Asistente: ") + m["content"] for m in charla)
        + "\nEl usuario (ultimo mensaje): " + texto
        + "\n\nDecide que ACCION pidio el usuario con su ultimo mensaje, usando la conversacion para completar datos "
          "(si respondio una hora o una fecha a una pregunta del asistente, combinala con lo que pidio antes). Reglas:\n"
          "- crear_tarea: algo por hacer o entregar en un dia, sin hora concreta. fecha en DD/MM.\n"
          "- recordatorio_con_hora: 'recuerdame X a las H' o algo a una hora concreta. fecha DD/MM y hora HH:MM (24 h; '5' por la tarde = 17:00).\n"
          "- NUNCA inventes una hora ni una fecha: si el usuario no la dijo, deja ese campo vacio.\n"
          "- borrar_tarea / borrar_actividad / marcar_hecha: pon el numero de la lista que corresponde.\n"
          "- recordar_dato: el usuario conto un dato estable o preferencia suya (va en 'dato').\n"
          "- ninguna: solo pregunta, conversa, o cancela ('no', 'olvidalo').\n"
          "Campos que no apliquen: texto vacio o numero 0.")
    try:
        d = _json(instruccion, ESQUEMA_ACCION, conf)
    except Exception as exc:
        log.warning("Rescate fallo: %s", exc)
        return None
    log.info("Rescate decidio: %s", d)
    accion = d.get("accion", "ninguna")
    desc = (d.get("descripcion") or "").strip()
    dicho = _dicho(texto, charla)
    if accion == "crear_tarea" and desc and (not d.get("fecha") or not DIA_DICHO.search(dicho)):
        return "\u00bfPara qu\u00e9 d\u00eda anoto \u00ab" + desc + "\u00bb, se\u00f1or?"
    if accion == "recordatorio_con_hora" and desc and (not d.get("hora") or not _hora_dicha(d["hora"], dicho)):
        return "\u00bfA qu\u00e9 hora le recuerdo \u00ab" + desc + "\u00bb, se\u00f1or?"
    if accion == "crear_tarea" and desc and d.get("fecha"):
        res, _ = ejecutar("crear_tarea", {"descripcion": desc, "fecha": d["fecha"]}, ver_dia)
        ULTIMAS.append("crear_tarea")
        if res.startswith("Tarea #"):
            return "Listo, se\u00f1or. Anot\u00e9 la tarea \u00ab" + desc + "\u00bb para " + _cuando(d["fecha"]) + "."
        return "No pude anotarla, se\u00f1or: " + res.split(":", 1)[-1].replace("Pide el dato al usuario.", "").strip()
    if accion == "recordatorio_con_hora" and desc and d.get("hora"):
        res = crear_evento({"titulo": desc, "fecha": d.get("fecha") or ahora().strftime("%d/%m"), "hora_inicio": d["hora"],
                            "duracion_minutos": 15, "aviso_minutos": 0, "forzar": True})
        ULTIMAS.append("crear_evento")
        if res.startswith("Agendado"):
            return ("Listo, se\u00f1or. Le recordar\u00e9 \u00ab" + desc + "\u00bb " + _cuando(d.get("fecha") or ahora().strftime("%d/%m"))
                    + " a las " + (_hora(d["hora"]) or d["hora"]) + ", en la PC, Telegram y Google Calendar.")
        return "No pude agendarlo, se\u00f1or: " + res
    n = int(d.get("numero") or 0)
    if accion in ("borrar_tarea", "marcar_hecha") and tareas.obtener(n) and tareas.obtener(n)["estado"] == "pendiente":
        t = tareas.obtener(n)
        if accion == "marcar_hecha":
            ejecutar("marcar_hecha", {"numero": n}, ver_dia)
            ULTIMAS.append("marcar_hecha")
            return "Listo, se\u00f1or. Marqu\u00e9 como hecha \u00ab" + t["titulo"] + "\u00bb."
        pendientes.append(("borrar", n))
        ULTIMAS.append("borrar_tarea")
        donde = "Le envi\u00e9 los botones a Telegram" if canal == "voz" else "Conf\u00edrmelo con los botones"
        return donde + " para borrar \u00ab" + t["titulo"] + "\u00bb, se\u00f1or."
    if accion == "borrar_actividad":
        e = eventos.obtener(n)
        if e and e["estado"] == "activo":
            pendientes.append(("borrar_evento", n))
            ULTIMAS.append("borrar_evento")
            donde = "Le envi\u00e9 los botones a Telegram" if canal == "voz" else "Conf\u00edrmelo con los botones"
            return donde + " para borrar \u00ab" + e["titulo"] + "\u00bb, se\u00f1or."
    if accion == "recordar_dato" and (d.get("dato") or "").strip():
        ULTIMAS.append("recordar")
        return "Listo, se\u00f1or. " + guardar_dato(d["dato"])
    return None


def _ordenar(texto):
    """Limpia restos de markdown y deja el texto con espacios ordenados para Telegram."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)
    texto = re.sub(r"^[ \t]*#+[ \t]*", "", texto, flags=re.M)
    texto = re.sub(r"^[ \t]*[-*][ \t]+", "\u2022 ", texto, flags=re.M)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


TEMA_DINERO = re.compile(r"ahorr|presupuest|sueldo|salario|gast[eéoa]|ingres|deud|debe\b|deb[oe]\b|prest|pagu[eé]|"
                         r"tarjeta|movilidad|plata\b|dinero|d[oó]lares|\$", re.I)

CONSULTA_AGENDA = re.compile(r"\b(?:que|cual(?:es)?) (?:tengo|hay|me toca)\b|\bagenda\b|\bmi plan\b|\bplan de\b|"
                             r"\bclases?\b|\bhorario\b", re.I)
CONSULTA_TAREAS = re.compile(r"\b(?:mis|las|que|cuales|cuantas) (?:tareas|entregas|pendientes|deberes)\b|"
                             r"^\W*(?:tareas|pendientes)\W*$", re.I)
_FECHA_TEXTO = re.compile(r"pasado manana|manana|hoy|lunes|martes|miercoles|jueves|viernes|sabado|domingo|\d{1,2}/\d{1,2}")


def _consulta_directa(texto, ver_dia):
    """Modo juego/diseno: las preguntas de agenda y tareas se responden desde el codigo
    (el modelo chico se confunde con ellas). Devuelve el texto, o None si no es una consulta."""
    from modulos.tareas.tareas import _sin_tildes
    t = _sin_tildes(texto.lower())
    if PIDE_ACCION.search(texto) or PIDE_TAREA.search(texto):
        return None
    if CONSULTA_TAREAS.search(t):
        return ejecutar("ver_tareas", {}, ver_dia)[0]
    if not CONSULTA_AGENDA.search(t):
        return None
    if "semana" in t:
        return semana("siguiente" if re.search(r"proxima|siguiente|que viene", t) else "esta")
    m = _FECHA_TEXTO.search(t)
    return ejecutar("ver_dia", {"fecha": m.group() if m else "hoy"}, ver_dia)[0]


def responder(texto, historial=None, ver_dia=None, canal="telegram"):
    """Devuelve (respuesta, acciones_pendientes). La conversacion se guarda en la base (sobrevive reinicios)."""
    conf = config()
    ULTIMAS.clear()
    directo = _unir_pedido(texto)
    if not directo:
        try:                                  # alertas de precio y diario de decisiones (antes que gastos y noticias)
            from modulos.alertas import alertas
            directo = alertas.procesar(texto)
            if not directo:                   # «compré Nvidia», «vendí Visa», «qué acciones tengo» (antes que gastos)
                from modulos.portafolio import cambios
                directo = cambios.procesar(texto)
            if not directo:                   # "planifica la semana", "¿cómo me fue esta semana?"
                from modulos.proactivo import proactivo
                directo = proactivo.procesar(texto)
        except Exception as exc:
            log.warning("Alertas fallo: %s", exc)
    if not directo:
        try:                                  # «¿para cuándo es el deber del ensayo?»: se responde exacto, sin crear nada
            from modulos.tareas import consultas
            directo = consultas.procesar(texto)
            if not directo:                   # «recuérdame X el viernes», «toda la semana», «a las 5» (exacto, sin IA)
                from modulos.tareas import recordatorios
                directo = recordatorios.procesar(texto)
        except Exception as exc:
            log.warning("Consulta de deberes o recordatorio fallo: %s", exc)
    if not directo:
        try:                                  # lo aprendido de los videos: "¿qué dice Pepe de META?", /reglas, autor N
            from modulos.aprendizaje import aprendizaje
            directo = aprendizaje.procesar(texto)
            if not directo:                   # biblioteca: «según mis videos…», «resúmeme el video de…»
                from modulos.biblioteca import biblioteca
                directo = biblioteca.procesar(texto, canal)
        except Exception as exc:
            log.warning("Aprendizaje o biblioteca fallo: %s", exc)
    if not directo:
        try:                                  # cuaderno de Cava y diario de trading (antes que gastos: "compra 140")
            from modulos.cava import cava
            directo = cava.procesar(texto)
            if not directo:                   # "¿qué noticias hay de Nvidia?"
                from modulos.noticias import noticias
                directo = noticias.procesar(texto, canal)
        except Exception as exc:
            log.warning("Cava o noticias fallo: %s", exc)
    if not directo:
        try:                                  # deudas: las frases comunes las resuelve el codigo (exacto)
            from modulos.finanzas import deudas
            directo = deudas.procesar(texto)
            if not directo:                   # ahorros programados (saldo)
                from modulos.finanzas import ahorros
                directo = ahorros.procesar(texto)
            if not directo:                   # sueldo y presupuestos
                from modulos.finanzas import presupuesto
                directo = presupuesto.procesar(texto)
            if not directo and not deudas.parece_deuda(texto):   # gastos e ingresos claros (nunca una deuda)
                from modulos.finanzas import gastos
                directo = gastos.procesar(texto, "voz" if canal == "voz" else "telegram")
        except Exception as exc:
            log.warning("Finanzas fallo: %s", exc)
    if not directo and conf.get("modo_ligero") and ver_dia:
        directo = _consulta_directa(texto, ver_dia)
        if directo:
            log.info("Modo ligero: consulta respondida desde el codigo")
    if directo:
        memoria.guardar_turno(texto, directo)
        return directo, []
    sistema = _sistema() + ("\n\n" + VOZ.replace("senor", "se\u00f1or") if canal == "voz" else "")
    sistema += ("\n\nCONOCIMIENTO GENERAL: si el usuario pregunta algo de cultura general, ciencia, tecnologia, diseno, "
                "historia o como hacer algo, responde con tu conocimiento, claro y util. 'No tengo registrado' solo vale "
                "para datos PERSONALES del usuario que no esten en la agenda o la memoria. Para actualidad, noticias, "
                "empresas o mercados usa leer_noticia sin preguntar.")
    try:                                      # lo ultimo de Cava y Pablo Gil, si habla de bolsa
        from modulos.cava import cava
        sistema += cava.contexto_mercado(texto)
        from modulos.aprendizaje import aprendizaje
        sistema += aprendizaje.contexto(texto)
        from modulos.biblioteca import biblioteca
        sistema += biblioteca.contexto(texto)
        from modulos.noticias import noticias
        sistema += noticias.contexto_ia(texto)
    except Exception as exc:
        log.info("Sin contexto de analistas o noticias: %s", exc)
    mensajes = [{"role": "system", "content": sistema}] + memoria.historial(conf["memoria"]) + \
               [{"role": "user", "content": texto}]
    pendientes = []
    msg, usadas = _rondas(mensajes, conf, ver_dia, pendientes)
    respuesta = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
    previa = memoria.historial(1)
    tras_pregunta = bool(previa) and previa[-1]["role"] == "assistant" and previa[-1]["content"].rstrip().endswith("?") \
        and len(texto.split()) <= 10 and not CORTESIA.match(texto) \
        and bool(PREGUNTA_DATO.search(previa[-1]["content"]) or DIA_DICHO.search(texto.lower()) or re.search(r"\d", texto))
    afirma = AFIRMA_ACCION.search(respuesta)
    if TEMA_DINERO.search(texto):
        tras_pregunta = False         # dinero: nunca rescatar como tarea o recordatorio
        afirma = afirma if usadas else None
        if not usadas and AFIRMA_ACCION.search(respuesta) and re.search(r"\d", texto):
            # traia un monto y la IA dice que lo guardo sin hacerlo: avisar (si es solo conversacion, se deja fluir)
            respuesta = ("Disculpe, señor, ese dato no llegué a registrarlo. ¿Me lo repite de otra forma? Por ejemplo "
                         "«el ahorro de viaje tiene 70», «presupuesto comida 150» o «almuerzo 4.50».")
    if conf.get("modo_ligero"):
        tras_pregunta = False        # el modelo chico rescata mal: solo si el usuario pidio una accion clara
    if not usadas and (afirma or (PIDE_ACCION.search(texto) and not TEMA_DINERO.search(texto)) or tras_pregunta):
        if afirma:
            log.warning("La IA afirmo una accion sin herramienta: %s", respuesta[:100])
        hecho = _rescate(texto, conf, ver_dia, pendientes, canal)
        if hecho:
            respuesta = hecho
        elif afirma:
            respuesta = "Disculpe, se\u00f1or, no llegu\u00e9 a hacerlo. \u00bfMe lo repite con el qu\u00e9, el d\u00eda y la hora?"
    respuesta = _ordenar(respuesta) or "Hecho, se\u00f1or."
    memoria.guardar_turno(texto, respuesta)
    return respuesta, pendientes


def modelo_listo():
    conf = config()
    try:
        nombres = [m["name"] for m in requests.get(conf["ollama"] + "/api/tags", timeout=3).json()["models"]]
        return conf["modelo"] in nombres or conf["modelo"] + ":latest" in nombres
    except Exception:
        return False

