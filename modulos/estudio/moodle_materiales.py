"""Materiales de Moodle -> biblioteca personal (SOLO LECTURA, con la clave de servicio MOODLE_TOKEN).

Cada 6 horas (y con /materiales) revisa los cursos del semestre y descarga lo que suben los profesores:
PDF, Word (.docx), PowerPoint (.pptx), .txt y .md, y las "páginas" de Moodle (se guardan como .md).
Los guarda en  <informacion_ia>\\Moodle\\<Materia>\\  -> la biblioteca los lee sola
(la materia queda como tema) y el usuario puede preguntar «¿qué dijo el profesor sobre …?».

Reglas:
- Solo llama core_course_get_contents (lista PERMITIDAS de moodle_avisos) y baja archivos de ESTE Moodle.
  La clave nunca se manda a otro sitio.
- No descarga dos veces lo mismo; si el profesor cambia el archivo, baja la versión nueva (mismo nombre).
- Si el usuario borra un archivo descargado, no se vuelve a bajar.
- Se salta videos, formatos viejos (.doc, .ppt) y archivos de más de 60 MB (config/moodle_materiales.json).
- En modo juego/diseño espera a la siguiente vuelta.
Prueba en la PC:  python modulos\\estudio\\moodle_materiales.py --cursos | --revisar | --estado
"""
import json
import re
import sys
import time
from contextlib import closing
from html import escape, unescape
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modulos.comun import db  # noqa: E402
from modulos.comun.base import CONFIG, INFO_IA, ahora, registro  # noqa: E402

log = registro("moodle_materiales")
ARCHIVO_CONF = CONFIG / "moodle_materiales.json"
PREDETERMINADO = {
    "carpeta": str(INFO_IA / "Moodle"),
    "cada_horas": 6,
    "max_mb": 60,
    "extensiones": [".pdf", ".docx", ".pptx", ".txt", ".md"],
    "paginas": True,
    "cursos_extra": [],
    "cursos_excluir": [],
}
ESQUEMA = """
CREATE TABLE IF NOT EXISTS moodle_archivos (
    clave       TEXT PRIMARY KEY,        -- curso|modulo|ruta|nombre en Moodle
    curso       TEXT, materia TEXT, modulo TEXT, nombre TEXT,
    ruta        TEXT,                    -- dónde quedó en la PC
    modificado  INTEGER DEFAULT 0,       -- timemodified de Moodle
    tamano      INTEGER DEFAULT 0,
    estado      TEXT DEFAULT 'bajado',   -- bajado | omitido | borrado (lo borró el usuario) | error
    motivo      TEXT DEFAULT '',
    inicial     INTEGER DEFAULT 0,       -- vino en la primera descarga (la biblioteca no avisa uno por uno)
    visto       TEXT DEFAULT CURRENT_TIMESTAMP,
    actualizado TEXT
);
"""
MAGIA = {".pdf": b"%PDF", ".docx": b"PK", ".pptx": b"PK", ".xlsx": b"PK"}


class SinPermisoDescarga(Exception):
    pass


class SoloEnlaces(Exception):
    """Página de Moodle que solo trae enlaces (p. ej. la grabación de Teams): no aporta a la biblioteca."""


def solo_enlaces(texto):
    """True si, quitando título, enlaces y «URL 1:», quedan menos de 25 palabras."""
    lineas = [l for l in (texto or "").splitlines() if not l.lstrip().startswith("#")]
    resto = re.sub(r"https?://\S+|\bURL\s*\d*\s*:", " ", " ".join(lineas), flags=re.I)
    return len(re.findall(r"\w{2,}", resto)) < 25


def ajustes():
    datos = dict(PREDETERMINADO)
    if not ARCHIVO_CONF.exists():
        try:
            ARCHIVO_CONF.write_text(json.dumps(PREDETERMINADO, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    else:
        try:
            datos.update(json.loads(ARCHIVO_CONF.read_text(encoding="utf-8-sig")))
        except Exception as exc:
            log.warning("config/moodle_materiales.json no se pudo leer: %s", exc)
    return datos


def _con():
    con = db.conectar()
    con.executescript(ESQUEMA)
    return con


def _avisos():
    from modulos.estudio import moodle_avisos
    return moodle_avisos


# ------------------------------------------------------------------ nombres de archivo seguros ---
def limpio(nombre, largo=110):
    """Nombre válido en Windows (sin < > : " / \\ | ? * ni puntos o espacios al final)."""
    nombre = unescape(str(nombre or ""))
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", nombre)
    nombre = " ".join(nombre.split()).strip(" .")
    nombre = re.sub(r"\s+\.(\w{1,5})$", r".\1", nombre)          # «Lectura 1 .pdf» -> «Lectura 1.pdf»
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)", nombre or "x"):
        nombre = "_" + nombre
    if len(nombre) > largo:
        base, punto, ext = nombre.rpartition(".")
        if punto and len(ext) <= 5:
            nombre = base[:largo - len(ext) - 1].rstrip(" .") + "." + ext
        else:
            nombre = nombre[:largo].rstrip(" .")
    return nombre or "archivo"


def _ruta_libre(carpeta, nombre, clave, con):
    """Ruta para 'nombre'; si ya existe y es de otro archivo de Moodle (o del usuario), le agrega (2), (3)…"""
    base = Path(nombre).stem
    ext = Path(nombre).suffix
    for i in range(1, 100):
        ruta = carpeta / (nombre if i == 1 else base + " (" + str(i) + ")" + ext)
        duenio = con.execute("SELECT clave FROM moodle_archivos WHERE ruta = ?", (str(ruta),)).fetchone()
        if duenio and duenio["clave"] == clave:
            return ruta
        if not duenio and not ruta.exists():
            return ruta
    return carpeta / (base + " " + str(int(time.time())) + ext)


# ------------------------------------------------------------------ cursos del semestre ---
def cursos_actuales():
    """[(curso, materia)] — los cursos del horario de clases (o, si ninguno coincide, los vigentes por fecha)."""
    from modulos.estudio import moodle
    av = _avisos()
    a = ajustes()
    excluir = {x.upper() for x in a["cursos_excluir"]}
    extra = {x.upper() for x in a["cursos_extra"]}
    cursos = av.llamar("core_enrol_get_users_courses", userid=av._usuario())
    elegidos, vigentes = [], []
    ahora_ts = ahora().timestamp()
    for c in cursos:
        corto = (c.get("shortname") or "").strip()
        codigo = corto.split("_")[0].upper()
        if codigo in excluir or corto.upper() in excluir:
            continue
        materia = moodle.materia_de(corto) or (c.get("fullname") or corto).strip()
        if moodle.materia_de(corto) or codigo in extra or corto.upper() in extra:
            elegidos.append((c, materia))
            continue
        fin, inicio = int(c.get("enddate") or 0), int(c.get("startdate") or 0)
        if (fin == 0 or fin > ahora_ts - 14 * 86400) and inicio > ahora_ts - 200 * 86400 and not c.get("hidden"):
            vigentes.append((c, materia))
    return elegidos or vigentes


# ------------------------------------------------------------------ qué hay en cada curso ---
def _url_segura(url):
    """Solo archivos de ESTE Moodle, por la vía del servicio (con la clave). None si es de otro sitio."""
    av = _avisos()
    sitio = urlparse(av.SITIO)
    u = urlparse(url or "")
    if u.scheme != "https" or u.netloc.lower() != sitio.netloc.lower():
        return None
    camino = u.path
    if "/webservice/pluginfile.php/" not in camino:
        if "/pluginfile.php/" not in camino:
            return None
        camino = camino.replace("/pluginfile.php/", "/webservice/pluginfile.php/", 1)
    consulta = re.sub(r"(?:^|&)token=[^&]*", "", u.query).strip("&")
    return av.SITIO + camino + "?" + (consulta + "&" if consulta else "") + "token=" + av.token()


def materiales_de(curso, materia):
    """Lista de archivos del curso: dict(clave, nombre, url, modificado, tamano, modulo, tipo)."""
    a = ajustes()
    exts = {e.lower() for e in a["extensiones"]}
    salida = []
    secciones = _avisos().llamar("core_course_get_contents", courseid=curso["id"])
    for s in secciones:
        for m in s.get("modules", []):
            tipo = m.get("modname")
            if m.get("uservisible") is False or tipo not in ("resource", "folder", "page"):
                continue
            for f in m.get("contents") or []:
                if f.get("type") != "file":
                    continue
                nombre = f.get("filename") or ""
                clave = "|".join([str(curso["id"]), str(m.get("id")), f.get("filepath") or "/", nombre])
                if tipo == "page":
                    if not a["paginas"] or nombre.lower() != "index.html":
                        continue
                    nombre = limpio(m.get("name") or "Página") + ".md"
                ext = Path(nombre).suffix.lower()
                salida.append({"clave": clave, "nombre": limpio(nombre), "url": f.get("fileurl", ""),
                               "modificado": int(f.get("timemodified") or 0), "tamano": int(f.get("filesize") or 0),
                               "modulo": (m.get("name") or "").strip(), "tipo": tipo, "ext": ext,
                               "permitido": tipo == "page" or ext in exts, "titulo_pagina": m.get("name") or ""})
    return salida


# ------------------------------------------------------------------ descargar ---
def _html_a_md(titulo, crudo):
    texto = crudo.decode("utf-8", errors="ignore")
    texto = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", texto)
    texto = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>|</tr>", "\n", texto)
    texto = re.sub(r"(?i)<li[^>]*>", "• ", texto)
    texto = unescape(re.sub(r"<[^>]+>", " ", texto))
    lineas = [" ".join(l.split()) for l in texto.splitlines()]
    cuerpo = "\n".join(l for l in lineas if l)
    return ("# " + " ".join(titulo.split()) + "\n\n" + cuerpo + "\n").encode("utf-8")


def descargar(item, destino):
    """Baja el archivo a 'destino' (vía .part). Devuelve el tamaño. Lanza SinPermisoDescarga si Moodle no deja."""
    import requests
    url = _url_segura(item["url"])
    if not url:
        raise ValueError("enlace fuera de Moodle")
    maximo = float(ajustes()["max_mb"]) * 1024 * 1024
    parcial = destino.with_name(destino.name + ".part")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        if r.status_code == 429:
            raise _avisos().Ocupado("Moodle pidió esperar (demasiadas descargas seguidas)")
        r.raise_for_status()
        trozos, total = [], 0
        for bloque in r.iter_content(64 * 1024):
            total += len(bloque)
            if total > maximo:
                raise ValueError("pasa de " + str(int(ajustes()["max_mb"])) + " MB")
            trozos.append(bloque)
    crudo = b"".join(trozos)
    inicio = crudo[:600].lstrip()
    if inicio.startswith(b"{") and b"errorcode" in inicio:
        try:
            err = json.loads(crudo.decode("utf-8", errors="ignore"))
        except ValueError:
            err = {}
        raise SinPermisoDescarga(err.get("message") or err.get("errorcode") or "Moodle no dejó descargar")
    esperado = MAGIA.get(destino.suffix.lower())
    if esperado and not crudo.startswith(esperado):
        if inicio[:15].lower().startswith((b"<!doctype", b"<html")):
            raise SinPermisoDescarga("Moodle devolvió una página web en vez del archivo")
        raise ValueError("el archivo no es un " + destino.suffix + " válido")
    if item["tipo"] == "page":
        crudo = _html_a_md(item["titulo_pagina"], crudo)
        if solo_enlaces(crudo.decode("utf-8", errors="ignore")):
            raise SoloEnlaces()
    parcial.write_bytes(crudo)
    parcial.replace(destino)
    return len(crudo)


# ------------------------------------------------------------------ revisar todo ---
def _modo_juego():
    try:
        from modulos.ia import cerebro
        return bool(cerebro.config().get("modo_ligero"))
    except Exception:
        return False


def toca_revisar():
    ultima = db.obtener_evento("moodle_materiales|ultima")
    if not ultima:
        return True
    from datetime import datetime
    try:
        hace = (ahora() - datetime.fromisoformat(ultima["huella"])).total_seconds()
    except Exception:
        return True
    return hace >= float(ajustes()["cada_horas"]) * 3600 - 120


def _marcar_revision():
    db.guardar_evento("moodle_materiales|ultima", "interno", "Materiales de Moodle", None,
                      ahora().isoformat(timespec="seconds"))


def revisar(forzar=False):
    """Descarga lo nuevo o cambiado. Devuelve dict(nuevos, actualizados, omitidos, errores, primera, cursos).
    nuevos/actualizados: listas de (materia, nombre). None si no tocaba o no hay clave."""
    av = _avisos()
    if not av.token():
        return None
    if not forzar and (not toca_revisar() or _modo_juego()):
        return None
    a = ajustes()
    raiz = Path(a["carpeta"])
    maximo = float(a["max_mb"]) * 1024 * 1024
    primera = not db.aviso_enviado("moodle_materiales|inicial")
    res = {"nuevos": [], "actualizados": [], "omitidos": [], "errores": [], "primera": primera, "cursos": [],
           "ocupado": False, "limpiadas": 0}
    sin_permiso = None
    for curso, materia in cursos_actuales():
        res["cursos"].append(materia)
        try:
            items = materiales_de(curso, materia)
        except av.SinConexion:
            raise
        except av.Ocupado as exc:
            log.info("Moodle ocupado (%s): reintento en la próxima vuelta", exc)
            res["ocupado"] = True
            break
        except Exception as exc:
            log.warning("No pude ver el contenido de %s: %s", materia, exc)
            res["errores"].append((materia, "no pude ver el curso"))
            continue
        carpeta = raiz / limpio(materia, 80)
        for it in items:
            with closing(_con()) as con:
                previo = con.execute("SELECT * FROM moodle_archivos WHERE clave = ?", (it["clave"],)).fetchone()
            if previo and previo["estado"] == "borrado":
                continue
            if previo and previo["estado"] == "bajado":
                if not Path(previo["ruta"]).exists():                    # El usuario lo borró: no se vuelve a bajar
                    with closing(_con()) as con, con:
                        con.execute("UPDATE moodle_archivos SET estado='borrado', actualizado=? WHERE clave=?",
                                    (ahora().isoformat(timespec="minutes"), it["clave"]))
                    continue
                if it["tipo"] == "page" and _pagina_vacia(previo["ruta"]):   # versión anterior: páginas de solo enlaces
                    try:
                        Path(previo["ruta"]).unlink()
                    except OSError:
                        pass
                    _omitir(it, curso, materia, "solo enlaces", primera)
                    res["limpiadas"] += 1
                    continue
                if previo["modificado"] == it["modificado"]:
                    continue
            if previo and previo["estado"] == "omitido" and previo["modificado"] == it["modificado"]:
                continue
            motivo = ""
            if not it["permitido"]:
                motivo = "formato " + (it["ext"] or "sin extensión")
            elif not _url_segura(it["url"]):
                motivo = "enlace fuera de Moodle"
            elif it["tamano"] > maximo:
                motivo = "pesa %.0f MB" % (it["tamano"] / 1024 / 1024)
            if motivo:
                with closing(_con()) as con, con:
                    con.execute("INSERT OR REPLACE INTO moodle_archivos (clave, curso, materia, modulo, nombre, ruta, "
                                "modificado, tamano, estado, motivo, inicial, actualizado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                (it["clave"], curso.get("shortname", ""), materia, it["modulo"], it["nombre"], "",
                                 it["modificado"], it["tamano"], "omitido", motivo, int(primera),
                                 ahora().isoformat(timespec="minutes")))
                if not previo:
                    res["omitidos"].append((materia, it["nombre"], motivo))
                continue
            with closing(_con()) as con:
                destino = Path(previo["ruta"]) if previo and previo["ruta"] else _ruta_libre(carpeta, it["nombre"], it["clave"], con)
            try:
                tamano = descargar(it, destino)
            except SoloEnlaces:
                _omitir(it, curso, materia, "solo enlaces", primera)
                if previo and previo["ruta"] and Path(previo["ruta"]).exists():
                    Path(previo["ruta"]).unlink()
                continue
            except av.Ocupado as exc:
                log.info("Moodle ocupado (%s): reintento en la próxima vuelta", exc)
                res["ocupado"] = True
                break
            except SinPermisoDescarga as exc:
                sin_permiso = str(exc)
                log.warning("Moodle no deja descargar %s: %s", it["nombre"], exc)
                break
            except Exception as exc:
                log.warning("No pude bajar %s (%s): %s", it["nombre"], materia, exc)
                res["errores"].append((materia, it["nombre"]))
                continue
            with closing(_con()) as con, con:
                con.execute("INSERT OR REPLACE INTO moodle_archivos (clave, curso, materia, modulo, nombre, ruta, "
                            "modificado, tamano, estado, motivo, inicial, actualizado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (it["clave"], curso.get("shortname", ""), materia, it["modulo"], destino.name, str(destino),
                             it["modificado"], tamano, "bajado", "", int(primera and not previo),
                             ahora().isoformat(timespec="minutes")))
            (res["actualizados"] if previo and previo["estado"] == "bajado" else res["nuevos"]).append((materia, destino.name))
            log.info("%s %s (%s)", "Actualizado" if previo else "Bajado", destino.name, materia)
            time.sleep(0.3)
        if sin_permiso or res["ocupado"]:
            break
    if res["ocupado"]:
        return res                              # sin marcar la revisión: se reintenta en 30 min
    _marcar_revision()                          # también si falló: se reintenta en la próxima vuelta de 6 h
    if sin_permiso and not res["nuevos"]:
        raise SinPermisoDescarga(sin_permiso)
    if primera and res["cursos"]:
        db.marcar_aviso("moodle_materiales|inicial")
    log.info("Materiales revisados: %d cursos, %d nuevos, %d actualizados, %d omitidos, %d errores",
             len(res["cursos"]), len(res["nuevos"]), len(res["actualizados"]), len(res["omitidos"]), len(res["errores"]))
    return res


def _pagina_vacia(ruta):
    try:
        return solo_enlaces(Path(ruta).read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return False


def _omitir(it, curso, materia, motivo, primera):
    with closing(_con()) as con, con:
        con.execute("INSERT OR REPLACE INTO moodle_archivos (clave, curso, materia, modulo, nombre, ruta, modificado, "
                    "tamano, estado, motivo, inicial, actualizado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (it["clave"], curso.get("shortname", ""), materia, it["modulo"], it["nombre"], "", it["modificado"],
                     it["tamano"], "omitido", motivo, int(primera), ahora().isoformat(timespec="minutes")))


def tipos():
    """Diagnóstico: qué tipos de actividad y de archivo tiene cada curso (no descarga nada)."""
    from collections import Counter
    av = _avisos()
    lineas = []
    for curso, materia in cursos_actuales():
        secciones = av.llamar("core_course_get_contents", courseid=curso["id"])
        mods = [m for s in secciones for m in s.get("modules", [])]
        exts = Counter(Path(f.get("filename") or "").suffix.lower() or f.get("type", "?")
                       for m in mods for f in (m.get("contents") or []))
        lineas.append(materia + ":\n   actividades " + str(dict(Counter(m.get("modname") for m in mods)))
                      + "\n   archivos " + str(dict(exts)))
        time.sleep(1)
    return "\n".join(lineas)


def silencioso(ruta):
    """La biblioteca no avisa «Leí …» de los archivos que llegaron en la primera descarga (serían decenas)."""
    try:
        with closing(_con()) as con:
            f = con.execute("SELECT inicial FROM moodle_archivos WHERE ruta = ?", (str(ruta),)).fetchone()
        return bool(f and f["inicial"])
    except Exception:
        return False


# ------------------------------------------------------------------ textos para Telegram ---
def _agrupar(lista):
    por = {}
    for materia, nombre in lista:
        por.setdefault(materia, []).append(nombre)
    return por


def mensajes(res):
    """Mensajes HTML para Telegram a partir del resultado de revisar()."""
    if not res:
        return []
    salida = []
    if res["primera"]:
        if not res["cursos"]:
            return ["⚠️ No encontré sus cursos de este semestre en Moodle para bajar materiales."]
        por = _agrupar(res["nuevos"])
        lineas = ["📎 <b>Conecté los materiales de Moodle.</b>",
                  "Bajé " + str(len(res["nuevos"])) + " archivo(s) de " + str(len(res["cursos"])) + " materia(s):"]
        lineas += ["• <b>" + escape(m) + "</b>: " + str(len(n)) for m, n in sorted(por.items())]
        sin = [m for m in res["cursos"] if m not in por]
        if sin:
            lineas.append("• Sin archivos todavía: " + escape(", ".join(sin)))
        if res["omitidos"]:
            lineas.append("\nNo bajé " + str(len(res["omitidos"])) + " (videos, formatos viejos o muy pesados).")
        lineas += ["", "La biblioteca los irá leyendo de a poco (sin avisarle uno por uno).",
                   "Ya puede preguntarme: «¿qué dijo el profesor sobre …?»"]
        return ["\n".join(lineas)]
    if res["nuevos"]:
        lineas = ["📎 <b>Material nuevo en Moodle</b>"]
        for m, nombres in sorted(_agrupar(res["nuevos"]).items()):
            lineas += ["• <b>" + escape(m) + "</b> – " + escape(n) for n in nombres]
        lineas.append("\nYa está en su biblioteca; cuando lo lea le mando el resumen.")
        salida.append("\n".join(lineas))
    if res["actualizados"]:
        lineas = ["🔄 <b>El profesor actualizó material en Moodle</b>"]
        for m, nombres in sorted(_agrupar(res["actualizados"]).items()):
            lineas += ["• <b>" + escape(m) + "</b> – " + escape(n) for n in nombres]
        lineas.append("\nBajé la versión nueva.")
        salida.append("\n".join(lineas))
    if res["omitidos"]:
        salida.append("ℹ️ En Moodle hay material que no bajé:\n" + "\n".join(
            "• " + escape(m) + " – " + escape(n) + " (" + escape(mot) + ")" for m, n, mot in res["omitidos"][:8]))
    return salida


def estado_texto():
    a = ajustes()
    with closing(_con()) as con:
        filas = con.execute("SELECT materia, estado, COUNT(*) n FROM moodle_archivos GROUP BY materia, estado").fetchall()
        ultimos = con.execute("SELECT materia, nombre, actualizado FROM moodle_archivos WHERE estado='bajado' "
                              "ORDER BY actualizado DESC, rowid DESC LIMIT 5").fetchall()
    ultima = db.obtener_evento("moodle_materiales|ultima")
    if not filas:
        return ("📎 Todavía no bajé materiales de Moodle.\nCarpeta: " + a["carpeta"] +
                "\nEscriba /materiales para revisar ahora.")
    por = {}
    for f in filas:
        por.setdefault(f["materia"], {})[f["estado"]] = f["n"]
    lineas = ["📎 Materiales de Moodle (en su biblioteca):"]
    for m, e in sorted(por.items()):
        extra = []
        if e.get("omitido"):
            extra.append(str(e["omitido"]) + " sin bajar (grabaciones, videos o formatos viejos)")
        if e.get("borrado"):
            extra.append(str(e["borrado"]) + " borrados por usted")
        lineas.append("• " + m + ": " + str(e.get("bajado", 0)) + (" (" + ", ".join(extra) + ")" if extra else ""))
    if ultimos:
        lineas += ["", "Últimos:"] + ["• " + u["nombre"] + " – " + u["materia"] for u in ultimos]
    if ultima:
        lineas.append("\nÚltima revisión: " + ultima["huella"][:16].replace("T", " ") + " · cada "
                      + str(a["cada_horas"]) + " h")
    lineas.append("Carpeta: " + a["carpeta"])
    return "\n".join(lineas)


# ------------------------------------------------------------------ prueba desde la PC ---
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Materiales de Moodle")
    p.add_argument("--cursos", action="store_true", help="Ver qué cursos se revisarían")
    p.add_argument("--revisar", action="store_true", help="Revisar y descargar ya")
    p.add_argument("--estado", action="store_true")
    p.add_argument("--tipos", action="store_true", help="Qué tipos de actividad/archivo hay en cada curso")
    a = p.parse_args()
    if a.tipos:
        print(tipos())
    if a.cursos:
        for c, m in cursos_actuales():
            print("•", c.get("shortname"), "->", m)
    if a.revisar:
        r = revisar(forzar=True)
        for t in mensajes(r) or ["Nada nuevo."]:
            print(re.sub(r"<[^>]+>", "", t), "\n")
    if a.estado or not (a.cursos or a.revisar or a.tipos):
        print(estado_texto())
