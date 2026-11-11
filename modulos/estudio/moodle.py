"""Deberes de Moodle (el de MOODLE_SITIO en el .env) sin usar la contrasena del usuario.

- Lee el enlace PRIVADO del calendario de Moodle (MOODLE_ICAL_URL en .env; nunca sale de la PC).
- Cada deber nuevo ("Vencimiento de ...", "... se cierra") se guarda como TAREA (tabla 'tareas'), se sube a
  Google Calendar con sus avisos y se avisa por Telegram. Si el profesor cambia la fecha, se actualiza.
- Se recuerda que deberes ya se vieron (tabla 'moodle_eventos') para no repetir avisos.
- Solo LEE el calendario: no entra a Moodle ni sube nada.
"""
import os
import re
from contextlib import closing
from datetime import datetime, timedelta, timezone
from html import escape

import requests

from modulos.comun import db
from modulos.comun.base import ZONA, ahora, leer_json, registro
from modulos.tareas import tareas

log = registro("moodle")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS moodle_eventos (
    uid      TEXT PRIMARY KEY,           -- identificador del evento en Moodle
    tipo     TEXT NOT NULL,              -- deber | evento
    titulo   TEXT NOT NULL,
    curso    TEXT DEFAULT '',            -- codigo del curso en Moodle (ej. DGPA-3-4)
    materia  TEXT DEFAULT '',
    vence    TEXT NOT NULL,              -- fecha y hora local ISO
    tarea_id INTEGER,                    -- tarea creada en el asistente
    visto    TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

DEBER = re.compile(r"^(?:vencimiento de|cierre de|fecha l[ií]mite de|entrega de)\s+(.+)$|^(.+?)\s+(?:se cierra|vence|cierra)$|"
                   r"^(.+?)\s+(?:is due|closes)$|^(?:due|closes):?\s+(.+)$", re.I)
# "X se cierra" / "Cierre de X" / "X closes": fecha de CIERRE (último plazo tardío). Si el mismo deber también trae
# su fecha de ENTREGA ("Vencimiento de X", "X vence", "X is due"), solo cuenta la entrega: una sola tarea.
CIERRE = re.compile(r"^cierre de\s+|\s+(?:se cierra|cierra|closes)$", re.I)
APERTURA = re.compile(r"^(?:apertura de|abre)\s+|\s+(?:se abre|abre|opens)$", re.I)


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def url():
    return (os.getenv("MOODLE_ICAL_URL") or "").strip()


# ------------------------------------------------------------------ leer el calendario ---
def _desplegar(texto):
    """En iCal, una linea que empieza con espacio continua la anterior."""
    return re.sub(r"\r?\n[ \t]", "", texto).splitlines()


def _texto(v):
    return v.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def _fecha(valor, params):
    v = valor.strip()
    if re.fullmatch(r"\d{8}", v):                                  # solo fecha: vence al final del dia
        return datetime.strptime(v, "%Y%m%d").replace(hour=23, minute=59, tzinfo=ZONA)
    if v.endswith("Z"):
        return datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(ZONA)
    f = datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
    m = re.search(r"TZID=([^;:]+)", params)
    if m:
        from zoneinfo import ZoneInfo
        try:
            return f.replace(tzinfo=ZoneInfo(m.group(1))).astimezone(ZONA)
        except Exception:
            pass
    return f.replace(tzinfo=ZONA)


def leer_calendario(texto):
    """Lista de dict {uid, resumen, descripcion, curso, inicio} de cada VEVENT."""
    eventos, actual = [], None
    for linea in _desplegar(texto):
        if linea == "BEGIN:VEVENT":
            actual = {}
        elif linea == "END:VEVENT":
            if actual and actual.get("uid") and actual.get("inicio"):
                eventos.append(actual)
            actual = None
        elif actual is not None and ":" in linea:
            clave, valor = linea.split(":", 1)
            nombre, _, params = clave.partition(";")
            nombre = nombre.upper()
            if nombre == "UID":
                actual["uid"] = valor.strip()
            elif nombre == "SUMMARY":
                actual["resumen"] = _texto(valor)
            elif nombre == "DESCRIPTION":
                actual["descripcion"] = _texto(valor)
            elif nombre == "CATEGORIES":
                actual["curso"] = _texto(valor)
            elif nombre == "DTSTART":
                try:
                    actual["inicio"] = _fecha(valor, params)
                except ValueError:
                    pass
    return eventos


def materia_de(curso):
    """'DGPA-3-4_47_35840' -> 'Introduccion a la Animacion' (por el codigo del horario)."""
    codigo = (curso or "").split("_")[0].strip().upper()
    try:
        for c in leer_json("horario_clases.json")["clases"]:
            if c["codigo"].upper() == codigo:
                return c["materia"]
    except Exception:
        pass
    return ""


def clasificar(ev):
    """('deber', titulo_limpio) | ('apertura', ...) | ('evento', ...)."""
    resumen = ev.get("resumen", "").strip()
    m = DEBER.match(resumen)
    if m:
        return "deber", next(g for g in m.groups() if g).strip()
    if APERTURA.search(resumen):
        return "apertura", resumen
    return "evento", resumen


# ------------------------------------------------------------------ revisar y avisar ---
def _cuando(f):
    dias = (f.date() - ahora().date()).days
    base = tareas.fecha_bonita(f.date().isoformat())
    if dias > 1:
        base += " (en " + str(dias) + " días)"
    return base + " a las " + f.strftime("%H:%M")


def _clave(titulo):
    return re.sub(r"[^a-z0-9]+", " ", tareas._sin_tildes(titulo or "")).strip()


def _tarea_parecida(titulo, entrega):
    """Si ese deber ya está (anotado a mano o repetido), se usa esa tarea en vez de duplicarla."""
    t = tareas._sin_tildes(titulo)
    k = _clave(titulo)
    from datetime import date
    e = date.fromisoformat(entrega)
    for p in tareas.pendientes():
        if p["entrega"] == entrega and (t in tareas._sin_tildes(p["titulo"]) or tareas._sin_tildes(p["titulo"]) in t):
            return p["id"]
        if k and _clave(p["titulo"]) == k and abs((date.fromisoformat(p["entrega"]) - e).days) <= 10:
            return p["id"]                       # mismo título exacto, fechas cercanas: es el mismo deber
    return None


def reparar_duplicados(eventos=None):
    """Junta deberes repetidos (la fecha de entrega y la de cierre del mismo deber de Moodle, o el mismo deber
    anotado dos veces). Deja una sola tarea, borra las copias (también de Google) y quita sus bloques de estudio.
    No toca deberes distintos con el mismo nombre (p. ej. un foro semanal): esos tienen las dos fechas de entrega.
    Devuelve una lista de textos con lo que juntó."""
    from datetime import date
    resumen = {e["uid"]: e.get("resumen", "") for e in (eventos or [])}
    with closing(_con()) as con:
        filas = con.execute("SELECT * FROM moodle_eventos WHERE tarea_id IS NOT NULL").fetchall()
    origen = {}                                   # tarea -> 'entrega' | 'cierre' | 'moodle'
    for f in filas:
        r = resumen.get(f["uid"], "")
        tipo = "cierre" if r and CIERRE.search(r) else ("entrega" if r else "moodle")
        if origen.get(f["tarea_id"]) != "entrega":
            origen[f["tarea_id"]] = tipo
    grupos = {}
    for t in tareas.pendientes():
        grupos.setdefault((_clave(t["titulo"]), t["materia"]), []).append(t)
    hechos = []
    for (k, materia), lista in grupos.items():
        if not k or len(lista) < 2:
            continue
        lista.sort(key=lambda t: (t["entrega"], t["id"]))
        quedan = list(lista)
        while len(quedan) >= 2:
            a, b = quedan[0], quedan[1]
            cerca = abs((date.fromisoformat(b["entrega"]) - date.fromisoformat(a["entrega"])).days) <= 10
            oa, ob = origen.get(a["id"], "a mano"), origen.get(b["id"], "a mano")
            mismo = a["entrega"] == b["entrega"] or (cerca and ("cierre" in (oa, ob) or "a mano" in (oa, ob)))
            if not mismo:
                quedan.pop(0)
                continue
            # se queda la de ENTREGA; si ninguna se sabe, la de fecha más temprana
            if ob == "entrega" and oa != "entrega":
                queda, sobra = b, a
            else:
                queda, sobra = a, b
            tareas.cambiar_estado(sobra["id"], "borrada")
            try:
                tareas.quitar_de_google(sobra["id"])
            except Exception as exc:
                log.info("Copia %s sin quitar de Google: %s", sobra["id"], exc)
            with closing(_con()) as con, con:
                con.execute("UPDATE moodle_eventos SET tarea_id = ? WHERE tarea_id = ?", (queda["id"], sobra["id"]))
            log.info("Deber repetido: quedó #%s (%s), borré #%s (%s)", queda["id"], queda["entrega"],
                     sobra["id"], sobra["entrega"])
            hechos.append((queda, sobra))
            quedan = [queda] + [x for x in quedan if x["id"] not in (queda["id"], sobra["id"])]
    if hechos:
        try:
            from modulos.proactivo import proactivo
            proactivo.revisar_bloques()           # los bloques de estudio de las copias se borran solos
        except Exception as exc:
            log.warning("No pude limpiar bloques de copias: %s", exc)
    salida = []
    for queda, sobra in hechos:
        if any(q["id"] == queda["id"] and s_["entrega"] == sobra["entrega"] for q, s_ in hechos[:hechos.index((queda, sobra))]):
            continue                              # misma copia repetida: una sola línea
        salida.append("• " + queda["titulo"] + (" (" + queda["materia"] + ")" if queda["materia"] != "General" else "")
                      + ": quedó la entrega del " + tareas.fecha_bonita(queda["entrega"])
                      + " (quité la copia del " + tareas.fecha_bonita(sobra["entrega"]) + ")")
    return salida


def _subir(tid):
    try:
        tareas.subir(tid)
        return True
    except Exception as exc:
        log.warning("Tarea %s sin subir a Google: %s", tid, exc)
        return False


def _subir_evento(uid, titulo, materia, vence):
    """Eventos de Moodle que NO son deberes (examen, clase en vivo, tutoría...): también a Google Calendar.
    Si el usuario lo borra del celular, no se vuelve a poner."""
    from modulos.calendario import extra_google as eg
    clave = "moodle:" + uid[:120]
    if eg.borrado_por_usuario(clave):
        return
    titulo_g = "\U0001F393 " + titulo + (" (" + materia + ")" if materia else "")
    try:
        if vence.strftime("%H:%M") in ("00:00", "23:59"):
            eg.dia_completo(clave, "moodle", titulo_g, vence.date(), "Evento de Moodle.", avisos_min=(300,), color="9")
        else:
            eg.con_hora(clave, "moodle", titulo_g, vence, 60, "Evento de Moodle.", avisos_min=(60, 1440), color="9")
    except Exception as exc:
        log.warning("Evento de Moodle sin subir a Google: %s", exc)


def revisar():
    """Descarga el calendario y procesa los cambios. Devuelve (mensajes_html, cuantos_eventos)."""
    if not url():
        raise RuntimeError("Falta MOODLE_ICAL_URL en .env")
    r = requests.get(url(), timeout=60)
    r.raise_for_status()
    if "BEGIN:VCALENDAR" not in r.text[:200]:
        raise RuntimeError("Moodle no devolvio un calendario (¿enlace vencido?)")
    eventos = leer_calendario(r.text)
    con_entrega = set()                       # (titulo, curso) de deberes que traen su fecha de ENTREGA
    for ev in eventos:
        tipo_, titulo_ = clasificar(ev)
        if tipo_ == "deber" and not CIERRE.search(ev.get("resumen", "")):
            con_entrega.add((_clave(titulo_), ev.get("curso", "")))
    primera_vez = not db.aviso_enviado("moodle|inicial")
    nuevos, cambios, mensajes = [], [], []
    with closing(_con()) as con:
        vistos = {f["uid"]: dict(f) for f in con.execute("SELECT * FROM moodle_eventos")}

    for ev in eventos:
        tipo, titulo = clasificar(ev)
        if tipo == "apertura":
            continue
        if tipo == "deber" and CIERRE.search(ev.get("resumen", "")) and \
                (_clave(titulo), ev.get("curso", "")) in con_entrega:
            tipo = "cierre"                   # ya está la fecha de entrega de ese deber: el cierre no crea otra tarea
        vence = ev["inicio"]
        materia = materia_de(ev.get("curso", ""))
        previo = vistos.get(ev["uid"])
        if previo:
            if previo["vence"] != vence.isoformat():                          # el profesor cambio la fecha
                with closing(_con()) as con, con:
                    con.execute("UPDATE moodle_eventos SET vence = ?, titulo = ? WHERE uid = ?",
                                (vence.isoformat(), titulo, ev["uid"]))
                t = tareas.obtener(previo["tarea_id"]) if previo["tarea_id"] else None
                if t and t["estado"] == "pendiente":
                    tareas.cambiar_entrega(t["id"], vence.date().isoformat())
                    with closing(tareas._con()) as con, con:
                        con.execute("UPDATE tareas SET hora = ? WHERE id = ?", (vence.strftime("%H:%M"), t["id"]))
                    _subir(t["id"])
                if previo["tipo"] == "evento" and vence > ahora():
                    _subir_evento(ev["uid"], titulo, materia, vence)
                if vence > ahora() and (previo["tipo"] == "evento" or (t and t["estado"] == "pendiente")):
                    cambios.append((titulo, materia, datetime.fromisoformat(previo["vence"]), vence))
            elif previo["tipo"] == "evento" and vence > ahora() and not db.obtener_evento("moodle:" + ev["uid"][:120]):
                _subir_evento(ev["uid"], titulo, materia, vence)             # los que ya se habían visto antes
            continue
        tarea_id = None
        if tipo == "deber" and vence > ahora():
            tarea_id = _tarea_parecida(titulo, vence.date().isoformat())
            if not tarea_id:
                tarea_id = tareas.crear(materia or "General", titulo[:1].upper() + titulo[1:],
                                        vence.date().isoformat(), vence.strftime("%H:%M"))
                _subir(tarea_id)
        with closing(_con()) as con, con:
            con.execute("INSERT OR IGNORE INTO moodle_eventos (uid, tipo, titulo, curso, materia, vence, tarea_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)", (ev["uid"], tipo, titulo, ev.get("curso", ""), materia,
                                                          vence.isoformat(), tarea_id))
        if vence > ahora() and tipo != "cierre":
            nuevos.append((tipo, titulo, materia, vence, tarea_id))
            if tipo == "evento":
                _subir_evento(ev["uid"], titulo, materia, vence)

    try:
        juntados = reparar_duplicados(eventos)
    except Exception as exc:
        log.warning("Revisión de deberes repetidos falló: %s", exc)
        juntados = []
    if juntados:
        mensajes.append("\U0001F9F9 <b>Tenía deberes repetidos</b> (Moodle manda la fecha de entrega y la de cierre "
                        "del mismo deber). Dejé uno solo:\n" + escape("\n".join(juntados))
                        + "\nTambién quité de su agenda y de Google los bloques de estudio que sobraban.")
    nuevos.sort(key=lambda x: x[3])
    deberes = [n for n in nuevos if n[0] == "deber"]
    otros = [n for n in nuevos if n[0] != "deber"]
    if deberes:
        cabeza = ("\U0001F393 <b>Conecté Moodle.</b> Estos son sus deberes pendientes:" if primera_vez
                  else "\U0001F4DA <b>Deber nuevo en Moodle</b>" if len(deberes) == 1 else
                  "\U0001F4DA <b>" + str(len(deberes)) + " deberes nuevos en Moodle</b>")
        lineas = [cabeza, ""]
        for _, titulo, materia, vence, tid in deberes:
            lineas.append("• <b>" + escape(titulo) + "</b>" + (" – " + escape(materia) if materia else "")
                          + "\n   Entrega: " + _cuando(vence) + ("  <i>(tarea #" + str(tid) + ")</i>" if tid else ""))
        lineas += ["", "Ya están en sus /tareas y en Google Calendar con avisos. Cuando lo entregue, márquelo con /hecho."]
        mensajes.append("\n".join(lineas))
    if otros:
        mensajes.append("\U0001F4C5 <b>Evento en Moodle</b>\n" + "\n".join(
            "• " + escape(t) + (" – " + escape(m) if m else "") + ": " + _cuando(v) for _, t, m, v, _ in otros)
            + "\nYa está en su Google Calendar con aviso.")
    for titulo, materia, antes, ahora_ in cambios:
        mensajes.append("\U0001F504 <b>Cambió una fecha en Moodle</b>\n• " + escape(titulo)
                        + (" – " + escape(materia) if materia else "") + "\n   Antes: " + antes.strftime("%d/%m %H:%M")
                        + "  →  Ahora: " + _cuando(ahora_) + "\nYa lo actualicé en sus tareas y en Google Calendar.")
    if primera_vez:
        db.marcar_aviso("moodle|inicial")
        if not deberes:
            mensajes.append("\U0001F393 Conecté Moodle. Por ahora no hay deberes pendientes; le aviso cuando aparezca uno.")
    log.info("Moodle revisado: %d eventos, %d nuevos, %d cambios", len(eventos), len(nuevos), len(cambios))
    return mensajes, len(eventos)


def proximos(dias=21):
    """Deberes de Moodle que vencen pronto (para /moodle)."""
    limite = (ahora() + timedelta(days=dias)).isoformat()
    with closing(_con()) as con:
        filas = con.execute("SELECT * FROM moodle_eventos WHERE tipo = 'deber' AND vence >= ? AND vence <= ? "
                            "ORDER BY vence", (ahora().isoformat(), limite)).fetchall()
    salida = []
    for f in filas:
        t = tareas.obtener(f["tarea_id"]) if f["tarea_id"] else None
        salida.append({"titulo": f["titulo"], "materia": f["materia"], "vence": datetime.fromisoformat(f["vence"]),
                       "hecha": bool(t and t["estado"] == "hecha"), "tarea": f["tarea_id"]})
    return salida
