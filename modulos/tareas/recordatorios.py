"""Recordatorios entendidos desde el código (sin IA): «recuérdame X el viernes», «toda la semana», «a las 5»…

- Crea una actividad corta («🔔 X») en la agenda y en Google Calendar: avisa en la PC, Telegram y el celular.
- Una vez, todos los días, de lunes a viernes, fines de semana, ciertos días («los martes y jueves»),
  «toda la semana», «por 3 días», «hasta el viernes».
- Si falta algo, pregunta UNA cosa y entiende la respuesta («toda la semana», «el viernes a las 5», «comprar pan»).
- Sin hora: a las 09:00 (si es para hoy, pregunta la hora).
- Nada de dinero ni datos personales sale de la PC: a Google va solo el texto del recordatorio.
"""
import re
import time
import unicodedata
from datetime import date, datetime, timedelta

from modulos.comun.base import DIAS, DIAS_BONITO, ahora, registro

log = registro("recordatorios")

HORA_DEFECTO = "09:00"
NOTA = "Recordatorio"
ULTIMO = {}               # el último creado, para «mejor a las 7» / «no, toda la semana» (10 min)
PENDIENTE = {}            # lo que falta preguntar: {"desc", "fecha", "hora", "dias", "hasta", "falta", "ts"}
NUM = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
       "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20, "treinta": 30}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
_N = r"(\d{1,2}|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|quince|veinte|treinta)"
_DIA = r"(lunes|martes|miercoles|jueves|viernes|sabado|domingo)"


def _st(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _num(x):
    return NUM.get(x) if x in NUM else int(x)


# ------------------------------------------------------------------ frases ---
PIDE = re.compile(
    r"\b(?:recuerdamelo|recuerdamela|recuerdame|recuerdeme|recordarme|recordarmelo|me recuerdas|me recuerdes|"
    r"me puedes recordar|me podrias recordar|me podria recordar|puedes recordarme|podrias recordarme|"
    r"quiero que me recuerdes|necesito que me recuerdes|acuerdame|hazme acordar|haz que me acuerde|"
    r"que no se me olvide|no se me vaya a olvidar|no me dejes olvidar|no dejes que (?:se me olvide|me olvide|olvide)|"
    r"(?:pon|ponme|poner|crea|creame|crear|agenda|agendame|haz|hazme|programa|programame|anota|anotame|guarda|guardame)"
    r"\s+(?:un |una )?(?:recordatorio|alarma|aviso)s?|"
    r"recordatorio(?:\s+(?:de|para|que|el|la))?|alarma (?:para|de|que))\b")
AVISA = re.compile(r"\b(?:avisame|me avisas|me avises|avisarme|me puedes avisar|me podrias avisar)\b")
LISTAR = re.compile(r"\b(?:que|cuales|mis|ver|lista\w*|muestrame|tengo)\b.*\brecordatorios\b|^\W*recordatorios\W*$")
CANCELA = re.compile(r"^\W*(?:no|nada|olvidalo|olvida eso|cancela\w*|dejalo|mejor no|ya no)\W*$")
NO_SE_PUEDE = re.compile(r"\bcada\s+(?:\d+\s+)?(?:hora|horas|minuto|minutos)\b|\b(?:cada|todos los)\s+mes(?:es)?\b|"
                         r"\bmensual\w*\b|\bcada\s+ano\b|\banual\w*\b")


def _fecha_dia(nombre, hoy, permite_hoy):
    i = DIAS.index(nombre)
    dif = (i - hoy.weekday()) % 7
    if dif == 0 and not permite_hoy:
        dif = 7
    return hoy + timedelta(days=dif)


def interpretar(texto, momento=None):
    """dict con lo que entendió (sin crear nada):
    {"desc", "fecha": date|None, "hora": "HH:MM"|None, "dias": "lunes,..."|"" , "hasta": date|None,
     "con_cuando": bool, "no_soportado": bool}"""
    momento = momento or ahora()
    hoy = momento.date()
    orig = texto.strip()
    t = _st(orig)
    if len(t) != len(orig):                  # por si algún carácter cambió de largo: se trabaja sin tildes
        orig = t
    quitar = []                              # tramos que no son la descripción

    def marca(m, g=0):
        quitar.append((m.start(g), m.end(g)))

    r = {"desc": "", "fecha": None, "hora": None, "dias": "", "hasta": None, "con_cuando": False,
         "no_soportado": bool(NO_SE_PUEDE.search(t))}

    # --- hora
    hora = None
    m = re.search(r"\b(?:en|dentro de)\s+(media hora|" + _N + r"\s+(minutos?|mins?|horas?)(?:\s+y\s+media)?)\b", t)
    if m:
        if m.group(1) == "media hora":
            delta = timedelta(minutes=30)
        else:
            n = _num(m.group(2))
            delta = timedelta(hours=n) if m.group(3).startswith("hora") else timedelta(minutes=n)
            if "y media" in m.group(0):
                delta += timedelta(minutes=30)
        cuando = momento + delta
        r["fecha"], hora = cuando.date(), cuando.strftime("%H:%M")
        marca(m)
    patron_hora = (r"\b(?:a eso de las?|como a las?|tipo|a las?|para las?|desde las?|sobre las?|las)\s+"
                   r"(\d{1,2})(?:\s*[:.h]\s*(\d{2}))?(?:\s+y\s+(media|cuarto)|\s+menos\s+(cuarto))?"
                   r"(?:\s*(am|pm|a\s?m|p\s?m|de la manana|de la tarde|de la noche|de la madrugada|del mediodia|hrs|horas|h)\b)?")
    m = None if hora else (re.search(patron_hora, t) or
                           re.search(r"\b(\d{1,2})\s*[:h]\s*(\d{2})()()\s*(am|pm|a\s?m|p\s?m|hrs|horas)?\b", t) or
                           re.search(r"\b(\d{1,2})()()()\s*(am|pm|a\s?m|p\s?m)\b", t))
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) == "media":
            mi = 30
        elif m.group(3) == "cuarto":
            mi = 15
        if m.group(4):
            h, mi = h - 1, 45
        suf = (m.group(5) or "").replace(" ", "")
        if suf in ("pm", "delatarde", "delanoche") or suf.startswith("p") or "tarde" in suf or "noche" in suf:
            if h < 12:
                h += 12
        elif suf.startswith("a") or "manana" in suf or "madrugada" in suf:
            if h == 12:
                h = 0
        elif suf in ("", "h", "hrs", "horas") and not m.group(2) and 1 <= h <= 6:
            h += 12                          # «a las 5» = 17:00
        elif suf == "" and 7 <= h <= 11 and re.search(r"\b(?:noche|tarde)\b", t):
            h += 12
        if 0 <= h <= 23 and 0 <= mi <= 59:
            hora = "%02d:%02d" % (h, mi)
            marca(m)
    if not hora:
        for patron, valor in ((r"\b(?:al |a |en el |el )?medio ?dia\b", "12:00"),
                              (r"\b(?:en|por|a|durante) la (?:manana|mananita)\b", "09:00"),
                              (r"\btemprano\b|\ba primera hora\b|\bapenas me levante\b|\bal despertar\b", "08:00"),
                              (r"\b(?:en|por|a|durante) la tarde\b|\besta tarde\b", "15:00"),
                              (r"\b(?:en|por|a|durante) la noche\b|\besta noche\b|\bantes de dormir\b", "20:00")):
            m = re.search(patron, t)
            if m:
                hora = valor
                marca(m)
                if m.group(0).startswith("esta"):
                    r["fecha"] = r["fecha"] or hoy
                break
    r["hora"] = hora

    # --- repetición
    dias, hasta = [], None
    for patron, lista in ((r"\b(?:todos los dias|todo los dias|cada dia|diario|diariamente|a diario|todas las mananas|"
                           r"todas las noches|todas las tardes|cada manana|cada noche|cada tarde)\b", DIAS),
                          (r"\b(?:de lunes a viernes|entre semana|dias laborables|dias de semana|dias habiles)\b", DIAS[:5]),
                          (r"\b(?:los |cada |todos los )fines? de semana\b", DIAS[5:]),
                          (r"\b(?:toda la semana|toda esta semana|durante (?:la|esta) semana|cada dia de (?:la|esta) semana|"
                           r"todos los dias de (?:la|esta) semana|lo que queda de (?:la )?semana|el resto de la semana)\b", "SEMANA")):
        m = re.search(patron, t)
        if m:
            marca(m)
            if lista == "SEMANA":
                dias = list(DIAS)
                hasta = hoy + timedelta(days=6 - hoy.weekday())
                r["semana"] = True
            else:
                dias = list(lista)
            if re.search(r"todas las noches|cada noche", m.group(0)) and not hora:
                r["hora"] = hora = "20:00"
            if re.search(r"todas las mananas|cada manana", m.group(0)) and not hora:
                r["hora"] = hora = "09:00"
            if re.search(r"todas las tardes|cada tarde", m.group(0)) and not hora:
                r["hora"] = hora = "15:00"
            break
    m = re.search(r"\b(?:los|cada|todos los|todas las semanas el|cada semana el)\s+" + _DIA +
                  r"(?:\s*(?:,|y|e)\s*(?:los\s+)?" + _DIA + r")*(?:\s*(?:,|y|e)\s*(?:los\s+)?" + _DIA + r")?", t)
    if m and not dias:
        dias = [d for d in DIAS if re.search(r"\b" + d + r"\b", m.group(0))]
        marca(m)
    m = re.search(r"\b(?:por|durante|los proximos|las proximas|por los proximos)\s+" + _N + r"\s+(dias|semanas)\b", t)
    if m:
        n = _num(m.group(1))
        dias = dias or list(DIAS)
        hasta = hoy + timedelta(days=(n * 7 if m.group(2) == "semanas" else n) - 1)
        marca(m)
    if re.search(r"\bcada semana\b|\bsemanalmente\b|\btodas las semanas\b", t):
        marca(re.search(r"\bcada semana\b|\bsemanalmente\b|\btodas las semanas\b", t))
        r["semanal"] = True

    # --- hasta
    m = re.search(r"\bhasta (?:el |este |el proximo |el dia )?(?:" + _DIA + r"|(\d{1,2})[/-](\d{1,2})|(\d{1,2})(?: de (\w+))?|"
                  r"(manana|pasado manana|fin de mes|fin de semana))\b", t)
    if m:
        if m.group(1):
            hasta = _fecha_dia(m.group(1), hoy, False)
        elif m.group(2):
            hasta = _ddmm(int(m.group(2)), int(m.group(3)), hoy)
        elif m.group(4):
            hasta = _dia_mes(int(m.group(4)), m.group(5), hoy)
        elif m.group(6) == "manana":
            hasta = hoy + timedelta(days=1)
        elif m.group(6) == "pasado manana":
            hasta = hoy + timedelta(days=2)
        elif m.group(6) == "fin de mes":
            hasta = _fin_de_mes(hoy)
        elif m.group(6) == "fin de semana":
            hasta = hoy + timedelta(days=6 - hoy.weekday())
        marca(m)
        if not dias:
            dias = list(DIAS)                # «recuérdame X hasta el viernes» = cada día hasta el viernes

    # --- fecha
    fecha = r["fecha"]
    bloqueado = lambda a, b: any(qa <= a < qb or qa < b <= qb for qa, qb in quitar)
    if not fecha:
        for patron in (r"\bpasado manana\b", r"(?<!la )(?<!por la )(?<!en la )\bmanana\b", r"\bhoy(?: mismo)?\b|\bahorita\b|\bahora mismo\b",
                       r"\b(?:el |este |para el |para este )?fin de semana\b(?! que)",
                       r"\b(?:a |para |el )?fin de mes\b",
                       r"\b(?:en|dentro de)\s+" + _N + r"\s+(dias|semanas)\b",
                       r"\b(?:el |este |para el |para este |el proximo |este proximo |proximo |el siguiente |el otro )?"
                       + _DIA + r"(?:\s+(?:que viene|proximo|siguiente|de la (?:proxima|otra) semana))?\b",
                       r"\b(?:la )?(?:proxima semana|semana que viene|siguiente semana)\b",
                       r"\b(\d{1,2})[/-](\d{1,2})(?:[/-]\d{2,4})?\b",
                       r"\b(?:el |para el |el dia |este )(\d{1,2})(?: de (" + "|".join(MESES) + r"))?\b(?!\s*(?:dias|semanas|:|am|pm|minutos|horas))",
                       r"\b(\d{1,2}) de (" + "|".join(MESES) + r")\b"):
            for m in re.finditer(patron, t):
                if bloqueado(m.start(), m.end()):
                    continue
                g = m.group(0)
                if "pasado manana" in g:
                    fecha = hoy + timedelta(days=2)
                elif "manana" in g:
                    fecha = hoy + timedelta(days=1)
                elif re.search(r"hoy|ahorita|ahora mismo", g):
                    fecha = hoy
                elif "semana" in g and "fin" not in g:
                    fecha = hoy + timedelta(days=7 - hoy.weekday())
                elif "fin de semana" in g:
                    fecha = _fecha_dia("sabado", hoy, True)
                elif "fin de mes" in g:
                    fecha = _fin_de_mes(hoy)
                elif re.match(r"(?:en|dentro de)\s", g):
                    n = _num(m.group(1))
                    fecha = hoy + timedelta(days=n * 7 if m.group(2) == "semanas" else n)
                elif re.search(_DIA, g):
                    nombre = re.search(_DIA, g).group(1)
                    if re.search(r"proxima semana|otra semana|el otro", g):
                        fecha = _fecha_dia(nombre, hoy, False)
                        if (fecha - hoy).days < 7 and fecha.weekday() >= hoy.weekday():
                            fecha += timedelta(days=7)
                    else:
                        fecha = _fecha_dia(nombre, hoy, bool(re.search(r"\beste\b|para este", g)))
                elif "/" in g or "-" in g:
                    fecha = _ddmm(int(m.group(1)), int(m.group(2)), hoy)
                else:
                    try:
                        fecha = _dia_mes(int(m.group(1)), m.group(2) if m.lastindex and m.lastindex >= 2 else None, hoy)
                    except (ValueError, TypeError):
                        continue
                if fecha:
                    marca(m)
                    break
            if fecha:
                break
    if dias and fecha and (not hasta or r.get("semana")) and not r.get("semanal"):
        # «recuérdame X todos los días para el viernes» -> cada día HASTA el viernes
        hasta, fecha = fecha, None
    if r.get("semanal") and not dias:
        base = fecha or hoy
        dias = [DIAS[base.weekday()]]
    r["fecha"], r["dias"], r["hasta"] = fecha, ",".join(d for d in DIAS if d in dias), hasta
    r["con_cuando"] = bool(fecha or hora or dias)

    # --- descripción
    for m in [PIDE.search(t), AVISA.search(t)]:
        if m:
            marca(m)
    for patron in (r"\b(?:por favor|porfa|porfis|plis|please|senor|gracias)\b", r"^\W*(?:oye|hola|ey|asistente|lurnes)\b",
                   r"\b(?:puedes|podrias|podria|quiero que|necesito que)\b"):
        for m in re.finditer(patron, t):
            marca(m)
    quitar.sort()
    partes, pos = [], 0
    for a, b in quitar:
        if a > pos:
            partes.append(orig[pos:a])
        pos = max(pos, b)
    partes.append(orig[pos:])
    desc = " ".join(" ".join(partes).split())
    vacias = r"(?:que|de|del|para|el|la|los|las|a|al|en|por|y|e|me|lo|la|se|le|te|tambien|algo|eso|esto|un|una|" \
             r"recordatorio|alarma|aviso|todo|toda|cada|desde|hasta|hora|dia|dias|es|sea|,|\.|;|:|!|\?|¿|¡)"
    for _ in range(6):
        desc = re.sub(r"^\W*" + vacias + r"\b\W*", "", desc, flags=re.I) if re.match(r"^\W*" + vacias + r"\b", desc, re.I) else desc
        desc = re.sub(r"\W*\b" + vacias + r"\W*$", "", desc, flags=re.I) if re.search(r"\b" + vacias + r"\W*$", desc, re.I) else desc
    desc = desc.strip(" ,.;:¿?¡!-")
    if _st(desc) in ("", "algo", "eso", "esto", "una cosa", "algo importante"):
        desc = ""
    r["desc"] = desc[:1].upper() + desc[1:]
    return r


def _ddmm(d, m, hoy):
    try:
        f = date(hoy.year, m, d)
    except ValueError:
        return None
    return date(hoy.year + 1, m, d) if (hoy - f).days > 60 else f


def _dia_mes(d, mes, hoy):
    if mes:
        return _ddmm(d, MESES.index(mes) + 1, hoy)
    if not 1 <= d <= 31:
        return None
    y, mm = hoy.year, hoy.month
    if d < hoy.day:
        mm += 1
        if mm > 12:
            y, mm = y + 1, 1
    try:
        return date(y, mm, d)
    except ValueError:
        return None


def _fin_de_mes(hoy):
    sig = date(hoy.year + (hoy.month == 12), hoy.month % 12 + 1, 1)
    return sig - timedelta(days=1)


# ------------------------------------------------------------------ textos ---
_REF = {}                 # «hoy» de referencia (el del mensaje; en las pruebas, la fecha fija)


def _cuando_txt(d):
    hoy = _REF.get("hoy") or ahora().date()
    if d == hoy:
        return "hoy"
    if d == hoy + timedelta(days=1):
        return "mañana"
    return "el " + DIAS_BONITO[d.weekday()] + " " + d.strftime("%d/%m")


def _dias_txt(dias):
    lista = dias.split(",")
    if len(lista) == 7:
        return "todos los días"
    if lista == DIAS[:5]:
        return "de lunes a viernes"
    if lista == DIAS[5:]:
        return "los fines de semana"
    nombres = [DIAS_BONITO[DIAS.index(d)] for d in lista]
    return "los " + (", ".join(nombres[:-1]) + " y " + nombres[-1] if len(nombres) > 1 else nombres[0])


# ------------------------------------------------------------------ crear ---
def crear(r, momento=None):
    """Crea la actividad. Devuelve el texto para el usuario."""
    from modulos.agenda import eventos
    momento = momento or ahora()
    hoy = momento.date()
    _REF["hoy"] = hoy
    hora = r["hora"] or HORA_DEFECTO
    dias = r["dias"]
    fecha = r["fecha"] or hoy
    hasta = r["hasta"]
    aviso_hora = ""
    if not dias:
        if fecha == hoy and hora <= momento.strftime("%H:%M"):
            if r["hora"]:
                return None                  # la hora ya pasó: se pregunta
            hora = (momento + timedelta(minutes=60)).strftime("%H:00")
        if not r["hora"]:
            aviso_hora = " (si prefiere otra hora, dígame «a las 7», por ejemplo)"
    else:
        # primer día que toca, desde hoy (o mañana si la hora de hoy ya pasó)
        inicio = fecha if r["fecha"] else hoy
        while DIAS[inicio.weekday()] not in dias.split(",") or (inicio == hoy and hora <= momento.strftime("%H:%M")):
            inicio += timedelta(days=1)
            if hasta and inicio > hasta:
                return "Para cuando toca, señor, ya pasó la fecha final. ¿Me dice otra?"
        fecha = inicio
        if not r["hora"]:
            aviso_hora = " (si prefiere otra hora, dígame «a las 7», por ejemplo)"
    fin = (datetime.strptime(hora, "%H:%M") + timedelta(minutes=15)).strftime("%H:%M")
    if fin < hora:
        fin = "23:59"
    titulo = "\U0001F514 " + r["desc"][:70]
    eid = eventos.crear(titulo, fecha, hora, fin, dias, hasta.isoformat() if hasta else None, 0, NOTA)
    try:
        eventos.subir(eid)
        donde = "en la PC, Telegram y Google Calendar"
    except Exception as exc:
        log.warning("Recordatorio %s sin subir a Google: %s", eid, exc)
        donde = "en la PC y Telegram (Google Calendar no respondió; lo reintento luego)"
    if dias:
        cuando = _dias_txt(dias) + " a las " + hora + (", desde " + _cuando_txt(fecha) if fecha != hoy else "") + \
                 (" hasta " + _cuando_txt(hasta) if hasta else "")
    else:
        cuando = _cuando_txt(fecha) + " a las " + hora
    log.info("Recordatorio #%s: %s | %s", eid, r["desc"], cuando)
    ULTIMO.clear()
    ULTIMO.update(r, eid=eid, ts=time.time())
    return "\U0001F514 Listo, señor. Le recordaré «" + r["desc"] + "» " + cuando + aviso_hora + ", " + donde + "."


def listar(momento=None):
    from modulos.agenda import eventos
    hoy = (momento or ahora()).date().isoformat()
    lista = [e for e in eventos.activos() if (e["nota"] or "") == NOTA and (e["hasta"] or e["fecha"]) >= hoy]
    if not lista:
        return "No tiene recordatorios pendientes, señor."
    lineas = ["\U0001F514 Sus recordatorios:"]
    for e in lista:
        d = date.fromisoformat(e["fecha"])
        cuando = (_dias_txt(e["dias"]) + (" hasta " + _cuando_txt(date.fromisoformat(e["hasta"])) if e["hasta"] else "")
                  if e["dias"] else _cuando_txt(d))
        lineas.append("• #" + str(e["id"]) + " " + e["titulo"].replace("\U0001F514 ", "") + " — " + cuando + " a las " + e["inicio"])
    return "\n".join(lineas)


# ------------------------------------------------------------------ entrada ---
def _preguntar(r, falta):
    PENDIENTE.clear()
    PENDIENTE.update(r, falta=falta, ts=time.time())
    if falta == "que":
        cuando = _resumen_cuando(r)
        return "¿Qué le recuerdo" + (" " + cuando if cuando else "") + ", señor?"
    if falta == "hora":
        return "¿A qué hora le recuerdo «" + r["desc"] + "» " + _resumen_cuando(r) + ", señor?"
    return ("¿Para cuándo le recuerdo «" + r["desc"] + "», señor? Por ejemplo: «mañana a las 9», «el viernes», "
            "«toda la semana» o «de lunes a viernes a las 7».")


def _resumen_cuando(r):
    if r.get("dias"):
        return _dias_txt(r["dias"]) + (" hasta " + _cuando_txt(r["hasta"]) if r.get("hasta") else "")
    if r.get("fecha"):
        return _cuando_txt(r["fecha"]) + (" a las " + r["hora"] if r.get("hora") else "")
    if r.get("hora"):
        return "a las " + r["hora"]
    return ""


def _mezclar(base, nuevo):
    junto = dict(base)
    for k in ("fecha", "hora", "dias", "hasta"):
        if nuevo.get(k):
            junto[k] = nuevo[k]
    if nuevo.get("dias") and base.get("fecha") and not base.get("dias") and not nuevo.get("fecha") and \
            (not nuevo.get("hasta") or nuevo.get("semana") or nuevo["hasta"] > base["fecha"]):
        junto["hasta"], junto["fecha"] = base["fecha"], None   # algo del viernes + «toda la semana»: cada día hasta el viernes
    junto["con_cuando"] = bool(junto.get("fecha") or junto.get("hora") or junto.get("dias"))
    return junto


def _decidir(r, momento):
    if r.get("no_soportado"):
        PENDIENTE.clear()
        return ("Por ahora puedo repetir recordatorios cada día o ciertos días de la semana, señor, no cada hora ni "
                "cada mes. ¿Se lo pongo, por ejemplo, «todos los días a las 9» o «los lunes»?")
    if not r["desc"]:
        return _preguntar(r, "que")
    if not r["con_cuando"]:
        return _preguntar(r, "cuando")
    if not r["dias"] and (r["fecha"] or momento.date()) == momento.date() and not r["hora"]:
        return _preguntar(dict(r, fecha=momento.date()), "hora")
    texto = crear(r, momento)
    if texto is None:
        return _preguntar(dict(r, hora=None), "hora").replace("¿A qué hora", "Esa hora ya pasó hoy. ¿A qué hora")
    PENDIENTE.clear()
    return texto


def _pregunta_anterior():
    """Si el último mensaje del asistente preguntó por un recordatorio («¿A qué hora le recuerdo «X»?»,
    también los de la IA), devuelve lo pendiente. Sirve aunque el bot se haya reiniciado."""
    try:
        from modulos.ia import memoria
        h = memoria.historial(2)
    except Exception:
        return None
    if not h or h[-1]["role"] != "assistant" or "?" not in h[-1]["content"]:
        return None
    m = re.search(r"le recuerdo «(.+?)»|anoto «(.+?)»", h[-1]["content"])
    if not m:
        return None
    falta = "hora" if re.search(r"qu[eé] hora", h[-1]["content"]) else "cuando"
    return {"desc": m.group(1) or m.group(2), "fecha": None, "hora": None, "dias": "", "hasta": None,
            "con_cuando": False, "no_soportado": False, "falta": falta}


def procesar(texto, momento=None):
    """Devuelve el texto de respuesta, o None si el mensaje no es de recordatorios."""
    momento = momento or ahora()
    _REF["hoy"] = momento.date()
    t = _st(texto or "")
    if LISTAR.search(t) and not PIDE.search(re.sub(r"\brecordatorios\b", "", t)):
        return listar(momento)
    pide = PIDE.search(t) or (AVISA.search(t) and interpretar(texto, momento)["con_cuando"])
    if PENDIENTE and time.time() - PENDIENTE.get("ts", 0) > 900:
        PENDIENTE.clear()
    if not pide and not PENDIENTE and ULTIMO and time.time() - ULTIMO["ts"] < 600 and \
            re.match(r"^\W*(?:mejor|no\b|que sea|cambia\w*|pero|mejor que sea|en vez de eso|corrige\w*)", t):
        nuevo = interpretar(texto, momento)
        resto = nuevo["desc"] or ""
        for _ in range(4):
            resto = re.sub(r"(?i)^\W*(?:no|mejor|pero|que sea|sea|cambia\w*|corrige\w*|en vez de eso|mejor que)\b\W*", "", resto)
        if nuevo["con_cuando"] and not resto.strip(" ,.;"):
            from modulos.agenda import eventos
            base = {k: v for k, v in ULTIMO.items() if k not in ("eid", "ts")}
            eventos.borrar(ULTIMO["eid"])
            ULTIMO.clear()
            if nuevo.get("hora") and not nuevo.get("fecha") and not nuevo.get("dias"):
                nuevo["fecha"] = base.get("fecha")
            junto = _mezclar({**base, "fecha": base.get("fecha") if not nuevo.get("dias") else base.get("fecha"),
                              "hora": base.get("hora")}, nuevo)
            if nuevo.get("fecha") and not nuevo.get("dias"):
                junto.update(dias="", hasta=None)
            return _decidir(junto, momento).replace("Listo, señor.", "Listo, señor, lo cambié.")
    if not pide and not PENDIENTE:
        previo = _pregunta_anterior()
        if previo:
            PENDIENTE.update(previo, ts=time.time())
    if not pide and PENDIENTE:
        if CANCELA.match(t):
            PENDIENTE.clear()
            return "Listo, señor, no lo anoto."
        if "?" in t or len(t.split()) > 15:
            PENDIENTE.clear()
            return None
        base = dict(PENDIENTE)
        falta = base.pop("falta")
        base.pop("ts", None)
        if falta in ("hora", "cuando") and re.match(r"^\W*(?:a las\s+)?\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)?\W*$", t):
            texto = "a las " + re.sub(r"^\W*(?:a las\s+)?", "", texto.strip())
        nuevo = interpretar(texto, momento)
        if falta == "que":
            base["desc"] = nuevo["desc"] or (texto.strip()[:1].upper() + texto.strip()[1:]).strip(" .")
            return _decidir(_mezclar(base, nuevo), momento)
        if not nuevo["con_cuando"]:
            PENDIENTE.clear()
            return None                      # habló de otra cosa
        return _decidir(_mezclar(base, nuevo), momento)
    if not pide:
        return None
    r = interpretar(texto, momento)
    if not r["con_cuando"]:
        try:                                  # «recuérdame que Juan me debe 300» es una deuda, no un recordatorio
            from modulos.finanzas import deudas
            if deudas.parece_deuda(texto):
                return None
        except Exception:
            pass
    return _decidir(r, momento)
