"""Preguntas sobre deberes respondidas desde el código (exacto, sin IA y sin crear nada).

  «¿tienes registrado el deber que tengo en 6 días de multimedia?»
  «¿para cuándo es el deber del ensayo?»   «¿cuándo entrego el informe?»
  «¿qué deberes tengo de animación?»       «¿qué entregas tengo esta semana?»

Solo LEE: nunca crea tareas ni agenda bloques. Si no encuentra lo pedido, lo dice y muestra lo que sí tiene.
"""
import re
from contextlib import closing
from datetime import date, timedelta

from modulos.comun.base import DIAS, ahora, leer_json, registro
from modulos.tareas import tareas

log = registro("tareas")

# palabras que dicen "deber" (las genéricas no sirven para filtrar; las específicas sí)
GENERICAS = {"deber", "deberes", "tarea", "tareas", "entrega", "entregas", "pendiente", "pendientes",
             "actividad", "actividades", "trabajo", "trabajos", "deberito"}
# palabras de un deber concreto: solo cuentan si además pregunta por la entrega («¿cuándo es el ensayo?»)
ESPECIFICAS = r"ensayo|informe|proyecto|foro|cuestionario|taller|investigaci[oó]n|exposici[oó]n|maqueta|" \
              r"portafolio|infograf[ií]a|storyboard|afiche|cartel|trabajo"
HABLA_DE_DEBER = re.compile(r"\b(?:deber(?:es|ito)?|tareas?|entregas?|pendientes|entrego|entregar|entregarlo|"
                            r"entregarla)\b", re.I)
ESPECIFICA = re.compile(r"\b(?:" + ESPECIFICAS + r")s?\b", re.I)
PIDE_FECHA = re.compile(r"\bcu[aá]ndo\b|\bqu[eé] (?:d[ií]a|fecha)\b|registrad|anotad|apuntad|guardad|"
                        r"\bfalta[n]?\b|\bqueda[n]?\b", re.I)
OTRO_TEMA = re.compile(r"deud|\bdeb[eo]\b|\bdeben\b|prest|pag[oóué]|gast|ahorr|sueldo|\$|d[oó]lar|video|pepe|cava|"
                       r"pablo gil|acci[oó]n|bolsa|noticia", re.I)
ES_CONSULTA = re.compile(r"\?|\bcu[aá]ndo\b|\bpara cu[aá]ndo\b|\bqu[eé] d[ií]a\b|\bqu[eé] fecha\b|\bhasta cu[aá]ndo\b|"
                         r"\b(?:tienes|tiene|esta|est[aá]|lo tienes|la tienes|tengo|hay|queda[n]?)\s+"
                         r"(?:registrad|anotad|apuntad|guardad|agendad)\w*|\bqu[eé]\b|\bcu[aá]l(?:es)?\b|"
                         r"\bcu[aá]ntos?\b|\bcu[aá]ntas?\b|\bdime\b|\bdecirme\b|\bmu[eé]strame\b|\bsabes\b|"
                         r"\brevisa\b|\bconfirma\w*\b|\bver\b|\blista\w*\b|^\W*(?:mis\s+)?(?:deberes|tareas|entregas|pendientes)\W*$",
                         re.I)
# órdenes: eso lo hacen otras partes (anotar, borrar, marcar hecha, planificar…)
_IMP = r"(?:me|lo|la|los|las|r|melo|mela)?\b"
ES_ORDEN = re.compile(r"\b(?:an[oó]ta" + _IMP + r"|ap[uú]nta" + _IMP + r"|recu[eé]rda" + _IMP + r"|recordarme|"
                      r"agr[eé]ga" + _IMP + r"|a[nñ]ade" + _IMP + r"|cr[eé]a" + _IMP + r"|"
                      r"b[oó]rra" + _IMP + r"|elimina" + _IMP + r"|quita" + _IMP + r"|m[aá]rca" + _IMP + r"|ya (?:la |lo )?(?:hice|entregu[eé]|termin[eé]|acab[eé])|"
                      r"termin[eé]|entregu[eé]|cambi[ao]\w*|mueve\w*|mu[eé]vela|planifica\w*|organ[ií]za\w*|"
                      r"ag[eé]nda(?:me|la|lo|r)\b|adel[aá]nta\w*|p[oó]n(?:me|la|lo)?\b)", re.I)
VACIAS = set("""a al algo alguna alguno ante como con cual cuales cuando cuanto cuantos cuantas de del desde dime
decirme el ella en entre es esa ese eso esta este esto estoy estan hay hasta la las le lo los me mi mis muestrame
no nos o para pero por porfa porfavor puedes podrias que quiero registrado registrada anotado anotada apuntado
apuntada guardado guardada agendado agendada se si sobre su sus tal te tengo tienes tiene toca tu tus un una uno
unos unas va ver y ya algun alguno alguna ningun ninguno ninguna tienes tiene dias dia semana semanas hoy manana pasado proxima proximo siguiente esta este fecha
lunes martes miercoles jueves viernes sabado domingo sabes revisa confirma confirmame lista listame hora
entrego entregar entregarlo entregarla queda quedan falta faltan materia clase curso favor""".split())


def _n(t):
    return re.sub(r"[^a-z0-9ñ ]+", " ", tareas._sin_tildes(t or "")).strip()


def es_consulta(texto):
    t = texto or ""
    if not ES_CONSULTA.search(t) or ES_ORDEN.search(t) or OTRO_TEMA.search(t):
        return False
    return bool(HABLA_DE_DEBER.search(t) or (ESPECIFICA.search(t) and PIDE_FECHA.search(t)))


def _materias():
    nombres = set()
    try:
        nombres |= {c["materia"] for c in leer_json("horario_clases.json")["clases"]}
    except Exception:
        pass
    try:
        nombres |= {t["materia"] for t in tareas.pendientes() if t["materia"] != "General"}
    except Exception:
        pass
    return nombres


def _materia_pedida(tn):
    """Materias nombradas en el texto (por una palabra distintiva de 4+ letras)."""
    salida, usadas = set(), set()
    palabras = set(tn.split())
    for m in _materias():
        claves = [w for w in _n(m).split() if len(w) >= 4 and w not in ("introduccion", "taller", "fundamentos")]
        hit = [w for w in claves if w in palabras or w + "s" in palabras or (w.endswith("s") and w[:-1] in palabras)]
        if hit:
            salida.add(m)
            usadas |= set(hit)
    return salida, usadas


def _rango(tn, hoy):
    """(desde, hasta, texto) de la fecha pedida, o None."""
    m = re.search(r"\b(?:en|dentro de)\s+(\d{1,2}|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+dias?\b", tn)
    if m:
        num = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
               "nueve": 9, "diez": 10}.get(m.group(1)) or int(m.group(1))
        d = hoy + timedelta(days=num)
        return d - timedelta(days=1), d + timedelta(days=1), "en " + str(num) + " días (" + tareas.fecha_bonita(d.isoformat()) + ")"
    if re.search(r"\bpasado manana\b", tn):
        d = hoy + timedelta(days=2)
        return d, d, "pasado mañana"
    if re.search(r"\bmanana\b", tn):
        d = hoy + timedelta(days=1)
        return d, d, "mañana"
    if re.search(r"\bhoy\b", tn):
        return hoy, hoy, "hoy"
    if re.search(r"\b(?:proxima|siguiente)\s+semana\b|\bsemana que viene\b", tn):
        ini = hoy + timedelta(days=7 - hoy.weekday())
        return ini, ini + timedelta(days=6), "la próxima semana"
    if re.search(r"\besta semana\b", tn):
        return hoy, hoy + timedelta(days=6 - hoy.weekday()), "esta semana"
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", tn)
    if m:
        try:
            d = date(hoy.year, int(m.group(2)), int(m.group(1)))
            if (hoy - d).days > 60:
                d = date(hoy.year + 1, d.month, d.day)
            return d, d, "el " + d.strftime("%d/%m")
        except ValueError:
            pass
    for i, nombre in enumerate(DIAS):
        if re.search(r"\b" + nombre + r"\b", tn):
            d = hoy + timedelta(days=(i - hoy.weekday()) % 7 or 7)
            return d, d, "el " + tareas.fecha_bonita(d.isoformat())
    return None


def _bloques(tid):
    """Bloques de estudio futuros ya agendados para ese deber."""
    try:
        from modulos.proactivo import proactivo
        with closing(proactivo._con_bloques()) as con:
            filas = con.execute("SELECT * FROM plan_bloques WHERE tid = ? AND estado = 'activo' ORDER BY dia, ini",
                                (tid,)).fetchall()
        return [b for b in filas if not proactivo._ya_paso(b)]
    except Exception:
        return []


def _linea(t, hoy):
    d = date.fromisoformat(t["entrega"])
    dif = (d - hoy).days
    texto = "• «" + t["titulo"] + "»" + (" (" + t["materia"] + ")" if t["materia"] != "General" else "")
    texto += " — se entrega " + ("el " if dif > 1 or dif < 0 else "") + tareas.fecha_bonita(t["entrega"], hoy)
    if t["hora"]:
        texto += " a las " + t["hora"]
    if dif > 1:
        texto += ", en " + str(dif) + " días"
    bl = _bloques(t["id"])
    if bl:
        from modulos.proactivo import proactivo
        texto += "\n   Tiempo de estudio agendado: " + ", ".join(
            proactivo._dia_corto(date.fromisoformat(b["dia"])).lower() + " " + b["ini"] for b in bl[:4])
    return texto


def procesar(texto, hoy=None):
    if not es_consulta(texto):
        return None
    hoy = hoy or ahora().date()
    tn = _n(texto)
    todas = list(tareas.pendientes())
    materias, usadas = _materia_pedida(tn)
    rango = _rango(tn, hoy)
    claves = [w for w in tn.split() if len(w) >= 4 and w not in VACIAS and w not in GENERICAS and w not in usadas
              and not w.isdigit()]

    def filtrar(con_fecha=True, con_claves=True, con_materia=True):
        out = []
        for t in todas:
            tt = _n(t["titulo"] + " " + t["materia"])
            if con_materia and materias and t["materia"] not in materias:
                continue
            if con_claves and claves and not all(re.search(r"\b" + re.escape(c[:-1] if c.endswith("s") else c), tt)
                                                 for c in claves):
                continue
            if con_fecha and rango and not (rango[0] <= date.fromisoformat(t["entrega"]) <= rango[1]):
                continue
            out.append(t)
        return out

    lista = filtrar()
    nota = ""
    pedido = " ".join(x for x in [
        ("de " + " / ".join(sorted(materias))) if materias else "",
        ("sobre «" + " ".join(claves) + "»") if claves else "",
        rango[2] if rango else ""] if x)
    if not lista and rango and not (materias or claves):
        return ("No tiene entregas " + rango[2] + ", señor." +
                ("\nLo próximo que tengo:\n" + "\n".join(_linea(t, hoy) for t in todas[:3]) if todas else ""))
    if not lista and (materias or claves or rango):
        flexibles = [{"con_fecha": False}]
        if materias:
            flexibles += [{"con_claves": False}, {"con_claves": False, "con_fecha": False}]
        for flex in flexibles:
            lista = filtrar(**flex)
            if lista:
                nota = "No tengo un deber exactamente " + pedido + ", señor, pero encontré " + \
                       ("este" if len(lista) == 1 else "estos") + ":"
                break
    if not lista:
        if not todas:
            return "No tengo deberes pendientes registrados, señor."
        cabeza = ("No tengo registrado ningún deber " + pedido + ", señor." if pedido else
                  "No encontré ese deber, señor.")
        return cabeza + "\nEstos son los pendientes que sí tengo:\n" + "\n".join(_linea(t, hoy) for t in todas[:8])
    if not nota:
        tn_ = tn
        if re.search(r"registrad|anotad|apuntad|guardad|agendad", tn_):
            nota = "Sí, señor, lo tengo registrado:" if len(lista) == 1 else "Sí, señor, tengo estos:"
        elif re.search(r"\bcuando\b|\bque dia\b|\bque fecha\b|\bhasta cuando\b", tn_) and len(lista) == 1:
            nota = ""
        else:
            nota = ("Este es su deber" if len(lista) == 1 else "Estos son sus deberes") + \
                   ((" " + pedido) if pedido else " pendientes") + ":"
    log.info("Consulta de deberes respondida desde el código (%d)", len(lista))
    return ((nota + "\n") if nota else "📝 ") + "\n".join(_linea(t, hoy) for t in lista[:10]).lstrip("• " if not nota else "")
