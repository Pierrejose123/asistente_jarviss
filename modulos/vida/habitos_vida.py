"""Hábitos de la vida diaria (Fase 2 del plan «vida y empresa»): lectura, agua, inglés, fisio, gimnasio…

- Configuración en config/vida.json (se crea sola la primera vez con los valores de abajo).
  Cada hábito: id, nombre, emoji, tipo ("si_no" o "contador"), dias ("todos", "libre" o lista de días) y activo.
  "libre" = no se espera ningún día (cuenta cuando lo hace: fisio, práctica extra).
- Se marca por frase (texto, nota de voz, «hey Jarvis»), por botón en Telegram o tocando el panel:
    «agua», «tomé 2 vasos de agua», «leí», «ya leí 20 minutos», «hice la llamada de inglés»,
    «practiqué inglés con la IA», «fui a fisio», «fui al gimnasio», «hoy no leí», «quita un vaso de agua»,
    «mis hábitos».
- El sueño es aparte (modulos/vida/sueno.py): «me voy a dormir» lo anota allí.
Tabla vida_habitos en datos/asistente.db.
"""
import json
import re
import unicodedata
from contextlib import closing
from datetime import timedelta

from modulos.comun import db
from modulos.comun.base import CONFIG, DIAS, DIAS_BONITO, ahora, registro

log = registro("vida")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS vida_habitos (
    fecha   TEXT NOT NULL,                -- AAAA-MM-DD
    habito  TEXT NOT NULL,
    valor   REAL NOT NULL,                -- si_no: 1 hecho, 0 hoy no | contador: cantidad
    momento TEXT NOT NULL,                -- última vez que se tocó (ISO)
    PRIMARY KEY (fecha, habito)
);
CREATE TABLE IF NOT EXISTS vida_marcas (    -- cada toque, con su hora (sirve p. ej. para ver agua tomada de noche)
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha   TEXT NOT NULL,
    habito  TEXT NOT NULL,
    delta   REAL NOT NULL,
    momento TEXT NOT NULL
);
"""

PREDETERMINADO = {
    "hora_dormir": "22:00",          # meta: acostarse antes de esta hora
    "aviso_noche": "21:30",          # un solo mensaje: hábitos pendientes del día + «hora de prepararse»
    "puerto_panel": 8765,
    "habitos": [
        {"id": "lectura", "nombre": "Lectura", "emoji": "📖", "tipo": "si_no", "dias": "todos", "activo": True},
        {"id": "agua", "nombre": "Agua", "emoji": "💧", "tipo": "contador", "unidad": "vasos", "dias": "todos",
         "activo": True},
        {"id": "ingles", "nombre": "Llamada de inglés", "emoji": "🇬🇧", "tipo": "si_no",
         "dias": ["lunes", "martes", "jueves"], "activo": True},
        {"id": "practica_ingles", "nombre": "Práctica de inglés", "emoji": "🗣️", "tipo": "si_no", "dias": "libre",
         "activo": True},
        {"id": "fisio", "nombre": "Fisioterapia", "emoji": "🦵", "tipo": "si_no", "dias": "libre", "activo": False},
        {"id": "gimnasio", "nombre": "Gimnasio", "emoji": "🏋️", "tipo": "si_no", "dias": "todos", "activo": False},
    ],
}
ARCHIVO = CONFIG / "vida.json"


def _sin_tildes(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def ajustes():
    try:
        datos = json.loads(ARCHIVO.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        datos = json.loads(json.dumps(PREDETERMINADO))
        try:
            ARCHIVO.parent.mkdir(exist_ok=True)
            ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            log.info("No pude crear config/vida.json: %s", exc)
    except Exception as exc:
        log.warning("config/vida.json no se pudo leer (%s): uso los valores por defecto", exc)
        datos = json.loads(json.dumps(PREDETERMINADO))
    for k, v in PREDETERMINADO.items():
        datos.setdefault(k, v)
    return datos


def habitos(solo_activos=True):
    return [h for h in ajustes()["habitos"] if h.get("activo", True) or not solo_activos]


def habito(hid):
    return next((h for h in ajustes()["habitos"] if h["id"] == hid), None)


def toca(h, fecha):
    """¿Se espera este hábito ese día?"""
    dias = h.get("dias", "todos")
    if dias == "libre" or not h.get("activo", True):
        return False
    return dias == "todos" or DIAS[fecha.weekday()] in [_sin_tildes(d) for d in dias]


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def valor(hid, fecha=None):
    dia = (fecha or ahora()).date().isoformat()
    with closing(_con()) as con:
        f = con.execute("SELECT valor FROM vida_habitos WHERE fecha = ? AND habito = ?", (dia, hid)).fetchone()
    return None if f is None else f["valor"]


def marcar(hid, nuevo=None, delta=None, fecha=None):
    """Marca un hábito. si_no: nuevo=1/0. contador: delta (+1, -1…). nuevo=None y delta=None borra el registro."""
    momento = fecha or ahora()
    dia = momento.date().isoformat()
    with closing(_con()) as con, con:
        actual = con.execute("SELECT valor FROM vida_habitos WHERE fecha = ? AND habito = ?", (dia, hid)).fetchone()
        if nuevo is None and delta is None:
            con.execute("DELETE FROM vida_habitos WHERE fecha = ? AND habito = ?", (dia, hid))
            return None
        if delta is not None:
            nuevo = max(0.0, (actual["valor"] if actual else 0.0) + delta)
            con.execute("INSERT INTO vida_marcas (fecha, habito, delta, momento) VALUES (?, ?, ?, ?)",
                        (dia, hid, delta, momento.isoformat(timespec="seconds")))
        con.execute("INSERT OR REPLACE INTO vida_habitos (fecha, habito, valor, momento) VALUES (?, ?, ?, ?)",
                    (dia, hid, float(nuevo), momento.isoformat(timespec="seconds")))
    return nuevo


def del_dia(fecha=None):
    """[{id, nombre, emoji, tipo, toca, valor}] para ese día (incluye los 'libre' solo si se hicieron)."""
    fecha = fecha or ahora()
    dia = fecha.date().isoformat()
    with closing(_con()) as con:
        vals = {f["habito"]: f["valor"] for f in con.execute("SELECT habito, valor FROM vida_habitos WHERE fecha = ?",
                                                             (dia,))}
    salida = []
    for h in habitos():
        t = toca(h, fecha)
        v = vals.get(h["id"])
        if t or v or h.get("tipo") == "contador" or h.get("dias") == "libre":
            salida.append({"id": h["id"], "nombre": h["nombre"], "emoji": h.get("emoji", "•"),
                           "tipo": h.get("tipo", "si_no"), "toca": t, "valor": v, "libre": h.get("dias") == "libre",
                           "unidad": h.get("unidad", "")})
    return salida


def pendientes(fecha=None):
    return [h for h in del_dia(fecha) if h["toca"] and h["tipo"] == "si_no" and h["valor"] is None]


def semana(fin=None, dias=7):
    """{'dias': [AAAA-MM-DD…], 'habitos': [{id, nombre, emoji, tipo, celdas: [valor|None|'·']}]}"""
    fin = fin or ahora()
    fechas = [fin - timedelta(days=i) for i in range(dias - 1, -1, -1)]
    desde = fechas[0].date().isoformat()
    with closing(_con()) as con:
        filas = con.execute("SELECT fecha, habito, valor FROM vida_habitos WHERE fecha >= ?", (desde,)).fetchall()
    vals = {(f["fecha"], f["habito"]): f["valor"] for f in filas}
    salida = []
    for h in habitos():
        celdas = []
        for f in fechas:
            v = vals.get((f.date().isoformat(), h["id"]))
            celdas.append(v if v is not None else (None if toca(h, f) else "·"))
        salida.append({"id": h["id"], "nombre": h["nombre"], "emoji": h.get("emoji", "•"),
                       "tipo": h.get("tipo", "si_no"), "celdas": celdas})
    return {"dias": [f.date().isoformat() for f in fechas], "habitos": salida}


def racha(hid, fecha=None):
    """Días seguidos (hacia atrás) cumpliendo un hábito que toca; los días que no toca no cortan la racha."""
    h = habito(hid)
    if not h:
        return 0
    fecha = fecha or ahora()
    n = 0
    for i in range(0, 120):
        d = fecha - timedelta(days=i)
        v = valor(hid, d)
        if h.get("dias") == "libre":
            break
        if not toca(h, d):
            continue
        if v and v > 0:
            n += 1
        elif i == 0 and v is None:
            continue                      # hoy todavía no lo marca: no corta la racha
        else:
            break
    return n


def texto_semana(fin=None):
    s = semana(fin)
    fechas = [s["dias"][0], s["dias"][-1]]
    lineas = ["📊 Sus hábitos (" + fechas[0][8:] + "/" + fechas[0][5:7] + " – " + fechas[1][8:] + "/" + fechas[1][5:7] + ")"]
    for h in s["habitos"]:
        if h["tipo"] == "contador":
            vals = [c for c in h["celdas"] if isinstance(c, (int, float))]
            lineas.append(h["emoji"] + " " + h["nombre"] + ": " + (str(round(sum(vals) / 7, 1)) + " al día en promedio"
                                                                 if vals else "sin registros"))
            continue
        marcas = "".join("✅" if c == 1 else "➖" if c == 0 else "❔" if c is None else "·" for c in h["celdas"])
        if set(marcas) == {"·"}:
            continue
        hechos = sum(1 for c in h["celdas"] if c == 1)
        tocaban = sum(1 for c in h["celdas"] if c != "·")
        lineas.append(h["emoji"] + " " + h["nombre"] + "  " + marcas + ("  " + str(hechos) + "/" + str(tocaban)
                                                                       if tocaban else "  " + str(hechos) + " veces"))
    lineas.append("\n✅ hecho  ➖ no  ❔ sin marcar  · no tocaba")
    return "\n".join(lineas)


# --- frases --------------------------------------------------------------------------------------------------
NUM = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "medio": 0.5}
_R = r"^\W*(?:jarvis\W+|oye\W+|ya\W+|listo\W+)*"
AGUA = re.compile(_R + r"(?:agua|💧+|\+\s*(\d+)\s*(?:de\s+)?agua|(?:\+\s*)?(\d+|un|una|dos|tres|cuatro|cinco)\s+vasos?\s+de\s+agua|"
                  r"(?:me\s+)?(?:tom[eé]|beb[ií])\s+(?:(\d+|un|una|dos|tres|cuatro|cinco|medio)\s+)?"
                  r"(vasos?|botellas?|litros?)\s+de\s+agua|(?:me\s+)?(?:tom[eé]|beb[ií])\s+agua)\W*$", re.I)
QUITA_AGUA = re.compile(_R + r"(?:quita|resta|borra)(?:me)?\s+(?:un|1)\s+vaso\s+de\s+agua\W*$|^\W*(?:-\s*1\s*agua|"
                        r"me\s+equivoqu[eé]\s+con\s+el\s+agua)\W*$", re.I)
_TIEMPO = r"(?:\s+(?:hoy|un\s+rato|un\s+poco|mi\s+libro|el\s+libro|antes\s+de\s+dormir|\d+\s*(?:min(?:utos)?|p[aá]ginas|" \
          r"cap[ií]tulos?|horas?|h)))*"
# (patrón, hábito, valor)
FRASES = [
    (re.compile(_R + r"(?:le[ií]|termin[eé]\s+de\s+leer|hice\s+(?:mi|la)\s+lectura|lectura\s+(?:hecha|lista|de\s+hoy\s+lista))"
                + _TIEMPO + r"\W*$", re.I), "lectura", 1),
    (re.compile(_R + r"(?:hoy\s+)?no\s+(?:le[ií]|hice\s+(?:mi|la)\s+lectura)(?:\s+hoy)?\W*$", re.I), "lectura", 0),
    (re.compile(_R + r"(?:hice|tuve|termin[eé])\s+(?:la\s+|mi\s+)?(?:llamada|clase)(?:\s+de\s+ingl[eé]s)?\W*$|"
                r"^\W*(?:llamada|clase)\s+de\s+ingl[eé]s\s+(?:hecha|lista)\W*$", re.I), "ingles", 1),
    (re.compile(_R + r"(?:hoy\s+)?no\s+(?:hice|tuve)\s+(?:la\s+)?(?:llamada|clase)(?:\s+de\s+ingl[eé]s)?(?:\s+hoy)?\W*$", re.I),
     "ingles", 0),
    (re.compile(_R + r"(?:practiqu[eé]|habl[eé]|estudi[eé])\s+(?:en\s+)?ingl[eé]s(?:\s+con\s+(?:la\s+)?(?:ia|inteligencia\s+"
                r"artificial|chatgpt|jarvis|una\s+ia|claude))?" + _TIEMPO + r"\W*$", re.I), "practica_ingles", 1),
    (re.compile(_R + r"(?:fui\s+a\s+(?:la\s+)?fisio(?:terapia)?|termin[eé]\s+(?:la\s+)?fisio(?:terapia)?|"
                r"hice\s+(?:los\s+|mis\s+)?ejercicios\s+de\s+(?:la\s+)?(?:fisio(?:terapia)?|rodilla)|fisio\s+(?:hecha|lista))"
                r"(?:\s+hoy)?\W*$", re.I), "fisio", 1),
    (re.compile(_R + r"(?:fui\s+al\s+(?:gym|gimnasio)|entren[eé]|termin[eé]\s+(?:de\s+)?entrenar|gym\s+(?:hecho|listo))"
                r"(?:\s+hoy)?\W*$", re.I), "gimnasio", 1),
    (re.compile(_R + r"(?:hoy\s+)?no\s+(?:fui\s+al\s+(?:gym|gimnasio)|entren[eé])(?:\s+hoy)?\W*$", re.I), "gimnasio", 0),
]
MARCA_EMOJI = re.compile(r"^\W*(✅|✔️|❌|➖)\s*(.+?)\W*$")
VER = re.compile(r"^\W*(?:mis\s+h[aá]bitos|c[oó]mo\s+voy\s+con\s+(?:mis\s+)?(?:los\s+)?h[aá]bitos|h[aá]bitos(?:\s+de\s+la\s+semana)?|"
                 r"mi\s+racha)\W*$", re.I)
DORMIR = re.compile(r"^\W*(?:jarvis\W+|oye\W+|bueno\W+|ya\W+)*(?:me\s+voy\s+a\s+dormir|me\s+voy\s+a\s+acostar|me\s+acuesto|"
                    r"a\s+dormir|ya\s+me\s+duermo|me\s+voy\s+a\s+la\s+cama|buenas\s+noches(?:\s+jarvis)?)\W*$", re.I)


def _cantidad(m):
    for g in m.groups():
        if not g:
            continue
        g2 = _sin_tildes(g)
        if g2.isdigit():
            return float(g2)
        if g2 in NUM:
            return float(NUM[g2])
    return 1.0


def _por_nombre(texto):
    s = _sin_tildes(texto)
    for h in habitos(False):
        if s in (_sin_tildes(h["id"]), _sin_tildes(h["nombre"])) or _sin_tildes(h["nombre"]).startswith(s) \
                or s.replace("gym", "gimnasio") == _sin_tildes(h["id"]):
            return h
    sinon = {"ingles": "ingles", "llamada": "ingles", "fisio": "fisio", "fisioterapia": "fisio", "gym": "gimnasio",
             "leer": "lectura", "libro": "lectura"}
    return habito(sinon.get(s, "")) if s in sinon else None


def _confirmar(h, v, fecha=None):
    if h.get("tipo") == "contador":
        u = h.get("unidad", "")
        return h.get("emoji", "") + " " + ("%g" % v) + " " + u + " de " + h["nombre"].lower() + " hoy."
    if v == 0:
        return "➖ Anotado: hoy sin " + h["nombre"].lower() + ". Mañana será."
    r = racha(h["id"], fecha)
    return (h.get("emoji", "✅") + " " + h["nombre"] + ": hecho." + (" Racha de " + str(r) + " días 🔥" if r >= 2 else ""))


def procesar(texto, canal="telegram"):
    """Frases de hábitos y «me voy a dormir». Devuelve la respuesta o None."""
    t = (texto or "").strip()
    if not t or len(t) > 120:
        return None
    if DORMIR.match(t):
        from modulos.vida import sueno
        return sueno.me_voy_a_dormir()
    if VER.match(t):
        return texto_semana()
    if QUITA_AGUA.match(t) and habito("agua"):
        v = marcar("agua", delta=-1)
        return "💧 Listo, quité un vaso. Lleva " + ("%g" % v) + " hoy."
    m = AGUA.match(t)
    if m and habito("agua") and habito("agua").get("activo", True):
        n = _cantidad(m)
        unidad = _sin_tildes(next((g for g in m.groups() if g and _sin_tildes(g).rstrip("s") in ("vaso", "botella", "litro")),
                                  "vaso"))
        n *= {"botella": 2, "botellas": 2, "litro": 4, "litros": 4}.get(unidad, 1)
        v = marcar("agua", delta=n)
        return _confirmar(habito("agua"), v)
    for patron, hid, val in FRASES:
        if patron.match(t):
            h = habito(hid)
            if not h:
                return None
            marcar(hid, nuevo=val)
            return _confirmar(h, val)
    m = MARCA_EMOJI.match(t)
    if m:
        h = _por_nombre(m.group(2))
        if h:
            if h.get("tipo") == "contador":
                return _confirmar(h, marcar(h["id"], delta=1))
            val = 1 if m.group(1) in ("✅", "✔️") else 0
            marcar(h["id"], nuevo=val)
            return _confirmar(h, val)
    return None


def texto_pendientes(fecha=None):
    fecha = fecha or ahora()
    p = pendientes(fecha)
    agua = valor("agua", fecha) if habito("agua") else None
    lineas = []
    if p:
        lineas.append("Pendientes de hoy: " + ", ".join(h["emoji"] + " " + h["nombre"].lower() for h in p) + ".")
    if habito("agua") and habito("agua").get("activo", True):
        lineas.append("💧 Agua: " + ("%g" % (agua or 0)) + " vasos.")
    return "\n".join(lineas)


def dia_bonito(fecha):
    return DIAS_BONITO[fecha.weekday()] + " " + fecha.strftime("%d/%m")
