"""Modo juego / diseño: detecta si hay un juego o una app de diseño abierta y libera la tarjeta gráfica.

- La lista de programas está en config/modos.json (nombres de proceso, se pueden editar).
- Mientras hay uno abierto: la voz queda en pausa y la IA usa el modelo chico SOLO en el procesador
  (num_gpu = 0, con pocos hilos para no quitarle FPS al juego), así la tarjeta gráfica queda entera.
- Al cerrarlo, espera "segundos_para_volver" (por si solo se reinicia la partida) y vuelve a lo normal.

Uso rápido (para probar):  python modulos\\comun\\modos.py
"""
import json
import sys
import time
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

OLLAMA = "http://127.0.0.1:11434"
_DEFECTO = {"activado": True, "juego": [], "diseno": [], "modelo_liviano": "qwen3.5:2b",
            "segundos_para_volver": 60, "hilos_procesador": 4, "avisar_por_telegram": True}
_estado = {"modo": None, "programa": None, "visto": 0.0, "revisado": 0.0}


def ajustes():
    try:
        datos = json.loads((RAIZ / "config" / "modos.json").read_text(encoding="utf-8-sig"))
        return {**_DEFECTO, **datos}
    except Exception:
        return dict(_DEFECTO)


NOMBRES = {"discovery": "The Finals", "fortniteclient": "Fortnite", "afterfx": "After Effects",
           "blender": "Blender", "figma": "Figma"}


def _bonito(exe):
    base = Path(exe).stem.replace("-Win64-Shipping", "")
    return NOMBRES.get(base.lower().replace("-win64-shipping", ""), base)


def _buscar(cfg):
    """Devuelve ("juego"|"diseno", "Nombre bonito") del primer programa de la lista que esté abierto."""
    import psutil
    juegos = {n.lower(): n for n in cfg["juego"]}
    diseno = {n.lower(): n for n in cfg["diseno"]}
    hallado_diseno = None
    for p in psutil.process_iter(["name"]):
        nombre = (p.info.get("name") or "").lower()
        if nombre in juegos:                       # el juego manda sobre el diseño
            return "juego", _bonito(juegos[nombre])
        if nombre in diseno and not hallado_diseno:
            hallado_diseno = ("diseno", _bonito(diseno[nombre]))
    return hallado_diseno or (None, None)


def modo_actual(cada=5.0):
    """("juego"|"diseno"|None, programa). Revisa los procesos como mucho cada 5 s.
    Al cerrar el programa mantiene el modo 'segundos_para_volver' antes de volver a lo normal."""
    ahora = time.monotonic()
    if ahora - _estado["revisado"] < cada:
        return _estado["modo"], _estado["programa"]
    _estado["revisado"] = ahora
    cfg = ajustes()
    if not cfg["activado"]:
        _estado.update(modo=None, programa=None)
        return None, None
    try:
        modo, programa = _buscar(cfg)
    except Exception:
        return _estado["modo"], _estado["programa"]
    if modo:
        _estado.update(modo=modo, programa=programa, visto=ahora)
    elif _estado["modo"] and ahora - _estado["visto"] > cfg["segundos_para_volver"]:
        _estado.update(modo=None, programa=None)
    return _estado["modo"], _estado["programa"]


def en_modo_ligero():
    return modo_actual()[0] is not None


def modelo_y_opciones(modelo_normal):
    """Qué modelo usar AHORA. En modo juego/diseño: el chico, solo en el procesador."""
    if en_modo_ligero():
        cfg = ajustes()
        return cfg["modelo_liviano"], {"num_gpu": 0, "num_thread": int(cfg["hilos_procesador"]),
                                       "num_ctx": 8192}, "5m"     # 8192: que no se corte la agenda
    return modelo_normal, {}, None


def liberar_tarjeta():
    """Saca de la tarjeta gráfica todos los modelos de Ollama que estén cargados en ella."""
    try:
        cargados = requests.get(OLLAMA + "/api/ps", timeout=5).json().get("models", [])
    except Exception:
        return []
    sacados = []
    for m in cargados:
        if m.get("size_vram", 0) > 0:
            try:
                requests.post(OLLAMA + "/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=15)
                sacados.append(m["name"])
            except Exception:
                pass
    return sacados


def texto_modo(modo, programa):
    return ("🎮 Modo juego" if modo == "juego" else "🎨 Modo diseño") + " (" + programa + ")"


if __name__ == "__main__":
    modo, programa = modo_actual(cada=0)
    if modo:
        print(texto_modo(modo, programa) + ": la voz se pausaría y la IA usaría "
              + ajustes()["modelo_liviano"] + " en el procesador.")
    else:
        print("Modo normal: no hay juegos ni apps de diseño de la lista abiertos.")
    try:
        for m in requests.get(OLLAMA + "/api/ps", timeout=5).json().get("models", []):
            print("  Ollama tiene cargado %s: %.1f GB en tarjeta grafica" % (m["name"], m.get("size_vram", 0) / 1e9))
    except Exception:
        print("  (Ollama no responde)")
