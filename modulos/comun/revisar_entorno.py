"""Revisa que el entorno del asistente este listo (Fase 0)."""
import importlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ok = True


def linea(bien, texto):
    global ok
    ok = ok and bien
    print(("[OK]   " if bien else "[FALLA] ") + texto)


linea(sys.version_info >= (3, 10), "Python " + sys.version.split()[0])
linea(".venv" in sys.prefix, "Usando el entorno del proyecto (.venv)")

for modulo in ["dotenv", "requests", "telegram", "apscheduler", "googleapiclient",
               "google_auth_oauthlib", "winotify", "psutil"]:
    try:
        importlib.import_module(modulo)
        linea(True, "Libreria " + modulo)
    except Exception as exc:
        linea(False, "Libreria " + modulo + ": " + str(exc)[:80])

rutas = json.loads((RAIZ / "config" / "rutas.json").read_text(encoding="utf-8-sig"))
for nombre in ["proyecto", "pesado", "respaldos"]:
    carpeta = Path(rutas.get(nombre, "."))
    carpeta = carpeta if carpeta.is_absolute() else RAIZ / carpeta
    linea(carpeta.exists(), "Carpeta " + nombre + ": " + str(carpeta))

try:
    import requests
    modelos = requests.get("http://127.0.0.1:11434/api/tags", timeout=5).json()["models"]
    linea(True, "Ollama responde. Modelos: " + ", ".join(m["name"] for m in modelos))
    r = requests.post("http://127.0.0.1:11434/api/chat", timeout=120, json={
        "model": modelos[0]["name"], "stream": False,
        "messages": [{"role": "user", "content": "Responde solo: listo"}]})
    linea(r.status_code == 200, "El modelo responde: " + r.json().get("message", {}).get("content", "").strip()[:40])
except Exception as exc:
    linea(False, "Ollama no responde (abre la app de Ollama): " + str(exc)[:80])

print()
print("TODO LISTO" if ok else "Hay cosas por revisar (ver [FALLA])")
