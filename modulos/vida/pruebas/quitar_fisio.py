"""Apaga el hábito de fisioterapia en config/vida.json (no borra lo ya marcado). Copia: config/vida.json.antes_panel2.
python modulos\\vida\\pruebas\\quitar_fisio.py"""
import json
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
archivo = Path(__file__).resolve().parents[3] / "config" / "vida.json"
if not archivo.exists():
    print("No hay config/vida.json (se creará sola, ya sin fisio).")
    sys.exit()
datos = json.loads(archivo.read_text(encoding="utf-8-sig"))
cambio = False
for h in datos.get("habitos", []):
    if h.get("id") == "fisio" and h.get("activo", True):
        h["activo"] = False
        cambio = True
if cambio:
    if not archivo.with_name("vida.json.antes_panel2").exists():
        shutil.copy2(archivo, archivo.with_name("vida.json.antes_panel2"))
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Fisioterapia quitada de los hábitos.")
else:
    print("Fisioterapia ya estaba apagada.")
