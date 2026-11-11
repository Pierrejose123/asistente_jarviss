"""Fase 2: el asistente se adelanta.

1. PLANIFICADOR (solo, cada 30 min; domingo 18:00 con la revisión; o /planificar cuando quiera):
   Mira las tareas pendientes (también las de Moodle), sus clases, actividades, bloques de estudio y
   entreno, y decide en qué bloque hacer cada deber ANTES de su entrega. Primero usa sus bloques de
   estudio; si no alcanzan, busca huecos libres (config/proactivo.json). AGENDA SOLO cada bloque
   "Estudio: <deber>" en la agenda y en Google Calendar (sin botón) y avisa por Telegram con un botón
   "Quitar". Tabla 'plan_bloques': si el usuario quita un bloque (botón o borrándolo del celular) se busca
   otro hueco una vez; si quita dos del mismo deber, ese deber ya no se agenda solo. Al marcar un deber
   como hecho, sus bloques futuros se borran. También reintenta subir a Google las entregas que no subieron.
2. REVISIÓN DEL DOMINGO (antes del plan): qué cumplió en la semana, qué quedó pendiente, entreno y
   gastos frente a la semana anterior. Sin culpas: solo para ajustar.
3. AVISOS QUE CONECTAN:
   - 20 min antes de una clase, si tiene un deber de ESA materia que vence pronto.
   - Miércoles 20:00: si el gasto del mes va bastante más rápido que el mes.
   - 20:30: si mañana es un día cargado (clases + entregas + actividades).
Todo se calcula en código; la IA no decide nada.
"""
import json
import re
import threading
import unicodedata
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modulos.comun import db  # noqa: E402
from modulos.comun.base import CONFIG, DIAS, DIAS_BONITO, ZONA, ahora, registro  # noqa: E402

log = registro("proactivo")
ARCHIVO = CONFIG / "proactivo.json"
PREDETERMINADO = {
    "huecos_entre_semana": ["19:00", "22:00"],
    "huecos_fin_de_semana": ["09:00", "19:00"],
    "minutos_bloque": 60,
    "max_bloques_nuevos_por_dia": 2,
    "minutos_entreno": 45,
    "palabras_de_tarea_larga": ["proyecto", "informe", "video", "ensayo", "presentaci", "portafolio", "investigaci",
                                "examen", "prueba", "maqueta", "animaci", "afiche", "cartel", "storyboard"],
    "aviso_clase_minutos": 20,
    "dia_cargado_horas": 4,
    "dias_adelanto": 14,
}
LETRAS = ["L", "M", "X", "J", "V", "S", "D"]
CANDADO = threading.Lock()            # que el aviso automático y /planificar no agenden lo mismo a la vez
ESQUEMA_BLOQUES = """
CREATE TABLE IF NOT EXISTS plan_bloques (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    tid    INTEGER NOT NULL,             -- tarea
    eid    INTEGER NOT NULL,             -- actividad de la agenda ("Estudio: ...")
    dia    TEXT NOT NULL,
    ini    TEXT NOT NULL,
    fin    TEXT NOT NULL,
    estado TEXT DEFAULT 'activo',        -- activo | quitado (lo quitó el usuario) | cerrado (deber hecho o fecha cambiada)
    creado TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def ajustes():
    datos = dict(PREDETERMINADO)
    if not ARCHIVO.exists():
        try:
            ARCHIVO.write_text(json.dumps(PREDETERMINADO, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    try:
        datos.update(json.loads(ARCHIVO.read_text(encoding="utf-8-sig")))
    except Exception as exc:
        log.warning("config/proactivo.json no se pudo leer: %s", exc)
    return datos


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


def _min(h):
    return int(h[:2]) * 60 + int(h[3:5])


def _hhmm(m):
    return "%02d:%02d" % (m // 60, m % 60)


def _momento(d):
    return datetime.combine(d, datetime.min.time(), tzinfo=ZONA)


# ------------------------------------------------------------------ lo que ocupa cada día ---
def ocupado(d):
    """[(inicio_min, fin_min, texto, es_estudio, tarea_reservada)] de un día: clases, actividades y entreno."""
    from modulos.agenda import eventos
    from modulos.clases.agenda import clases_efectivas
    from modulos.habitos import habitos
    lista = []
    for c in clases_efectivas(_momento(d)):
        if c["nota"] != "cancelada":
            lista.append((_min(c["inicio"]), _min(c["fin"]), "Clase " + c["materia"], False, None))
    for e in eventos.del_dia(d):
        fin = _min(e["fin"]) if _min(e["fin"]) > _min(e["inicio"]) else 24 * 60
        reservada = re.search(r"tarea #(\d+)", e.get("nota") or "")
        lista.append((_min(e["inicio"]), fin, e["titulo"], "estudio" in _norm(e["titulo"]),
                      int(reservada.group(1)) if reservada else None))
    try:
        if habitos.toca_hoy(_momento(d)):
            h = _min(habitos.config()["hora"])
            lista.append((h, h + int(ajustes()["minutos_entreno"]), _nombre_habito(), False, None))
    except Exception:
        pass
    return sorted(lista)


def huecos_libres(d, ocupados, ya_usados=()):
    """Bloques libres de 'minutos_bloque' dentro de la ventana del día, sin pisar nada."""
    a = ajustes()
    ventana = a["huecos_fin_de_semana"] if d.weekday() >= 5 else a["huecos_entre_semana"]
    ini, fin, largo = _min(ventana[0]), _min(ventana[1]), int(a["minutos_bloque"])
    if d == ahora().date():
        ini = max(ini, (ahora().hour * 60 + ahora().minute + 30) // 30 * 30)
    tomados = [(o[0], o[1]) for o in ocupados] + list(ya_usados)
    bloques, t = [], ini
    while t + largo <= fin:
        if any(t < b and a_ < t + largo for a_, b in tomados):
            t += 30
            continue
        bloques.append((t, t + largo))
        t += largo
    return bloques


def bloques_necesarios(t):
    largas = ajustes()["palabras_de_tarea_larga"]
    return 2 if any(p in _norm(t["titulo"]) for p in largas) else 1


# ------------------------------------------------------------------ bloques agendados solos ---
def _con_bloques():
    con = db.conectar()
    con.executescript(ESQUEMA_BLOQUES)
    return con


def _ya_paso(b):
    hoy, ya = ahora().date().isoformat(), ahora().strftime("%H:%M")
    return b["dia"] < hoy or (b["dia"] == hoy and b["fin"] <= ya)


def _empezo(b):
    hoy, ya = ahora().date().isoformat(), ahora().strftime("%H:%M")
    return b["dia"] < hoy or (b["dia"] == hoy and b["ini"] <= ya)


def _nombre_habito():
    try:
        from modulos.habitos import habitos
        return habitos.nombre()
    except Exception:
        return "Entrenamiento"


def _lo_quito_usuario(b):
    """True si el bloque ya no está en la agenda: lo borró desde el celular (sincronización) o con el botón."""
    from modulos.agenda import eventos
    clave = "evento:" + str(b["eid"])
    ev = eventos.obtener(b["eid"])
    if not ev or ev["estado"] != "activo":
        return True
    exc = db.excepcion(clave, b["dia"])
    if exc and exc["estado"] == "cancelada":
        return True
    fila = db.obtener_evento(clave)
    return bool(fila and fila["estado"] == "borrado")


def revisar_bloques():
    """Pone al día la tabla: bloques que el usuario quitó y bloques que ya no hacen falta (deber hecho o
    fecha adelantada). Devuelve cuántos bloques futuros se borraron."""
    from modulos.agenda import eventos
    from modulos.tareas import tareas
    with closing(_con_bloques()) as con:
        filas = con.execute("SELECT * FROM plan_bloques WHERE estado = 'activo'").fetchall()
    borrados = 0
    for b in filas:
        if _lo_quito_usuario(b):
            with closing(_con_bloques()) as con, con:
                con.execute("UPDATE plan_bloques SET estado = 'quitado' WHERE id = ?", (b["id"],))
            log.info("El usuario quitó el bloque %s (tarea #%s, %s %s)", b["eid"], b["tid"], b["dia"], b["ini"])
            continue
        t = tareas.obtener(b["tid"])
        sobra = not t or t["estado"] != "pendiente" or b["dia"] > t["entrega"]
        if sobra and not _empezo(b):
            eventos.borrar(b["eid"])
            with closing(_con_bloques()) as con, con:
                con.execute("UPDATE plan_bloques SET estado = 'cerrado' WHERE id = ?", (b["id"],))
            borrados += 1
            log.info("Bloque %s borrado: la tarea #%s ya no lo necesita", b["eid"], b["tid"])
    return borrados


def _historial_bloques():
    """{tid: {"pasados": n, "quitados": n, "huecos_quitados": {(dia, ini)}}}"""
    salida = {}
    with closing(_con_bloques()) as con:
        filas = con.execute("SELECT * FROM plan_bloques WHERE estado IN ('activo', 'quitado')").fetchall()
    for b in filas:
        h = salida.setdefault(b["tid"], {"pasados": 0, "quitados": 0, "huecos_quitados": set()})
        if b["estado"] == "quitado":
            h["quitados"] += 1
            h["huecos_quitados"].add((b["dia"], b["ini"]))
        elif _ya_paso(b):
            h["pasados"] += 1
    return salida


def asegurar_google():
    """Entregas y bloques que nunca llegaron a Google Calendar (p. ej. permiso caído): se reintentan.
    No vuelve a subir lo que el usuario borró del celular."""
    from modulos.agenda import eventos
    from modulos.tareas import tareas
    subidos = 0
    for t in tareas.pendientes():
        if t["entrega"] < ahora().date().isoformat():
            continue
        fila = db.obtener_evento("tarea:" + str(t["id"]))
        if fila and fila["google_id"]:
            continue
        try:
            tareas.subir(t["id"])
            subidos += 1
            log.info("Tarea #%s subida a Google en el reintento", t["id"])
        except Exception as exc:
            log.info("Tarea #%s sigue sin subir a Google: %s", t["id"], exc)
            return subidos                      # sin Google ahora: no insistir con las demás
    with closing(_con_bloques()) as con:
        filas = con.execute("SELECT * FROM plan_bloques WHERE estado = 'activo'").fetchall()
    for b in filas:
        fila = db.obtener_evento("evento:" + str(b["eid"]))
        if (fila and fila["google_id"]) or _ya_paso(b):
            continue
        try:
            eventos.subir(b["eid"])
            subidos += 1
        except Exception as exc:
            log.info("Bloque %s sigue sin subir a Google: %s", b["eid"], exc)
            break
    return subidos


# ------------------------------------------------------------------ planificador ---
def planificar(desde=None, dias=7, adelanto=None):
    """Devuelve dict con: fechas, asignaciones, sin_hueco, cargados, tareas, vencidas, quitadas."""
    from modulos.tareas import tareas
    hoy = ahora().date()
    desde = desde or hoy
    fechas = [desde + timedelta(days=i) for i in range(dias)]
    limite = (fechas[-1] + timedelta(days=int(adelanto if adelanto is not None else ajustes().get("dias_adelanto", 14)))).isoformat()
    lista = [t for t in tareas.pendientes(hasta=limite)]          # también lo que vence en 3 semanas: adelantar
    a = ajustes()
    historial = _historial_bloques()
    pendientes_ids = {t["id"] for t in tareas.pendientes()}
    ya = ahora().hour * 60 + ahora().minute

    # espacios disponibles por día: primero sus bloques de estudio, luego huecos libres
    espacios = []
    ocup = {d: ocupado(d) for d in fechas}
    for d in fechas:
        reservados = [(o[0], o[1]) for o in ocup[d] if o[3] and o[4] is not None]
        for ini, fin, titulo, es_estudio, reservada in ocup[d]:
            if not es_estudio or (d == hoy and fin <= ya):
                continue
            if reservada is not None and reservada not in pendientes_ids:
                continue                                   # bloque de un deber ya hecho: no se reusa
            largo = int(a["minutos_bloque"])
            t = ini
            while t + 30 <= fin:
                f = min(t + largo, fin)
                # su bloque general de estudio, pero en esa hora ya hay un "Estudio: <deber>" encima
                if reservada is None and any(t < rb and ra < f for ra, rb in reservados):
                    t += largo
                    continue
                espacios.append({"dia": d, "ini": t, "fin": f, "existente": True, "titulo": titulo,
                                 "reservada": reservada})
                t += largo
        for ini, fin in huecos_libres(d, ocup[d]):
            espacios.append({"dia": d, "ini": ini, "fin": fin, "existente": False, "titulo": "", "reservada": None})

    asignaciones, sin_hueco, nuevos_por_dia = [], [], {}
    vencidas, quitadas = [], []
    usados = set()
    def prioridad(x):
        dias_ = (date.fromisoformat(x["entrega"]) - hoy).days
        return (0 if 0 <= dias_ <= 2 else 1, x["entrega"], x["hora"] or "23:59")

    for t in sorted(lista, key=prioridad):
        entrega = date.fromisoformat(t["entrega"])
        if entrega < hoy:                                   # ya venció: no se agenda solo, se recuerda
            vencidas.append(t)
            continue
        h = historial.get(t["id"], {"pasados": 0, "quitados": 0, "huecos_quitados": set()})
        if h["quitados"] >= 2:                              # quitó dos bloques de este deber: no insistir
            quitadas.append(t)
            continue
        faltan = bloques_necesarios(t) - h["pasados"]       # los bloques que ya pasaron cuentan
        if faltan <= 0:
            continue
        candidatos = [i for i, e in enumerate(espacios) if i not in usados and
                      e["reservada"] in (None, t["id"]) and
                      (e["dia"].isoformat(), _hhmm(e["ini"])) not in h["huecos_quitados"] and
                      (e["dia"] < entrega or
                       (e["dia"] == entrega and t["hora"] and e["fin"] <= _min(t["hora"]) - 30))]
        candidatos.sort(key=lambda i: (espacios[i]["reservada"] != t["id"], not espacios[i]["existente"],
                                       espacios[i]["dia"], espacios[i]["ini"]))
        elegidos = []
        for i in candidatos:
            e = espacios[i]
            if not e["existente"] and nuevos_por_dia.get(e["dia"], 0) >= int(a["max_bloques_nuevos_por_dia"]):
                continue
            if any(u["dia"] == e["dia"] and u["ini"] < e["fin"] and e["ini"] < u["fin"] for u in
                   (espacios[j] for j in usados)):
                continue
            elegidos.append(i)
            usados.add(i)
            if not e["existente"]:
                nuevos_por_dia[e["dia"]] = nuevos_por_dia.get(e["dia"], 0) + 1
            if len(elegidos) == faltan:
                break
        for i in elegidos:
            asignaciones.append({**espacios[i], "tarea": t, "agendado": espacios[i]["reservada"] == t["id"]})
        if len(elegidos) < faltan:
            sin_hueco.append((t, faltan - len(elegidos)))

    cargados = []
    for d in fechas:
        horas = sum(o[1] - o[0] for o in ocup[d] if not o[3]) / 60
        entregas = [t for t in lista if t["entrega"] == d.isoformat()]
        if horas >= float(a["dia_cargado_horas"]) or len(entregas) >= 2:
            cargados.append((d, horas, len(entregas)))
    return {"fechas": fechas, "asignaciones": sorted(asignaciones, key=lambda x: (x["dia"], x["ini"])),
            "sin_hueco": sin_hueco, "cargados": cargados, "tareas": lista, "vencidas": vencidas,
            "quitadas": quitadas}


def agendar(plan):
    """Crea en la agenda y en Google Calendar cada bloque del plan que aún no está agendado.
    Devuelve (lista de bloques creados, cuántos no subieron a Google)."""
    from modulos.agenda import eventos
    creados, sin_google = [], 0
    for x in plan["asignaciones"]:
        t = x["tarea"]
        if x["agendado"]:
            continue
        # seguridad: solo puede caer encima de un bloque de estudio general, nunca de una clase u otra cosa
        pisa = [o for o in ocupado(x["dia"]) if o[0] < x["fin"] and x["ini"] < o[1] and
                not (o[3] and o[4] is None)]
        if pisa:
            log.info("No agendé %s el %s %s: se cruza con %s", t["titulo"], x["dia"], _hhmm(x["ini"]), pisa[0][2])
            continue
        ini, fin = _hhmm(x["ini"]), _hhmm(x["fin"])
        eid = eventos.crear("Estudio: " + t["titulo"][:60], x["dia"], ini, fin, aviso_min=10,
                            nota="Bloque del plan semanal (tarea #" + str(t["id"]) + ")")
        with closing(_con_bloques()) as con, con:
            bid = con.execute("INSERT INTO plan_bloques (tid, eid, dia, ini, fin) VALUES (?, ?, ?, ?, ?)",
                              (t["id"], eid, x["dia"].isoformat(), ini, fin)).lastrowid
        try:
            eventos.subir(eid)
        except Exception as exc:
            sin_google += 1
            log.info("Bloque %s sin subir a Google por ahora: %s", eid, exc)
        x["agendado"] = True
        creados.append({"id": bid, "eid": eid, "dia": x["dia"], "ini": ini, "fin": fin, "tarea": t,
                        "encima_de": x["titulo"] if x["existente"] else ""})
        log.info("Agendado solo: Estudio: %s el %s %s-%s", t["titulo"], x["dia"], ini, fin)
    return creados, sin_google


def sincronizar(desde=None, adelanto=None):
    """Lo que corre solo cada 30 min y con /planificar: reintenta Google, limpia y agenda lo que falte.
    Devuelve (plan, creados, sin_google)."""
    with CANDADO:
        try:
            asegurar_google()
        except Exception as exc:
            log.info("Reintento de Google falló: %s", exc)
        revisar_bloques()
        plan = planificar(desde, 7, adelanto)
        creados, sin_google = agendar(plan)
        return plan, creados, sin_google


def quitar_bloque(bid):
    """Botón 'Quitar': borra el bloque de la agenda y de Google y lo recuerda."""
    from modulos.agenda import eventos
    with closing(_con_bloques()) as con:
        b = con.execute("SELECT * FROM plan_bloques WHERE id = ?", (bid,)).fetchone()
    if not b or b["estado"] != "activo":
        return "Ese bloque ya no estaba en su agenda, señor."
    eventos.borrar(b["eid"])
    with closing(_con_bloques()) as con, con:
        con.execute("UPDATE plan_bloques SET estado = 'quitado' WHERE id = ?", (bid,))
        quitados = con.execute("SELECT COUNT(*) FROM plan_bloques WHERE tid = ? AND estado = 'quitado'",
                               (b["tid"],)).fetchone()[0]
    cuando = _dia_corto(date.fromisoformat(b["dia"])) + " " + b["ini"]
    if quitados >= 2:
        return ("🗑 Quité el bloque del " + cuando + ", también de Google Calendar.\n"
                "Ya quitó dos bloques de este deber, así que no le vuelvo a agendar tiempo para él.")
    return "🗑 Quité el bloque del " + cuando + ", también de Google Calendar. Le busco otro hueco."


def _dia_corto(d):
    return DIAS_BONITO[d.weekday()][:3].capitalize() + " " + d.strftime("%d/%m")


def _linea_bloque(t, ini, fin, donde):
    from html import escape
    from modulos.tareas import tareas
    return ("• " + ini + "–" + fin + " " + escape(t["titulo"]) +
            (" <i>(" + escape(t["materia"]) + ")</i>" if t["materia"] != "General" else "") +
            " — entrega " + tareas.fecha_bonita(t["entrega"]) + (" · " + donde if donde else ""))


def texto_plan(plan, creados=(), sin_google=0):
    from html import escape
    from modulos.tareas import tareas
    if not plan["tareas"]:
        todas = tareas.pendientes()
        texto = "🗓 <b>Plan de la semana</b>\nNo tiene deberes que venzan en las próximas 3 semanas. 🎉"
        if todas:
            t = todas[0]
            texto += ("\nLo próximo es «" + escape(t["titulo"]) + "» para el " + tareas.fecha_bonita(t["entrega"]) +
                      ". Si quiere adelantarlo, escriba «adelanta mis deberes» o /planificar todo.")
        else:
            texto += "\nTampoco veo deberes más adelante. Si Moodle publica alguno, se lo aviso y lo agendo solo."
        return texto
    lineas = ["🗓 <b>Plan de la semana</b> (" + _dia_corto(plan["fechas"][0]) + " → " + _dia_corto(plan["fechas"][-1]) + ")"]
    nuevos = {(c["dia"], c["ini"], c["tarea"]["id"]) for c in creados}
    dia_actual = None
    for x in plan["asignaciones"]:
        if x["dia"] != dia_actual:
            dia_actual = x["dia"]
            lineas.append("\n<b>" + _dia_corto(dia_actual) + "</b>")
        t = x["tarea"]
        if (x["dia"], _hhmm(x["ini"]), t["id"]) in nuevos:
            donde = "🆕 agendado ahora" + (" (en su bloque «" + escape(x["titulo"]) + "»)" if x["existente"] else "")
        elif x["agendado"]:
            donde = "✅ ya agendado"
        else:
            donde = "⚠️ no lo pude agendar (se cruza con algo)"
        lineas.append(_linea_bloque(t, _hhmm(x["ini"]), _hhmm(x["fin"]), donde))
    if not plan["asignaciones"] and not plan["sin_hueco"]:
        lineas.append("\nTodo lo que vence pronto ya tuvo o tiene su tiempo de estudio agendado. 👍")
    if plan["sin_hueco"]:
        lineas.append("\n⚠️ <b>No me alcanzó el tiempo para:</b>")
        for t, faltan in plan["sin_hueco"]:
            lineas.append("• " + escape(t["titulo"]) + " — entrega " + tareas.fecha_bonita(t["entrega"]) +
                          (" (faltan " + str(faltan) + " bloques)" if faltan > 1 else " (falta 1 bloque)"))
        lineas.append("Puede mover algo, pedir más tiempo o hacerla en un rato libre que yo no veo.")
    if plan["vencidas"]:
        lineas.append("\n⏰ <b>Ya vencieron</b> (no les agendo tiempo):")
        lineas += ["• " + escape(t["titulo"]) + " — márquela con /hecho " + str(t["id"]) + " si ya la entregó"
                   for t in plan["vencidas"][:5]]
    if plan["quitadas"]:
        lineas.append("\nSin bloque porque usted quitó los que le puse: " +
                      ", ".join("«" + escape(t["titulo"]) + "»" for t in plan["quitadas"]))
    if plan["cargados"]:
        lineas.append("\n🔥 <b>Días cargados:</b> " + ", ".join(
            _dia_corto(d) + " (" + ("%.0f h ocupadas" % h if h >= 1 else "") + (", " if h >= 1 and e else "") +
            (str(e) + " entregas" if e else "") + ")" for d, h, e in plan["cargados"]))
        lineas.append("Esos días conviene no sumar nada más y descansar bien la noche anterior.")
    if creados:
        lineas.append("\n" + _pie(sin_google))
    return "\n".join(lineas)


def _pie(sin_google):
    if sin_google:
        texto = "Están en su agenda; " + str(sin_google) + " aún no subió a Google Calendar, lo reintento solo."
    else:
        texto = "Ya están en su agenda y en Google Calendar (calendario «Asistente»)."
    return texto + " Si alguno no le sirve, use «Quitar» o bórrelo del celular: le busco otro hueco."


def texto_creados(creados, sin_google=0):
    """Aviso del agendado automático (cada 30 min): solo lo nuevo."""
    lineas = ["🗓 <b>Le agendé tiempo de estudio</b>"]
    for c in creados:
        donde = "en su bloque «" + c["encima_de"] + "»" if c["encima_de"] else ""
        lineas.append(_linea_bloque(c["tarea"], c["ini"], c["fin"], donde).replace(
            "• ", "• " + _dia_corto(c["dia"]) + " ", 1))
    lineas.append("\n" + _pie(sin_google))
    return "\n".join(lineas)


def guardar_plan(plan):
    """(Antiguo) Guarda los bloques nuevos propuestos para el botón 'Agendar'."""
    nuevos = [{"dia": x["dia"].isoformat(), "ini": _hhmm(x["ini"]), "fin": _hhmm(x["fin"]),
               "tid": x["tarea"]["id"], "titulo": x["tarea"]["titulo"]} for x in plan["asignaciones"] if not x["existente"]]
    with closing(db.conectar()) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS plan_semana (id INTEGER PRIMARY KEY, creado TEXT, bloques TEXT, agendado INTEGER DEFAULT 0)")
        cur = con.execute("INSERT INTO plan_semana (creado, bloques) VALUES (?, ?)",
                          (ahora().isoformat(timespec="minutes"), json.dumps(nuevos, ensure_ascii=False)))
        return cur.lastrowid, len(nuevos)


def agendar_plan(pid):
    """(Antiguo) Botón 'Agendar' de mensajes viejos: ahora todo se agenda solo."""
    plan, creados, sin_google = sincronizar()
    if not creados:
        return "Ya no hace falta, señor: ahora agendo los bloques de estudio solo. Todo está en su agenda."
    return re.sub(r"<[^>]+>", "", texto_creados(creados, sin_google))


# ------------------------------------------------------------------ revisión del domingo ---
def revision_semana(hasta=None):
    from html import escape
    from modulos.habitos import habitos
    from modulos.tareas import tareas
    hasta = hasta or ahora().date()
    desde = hasta - timedelta(days=6)
    hechas = []
    for i in range(7):
        hechas += tareas.hechas_el((desde + timedelta(days=i)).isoformat())
    vencidas = [t for t in tareas.pendientes(hasta=hasta.isoformat()) if t["entrega"] < hasta.isoformat()]
    lineas = ["📋 <b>Revisión de la semana</b> (" + _dia_corto(desde) + " → " + _dia_corto(hasta) + ")"]
    lineas.append("\n✅ Deberes terminados: " + str(len(hechas)) +
                  ("\n" + "\n".join("• " + escape(t["titulo"]) for t in hechas[:6]) if hechas else ""))
    if vencidas:
        lineas.append("\n⏰ Quedaron pendientes con la fecha pasada: " + str(len(vencidas)) + "\n" +
                      "\n".join("• " + escape(t["titulo"]) + " (era " + date.fromisoformat(t["entrega"]).strftime("%d/%m") + ")"
                                for t in vencidas[:5]) +
                      "\nSi ya los entregó, márquelos con /hecho; si no, los pongo primero en el plan.")
    hechos = tocaban = 0
    for i in range(7):
        d = desde + timedelta(days=i)
        if habitos.toca_hoy(_momento(d)):
            tocaban += 1
            hechos += habitos.registro_de(_momento(d)) == "si"
    if tocaban:
        lineas.append("\n🏋️ " + _nombre_habito() + ": " + str(hechos) + " de " + str(tocaban) + " días" +
                      (" — ¡constancia total!" if hechos == tocaban else " — cada día cuenta, sin presión."))
    try:
        from modulos.finanzas import gastos
        esta = sum(g["monto"] for g in gastos.del_periodo(desde, hasta, "gasto"))
        antes = sum(g["monto"] for g in gastos.del_periodo(desde - timedelta(days=7), desde - timedelta(days=1), "gasto"))
        if esta or antes:
            cambio = ((esta / antes - 1) * 100) if antes else None
            lineas.append("\n💳 Gastos de la semana: " + ("%.0f" % esta) + " USD" +
                          ((" (" + ("+" if cambio > 0 else "") + "%.0f" % cambio + " % frente a la anterior)") if cambio is not None else ""))
    except Exception as exc:
        log.info("Sin gastos para la revisión: %s", exc)
    try:
        from modulos.cava import cava
        with cava._con() as con:
            ops = con.execute("SELECT * FROM practica_trades WHERE estado='cerrada' AND cerrado >= ?",
                              (desde.isoformat(),)).fetchall()
        if ops:
            ganadas = sum(1 for t in ops if cava.resultado(t, t["salida"])[0] > 0)
            lineas.append("\n📒 Trading de práctica: " + str(len(ops)) + " operaciones cerradas, " + str(ganadas) + " ganadoras.")
    except Exception:
        pass
    lineas.append("\nSin culpas, señor: esto es solo para ajustar. Ahora le organizo la semana que viene.")
    return "\n".join(lineas)


# ------------------------------------------------------------------ avisos que conectan ---
def aviso_clase_con_deber(momento=None):
    """20 min antes de una clase: si hay un deber de ESA materia que vence en los próximos 2 días."""
    from html import escape
    from modulos.clases.agenda import clases_efectivas
    from modulos.tareas import tareas
    momento = momento or ahora()
    hoy = momento.date()
    antes = int(ajustes()["aviso_clase_minutos"])
    mensajes = []
    for c in clases_efectivas(momento):
        if c["nota"] == "cancelada":
            continue
        inicio = datetime.combine(hoy, datetime.strptime(c["inicio"], "%H:%M").time(), tzinfo=ZONA)
        faltan = (inicio - momento).total_seconds() / 60
        if not (antes - 6 <= faltan <= antes + 1):
            continue
        clave = hoy.isoformat() + "|deber_clase|" + c["codigo"]
        if db.aviso_enviado(clave):
            continue
        limite = (hoy + timedelta(days=2)).isoformat()
        materia = _norm(c["materia"])
        suyas = [t for t in tareas.pendientes(hasta=limite)
                 if _norm(t["materia"]) and (_norm(t["materia"]) in materia or materia in _norm(t["materia"]))]
        if not suyas:
            continue
        db.marcar_aviso(clave)
        lineas = ["📚 Su clase de <b>" + escape(c["materia"]) + "</b> empieza en " + str(round(faltan)) + " min, y tiene:"]
        lineas += ["• " + tareas.linea(t) for t in suyas]
        lineas.append("Buen momento para preguntarle al profesor si tiene dudas.")
        mensajes.append("\n".join(lineas))
    return mensajes


def aviso_ritmo_gasto(hoy=None):
    """Una vez por semana: si el gasto del mes va bastante más rápido que el mes."""
    try:
        from modulos.finanzas import presupuesto
    except Exception:
        return []
    hoy = hoy or ahora().date()
    total, _ = presupuesto.disponible_mes(hoy)
    if not total:
        return []
    gastado = presupuesto.gastado_mes(hoy)
    pct, paso = gastado / total * 100, presupuesto.avance_del_mes(hoy)
    clave = hoy.isoformat() + "|ritmo_gasto"
    if pct < paso + 15 or db.aviso_enviado(clave):
        return []
    db.marcar_aviso(clave)
    return ["🧭 A mitad de semana: lleva " + str(round(pct)) + " % de su dinero del mes y va el " + str(paso) +
            " % del mes.\n" + presupuesto.linea_sueldo(hoy) + "\nSi quiere ver en qué se fue: /gastos"]


def aviso_manana_cargado(hoy=None):
    from html import escape
    from modulos.tareas import tareas
    hoy = hoy or ahora().date()
    manana = hoy + timedelta(days=1)
    clave = hoy.isoformat() + "|manana_cargado"
    if db.aviso_enviado(clave):
        return []
    ocup = [o for o in ocupado(manana) if not o[3]]
    horas = sum(o[1] - o[0] for o in ocup) / 60
    entregas = tareas.para_fecha(manana.isoformat())
    if horas < float(ajustes()["dia_cargado_horas"]) and len(entregas) < 2:
        return []
    db.marcar_aviso(clave)
    lineas = ["🔥 Mañana (" + _dia_corto(manana) + ") viene cargado: " + ("%.0f h ocupadas" % horas) +
              (", " + str(len(entregas)) + " entregas" if entregas else "") + "."]
    lineas += ["• " + _hhmm(o[0]) + " " + escape(o[2]) for o in ocup[:6]]
    lineas += ["• Entrega: " + escape(t["titulo"]) for t in entregas]
    lineas.append("Deje lista la ropa del gimnasio y duerma temprano, señor.")
    return ["\n".join(lineas)]


# ------------------------------------------------------------------ frases ---
PIDE_PLAN = re.compile(r"^\W*(?:plan(?:ifica\w*)?|organ[ií]za\w*|arma\w*|hazme)\s*(?:me\s+)?(?:el\s+|mi\s+|la\s+|un\s+)?"
                       r"(?:plan\s+de\s+)?(?:la\s+)?semana\W*$|^\W*c[oó]mo\s+(?:me\s+)?organizo\s+(?:la\s+|esta\s+)?semana\W*$|"
                       r"^\W*cu[aá]ndo\s+hago\s+(?:mis\s+)?(?:deberes|tareas)\W*$", re.I)
PIDE_ADELANTO = re.compile(r"^\W*(?:s[ií]\W+)?(?:adel[aá]nta\w*|b[uú]sca\w*\s+huecos|empez(?:ar|emos)\s+(?:ya|antes)|"
                           r"planifica\w*\s+todo)\b", re.I)
PIDE_REVISION = re.compile(r"^\W*(?:revisi[oó]n|resumen|balance)\s+(?:de\s+)?(?:la\s+|mi\s+)?semana\W*$|"
                           r"^\W*c[oó]mo\s+me\s+fue\s+(?:esta|la)\s+semana\W*$", re.I)


def _texto_sin_botones(adelanto=None):
    """Plan pedido con una frase (texto, nota de voz o voz): agenda igual, sin botones."""
    plan, creados, sin_google = sincronizar(adelanto=adelanto)
    texto = re.sub(r"<[^>]+>", "", texto_plan(plan, creados, sin_google))
    return texto.replace("use «Quitar» o bórrelo", "bórrelo")


def procesar(texto):
    if PIDE_REVISION.match(texto or ""):
        return re.sub(r"<[^>]+>", "", revision_semana())
    if PIDE_ADELANTO.match(texto or ""):
        return _texto_sin_botones(adelanto=90)
    if PIDE_PLAN.match(texto or ""):
        return _texto_sin_botones()
    return None
