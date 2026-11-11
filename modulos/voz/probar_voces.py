"""Escuche varias voces con el estilo JARVIS y elija una. La eleccion queda en config/voz.json.

Ejecutar:  .\\.venv\\Scripts\\python.exe modulos\\voz\\probar_voces.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modulos.voz import voz  # noqa: E402

FRASE = ("Buenas tardes, señor. Todos los sistemas están en línea. "
         "Su próxima clase es Multimedia a las ocho; ¿desea que prepare Teams?")

VOCES = [
    ("es-ES-AlvaroNeural", "España, grave y formal (la actual)"),
    ("es-MX-JorgeNeural", "México, neutro"),
    ("es-US-AlonsoNeural", "Latino neutro"),
    ("es-CO-GonzaloNeural", "Colombia, suave"),
    ("en-US-AndrewMultilingualNeural", "Multilingüe, cálido (acento leve)"),
    ("en-US-BrianMultilingualNeural", "Multilingüe, sereno (acento leve)"),
    ("fr-FR-RemyMultilingualNeural", "Multilingüe, elegante (acento europeo)"),
    ("it-IT-GiuseppeMultilingualNeural", "Multilingüe, profundo (acento europeo)"),
]


def sonar(texto):
    import sounddevice as sd
    audio, tasa = voz.sintetizar(texto)
    sd.play(audio, tasa)
    sd.wait()


def main():
    print("Escuchará " + str(len(VOCES)) + " voces, todas con el efecto de asistente de IA.\n")
    for n, (nombre, desc) in enumerate(VOCES, 1):
        voz.AJUSTES["voz"] = nombre
        print("%d) %s  -  %s" % (n, desc, nombre))
        try:
            sonar(FRASE)
        except Exception as exc:
            print("   (esta voz no está disponible: " + str(exc)[:60] + ")")
    eleccion = input("\n¿Cuál prefiere? (número, o Enter para no cambiar): ").strip()
    if not eleccion.isdigit() or not 1 <= int(eleccion) <= len(VOCES):
        print("Sin cambios.")
        return
    nombre = VOCES[int(eleccion) - 1][0]
    voz.AJUSTES["voz"] = nombre
    for intensidad in (0.0, 0.4, 0.6, 0.9):
        voz.AJUSTES["efecto"] = "jarvis" if intensidad else "ninguno"
        voz.AJUSTES["intensidad_efecto"] = intensidad
        print("Efecto %s" % ("apagado" if not intensidad else str(intensidad)))
        sonar("Así sonaría con este nivel de efecto, señor.")
    nivel = input("¿Qué nivel de efecto? (0 = sin efecto, 0.4, 0.6, 0.9; Enter = 0.6): ").strip() or "0.6"
    try:
        nivel = float(nivel.replace(",", "."))
    except ValueError:
        nivel = 0.6
    ruta = voz.CONFIG / "voz.json"
    datos = json.loads(ruta.read_text(encoding="utf-8-sig")) if ruta.exists() else {}
    datos.update(voz=nombre, efecto="jarvis" if nivel > 0 else "ninguno", intensidad_efecto=nivel)
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Guardado: " + nombre + ", efecto " + str(nivel) + ". Cierre y vuelva a abrir jarvis-voz.cmd.")


if __name__ == "__main__":
    main()
