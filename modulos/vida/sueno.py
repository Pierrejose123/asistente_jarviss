"""Sueño (Fase 2): datos de la banda (Zepp → Apple Health → atajo del iPhone → panel de la PC) y consejos.

Entrada (POST /api/salud desde el atajo del iPhone, texto con una línea por muestra; acepta | ; o tabulador):
    S|inicio|fin|valor      fase de sueño (valor: En cama, Dormido, Núcleo/Básico, Profundo, REM, Despierto o 0-5)
    P|fecha|valor           pasos del día          R|fecha|valor   pulso en reposo
    V|fecha|valor           VFC (HRV, ms)          O|fecha|valor   oxígeno en sangre (% o 0-1)
    E|fecha|valor           energía activa (kcal)
    D|fecha                 «me voy a dormir» automático (atajo del modo Dormir del iPhone); basta «D» sola = ahora
Fechas en ISO 8601 (lo recomendado en el atajo) o «12 nov 2026, 23:10», «12/11/2026 23:10».

Cada noche se guarda con la fecha del DÍA EN QUE SE DESPERTÓ. Si no hay datos de la banda, vale la hora de
«me voy a dormir». Los consejos se calculan en código (sin IA): son hábitos de sueño generales, no consejo médico.
Tablas sueno_noches, sueno_manual, salud_dia en datos/asistente.db.
"""
import re
import statistics
from contextlib import closing
from datetime import date, datetime, timedelta

from modulos.comun import db
from modulos.comun.base import ZONA, ahora, registro

log = registro("vida")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS sueno_noches (
    fecha     TEXT PRIMARY KEY,          -- día en que se despertó (AAAA-MM-DD)
    dormir    TEXT NOT NULL,             -- se durmió (ISO)
    despertar TEXT NOT NULL,             -- se despertó (ISO)
    total     INTEGER NOT NULL,          -- minutos dormido
    profundo  INTEGER, rem INTEGER, ligero INTEGER, despierto INTEGER,
    fuente    TEXT DEFAULT 'banda',
    actualizado TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sueno_manual (
    noche  TEXT PRIMARY KEY,             -- día en que se fue a dormir (AAAA-MM-DD)
    hora   TEXT NOT NULL                 -- ISO del «me voy a dormir»
);
CREATE TABLE IF NOT EXISTS salud_dia (
    fecha  TEXT PRIMARY KEY,
    pasos  REAL, pulso_reposo REAL, vfc REAL, spo2 REAL, energia REAL,
    actualizado TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sueno_consejos (   -- para no repetir el mismo consejo dos mañanas seguidas
    fecha  TEXT PRIMARY KEY,
    clave  TEXT NOT NULL
);
"""


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def meta_dormir():
    from modulos.vida import habitos_vida
    h, m = habitos_vida.ajustes()["hora_dormir"].split(":")
    return int(h), int(m)


# --- leer fechas y valores del atajo -------------------------------------------------------------------------
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10,
         "nov": 11, "dic": 12, "jan": 1, "apr": 4, "aug": 8, "dec": 12}


def fecha_de(texto):
    """datetime con zona (la del usuario si no trae). None si no se entiende."""
    t = (texto or "").strip().replace(" ", " ").replace("\xa0", " ")
    if not t:
        return None
    try:
        d = datetime.fromisoformat(t.replace("Z", "+00:00"))
        return d.astimezone(ZONA) if d.tzinfo else d.replace(tzinfo=ZONA)
    except ValueError:
        pass
    s = t.lower().replace(".", "").replace(" de ", " ")
    ampm = None
    m_ampm = re.search(r"\s*([ap])\s*m\b", s)
    if m_ampm:
        ampm = m_ampm.group(1)
        s = s[:m_ampm.start()] + s[m_ampm.end():]
    hora = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    hh, mm, ss = (int(hora.group(1)), int(hora.group(2)), int(hora.group(3) or 0)) if hora else (0, 0, 0)
    if ampm == "p" and hh < 12:
        hh += 12
    if ampm == "a" and hh == 12:
        hh = 0
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)
    if m:
        d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"(\d{1,2})\s+([a-záéíóú]{3,})\w*\s+(\d{4})", s) or re.search(r"([a-z]{3,})\w*\s+(\d{1,2}),?\s+(\d{4})", s)
        if not m:
            return None
        if m.group(1).isdigit():
            d, mes, a = int(m.group(1)), MESES.get(m.group(2)[:3]), int(m.group(3))
        else:
            d, mes, a = int(m.group(2)), MESES.get(m.group(1)[:3]), int(m.group(3))
        if not mes:
            return None
    if a < 100:
        a += 2000
    try:
        return datetime(a, mes, d, hh, mm, ss, tzinfo=ZONA)
    except ValueError:
        return None


FASE = [(r"en\s*cama|in\s*bed|^0$", "cama"), (r"despiert|awake|^2$", "despierto"), (r"profund|deep|^4$", "profundo"),
        (r"rem|^5$", "rem"), (r"n[uú]cleo|b[aá]sico|core|ligero|light|^3$", "ligero"),
        (r"dormid|asleep|sin\s*especificar|unspecified|^1$|sueño|sleep", "dormido")]


def fase_de(valor):
    v = (valor or "").strip().lower()
    for patron, nombre in FASE:
        if re.search(patron, v):
            return nombre
    return None


def _numero(t):
    t = (t or "").strip().replace(" ", "")
    m = re.search(r"-?\d+(?:[.,]\d+)?", t)
    if not m:
        return None
    n = m.group(0)
    if "," in n and "." not in n:
        n = n.replace(",", ".")
    else:
        n = n.replace(",", "")
    return float(n)


# --- guardar -------------------------------------------------------------------------------------------------
def noches_de(muestras):
    """muestras: [(inicio, fin, fase)]. Agrupa en noches (huecos < 3 h) y calcula cada una. [dict]"""
    utiles = sorted((i, f, fase) for i, f, fase in muestras if fase and f > i)
    grupos, actual = [], []
    for m in utiles:
        if actual and m[0] - max(x[1] for x in actual) > timedelta(hours=3):
            grupos.append(actual)
            actual = []
        actual.append(m)
    if actual:
        grupos.append(actual)
    noches = []
    for g in grupos:
        dormido = [m for m in g if m[2] in ("dormido", "ligero", "profundo", "rem")]
        if not dormido:
            continue
        # minutos por fase, sin contar dos veces lo que se pisa (p. ej. «Dormido» y «Profundo» a la vez)
        hay_fases = any(m[2] in ("ligero", "profundo", "rem") for m in dormido)
        base = [m for m in dormido if m[2] != "dormido"] if hay_fases else dormido
        minutos = {"profundo": 0, "rem": 0, "ligero": 0, "dormido": 0}
        intervalos = []
        for i, f, fase in sorted(base):
            if intervalos and i < intervalos[-1][1]:
                i = intervalos[-1][1]
            if f <= i:
                continue
            intervalos.append((i, f))
            minutos[fase] += (f - i).total_seconds() / 60
        total = sum(minutos.values())
        if total < 120:                                   # siestas y fragmentos: no son la noche principal
            continue
        despierto = sum((f - i).total_seconds() / 60 for i, f, fase in g if fase == "despierto")
        inicio = min(m[0] for m in dormido)
        fin = max(m[1] for m in dormido)
        noches.append({"fecha": fin.date().isoformat(), "dormir": inicio, "despertar": fin, "total": round(total),
                       "profundo": round(minutos["profundo"]) if hay_fases else None,
                       "rem": round(minutos["rem"]) if hay_fases else None,
                       "ligero": round(minutos["ligero"]) if hay_fases else None,
                       "despierto": round(despierto)})
    return noches


def ingestar(texto):
    """Guarda lo que manda el atajo. Devuelve {'noches': n, 'dias': n, 'ignoradas': n}."""
    muestras, por_dia, ignoradas, acostado = [], {}, 0, None
    campos = {"P": "pasos", "R": "pulso_reposo", "V": "vfc", "O": "spo2", "E": "energia"}
    for crudo in re.split(r"[\r\n]+", texto or ""):
        partes = [p.strip() for p in re.split(r"\s*[|;\t]\s*", crudo.strip()) if p is not None]
        if partes and partes[0].upper() == "D":            # modo Dormir activado en el iPhone
            acostado = (fecha_de(partes[1]) if len(partes) > 1 and partes[1] else None) or ahora()
            continue
        if len(partes) < 3:
            if crudo.strip():
                ignoradas += 1
            continue
        tipo = partes[0].upper()[:1]
        if tipo == "S" and len(partes) >= 4:
            i, f, fase = fecha_de(partes[1]), fecha_de(partes[2]), fase_de(partes[3])
            if i and f and fase:
                muestras.append((i, f, fase))
            else:
                ignoradas += 1
        elif tipo in campos:
            d, v = fecha_de(partes[1]), _numero(partes[2])
            if d is None or v is None:
                ignoradas += 1
                continue
            if tipo == "O" and v <= 1:
                v *= 100
            dia = por_dia.setdefault(d.date().isoformat(), {})
            clave = campos[tipo]
            dia[clave] = dia.get(clave, 0) + v if clave in ("pasos", "energia") else v
        else:
            ignoradas += 1
    noches = noches_de(muestras)
    with closing(_con()) as con, con:
        for n in noches:
            con.execute("INSERT OR REPLACE INTO sueno_noches (fecha, dormir, despertar, total, profundo, rem, ligero, "
                        "despierto, fuente, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'banda', CURRENT_TIMESTAMP)",
                        (n["fecha"], n["dormir"].isoformat(timespec="minutes"), n["despertar"].isoformat(timespec="minutes"),
                         n["total"], n["profundo"], n["rem"], n["ligero"], n["despierto"]))
        for dia, vals in por_dia.items():
            con.execute("INSERT INTO salud_dia (fecha) VALUES (?) ON CONFLICT(fecha) DO NOTHING", (dia,))
            for k, v in vals.items():                # el atajo manda el total del día: se reemplaza, no se suma
                con.execute("UPDATE salud_dia SET " + k + " = ?, actualizado = CURRENT_TIMESTAMP WHERE fecha = ?",
                            (round(v, 1), dia))
    log.info("Salud recibida: %d noches, %d días, %d líneas ignoradas", len(noches), len(por_dia), ignoradas)
    r = {"noches": len(noches), "dias": len(por_dia), "ignoradas": ignoradas}
    if acostado:
        r["dormir"] = me_voy_a_dormir(acostado)
    return r


def me_voy_a_dormir(momento=None):
    momento = momento or ahora()
    noche = (momento - timedelta(hours=6)).date().isoformat()   # 00:30 del martes cuenta como la noche del lunes
    with closing(_con()) as con, con:
        con.execute("INSERT OR REPLACE INTO sueno_manual (noche, hora) VALUES (?, ?)",
                    (noche, momento.isoformat(timespec="minutes")))
    h, m = meta_dormir()
    limite = momento.replace(hour=h, minute=m, second=0, microsecond=0)
    if momento.hour < 6:
        limite -= timedelta(days=1)
    diferencia = round((momento - limite).total_seconds() / 60)
    hora = momento.strftime("%H:%M")
    if diferencia <= 0:
        return "🌙 Anotado: " + hora + ", antes de su meta de las " + "%02d:%02d" % (h, m) + ". Que descanse, señor."
    if diferencia <= 15:
        return "🌙 Anotado: " + hora + ", casi en su meta. Que descanse, señor."
    return ("🌙 Anotado: " + hora + " (" + _duracion(diferencia) + " después de su meta). Mañana intentemos un poco antes. "
            "Que descanse.")


# --- leer ----------------------------------------------------------------------------------------------------
def _duracion(minutos):
    minutos = int(round(minutos))
    h, m = divmod(abs(minutos), 60)
    partes = ([str(h) + " h"] if h else []) + ([str(m) + " min"] if m or not h else [])
    return " ".join(partes)


def _hm(minutos):
    h, m = divmod(int(round(minutos)), 60)
    return str(h) + "h" + str(m).zfill(2)


def noches(dias=14, hasta=None):
    """Últimas noches (la más reciente al final). Incluye las manuales si no hay de la banda."""
    hasta = (hasta or ahora()).date()
    desde = (hasta - timedelta(days=dias - 1)).isoformat()
    with closing(_con()) as con:
        banda = {f["fecha"]: dict(f) for f in con.execute("SELECT * FROM sueno_noches WHERE fecha >= ? AND fecha <= ?",
                                                           (desde, hasta.isoformat()))}
        manuales = con.execute("SELECT * FROM sueno_manual WHERE noche >= ?",
                               ((hasta - timedelta(days=dias)).isoformat(),)).fetchall()
    for f in manuales:
        despierta = (date.fromisoformat(f["noche"]) + timedelta(days=1)).isoformat()
        if despierta not in banda and desde <= despierta <= hasta.isoformat():
            banda[despierta] = {"fecha": despierta, "dormir": f["hora"], "despertar": None, "total": None, "profundo": None,
                                "rem": None, "ligero": None, "despierto": None, "fuente": "manual"}
    return [banda[k] for k in sorted(banda)]


def _min_desde_18(iso):
    """Minutos desde las 18:00 del día en que se acostó (21:30 = 210, 00:30 = 390)."""
    d = datetime.fromisoformat(iso)
    m = d.hour * 60 + d.minute - 18 * 60
    return m + 24 * 60 if m < 0 else m


def _reloj(min18):
    t = (int(round(min18)) + 18 * 60) % (24 * 60)
    return "%02d:%02d" % divmod(t, 60)


def salud(dias=7, hasta=None):
    hasta = (hasta or ahora()).date()
    desde = (hasta - timedelta(days=dias - 1)).isoformat()
    with closing(_con()) as con:
        return [dict(f) for f in con.execute("SELECT * FROM salud_dia WHERE fecha >= ? ORDER BY fecha", (desde,))]


def analisis(dias=14, hasta=None):
    """Números de las últimas noches + consejos ordenados por importancia."""
    lista = noches(dias, hasta)
    h, m = meta_dormir()
    meta18 = (h * 60 + m) - 18 * 60
    con_hora = [n for n in lista if n["dormir"]]
    con_total = [n for n in lista if n["total"]]
    if not con_hora:
        return {"noches": 0, "consejos": []}
    horas = [_min_desde_18(n["dormir"]) for n in con_hora]
    r = {"noches": len(con_hora), "meta": "%02d:%02d" % (h, m),
         "hora_media": _reloj(statistics.mean(horas)),
         "variacion": round(statistics.pstdev(horas)) if len(horas) > 1 else 0,
         "en_meta": sum(1 for x in horas if x <= meta18 + 5), "tarde_media": round(statistics.mean(horas) - meta18)}
    if con_total:
        r["total_medio"] = round(statistics.mean(n["total"] for n in con_total))
        r["menos_de_7h"] = sum(1 for n in con_total if n["total"] < 420)
        con_fases = [n for n in con_total if n["profundo"] is not None]
        if con_fases:
            r["profundo_pct"] = round(100 * sum(n["profundo"] for n in con_fases) / sum(n["total"] for n in con_fases))
            r["rem_pct"] = round(100 * sum(n["rem"] or 0 for n in con_fases) / sum(n["total"] for n in con_fases))
        despiertos = [n["despierto"] for n in con_total if n["despierto"] is not None]
        if despiertos:
            r["despierto_medio"] = round(statistics.mean(despiertos))
    finde = [_min_desde_18(n["dormir"]) for n in con_hora
             if (date.fromisoformat(n["fecha"]) - timedelta(days=1)).weekday() in (4, 5)]
    semana = [_min_desde_18(n["dormir"]) for n in con_hora
              if (date.fromisoformat(n["fecha"]) - timedelta(days=1)).weekday() not in (4, 5)]
    if len(finde) >= 1 and len(semana) >= 2:
        r["finde_diferencia"] = round(statistics.mean(finde) - statistics.mean(semana))
    r["relaciones"] = _relaciones(con_total)
    r["agua_noche"] = _agua_de_noche(con_total)
    r["consejos"] = consejos(r)
    return r


def _relaciones(con_total):
    """Compara el sueño de las noches DESPUÉS de hacer cada hábito frente a las que no (necesita ≥3 de cada una)."""
    from modulos.vida import habitos_vida
    salida = []
    for h in habitos_vida.habitos():
        if h.get("tipo") == "contador":
            continue
        si, no = [], []
        for n in con_total:
            dia_antes = datetime.fromisoformat(n["fecha"] + "T12:00").replace(tzinfo=ZONA) - timedelta(days=1)
            v = habitos_vida.valor(h["id"], dia_antes)
            (si if v and v > 0 else no).append(n["total"])
        if len(si) >= 3 and len(no) >= 3:
            dif = round(statistics.mean(si) - statistics.mean(no))
            if abs(dif) >= 20:
                salida.append({"habito": h["nombre"], "id": h["id"], "diferencia": dif, "veces": len(si)})
    return sorted(salida, key=lambda x: -abs(x["diferencia"]))


def _agua_de_noche(con_total):
    """¿Las noches en que tomó agua después de las 20:00 se despertó más? {'con': min, 'sin': min} o None."""
    from modulos.vida import habitos_vida
    con_agua, sin_agua = [], []
    with closing(habitos_vida._con()) as con:
        for n in con_total:
            if n["despierto"] is None:
                continue
            dia_antes = (date.fromisoformat(n["fecha"]) - timedelta(days=1)).isoformat()
            tarde = con.execute("SELECT SUM(delta) s FROM vida_marcas WHERE habito = 'agua' AND fecha = ? "
                                "AND substr(momento, 12, 5) >= '20:00'", (dia_antes,)).fetchone()["s"] or 0
            (con_agua if tarde >= 2 else sin_agua).append(n["despierto"])
    if len(con_agua) >= 2 and len(sin_agua) >= 2:
        return {"con": round(statistics.mean(con_agua)), "sin": round(statistics.mean(sin_agua))}
    return None


def consejos(r):
    """[(clave, texto)] del más importante al menos. Hábitos de sueño generales; no es consejo médico."""
    c = []
    meta = r["meta"]
    if r["noches"] >= 3 and r["en_meta"] < r["noches"] * 0.5:
        if r["tarde_media"] > 45:
            c.append(("gradual", "Se está durmiendo en promedio a las " + r["hora_media"] + ", " + _duracion(r["tarde_media"])
                      + " después de su meta. En vez de saltar de golpe a las " + meta + ", adelante la hora 15 minutos "
                      "cada 3 días: el cuerpo se adapta mejor así."))
        else:
            c.append(("rutina_noche", "Le falta poco para su meta de las " + meta + ". Arme una rutina fija de 30 min antes "
                      "(luz baja, sin pantallas, su lectura): así le dará sueño a la hora."))
    if r.get("variacion", 0) > 45 and r["noches"] >= 4:
        c.append(("constancia", "Su hora de dormir cambia mucho (±" + _duracion(r["variacion"]) + "). Lo que más ayuda "
                  "al sueño es la constancia: acostarse y levantarse a la misma hora todos los días, también el fin de semana."))
    if r.get("finde_diferencia", 0) > 60:
        c.append(("finde", "Los fines de semana se acuesta " + _duracion(r["finde_diferencia"]) + " más tarde. Eso desordena "
                  "su reloj y el domingo cuesta dormirse: intente no pasar de una hora de diferencia."))
    if r.get("total_medio") and r["total_medio"] < 420:
        c.append(("poco", "Está durmiendo " + _hm(r["total_medio"]) + " en promedio. Lo recomendado para adultos es entre "
                  "7 y 9 horas: acostarse a las " + meta + " le daría ese margen."))
    if r.get("profundo_pct") is not None and r["profundo_pct"] < 13:
        c.append(("profundo", "Su sueño profundo es bajo (" + str(r["profundo_pct"]) + " %). Suele ayudar: nada de café "
                  "después de las 14:00, cenar al menos 2 horas antes de dormir y un cuarto fresco, oscuro y silencioso."))
    agua = r.get("agua_noche")
    if agua and agua["con"] - agua["sin"] >= 10:
        c.append(("agua_noche", "Las noches que toma agua después de las 20:00 pasa " + str(agua["con"] - agua["sin"])
                  + " min más despierto. Tome la mayor parte del agua antes de las 19:00."))
    elif r.get("despierto_medio", 0) > 40:
        c.append(("despierto", "Pasa unos " + str(r["despierto_medio"]) + " min despierto por noche. Si se despierta y no "
                  "se duerme en ~20 min, levántese un rato con luz baja en vez de mirar el celular en la cama."))
    for rel in r.get("relaciones", []):
        if rel["diferencia"] > 0:
            c.append(("rel_" + rel["id"], "Las noches después de «" + rel["habito"].lower() + "» durmió " + _duracion(rel["diferencia"])
                      + " más en promedio (" + str(rel["veces"]) + " veces). Le está funcionando: manténgalo."))
        else:
            c.append(("rel_" + rel["id"], "Las noches después de «" + rel["habito"].lower() + "» durmió " + _duracion(-rel["diferencia"])
                      + " menos. Si es algo intenso, pruebe hacerlo más temprano."))
    if r.get("total_medio") and r["total_medio"] < 360 and r["noches"] >= 10:
        c.append(("medico", "Lleva dos semanas durmiendo menos de 6 horas. Si le cuesta dormirse o se siente cansado de día "
                  "aunque duerma, vale la pena comentarlo con un médico."))
    if not c and r["noches"] >= 3:
        c.append(("bien", "Va muy bien: buena hora y buena duración. Mantenga la misma rutina."))
    return c


def linea_manana(hoy=None):
    """Una línea para el resumen de la mañana (None si no hay datos de anoche)."""
    hoy = hoy or ahora()
    lista = noches(2, hoy)
    anoche = next((n for n in lista if n["fecha"] == hoy.date().isoformat()), None)
    if not anoche:
        return None
    h, m = meta_dormir()
    d18 = _min_desde_18(anoche["dormir"])
    tarde = d18 - ((h * 60 + m) - 18 * 60)
    texto = "😴 Anoche: se durmió " + _reloj(d18)
    if anoche["total"]:
        texto += " y durmió " + _hm(anoche["total"])
        if anoche["profundo"] is not None and anoche["total"]:
            texto += " (profundo " + str(round(100 * anoche["profundo"] / anoche["total"])) + " %)"
    texto += ". " + ("✅ En su meta." if tarde <= 5 else "Meta " + "%02d:%02d" % (h, m) + ": +" + _duracion(tarde) + ".")
    r = analisis(14, hoy)
    elegido = None
    with closing(_con()) as con, con:
        ayer = con.execute("SELECT clave FROM sueno_consejos WHERE fecha = ?",
                           ((hoy.date() - timedelta(days=1)).isoformat(),)).fetchone()
        for clave, consejo in r.get("consejos", []):
            if not ayer or clave != ayer["clave"] or len(r["consejos"]) == 1:
                elegido = (clave, consejo)
                break
        if elegido:
            con.execute("INSERT OR REPLACE INTO sueno_consejos (fecha, clave) VALUES (?, ?)",
                        (hoy.date().isoformat(), elegido[0]))
    if elegido and r["noches"] >= 3:
        texto += "\n💡 " + elegido[1]
    return texto


def informe_semanal(hoy=None):
    """Texto del domingo. None si casi no hay datos."""
    r = analisis(7, hoy)
    if r["noches"] < 3:
        return None
    lineas = ["😴 Su sueño esta semana (" + str(r["noches"]) + " noches)", "",
              "• Hora media de dormir: " + r["hora_media"] + " (meta " + r["meta"] + "): en meta " + str(r["en_meta"])
              + " de " + str(r["noches"]) + " noches."]
    if r.get("total_medio"):
        lineas.append("• Duración media: " + _hm(r["total_medio"]) + (" · menos de 7 h: " + str(r["menos_de_7h"]) + " noches"
                                                                   if r.get("menos_de_7h") else ""))
    if r.get("profundo_pct") is not None:
        lineas.append("• Fases: profundo " + str(r["profundo_pct"]) + " %, REM " + str(r.get("rem_pct", 0)) + " %.")
    if r.get("variacion"):
        lineas.append("• Constancia: ±" + _duracion(r["variacion"]) + " de una noche a otra.")
    anterior = analisis(7, (hoy or ahora()) - timedelta(days=7))
    if anterior["noches"] >= 3 and anterior.get("total_medio") and r.get("total_medio"):
        dif = r["total_medio"] - anterior["total_medio"]
        lineas.append("• Frente a la semana pasada: " + ("+" if dif >= 0 else "−") + _duracion(abs(dif)) + " de sueño por noche.")
    if r["consejos"]:
        lineas += ["", "Para la próxima semana:"] + ["💡 " + t for _, t in r["consejos"][:3]]
    return "\n".join(lineas)


def texto_sueno(hoy=None):
    """Respuesta a «cómo dormí» / /sueno."""
    lista = noches(7, hoy)
    if not lista:
        return ("Todavía no tengo datos de su sueño. Cuando el atajo del iPhone mande los datos de la banda (o me diga "
                "«me voy a dormir» al acostarse), aquí verá sus noches y consejos.")
    lineas = ["😴 Sus últimas noches"]
    for n in lista[-7:]:
        d = date.fromisoformat(n["fecha"])
        linea = "• " + ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"][d.weekday()] + " " + d.strftime("%d/%m") + ": " \
                + _reloj(_min_desde_18(n["dormir"]))
        if n["despertar"]:
            linea += " → " + n["despertar"][11:16]
        if n["total"]:
            linea += "  " + _hm(n["total"])
        if n["profundo"] is not None and n["total"]:
            linea += " (prof. " + str(round(100 * n["profundo"] / n["total"])) + " %)"
        if n["fuente"] == "manual":
            linea += " (hora que me dijo)"
        lineas.append(linea)
    r = analisis(14, hoy)
    if r.get("consejos") and r["noches"] >= 3:
        lineas += ["", "💡 " + r["consejos"][0][1]]
    return "\n".join(lineas)


CONSULTA = re.compile(r"^\W*(?:c[oó]mo\s+(?:dorm[ií]|he\s+dormido|estoy\s+durmiendo|va\s+mi\s+sueño)|mi\s+sueño|"
                      r"cu[aá]nto\s+dorm[ií]|a\s+qu[eé]\s+hora\s+me\s+dorm[ií]|consejos?\s+(?:de|para)\s+(?:dormir|el\s+sueño))"
                      r"(?:\s+(?:anoche|esta\s+semana|hoy))?\W*$", re.I)


def procesar(texto):
    if CONSULTA.match(texto or ""):
        return texto_sueno()
    return None
