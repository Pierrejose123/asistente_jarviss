"""Guarda el vinculo de Teams de una clase en config/horario_clases.json.

Ejecutar:  .\\.venv\\Scripts\\python.exe modulos\\clases\\guardar_enlace.py
"""
import json
from pathlib import Path

ARCHIVO = Path(__file__).resolve().parents[2] / "config" / "horario_clases.json"
horario = json.loads(ARCHIVO.read_text(encoding="utf-8-sig"))
clases = horario["clases"]

print("Clases:")
for i, c in enumerate(clases, 1):
    marca = "  (ya tiene vinculo)" if c.get("enlace") else ""
    print("  " + str(i) + ") " + c["dia"].capitalize() + " " + c["inicio"] + "  " + c["materia"] + marca)

eleccion = input("Numero de la clase: ").strip()
if not eleccion.isdigit() or not 1 <= int(eleccion) <= len(clases):
    raise SystemExit("Numero no valido. No se guardo nada.")
clase = clases[int(eleccion) - 1]

enlace = input("Pega el vinculo de Teams (clic derecho para pegar) y Enter: ").strip()
if not enlace.startswith("http"):
    raise SystemExit("Eso no parece un vinculo. No se guardo nada.")
if "teams.microsoft.com" not in enlace and "teams.live.com" not in enlace:
    if input("No parece un vinculo de Teams. Guardar igual? (s/n): ").strip().lower() != "s":
        raise SystemExit("No se guardo nada.")

clase["enlace"] = enlace
horario.setdefault("apertura_clase", {})["orden"] = ["enlace_teams", "calendario_teams", "ruedge"]
ARCHIVO.write_text(json.dumps(horario, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Guardado el vinculo de " + clase["materia"] + ".")