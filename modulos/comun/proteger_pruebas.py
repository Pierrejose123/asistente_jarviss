"""Instala la protección en google_cal.py y base.py (una sola vez) y comprueba que funciona.
Agrega al FINAL de cada archivo un envoltorio que llama a modo_prueba.bloquear(); no cambia nada más."""
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
MARCA = "# --- PROTECCION_PRUEBAS (10-11) ---"
PARCHES = {
    RAIZ / "modulos" / "calendario" / "google_cal.py": '''
%s
# Si la base no es la real (una prueba), Google queda bloqueado. No tocar.
_servicio_real_sin_proteccion = servicio


def servicio(*args, **kwargs):
    from modulos.comun import modo_prueba
    modo_prueba.bloquear("Google Calendar")
    return _servicio_real_sin_proteccion(*args, **kwargs)
''' % MARCA,
    RAIZ / "modulos" / "comun" / "base.py": '''
%s
# Si la base no es la real (una prueba), Telegram queda bloqueado. No tocar.
_enviar_telegram_sin_proteccion = enviar_telegram


def enviar_telegram(*args, **kwargs):
    from modulos.comun import modo_prueba
    modo_prueba.bloquear("Telegram")
    return _enviar_telegram_sin_proteccion(*args, **kwargs)
''' % MARCA,
}
for archivo, parche in PARCHES.items():
    texto = archivo.read_text(encoding="utf-8")
    if MARCA in texto:
        print("Ya protegido:", archivo.name)
        continue
    (archivo.parent / (archivo.name + ".antes_proteccion")).write_text(texto, encoding="utf-8")
    archivo.write_text(texto.rstrip() + "\n\n" + parche, encoding="utf-8")
    print("Protegido:", archivo.name)

# comprobación: con base temporal, Google y Telegram deben negarse
from modulos.comun import db  # noqa: E402
from modulos.comun import base  # noqa: E402
from modulos.calendario import google_cal as gc  # noqa: E402
real = db.ARCHIVO
ok = True
if gc.servicio is None or base.enviar_telegram is None:
    ok = False
db.ARCHIVO = Path(tempfile.mkdtemp()) / "prueba.db"
for nombre, fn in (("Google Calendar", lambda: gc.servicio(interactivo=False)), ("Telegram", lambda: base.enviar_telegram("prueba"))):
    try:
        fn()
        print("❌ FALLA: con base temporal", nombre, "NO se bloqueó")
        ok = False
    except RuntimeError as exc:
        if "Bloqueado" in str(exc):
            print("✅", nombre, "bloqueado en pruebas")
        else:
            print("❌", nombre, ":", exc)
            ok = False
db.ARCHIVO = real
from modulos.comun import modo_prueba  # noqa: E402
print("✅ Con la base real funciona normal" if not modo_prueba.activo() else "❌ La base real se ve como prueba")
print("\nPROTECCIÓN:", "ACTIVA" if ok and not modo_prueba.activo() else "CON PROBLEMAS (avíseme)")
