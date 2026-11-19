"""Panel de vida en el celular (Fase 2): un servidor web chiquito DENTRO del bot (un hilo), solo por Tailscale.

- Escucha en la IP de Tailscale de la PC (100.x.x.x) y en 127.0.0.1, puerto de config/vida.json (8765).
  Nunca en la red de la casa ni en internet. Además pide una clave (PANEL_TOKEN en el .env; se crea sola).
- GET  /?t=CLAVE        → el panel (guarda la clave en una cookie; después basta con abrir la dirección).
- GET  /api/datos       → todo lo que muestra el panel (JSON).
- POST /api/habito      → marcar un hábito desde el panel {"habito": "lectura", "accion": "si|no|mas|menos|borrar"}.
- POST /api/salud?t=CLAVE → lo que manda el atajo del iPhone (datos de la banda vía Apple Health).
- GET  /atajo           → instrucciones del atajo con su dirección y clave ya puestas.
El enlace lo da /panel en Telegram.
"""
import ipaddress
import json
import os
import secrets
import threading
import time
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from modulos.comun.base import RAIZ, ahora, registro

log = registro("panel")
HTML = Path(__file__).with_name("panel.html")
RED_TAILSCALE = ipaddress.ip_network("100.64.0.0/10")
_servidores = {}


# --- clave y dirección ---------------------------------------------------------------------------------------
def clave():
    t = (os.getenv("PANEL_TOKEN") or "").strip()
    if t:
        return t
    t = secrets.token_urlsafe(18)
    try:
        env = RAIZ / ".env"
        previo = env.read_text(encoding="utf-8") if env.exists() else ""
        env.write_text(previo.rstrip("\n") + ("\n" if previo else "") + "PANEL_TOKEN=" + t + "\n", encoding="utf-8")
    except Exception as exc:
        log.warning("No pude guardar PANEL_TOKEN en .env: %s", exc)
    os.environ["PANEL_TOKEN"] = t
    return t


def ip_tailscale():
    try:
        import psutil
        for nombre, direcciones in psutil.net_if_addrs().items():
            for d in direcciones:
                try:
                    if d.family.name == "AF_INET" and ipaddress.ip_address(d.address) in RED_TAILSCALE:
                        return d.address
                except ValueError:
                    continue
    except Exception as exc:
        log.info("No pude leer las interfaces de red: %s", exc)
    return None


def puerto():
    from modulos.vida import habitos_vida
    return int(habitos_vida.ajustes().get("puerto_panel", 8765))


def direccion(con_clave=True):
    ip = ip_tailscale()
    if not ip:
        return None
    return "http://" + ip + ":" + str(puerto()) + "/" + ("?t=" + clave() if con_clave else "")


# --- datos del panel -----------------------------------------------------------------------------------------
def _seguro(nombre, funcion):
    try:
        return funcion()
    except Exception as exc:
        log.info("Panel sin %s: %s", nombre, exc)
        return None


def _hoy():
    from modulos.vida import habitos_vida
    f = ahora()
    return {"fecha": f.date().isoformat(), "dia": habitos_vida.dia_bonito(f), "hora": f.strftime("%H:%M"),
            "habitos": habitos_vida.del_dia(f), "meta_dormir": habitos_vida.ajustes()["hora_dormir"],
            "rachas": {h["id"]: habitos_vida.racha(h["id"]) for h in habitos_vida.habitos() if h.get("tipo") != "contador"}}


def _sueno():
    from modulos.vida import sueno
    lista = sueno.noches(14)
    r = sueno.analisis(14)
    noches = []
    for n in lista:
        noches.append({"fecha": n["fecha"], "dormir": sueno._reloj(sueno._min_desde_18(n["dormir"])),
                       "dormir18": sueno._min_desde_18(n["dormir"]),
                       "despertar": (n["despertar"] or "")[11:16] or None, "total": n["total"], "profundo": n["profundo"],
                       "rem": n["rem"], "ligero": n["ligero"], "despierto": n["despierto"], "fuente": n["fuente"]})
    r = {k: v for k, v in r.items() if k != "consejos"} | {"consejos": [t for _, t in r.get("consejos", [])]}
    return {"noches": noches, "analisis": r}


def _salud():
    from modulos.vida import sueno
    return sueno.salud(14)


def _semana():
    from modulos.vida import habitos_vida
    return habitos_vida.semana()


def _cierres():
    """{tarea_id: 'AAAA-MM-DDTHH:MM'} con la fecha de CIERRE de Moodle (el último momento para entregar) de cada deber."""
    from modulos.estudio import moodle
    from contextlib import closing
    with closing(moodle._con()) as con:
        filas = [dict(f) for f in con.execute("SELECT * FROM moodle_eventos WHERE tipo IN ('deber', 'cierre')")]
    cierres = {}
    for f in filas:
        if f["tipo"] == "cierre":
            cierres[(moodle._clave(f["titulo"]), f["curso"])] = f["vence"][:16]
    salida = {}
    for f in filas:
        if f["tipo"] == "deber" and f["tarea_id"]:
            c = cierres.get((moodle._clave(f["titulo"]), f["curso"]))
            if c and c != f["vence"][:16]:
                salida[f["tarea_id"]] = c
            if f["tarea_id"] not in salida:
                salida.setdefault(-f["tarea_id"], "moodle")          # marca: vino de Moodle (sin cierre aparte)
    return salida


def _estados_moodle():
    """{tarea_id: (estado, 'AAAA-MM-DDTHH:MM')} con lo último que dijo Moodle de cada deber."""
    from modulos.estudio import moodle_avisos
    from contextlib import closing
    with closing(moodle_avisos._con()) as con:
        return {f["tarea_id"]: (f["estado"], f["revisado"]) for f in con.execute("SELECT * FROM moodle_entregas")}


def _moodle():
    """Última revisión de entregas y deberes que Jarvis vio entregados en Moodle (últimos 14 días)."""
    from modulos.estudio import moodle_avisos
    from modulos.tareas import tareas
    from contextlib import closing
    hoy = ahora().date()
    with closing(moodle_avisos._con()) as con:
        r = con.execute("SELECT * FROM moodle_revision WHERE id = 1").fetchone()
        filas = con.execute("SELECT * FROM moodle_entregas WHERE estado = 'submitted' AND revisado >= ? "
                            "ORDER BY revisado DESC", ((hoy - timedelta(days=14)).isoformat(),)).fetchall()
    entregados = []
    for f in filas[:10]:
        t = tareas.obtener(f["tarea_id"])
        if t and t["estado"] != "borrada":
            entregados.append({"id": t["id"], "titulo": t["titulo"], "materia": t["materia"],
                               "visto": tareas.fecha_bonita(f["revisado"][:10], hoy) + " " + f["revisado"][11:16]})
    revision = None
    if r:
        revision = {"cuando": tareas.fecha_bonita(r["cuando"][:10], hoy) + " " + r["cuando"][11:16],
                    "revisados": r["revisados"], "entregados": r["entregados"], "errores": r["errores"],
                    "ultimo_error": r["ultimo_error"] or ""}
    return {"revision": revision, "entregados": entregados}


def _tareas():
    from modulos.tareas import tareas
    hoy = ahora().date()
    limite = (hoy + timedelta(days=14)).isoformat()
    cierres = _seguro("cierres de Moodle", _cierres) or {}
    estados = _seguro("entregas de Moodle", _estados_moodle) or {}
    salida = []
    for t in tareas.pendientes(hasta=limite):
        c = cierres.get(t["id"])
        salida.append({"id": t["id"], "titulo": t["titulo"], "materia": t["materia"], "entrega": t["entrega"], "hora": t["hora"],
                       "vencida": t["entrega"] < hoy.isoformat(), "cuando": tareas.fecha_bonita(t["entrega"], hoy),
                       "cierre": c[:10] if c else None, "cierre_hora": c[11:16] if c and len(c) > 10 else None,
                       "cierre_cuando": tareas.fecha_bonita(c[:10], hoy) if c else None,
                       "moodle": bool(c) or (-t["id"]) in cierres,
                       "moodle_estado": (estados.get(t["id"]) or (None,))[0],
                       "moodle_revisado": (estados.get(t["id"]) or (None, ""))[1][11:16] or None})
    return salida[:20]


PALABRAS_DEBER = ("deber", "tarea", "ensayo", "entrega", "entregar", "examen", "prueba", "leccion", "proyecto", "trabajo",
                  "informe", "exposicion", "taller", "foro", "lectura", "presentacion", "practica")


def _sin_tildes(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


def _recordatorios_deberes():
    """Recordatorios que usted guardó para una materia (o que suenan a deber) en los próximos 14 días. Los que ya están
    como deber (misma materia, fecha cercana y alguna palabra en común) no se repiten."""
    from modulos.agenda import eventos
    from modulos.comun.base import leer_json
    from modulos.tareas import recordatorios, tareas
    hoy = ahora().date()
    try:
        materias = [c["materia"] for c in leer_json("horario_clases.json")["clases"]]
    except Exception:
        materias = []
    pendientes = tareas.pendientes(hasta=(hoy + timedelta(days=30)).isoformat())
    salida, vistos = [], set()
    for i in range(15):
        dia = hoy + timedelta(days=i)
        for e in eventos.del_dia(dia):
            if (e["nota"] or "") != recordatorios.NOTA or e["id"] in vistos:
                continue
            texto = e["titulo"].replace("\U0001F514", "").strip()
            st = _sin_tildes(texto)
            materia = next((m for m in materias if any(t.startswith(w[:6]) for w in _sin_tildes(m).split() if len(w) >= 5
                                                         for t in st.split() if len(t) >= 5)), None)   # «creativa» ~ Diseño Creativo
            if not materia and not any(p in st for p in PALABRAS_DEBER):
                continue
            palabras = {w for w in st.split() if len(w) >= 5} - {_sin_tildes(w) for m in materias for w in m.split()}
            repetido = any(abs((date.fromisoformat(t["entrega"]) - dia).days) <= 2
                           and (not materia or t["materia"] == materia)
                           and palabras & {w for w in _sin_tildes(t["titulo"]).split() if len(w) >= 5} for t in pendientes)
            if repetido:
                continue
            vistos.add(e["id"])
            salida.append({"id": e["id"], "texto": texto, "materia": materia, "fecha": dia.isoformat(), "hora": e["inicio"],
                           "cuando": tareas.fecha_bonita(dia.isoformat(), hoy)})
    return salida[:10]


def _agenda():
    """Lo de hoy en orden: clases (con cambios del celular), actividades, bloques de estudio y recordatorios."""
    from modulos.agenda import eventos
    from modulos.clases import agenda
    from modulos.tareas import recordatorios
    hoy = ahora().date()
    items = []
    try:
        clases = agenda.clases_efectivas(hoy)
    except Exception as exc:                                   # sin horario de clases: igual se muestran las actividades
        log.info("Agenda del panel sin clases: %s", exc)
        clases = []
    for c in clases:
        items.append({"inicio": c["inicio"], "fin": c["fin"], "titulo": c["materia"], "tipo": "clase", "nota": c.get("nota", "")})
    for e in eventos.del_dia(hoy):
        nota = e["nota"] or ""
        tipo = "recordatorio" if nota == recordatorios.NOTA else "estudio" if e["titulo"].lower().startswith("estudio") else "actividad"
        items.append({"inicio": e["inicio"], "fin": e["fin"], "titulo": e["titulo"].replace("\U0001F514", "").strip(),
                      "tipo": tipo, "nota": ""})
    ahora_ = ahora().strftime("%H:%M")
    for x in items:
        x["pasado"] = (x["fin"] or x["inicio"]) < ahora_
    return sorted(items, key=lambda x: x["inicio"])


def _dinero():
    from modulos.finanzas import gastos, presupuesto
    hoy = ahora().date()
    a, b = gastos.mes(hoy.year, hoy.month)
    lista = gastos.del_periodo(a, min(b, hoy), "gasto")
    por_cat = {}
    for g in lista:
        por_cat[g["categoria"]] = por_cat.get(g["categoria"], 0) + g["monto"]
    ingresos, _ = presupuesto.ingresos_mes(hoy)
    disponible, aportes = presupuesto.disponible_mes(hoy)
    d = {"gastado": round(sum(por_cat.values()), 2), "ingresos": ingresos, "disponible": disponible,
         "aportes": aportes, "avance_mes": presupuesto.avance_del_mes(hoy),
         "categorias": [{"nombre": k, "monto": round(v, 2)} for k, v in sorted(por_cat.items(), key=lambda x: -x[1])][:8],
         "presupuestos": []}
    for categoria, monto in (presupuesto.presupuestos() or {}).items():
        d["presupuestos"].append({"nombre": categoria, "limite": monto,
                                  "gastado": round(por_cat.get(categoria, 0), 2)})
    deudas = _seguro("deudas", _deudas)
    if deudas:
        d["deudas"] = deudas
    ahorros = _seguro("ahorros", _ahorros)
    if ahorros:
        d["ahorros"] = ahorros
    port = _seguro("portafolio", _portafolio)
    if port:
        d["portafolio"] = port
    inversion = _seguro("inversión", _inversion)
    if inversion:
        d["inversion"] = inversion
    cuentas = _seguro("cuentas", _cuentas)
    if cuentas:
        d["cuentas"] = cuentas
    tarjetas = _seguro("tarjetas", _tarjetas)
    if tarjetas and (tarjetas["tarjetas"] or any(m["total"] for m in tarjetas["cuotas_meses"])):
        d["tarjetas"] = tarjetas
    return d


def _cuentas():
    from modulos.finanzas import cuentas
    lista = []
    for c in cuentas.nombres_cuentas():
        s, det = cuentas.saldo(c)
        if s is not None:
            lista.append({"nombre": c, "saldo": s, "desde": det["desde"][:10]})
    return {"lista": lista, "pendientes": len(cuentas.pendientes())} if lista or cuentas.pendientes() else None


def _tarjetas():
    from modulos.finanzas import tarjetas
    return tarjetas.datos_panel()


def _deudas():
    from modulos.finanzas import deudas
    me_deben = sum(deudas.saldo(x["id"]) for x in deudas.abiertas(sentido="me_debe"))
    debo = sum(deudas.saldo(x["id"]) for x in deudas.abiertas(sentido="le_debo"))
    return {"me_deben": round(me_deben, 2), "debo": round(debo, 2),
            "lista": [{"persona": x["persona"], "saldo": round(deudas.saldo(x["id"]), 2), "sentido": x["sentido"]}
                      for x in deudas.abiertas()][:8]}


def _icono_ahorro(nombre):
    n = _sin_tildes(nombre)
    for claves, icono in ((("viaje", "vuelo", "vacacion"), "✈️"), (("emergencia", "imprevisto", "colchon"), "🛟"),
                          (("estudio", "universidad", "curso"), "🎓"), (("casa", "depa", "hogar"), "🏠"),
                          (("auto", "carro", "moto"), "🚗"), (("compu", "laptop", "pc"), "💻")):
        if any(c in n for c in claves):
            return icono
    return "🎯"


def _ahorros():
    from modulos.finanzas import ahorros
    lista = ahorros.activos()
    return {"total": round(sum(a["saldo"] or 0 for a in lista), 2),
            "lista": [{"nombre": a["nombre"], "saldo": a["saldo"] or 0, "meta": a["meta"], "icono": _icono_ahorro(a["nombre"]),
                       "aporte": ahorros.aporte_efectivo(a), "dia": a["dia_aporte"]} for a in lista]}


def _inversion():
    """Lo que pasó a su bróker (XTB…): no es gasto. Este mes, el año y los últimos movimientos."""
    from modulos.finanzas import gastos
    hoy = ahora().date()
    mes = gastos.del_periodo(hoy.replace(day=1), hoy, "inversion")
    anio = gastos.del_periodo(date(hoy.year, 1, 1), hoy, "inversion")
    ultimos = gastos.del_periodo(hoy - timedelta(days=365), hoy, "inversion")[-6:]
    if not anio and not ultimos:
        return None
    return {"mes": round(sum(m["monto"] for m in mes), 2), "anio": round(sum(m["monto"] for m in anio), 2),
            "lista": [{"fecha": m["fecha"], "monto": m["monto"], "descripcion": m["descripcion"]} for m in reversed(ultimos)]}


_port = {"calculando": False}


def _portafolio():
    """Solo porcentajes (como en Telegram). Si no está calculado, lo calcula en segundo plano para la próxima vez."""
    from modulos.portafolio import portafolio
    datos = portafolio._cache.get("datos") if time.time() - portafolio._cache.get("t", 0) < 3600 else None
    if not datos:
        if not _port["calculando"]:
            _port["calculando"] = True

            def calcular():
                try:
                    portafolio.calcular()
                except Exception as exc:
                    log.info("Portafolio no calculado: %s", exc)
                finally:
                    _port["calculando"] = False
            threading.Thread(target=calcular, daemon=True).start()
        return {"calculando": True}
    return {"ganancia_pct": round(datos["ganancia_pct"], 1), "hoy_pct": round(datos["hoy_pct"], 2),
            "ref_pct": None if datos["ref_pct"] is None else round(datos["ref_pct"], 1),
            "acciones": [{"nombre": p["yahoo"], "peso": round(p["peso"]), "ganancia_pct": round(p["ganancia_pct"], 1)}
                         for p in datos["posiciones"][:8]],
            "calculado": datos["calculado"].strftime("%d/%m %H:%M")}


def _negocio():
    from modulos.segundo_cerebro import segundo_cerebro as sc
    return {"ideas": [{"id": n["id"], "texto": n["texto"], "fecha": n["creado"][:10]} for n in sc.ultimas(5, "idea")],
            "metas": [{"id": n["id"], "texto": n["texto"]} for n in sc.ultimas(5, "meta")],
            "decisiones": [{"id": n["id"], "texto": n["texto"]} for n in sc.ultimas(3, "decision")],
            "total": len(sc.ultimas(100000))}


def _empresa():
    from modulos.empresa import empresa
    return empresa.datos_panel()


def _equipo():
    from modulos.equipo import equipo
    return equipo.datos_panel()


def _ingles():
    from modulos.ingles import vocab
    e = vocab.estadisticas()
    return e if e["total"] else None


def _bolsa():
    """Alertas de precio activas y los próximos resultados/dividendos (los que ya se pusieron en Google Calendar)."""
    from contextlib import closing
    from modulos.alertas import alertas
    from modulos.comun import db
    lista = [{"id": a["id"], "texto": alertas.describir(dict(a))} for a in alertas.activas()]
    hoy = ahora().date().isoformat()
    eventos = []
    with closing(db.conectar()) as con:
        for f in con.execute("SELECT clave, titulo FROM eventos WHERE clave LIKE 'mercado:%' AND estado = 'activo'"):
            try:
                ticker, tipo, fecha = f["clave"][8:].split("|")[:3]
            except ValueError:
                continue
            if fecha >= hoy:
                eventos.append({"fecha": fecha, "ticker": ticker, "tipo": tipo})
    eventos.sort(key=lambda x: x["fecha"])
    return {"alertas": lista, "eventos": eventos[:8]} if lista or eventos else None


_salud_cache = {"t": 0.0, "datos": None, "calculando": False}


def _sistema():
    """Último chequeo del asistente (se hace en segundo plano cada 6 h para no hacer esperar al panel)."""
    if time.time() - _salud_cache["t"] > 6 * 3600 and not _salud_cache["calculando"]:
        _salud_cache["calculando"] = True

        def revisar():
            try:
                from modulos.comun import salud
                _salud_cache["datos"] = [{"nombre": r["nombre"], "estado": r["estado"], "detalle": r["detalle"]}
                                         for r in salud.revisar()]
                _salud_cache["t"] = time.time()
                _salud_cache["hora"] = ahora().strftime("%d/%m %H:%M")
            except Exception as exc:
                log.info("Chequeo para el panel falló: %s", exc)
            finally:
                _salud_cache["calculando"] = False
        threading.Thread(target=revisar, daemon=True).start()
    if not _salud_cache["datos"]:
        return {"calculando": True}
    return {"piezas": _salud_cache["datos"], "hora": _salud_cache.get("hora")}


def datos():
    return {"agenda": _seguro("agenda", _agenda), "recordatorios": _seguro("recordatorios", _recordatorios_deberes),
            "ingles": _seguro("inglés", _ingles), "bolsa": _seguro("bolsa", _bolsa), "sistema": _seguro("sistema", _sistema),"equipo": _seguro("equipo", _equipo), "empresa": _seguro("empresa", _empresa), "hoy": _seguro("hoy", _hoy), "semana": _seguro("semana", _semana), "sueno": _seguro("sueño", _sueno),
            "salud": _seguro("salud", _salud), "tareas": _seguro("tareas", _tareas), "moodle": _seguro("moodle", _moodle), "dinero": _seguro("dinero", _dinero),
            "negocio": _seguro("negocio", _negocio), "generado": ahora().strftime("%d/%m %H:%M")}


def accion_habito(hid, accion):
    from modulos.vida import habitos_vida
    h = habitos_vida.habito(hid)
    if not h:
        return False
    if accion == "si":
        habitos_vida.marcar(hid, nuevo=1)
    elif accion == "no":
        habitos_vida.marcar(hid, nuevo=0)
    elif accion == "mas":
        habitos_vida.marcar(hid, delta=1)
    elif accion == "menos":
        habitos_vida.marcar(hid, delta=-1)
    elif accion == "borrar":
        habitos_vida.marcar(hid)
    else:
        return False
    return True


# --- servidor ------------------------------------------------------------------------------------------------
PAGINA_SIN_CLAVE = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                    "<body style='font-family:system-ui;padding:2em'><h2>🔒 Panel privado</h2>"
                    "<p>Abra el enlace que le manda el asistente con <b>/panel</b> en Telegram.</p></body>")


class Manejador(BaseHTTPRequestHandler):
    server_version = "PanelVida/1"

    def log_message(self, formato, *args):          # sin ruido en la consola; lo importante va a logs/panel.log
        pass

    def _permitido_ip(self):
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return ip.is_loopback or ip in RED_TAILSCALE

    def _clave_ok(self, consulta):
        t = clave()
        dada = (consulta.get("t") or [""])[0]
        cookie = self.headers.get("Cookie") or ""
        en_cookie = any(p.strip() == "panel=" + t for p in cookie.split(";"))
        return secrets.compare_digest(dada, t) or en_cookie, bool(dada and secrets.compare_digest(dada, t))

    def _enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8", extra=None):
        if isinstance(cuerpo, (dict, list)):
            cuerpo = json.dumps(cuerpo, ensure_ascii=False, default=str)
        datos = cuerpo.encode("utf-8") if isinstance(cuerpo, str) else cuerpo
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(datos)

    def _cuerpo(self):
        largo = min(int(self.headers.get("Content-Length") or 0), 2_000_000)
        return self.rfile.read(largo) if largo else b""

    def do_GET(self):
        if not self._permitido_ip():
            return self._enviar(403, {"error": "solo por Tailscale"})
        url = urlparse(self.path)
        consulta = parse_qs(url.query)
        ok, por_url = self._clave_ok(consulta)
        if not ok:
            return self._enviar(403, PAGINA_SIN_CLAVE, "text/html; charset=utf-8")
        cookie = {"Set-Cookie": "panel=" + clave() + "; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict"} \
            if por_url else None
        if url.path in ("/", "/index.html"):
            return self._enviar(200, HTML.read_text(encoding="utf-8"), "text/html; charset=utf-8", cookie)
        if url.path == "/api/datos":
            return self._enviar(200, datos())
        if url.path == "/atajo":
            return self._enviar(200, pagina_atajo(), "text/html; charset=utf-8", cookie)
        if url.path == "/favicon.ico":
            return self._enviar(204, b"", "image/x-icon")
        return self._enviar(404, {"error": "no existe"})

    def do_POST(self):
        if not self._permitido_ip():
            return self._enviar(403, {"error": "solo por Tailscale"})
        url = urlparse(self.path)
        consulta = parse_qs(url.query)
        ok, _ = self._clave_ok(consulta)
        if not ok:
            return self._enviar(403, {"error": "falta la clave"})
        crudo = self._cuerpo()
        if url.path == "/api/habito":
            try:
                pedido = json.loads(crudo or b"{}")
            except ValueError:
                return self._enviar(400, {"error": "JSON inválido"})
            if accion_habito(str(pedido.get("habito", "")), str(pedido.get("accion", ""))):
                return self._enviar(200, {"ok": True, "hoy": _seguro("hoy", _hoy)})
            return self._enviar(400, {"error": "hábito o acción desconocidos"})
        if url.path == "/api/salud":
            texto = texto_de_salud(crudo, self.headers.get("Content-Type") or "")
            from modulos.vida import sueno
            try:
                r = sueno.ingestar(texto)
            except Exception as exc:
                log.warning("Error al leer los datos de salud: %s", exc)
                return self._enviar(500, "Error: " + str(exc)[:200], "text/plain; charset=utf-8")
            (Path(RAIZ) / "logs").mkdir(exist_ok=True)
            try:                                       # copia de lo último recibido (para revisar si algo no cuadra)
                (Path(RAIZ) / "logs" / "salud_ultimo.txt").write_text(texto[:200000], encoding="utf-8")
            except Exception:
                pass
            if r.get("dormir"):                            # atajo del modo Dormir: respuesta corta
                return self._enviar(200, r["dormir"], "text/plain; charset=utf-8")
            if not r["noches"] and not r["dias"]:          # diagnóstico para armar el atajo
                lineas = [x for x in texto.splitlines() if x.strip()]
                log.info("Salud sin datos útiles. Tipo=%s, bytes=%d, cuerpo=%r", self.headers.get("Content-Type"),
                         len(crudo), crudo[:300])
                if not lineas:
                    return self._enviar(200, "⚠️ Llegó vacío (" + str(len(crudo)) + " bytes, tipo «"
                                        + (self.headers.get("Content-Type") or "?") + "»). Revise que el campo «datos» "
                                        "tenga la variable Texto combinado y que Buscar muestras de salud encuentre algo.",
                                        "text/plain; charset=utf-8")
                return self._enviar(200, "⚠️ Llegaron " + str(len(lineas)) + " líneas pero no entendí ninguna. "
                                    "Primera: «" + lineas[0][:150] + "»", "text/plain; charset=utf-8")
            return self._enviar(200, "✅ Recibido: " + str(r["noches"]) + " noches, " + str(r["dias"]) + " días"
                                + (" (" + str(r["ignoradas"]) + " líneas no entendidas)" if r["ignoradas"] else ""),
                                "text/plain; charset=utf-8")
        return self._enviar(404, {"error": "no existe"})


def texto_de_salud(crudo, tipo):
    """El atajo puede mandar texto plano, formulario (campo «datos») o JSON ({"datos": "..."})."""
    texto = crudo.decode("utf-8", errors="replace")
    tipo = tipo.lower()
    if "application/x-www-form-urlencoded" in tipo:
        campos = parse_qs(texto)
        return "\n".join(campos.get("datos") or campos.get("texto") or list(campos.keys()))
    if "multipart/form-data" in tipo and "boundary=" in tipo:
        frontera = tipo.split("boundary=", 1)[1].split(";")[0].strip('"')
        partes = [p.split("\r\n\r\n", 1)[1].rsplit("\r\n", 1)[0] for p in texto.split("--" + frontera)
                  if "\r\n\r\n" in p]
        return "\n".join(partes)
    if "json" in tipo or texto.lstrip().startswith(("{", "[")):
        try:
            j = json.loads(texto)
            if isinstance(j, dict):
                v = j.get("datos") or j.get("texto") or ""
                return "\n".join(v) if isinstance(v, list) else str(v)
            if isinstance(j, list):
                return "\n".join(str(x) for x in j)
        except ValueError:
            pass
    return texto


def pagina_atajo():
    url = "http://" + (ip_tailscale() or "IP-DE-TAILSCALE") + ":" + str(puerto()) + "/api/salud?t=" + clave()
    return ("<!doctype html><html lang=es><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Atajo de salud</title><style>body{font-family:system-ui;max-width:640px;margin:auto;padding:1em;"
            "line-height:1.5}code{background:#8882;padding:2px 5px;border-radius:5px;word-break:break-all}"
            "li{margin:.4em 0}</style><h2>📲 Atajo «Salud a Jarvis»</h2>"
            "<p>Dirección para el paso «Obtener contenido de URL» (tóquela para copiarla):</p>"
            "<p><code onclick='navigator.clipboard.writeText(this.innerText)'>" + url + "</code></p>"
            "<p>Las instrucciones completas se las mandé por el chat. Cuando el atajo funcione, esta página mostrará "
            "sus noches en el panel.</p>"
            "<h3>❤️ Sumar pulso en reposo y oxígeno (opcional)</h3><ol>"
            "<li>Abra el atajo «Salud a Jarvis» y, antes del paso «Combinar Lineas», agregue <b>Buscar muestras de salud</b>: "
            "tipo <b>Frecuencia cardíaca en reposo</b>, «Fecha de inicio» en los últimos 3 días.</li>"
            "<li>Agregue <b>Repetir con cada</b> (los resultados) y dentro un <b>Texto</b>: <code>R|</code> + «Fecha de inicio» + "
            "<code>|</code> + «Valor» de la muestra; luego <b>Agregar a variable</b> «Lineas».</li>"
            "<li>Repita los pasos 1 y 2 con <b>Oxígeno en la sangre</b> usando <code>O|</code> (y si quiere <b>Variabilidad de la "
            "frecuencia cardíaca</b> con <code>V|</code>).</li>"
            "<li>Si la búsqueda no trae nada, Zepp no guarda ese dato en Apple Salud (revíselo en Salud → Explorar): "
            "el panel seguirá mostrando solo el sueño.</li></ol>"
            "<p><a href='/'>← Volver al panel</a></p></html>")


def iniciar():
    """Arranca (o rearranca si cambió la IP de Tailscale) los servidores. Devuelve la dirección o None."""
    ip = ip_tailscale()
    p = puerto()
    clave()
    for host in ["127.0.0.1"] + ([ip] if ip else []):
        if host in _servidores:
            continue
        try:
            srv = ThreadingHTTPServer((host, p), Manejador)
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, daemon=True, name="panel-" + host).start()
            _servidores[host] = srv
            log.info("Panel escuchando en http://%s:%d", host, p)
        except OSError as exc:
            log.warning("No pude abrir el panel en %s:%d: %s", host, p, exc)
    for host in [h for h in _servidores if h not in ("127.0.0.1", ip)]:      # la IP de Tailscale cambió
        _servidores.pop(host).shutdown()
    return direccion() if ip and ip in _servidores else None


if __name__ == "__main__":                       # prueba suelta: python modulos\vida\servidor.py
    import sys
    sys.path.insert(0, str(RAIZ))
    print("Panel:", iniciar() or "sin Tailscale; solo http://127.0.0.1:" + str(puerto()) + "/?t=" + clave())
    print("Ctrl + C para salir")
    while True:
        time.sleep(3600)
