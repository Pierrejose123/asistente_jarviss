"""Prueba de la vigilancia de Ollama (19-11): sin abrir ni cerrar nada real.
    .\\.venv\\Scripts\\python.exe modulos\\comun\\pruebas\\prueba_vigilar_ollama.py
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
CONSOLA = sys.__stdout__

from modulos.comun import vigilar_ollama as V  # noqa: E402

fallos, total = [], 0
V.log = type("SinLog", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})()   # no ensucia logs/ollama.log


def ok(cond, que):
    global total
    total += 1
    if not cond:
        fallos.append(que)


estado = {"responde": True, "procs": [], "ruta": Path("C:/x/ollama app.exe"), "activado": True}
abiertos, cerrados = [], []
V.responde = lambda timeout=3: estado["responde"]
V.procesos = lambda: list(estado["procs"])
V.ruta_app = lambda: estado["ruta"]
V.abrir = lambda r: abiertos.append(r)
V.cerrar = lambda l: cerrados.append(len(l))
V.activado = lambda: estado["activado"]


def reset():
    V.ESTADO.update({"fallos": 0, "ultimo": 0.0, "intentos": [], "aviso_dia": ""})
    abiertos.clear()
    cerrados.clear()


# responde: nada
reset()
ok(V.revisar(1000) is None and not abiertos, "si responde no hace nada")
# apagado: 1.ª revisión espera, 2.ª abre
reset(); estado["responde"] = False
V.revisar(1000)
ok(not abiertos, "una sola falla no abre (puede ser un instante)")
V.revisar(1120)
ok(len(abiertos) == 1, "dos fallas seguidas: abre Ollama")
V.revisar(1240)
ok(len(abiertos) == 1, "no reintenta antes de 10 min")
# vuelve a responder: contador a cero
estado["responde"] = True
V.revisar(1360)
ok(V.ESTADO["fallos"] == 0, "al responder se reinicia el contador")
# proceso abierto arrancando: espera; colgado: cierra y abre
reset(); estado["responde"] = False; estado["procs"] = ["p1", "p2"]
for i in range(3):
    V.revisar(5000 + i * 120)
ok(not abiertos and not cerrados, "proceso abierto: espera mientras arranca")
V.revisar(5000 + 3 * 120)
ok(cerrados == [2] and len(abiertos) == 1, "colgado ~8 min: lo cierra y lo abre")
estado["procs"] = []
# 3 intentos en una hora: un aviso, y solo uno por día
reset()
avisos = [V.revisar(t) for t in (10000, 10120, 10720, 10840, 11440, 11560, 12160, 12280)]
reales = [a for a in avisos if a]
ok(len(abiertos) == 4, "reintenta cada 10 min: %d" % len(abiertos))
ok(len(reales) == 1 and "3 veces" in reales[0], "avisa una sola vez: %s" % reales)
# sin app instalada: avisa una vez
reset(); estado["ruta"] = None
a1, a2 = V.revisar(20000), V.revisar(20120)
ok(a1 is None and a2 and "no encuentro" in a2 and not abiertos, "sin app: avisa y no abre")
V.ESTADO["ultimo"] = 0
ok(V.revisar(21000) is None, "sin app: no repite el aviso el mismo día")
estado["ruta"] = Path("C:/x/ollama app.exe")
# desactivado
reset(); estado["activado"] = False
V.revisar(30000); V.revisar(30120)
ok(not abiertos, "con vigilar_ollama=false no hace nada")

if fallos:
    CONSOLA.write("VIGILAR OLLAMA: FALLOS %d\n" % len(fallos) + "".join(" - %s\n" % f for f in fallos))
    sys.exit(1)
CONSOLA.write("VIGILAR OLLAMA: TODO BIEN %d de %d\n" % (total, total))
