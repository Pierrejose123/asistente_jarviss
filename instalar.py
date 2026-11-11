"""Primera instalación del asistente JARVIS en su PC (Windows).

    python instalar.py

Qué hace (no borra nada):
  1. Revisa la versión de Python.
  2. Crea su .env a partir de .env.example y le pregunta su nombre y su token de Telegram.
  3. Copia cada config\\*.ejemplo.json a config\\*.json (solo los que aún no existen).
  4. Crea las carpetas locales (datos, logs y la carpeta «pesado» de config\\rutas.json).
  5. Le dice los siguientes pasos.
"""
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def poner_en_env(env, clave, valor):
    lineas = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    lineas = [l for l in lineas if not l.startswith(clave + "=")] + [clave + "=" + valor]
    env.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main():
    print("== Instalación del asistente ==\n")
    if sys.version_info < (3, 11):
        sys.exit("Necesita Python 3.11 o más nuevo (tiene " + sys.version.split()[0] + ").")
    print("[OK] Python " + sys.version.split()[0])

    env = RAIZ / ".env"
    if not env.exists():
        shutil.copy(RAIZ / ".env.example", env)
        nombre = input("¿Cómo se llama? (así le hablará el asistente): ").strip()
        if nombre:
            poner_en_env(env, "NOMBRE_USUARIO", nombre)
        token = input("Token de su bot de Telegram (de @BotFather; Enter para ponerlo después): ").strip()
        if token:
            poner_en_env(env, "TELEGRAM_BOT_TOKEN", token)
        print("[OK] Creado .env (ábralo con el Bloc de notas para revisar o completar)")
    else:
        print("[OK] Ya tiene .env (no lo toco)")

    copiados = []
    for ejemplo in sorted((RAIZ / "config").glob("*.ejemplo.json")):
        real = ejemplo.with_name(ejemplo.name.replace(".ejemplo.json", ".json"))
        if not real.exists():
            shutil.copy(ejemplo, real)
            copiados.append(real.name)
    print("[OK] Configuración: " + (", ".join(copiados) if copiados else "ya estaba toda"))

    sys.path.insert(0, str(RAIZ))
    from modulos.comun.base import PESADO
    for carpeta in (RAIZ / "datos", RAIZ / "logs", PESADO, PESADO / "respaldos"):
        carpeta.mkdir(parents=True, exist_ok=True)
    print("[OK] Carpetas listas (archivos pesados en " + str(PESADO) + ")")

    print("""
Siguientes pasos:
  1. Instale las librerías:            .venv\\Scripts\\python.exe -m pip install -r requirements.txt
  2. Instale Ollama (https://ollama.com) y los modelos:
         ollama pull qwen3.5:9b
         ollama pull qwen3.5:2b
         ollama pull nomic-embed-text
  3. Conecte Telegram (escriba algo a su bot y luego):
         .venv\\Scripts\\python.exe modulos\\telegram\\obtener_user_id.py
  4. Google Calendar y Gmail (opcional): vea «Google» en el README.
  5. Revise que todo esté listo:       .venv\\Scripts\\python.exe modulos\\comun\\revisar_entorno.py
  6. Arranque el asistente:            .venv\\Scripts\\python.exe modulos\\comun\\control.py iniciar
""")


if __name__ == "__main__":
    main()
