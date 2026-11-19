"""Prueba de HÁBITOS, SUEÑO y PANEL (Fase 2, 12-11). Base y config TEMPORALES; no usa Google ni Telegram.
El panel se prueba de verdad en 127.0.0.1 con un puerto libre.   python modulos\\vida\\pruebas\\prueba_vida.py"""
import json
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from modulos.comun import db  # noqa: E402
TMP = Path(tempfile.mkdtemp())
db.ARCHIVO = TMP / "prueba.db"                                   # base temporal (bloquea Google y Telegram)
import os  # noqa: E402
os.environ["PANEL_TOKEN"] = "clave-de-prueba"                   # no toca su .env
from modulos.comun.base import ZONA  # noqa: E402
from modulos.vida import habitos_vida as hv, sueno, servidor  # noqa: E402

hv.ARCHIVO = TMP / "vida.json"                                    # config temporal (se crea con los valores por defecto)
AHORA = [datetime(2026, 11, 12, 20, 0, tzinfo=ZONA)]             # jueves
hv.ahora = sueno.ahora = servidor.ahora = lambda: AHORA[0]

bien, mal = 0, []


def ok(cond, que, extra=""):
    global bien
    if cond:
        bien += 1
    else:
        mal.append(que + ("  =>  " + str(extra)[:300] if extra != "" else ""))


def limpiar():
    with hv._con() as con:
        con.execute("DELETE FROM vida_habitos")
        con.execute("DELETE FROM vida_marcas")
    with sueno._con() as con:
        for t in ("sueno_noches", "sueno_manual", "salud_dia", "sueno_consejos"):
            con.execute("DELETE FROM " + t)


# 1) config por defecto
a = hv.ajustes()
ok(hv.ARCHIVO.exists() and a["hora_dormir"] == "22:00", "crea config/vida.json")
ok([h["id"] for h in hv.habitos()] == ["lectura", "agua", "ingles", "practica_ingles"], "hábitos activos (gym y fisio apagados)",
   [h["id"] for h in hv.habitos()])
jueves, miercoles = AHORA[0], AHORA[0] - timedelta(days=1)
ok(hv.toca(hv.habito("ingles"), jueves) and not hv.toca(hv.habito("ingles"), miercoles), "inglés L-M-J")
ok(not hv.toca(hv.habito("fisio"), jueves), "fisio es libre (no se espera)")

# 2) frases de hábitos: (frase, hábito, valor esperado después)
FRASES = [("agua", "agua", 1), ("💧", "agua", 1), ("tomé 2 vasos de agua", "agua", 2), ("me tomé un vaso de agua", "agua", 1),
          ("bebí una botella de agua", "agua", 2), ("+3 agua", "agua", 3), ("tres vasos de agua", "agua", 3),
          ("tomé agua", "agua", 1), ("Jarvis, agua", "agua", 1),
          ("leí", "lectura", 1), ("ya leí 20 minutos", "lectura", 1), ("leí un rato antes de dormir", "lectura", 1),
          ("terminé de leer", "lectura", 1), ("hice mi lectura", "lectura", 1), ("hoy no leí", "lectura", 0),
          ("hice la llamada de inglés", "ingles", 1), ("ya hice la llamada", "ingles", 1), ("tuve la clase de inglés", "ingles", 1),
          ("llamada de inglés hecha", "ingles", 1), ("no hice la llamada de inglés", "ingles", 0),
          ("practiqué inglés con la IA", "practica_ingles", 1), ("hablé en inglés con ChatGPT 15 minutos", "practica_ingles", 1),
          ("practiqué inglés", "practica_ingles", 1),
          ("fui a fisio", "fisio", 1), ("fui a la fisioterapia", "fisio", 1), ("hice los ejercicios de fisio", "fisio", 1),
          ("hice mis ejercicios de rodilla", "fisio", 1),
          ("✅ lectura", "lectura", 1), ("❌ inglés", "ingles", 0), ("✅ fisio", "fisio", 1), ("✅ agua", "agua", 1)]
for frase, hid, esperado in FRASES:
    limpiar()
    r = hv.procesar(frase)
    ok(r is not None and hv.valor(hid) == esperado, "frase: " + frase, (r, hv.valor(hid)))

limpiar()
hv.procesar("agua")
hv.procesar("agua")
r = hv.procesar("quita un vaso de agua")
ok(hv.valor("agua") == 1 and "Lleva 1" in r, "quitar un vaso", r)

# 3) lo que NO es un hábito
NO = ["agua 1.50", "compré agua 2", "leí que Nvidia subió", "leí el informe de XTB y compré", "idea: leer más",
      "recuérdame tomar agua a las 5", "¿cuánta agua debo tomar?", "fui al banco", "el agua está fría", "hice la tarea",
      "decidí leer más", "Juan me debe 50", "mis deudas", "gasté 3 en agua", "llamada con Juan"]
for frase in NO:
    limpiar()
    ok(hv.procesar(frase) is None and sueno.procesar(frase) is None, "no es hábito: " + frase, hv.procesar(frase))

# 4) pendientes, semana y racha
limpiar()
ok([h["id"] for h in hv.pendientes(jueves)] == ["lectura", "ingles"], "pendientes del jueves", hv.pendientes(jueves))
hv.procesar("leí")
ok([h["id"] for h in hv.pendientes(jueves)] == ["ingles"], "tras leer queda inglés")
for i in range(1, 5):
    hv.marcar("lectura", nuevo=1, fecha=jueves - timedelta(days=i))
ok(hv.racha("lectura", jueves) == 5, "racha de lectura 5", hv.racha("lectura", jueves))
hv.marcar("ingles", nuevo=1, fecha=jueves - timedelta(days=3))         # lunes
hv.marcar("ingles", nuevo=1, fecha=jueves - timedelta(days=2))         # martes
ok(hv.racha("ingles", jueves) == 2, "racha inglés no la corta el miércoles (no toca)", hv.racha("ingles", jueves))
s = hv.semana(jueves)
lect = next(h for h in s["habitos"] if h["id"] == "lectura")
ok(lect["celdas"][-5:] == [1, 1, 1, 1, 1], "semana: lectura", lect)
ok("Lectura" in hv.texto_semana(jueves) and "5/7" in hv.texto_semana(jueves), "texto semana", hv.texto_semana(jueves))
ok("Racha de 5" in hv.procesar("leí"), "racha en la confirmación")
ok(hv.procesar("mis hábitos").startswith("📊"), "mis hábitos")

# 5) «me voy a dormir»
limpiar()
AHORA[0] = datetime(2026, 11, 12, 21, 50, tzinfo=ZONA)
ok("antes de su meta" in hv.procesar("me voy a dormir"), "dormir antes de la meta")
AHORA[0] = datetime(2026, 11, 13, 0, 20, tzinfo=ZONA)
r = hv.procesar("buenas noches jarvis")
ok("2 h 20 min después" in r, "dormir tarde (00:20)", r)
with sueno._con() as con:
    ok(con.execute("SELECT noche FROM sueno_manual").fetchall()[0]["noche"] == "2026-11-12", "00:20 cuenta como noche del 12")

# 6) fechas del atajo
F = [("2026-11-12T23:10:00-05:00", (23, 10)), ("2026-11-12 23:10:00 -0500", (23, 10)), ("12 nov 2026, 23:10", (23, 10)),
     ("12 de noviembre de 2026, 23:10", (23, 10)), ("12/11/2026 23:10", (23, 10)), ("Nov 12, 2026 at 11:10 PM", (23, 10)),
     ("12 nov 2026, 11:10 p. m.", (23, 10)), ("2026-11-13T04:10:00Z", (23, 10))]
for t, (hh, mm) in F:
    d = sueno.fecha_de(t)
    ok(d is not None and (d.hour, d.minute) == (hh, mm), "fecha: " + t, d)
ok(sueno.fecha_de("no es fecha") is None, "fecha inválida")
for v, f in [("En cama", "cama"), ("Dormido", "dormido"), ("Núcleo", "ligero"), ("Básico", "ligero"), ("Profundo", "profundo"),
             ("REM", "rem"), ("Despierto", "despierto"), ("Asleep (Core)", "ligero"), ("Deep", "profundo"), ("3", "ligero"),
             ("Sin especificar", "dormido")]:
    ok(sueno.fase_de(v) == f, "fase: " + v, sueno.fase_de(v))


# 7) ingestar una semana de sueño (como la mandaría el atajo, con fases)
def noche(dia, dormir, despertar, profundo_min=70, rem_min=90, despierto_min=10):
    """Arma las líneas S| de una noche: dormir y despertar son datetime."""
    lineas = ["S|" + (dormir - timedelta(minutes=15)).isoformat() + "|" + despertar.isoformat() + "|En cama"]
    t = dormir
    bloques = [("Núcleo", 60), ("Profundo", profundo_min // 2), ("Núcleo", 60), ("REM", rem_min // 2),
               ("Despierto", despierto_min), ("Profundo", profundo_min - profundo_min // 2), ("REM", rem_min - rem_min // 2)]
    for fase, m in bloques:
        lineas.append("S|" + t.isoformat() + "|" + (t + timedelta(minutes=m)).isoformat() + "|" + fase)
        t += timedelta(minutes=m)
    lineas.append("S|" + t.isoformat() + "|" + despertar.isoformat() + "|Núcleo")
    return lineas


limpiar()
base = datetime(2026, 11, 5, 0, 0, tzinfo=ZONA)
lineas = []
horas = [(23, 30), (23, 45), (0, 15), (23, 10), (1, 30), (1, 0), (21, 50)]      # jue … mié noche
for i, (h, m) in enumerate(horas):
    d0 = base + timedelta(days=i)
    dormir = (d0 + timedelta(days=1 if h < 12 else 0)).replace(hour=h, minute=m)
    despertar = (d0 + timedelta(days=1)).replace(hour=6, minute=30)
    lineas += noche(d0, dormir, despertar)
    lineas.append("P|" + (d0 + timedelta(days=1)).date().isoformat() + "|" + str(6000 + i * 500))
    lineas.append("R|" + (d0 + timedelta(days=1)).date().isoformat() + "|58")
lineas.append("S|" + base.replace(hour=15).isoformat() + "|" + base.replace(hour=15, minute=40).isoformat() + "|Dormido")  # siesta
lineas.append("O|2026-11-12|0.97")
lineas.append("basura sin formato")
texto = "\n".join(lineas)
r = sueno.ingestar(texto)
ok(r["noches"] == 7 and r["dias"] == 7 and r["ignoradas"] == 1, "ingestar 7 noches", r)
AHORA[0] = datetime(2026, 11, 12, 7, 0, tzinfo=ZONA)
lista = sueno.noches(7)
ok(len(lista) == 7 and lista[-1]["fecha"] == "2026-11-12", "noches con fecha de despertar", [n["fecha"] for n in lista])
n = lista[-1]
ok("T21:50" in n["dormir"] and n["profundo"] == 70 and n["rem"] == 90 and n["despierto"] == 10, "fases de la noche", n)
ok(sueno.ingestar(texto)["noches"] == 7 and len(sueno.noches(7)) == 7, "reenviar no duplica")
ok(sueno.salud(7)[-1]["spo2"] == 97 and sueno.salud(7)[-1]["pasos"] == 9000, "salud del día", sueno.salud(7)[-1])

r = sueno.analisis(7)
ok(r["noches"] == 7 and r["en_meta"] == 1, "análisis: 1 noche en meta", r)
claves = [c for c, _ in r["consejos"]]
ok(claves[0] == "gradual", "primer consejo: adelantar de a poco", claves)
ok("constancia" in claves or "finde" in claves, "consejo de constancia o fin de semana", claves)
lm = sueno.linea_manana()
ok(lm and "21:50" in lm and "✅ En su meta" in lm and "💡" in lm, "línea de la mañana", lm)
AHORA[0] = datetime(2026, 11, 13, 7, 0, tzinfo=ZONA)
with sueno._con() as con:
    con.execute("INSERT OR REPLACE INTO sueno_noches (fecha, dormir, despertar, total, profundo, rem, ligero, despierto) "
                "VALUES ('2026-11-13', '2026-11-12T23:40', '2026-11-13T06:30', 400, 40, 80, 280, 20)")
lm2 = sueno.linea_manana()
ok(lm2 and "+1 h 40 min" in lm2, "línea mañana tarde", lm2)
ok(lm.split("💡")[1] != lm2.split("💡")[1], "no repite el consejo de ayer", (lm, lm2))
inf = sueno.informe_semanal()
ok(inf and "noches" in inf and "Para la próxima semana" in inf, "informe semanal", inf)
ok(sueno.procesar("cómo dormí") and "Sus últimas noches" in sueno.procesar("cómo dormí"), "cómo dormí")

# relación hábito ↔ sueño: las noches tras leer duerme más
limpiar()
AHORA[0] = datetime(2026, 11, 30, 8, 0, tzinfo=ZONA)
with sueno._con() as con:
    for i in range(14):
        dia = datetime(2026, 11, 17, tzinfo=ZONA) + timedelta(days=i)
        leyo = i % 2 == 0
        total = 460 if leyo else 400
        con.execute("INSERT INTO sueno_noches (fecha, dormir, despertar, total, profundo, rem, ligero, despierto) VALUES "
                    "(?, ?, ?, ?, 80, 90, ?, 10)", (dia.date().isoformat(), (dia - timedelta(hours=2)).isoformat()[:16],
                                                    dia.replace(hour=6).isoformat()[:16], total, total - 170))
for i in range(0, 14, 2):
    hv.marcar("lectura", nuevo=1, fecha=datetime(2026, 11, 17, tzinfo=ZONA) + timedelta(days=i - 1))
r = sueno.analisis(14)
rel = [x for x in r["relaciones"] if x["id"] == "lectura"]
ok(rel and rel[0]["diferencia"] == 60, "relación lectura → +60 min", r["relaciones"])
ok(any(c == "rel_lectura" for c, _ in r["consejos"]), "consejo de la lectura", r["consejos"])

# 8) PANEL de verdad en 127.0.0.1
limpiar()
AHORA[0] = datetime(2026, 11, 12, 20, 0, tzinfo=ZONA)
libre = socket.socket()
libre.bind(("127.0.0.1", 0))
PUERTO = libre.getsockname()[1]
libre.close()
datos_cfg = hv.ajustes()
datos_cfg["puerto_panel"] = PUERTO
hv.ARCHIVO.write_text(json.dumps(datos_cfg), encoding="utf-8")
servidor.ip_tailscale = lambda: None                              # sin Tailscale en la prueba: solo 127.0.0.1
servidor.iniciar()
URL = "http://127.0.0.1:" + str(PUERTO)


def pedir(ruta, datos=None, tipo="application/json", cookie=None):
    req = urllib.request.Request(URL + ruta, data=datos, method="POST" if datos is not None else "GET")
    if datos is not None:
        req.add_header("Content-Type", tipo)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8"), e.headers


c, cuerpo, _ = pedir("/")
ok(c == 403 and "Panel privado" in cuerpo, "sin clave: 403")
c, cuerpo, h = pedir("/?t=mala")
ok(c == 403, "clave mala: 403")
c, cuerpo, h = pedir("/?t=clave-de-prueba")
ok(c == 200 and "Mi vida" in cuerpo and "panel=clave-de-prueba" in (h.get("Set-Cookie") or ""), "con clave: panel y cookie")
COOKIE = "panel=clave-de-prueba"
c, cuerpo, _ = pedir("/api/datos", cookie=COOKIE)
d = json.loads(cuerpo) if c == 200 else {}
ok(c == 200 and d.get("hoy") and len(d["hoy"]["habitos"]) == 4, "api/datos con cookie", cuerpo[:300])
ok(all(k in d for k in ("agenda", "recordatorios", "ingles", "bolsa", "sistema")), "panel 2: secciones nuevas en los datos")
ok(d.get("sueno") is not None and d.get("negocio") is not None and d.get("semana") is not None, "secciones del panel",
   {k: (v is not None) for k, v in d.items()})
c, cuerpo, _ = pedir("/api/datos")
ok(c == 403, "api/datos sin cookie: 403")
c, cuerpo, _ = pedir("/api/habito", json.dumps({"habito": "lectura", "accion": "si"}).encode(), cookie=COOKIE)
ok(c == 200 and hv.valor("lectura") == 1, "marcar lectura desde el panel", cuerpo[:200])
pedir("/api/habito", json.dumps({"habito": "agua", "accion": "mas"}).encode(), cookie=COOKIE)
pedir("/api/habito", json.dumps({"habito": "agua", "accion": "mas"}).encode(), cookie=COOKIE)
ok(hv.valor("agua") == 2, "agua +2 desde el panel", hv.valor("agua"))
c, _, _ = pedir("/api/habito", json.dumps({"habito": "nada", "accion": "si"}).encode(), cookie=COOKIE)
ok(c == 400, "hábito desconocido: 400")
# salud desde el atajo: texto, formulario y JSON
uno = "\n".join(noche(None, datetime(2026, 11, 11, 22, 0, tzinfo=ZONA), datetime(2026, 11, 12, 6, 0, tzinfo=ZONA)))
c, cuerpo, _ = pedir("/api/salud?t=clave-de-prueba", uno.encode(), "text/plain")
ok(c == 200 and "1 noches" in cuerpo, "salud como texto", cuerpo)
from urllib.parse import urlencode  # noqa: E402
c, cuerpo, _ = pedir("/api/salud?t=clave-de-prueba", urlencode({"datos": "P|2026-11-12|8000"}).encode(),
                     "application/x-www-form-urlencoded")
ok(c == 200 and "1 días" in cuerpo, "salud como formulario", cuerpo)
c, cuerpo, _ = pedir("/api/salud?t=clave-de-prueba", json.dumps({"datos": "R|2026-11-12|55"}).encode(), "application/json")
ok(c == 200 and sueno.salud(1)[-1]["pulso_reposo"] == 55 and sueno.salud(1)[-1]["pasos"] == 8000, "salud como JSON", cuerpo)
multi = ("--XyZ\r\nContent-Disposition: form-data; name=\"datos\"\r\n\r\nV|2026-11-12|48\r\n--XyZ--\r\n")
c, cuerpo, _ = pedir("/api/salud?t=clave-de-prueba", multi.encode(), "multipart/form-data; boundary=XyZ")
ok(c == 200 and sueno.salud(1)[-1]["vfc"] == 48, "salud como multipart", cuerpo)
c, cuerpo, _ = pedir("/api/salud", b"P|2026-11-12|1", "text/plain")
ok(c == 403, "salud sin clave: 403")
AHORA[0] = datetime(2026, 11, 12, 21, 47, tzinfo=ZONA)
c, cuerpo, _ = pedir("/api/salud?t=clave-de-prueba", b"D", "text/plain")
ok(c == 200 and "21:47" in cuerpo and "antes de su meta" in cuerpo, "modo Dormir: «D» = ahora", cuerpo)
c, cuerpo, _ = pedir("/api/salud?t=clave-de-prueba", "D|12 nov 2026, 23:05".encode(), "text/plain")
ok(c == 200 and "23:05" in cuerpo and "después de su meta" in cuerpo, "modo Dormir con hora", cuerpo)
with sueno._con() as con:
    ok(con.execute("SELECT hora FROM sueno_manual WHERE noche = '2026-11-12'").fetchone()["hora"].startswith("2026-11-12T23:05"),
       "hora de dormir guardada")
c, cuerpo, _ = pedir("/atajo", cookie=COOKIE)
ok(c == 200 and "/api/salud?t=clave-de-prueba" in cuerpo, "página del atajo")

print("VIDA:", bien + len(mal), "| BIEN:", bien, "| MAL:", len(mal))
for m in mal:
    print("  MAL:", m)
