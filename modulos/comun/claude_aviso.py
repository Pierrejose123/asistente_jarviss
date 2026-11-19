"""Lo llama claude_ejecutar.cmd al terminar: avisa por Telegram con un resumen corto (sin montos).
    python modulos\\comun\\claude_aviso.py
"""
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

CLAVE = re.compile(r"TODO BIEN|FALLOS|FALLA|Error|Traceback|Casos:|Listo|actualizado", re.I)


def resumen(texto, maximo=8):
    lineas = [l.strip() for l in texto.splitlines() if CLAVE.search(l) and " INFO " not in l]
    return [re.sub(r"\$\s?[\d.,]+", "$…", l)[:160] for l in lineas[:maximo]]


def main():
    salida = RAIZ / "para_claude_salida.txt"
    texto = salida.read_text(encoding="utf-8", errors="replace") if salida.exists() else ""
    puntos = resumen(texto)
    mensaje = ("✅ Terminó lo que preparó Claude.\n" + ("\n".join("• " + p for p in puntos) if puntos else "") +
               "\n\nDígale «listo» a Claude para que revise el resultado.")
    from modulos.comun.base import enviar_telegram
    enviar_telegram(mensaje)


if __name__ == "__main__":
    main()
