"""Fase 2, paso 1: compara modelos de Ollama en velocidad y en "entender ordenes" (tool calling).

Uso:  .\\.venv\\Scripts\\python.exe modulos\\comun\\probar_modelo.py qwen3.5:2b qwen3.5:9b
"""
import json
import sys
import time

import requests

OLLAMA = "http://127.0.0.1:11434"

HERRAMIENTAS = [
    {"type": "function", "function": {
        "name": "crear_tarea", "description": "Anota una tarea o deber con fecha de entrega.",
        "parameters": {"type": "object", "properties": {
            "materia": {"type": "string", "description": "Materia, o 'General'"},
            "descripcion": {"type": "string"},
            "fecha": {"type": "string", "description": "hoy, manana, lunes..domingo o DD/MM"}},
            "required": ["descripcion", "fecha"]}}},
    {"type": "function", "function": {
        "name": "ver_dia", "description": "Muestra clases, tareas y avisos de un dia.",
        "parameters": {"type": "object", "properties": {
            "fecha": {"type": "string", "description": "hoy, manana, lunes..domingo o DD/MM"}},
            "required": ["fecha"]}}},
    {"type": "function", "function": {
        "name": "marcar_hecha", "description": "Marca como terminada una tarea por su numero.",
        "parameters": {"type": "object", "properties": {"numero": {"type": "integer"}},
                       "required": ["numero"]}}},
]

PRUEBAS = [
    ("anota que tengo que entregar el afiche de grafica digital el viernes", "crear_tarea"),
    ("que tengo manana?", "ver_dia"),
    ("ya termine la tarea 3", "marcar_hecha"),
    ("recuerdame comprar pinceles el lunes", "crear_tarea"),
    ("cual es la diferencia entre RGB y CMYK?", None),
]

SISTEMA = ("Eres JARVIS, asistente personal del usuario. Responde en espanol, breve. "
           "Usa una herramienta solo si la peticion lo requiere; si es una pregunta general, responde tu.")


def chat(modelo, mensajes, herramientas=None, stream=False):
    cuerpo = {"model": modelo, "messages": mensajes, "stream": stream, "think": False,
              "keep_alive": "10m", "options": {"num_predict": 200}}
    if herramientas:
        cuerpo["tools"] = herramientas
    r = requests.post(OLLAMA + "/api/chat", json=cuerpo, stream=stream, timeout=300)
    if r.status_code == 400 and "think" in r.text:
        cuerpo.pop("think")
        r = requests.post(OLLAMA + "/api/chat", json=cuerpo, stream=stream, timeout=300)
    r.raise_for_status()
    return r


def velocidad(modelo):
    chat(modelo, [{"role": "user", "content": "hola"}])          # cargar en memoria
    t0 = time.time()
    r = chat(modelo, [{"role": "system", "content": SISTEMA},
                      {"role": "user", "content": "Explicame en tres frases que es la tipografia."}], stream=True)
    primero, fin = None, None
    for linea in r.iter_lines():
        if not linea:
            continue
        d = json.loads(linea)
        if primero is None and (d.get("message") or {}).get("content"):
            primero = time.time() - t0
        if d.get("done"):
            fin = d
            break
    tps = fin["eval_count"] / (fin["eval_duration"] / 1e9) if fin and fin.get("eval_duration") else 0
    return primero or 0, tps


def ordenes(modelo):
    aciertos, detalle = 0, []
    for texto, esperado in PRUEBAS:
        t0 = time.time()
        msg = chat(modelo, [{"role": "system", "content": SISTEMA}, {"role": "user", "content": texto}],
                   HERRAMIENTAS).json()["message"]
        llamadas = msg.get("tool_calls") or []
        usada = llamadas[0]["function"]["name"] if llamadas else None
        ok = usada == esperado
        aciertos += ok
        args = json.dumps(llamadas[0]["function"].get("arguments", {}), ensure_ascii=False) if llamadas else ""
        detalle.append(("OK " if ok else "MAL") + "  %-55s -> %s %s (%.1fs)" % (texto[:55], usada or "(responde)", args, time.time() - t0))
    return aciertos, detalle


def main():
    modelos = sys.argv[1:] or ["qwen3.5:2b"]
    instalados = [m["name"] for m in requests.get(OLLAMA + "/api/tags", timeout=10).json()["models"]]
    for modelo in modelos:
        print("\n=== " + modelo + " ===")
        if modelo not in instalados:
            print("No esta descargado. Ejecuta primero:  ollama pull " + modelo)
            continue
        primero, tps = velocidad(modelo)
        print("Primera palabra en %.2f s  |  %.0f palabras-token por segundo" % (primero, tps))
        aciertos, detalle = ordenes(modelo)
        print("\n".join(detalle))
        print("Entendio %d de %d ordenes" % (aciertos, len(PRUEBAS)))


if __name__ == "__main__":
    main()
