"""Prepara el CSV o Excel (.xlsx) de XTB: guarda el ORIGINAL en la carpeta privada (rutas.json → pesado\\xtb) (privado) y crea una COPIA
con todos los montos, cantidades, precios e IDs cambiados por numeros al azar, para enviarla a Claude.

- Las fechas y horas NO se cambian (no son sensibles y sirven para entender el formato).
- Los simbolos (KOF.US, O.US...) y los nombres de columnas quedan igual.
- Los dividendos por accion ("1.0433/ SHR") se dejan: son datos publicos de la empresa.

Uso:  python modulos\\portafolio\\anonimizar_xtb.py RUTA\\AL\\ARCHIVO.csv   (o .xlsx)
"""
import random
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from modulos.comun.base import PESADO  # noqa: E402

PRIVADO = PESADO / "xtb"
DESCARGAS = Path.home() / "Downloads"

# Un numero suelto (no parte de una fecha 23.10.2026 / 2026-10-23, una hora 05:08, ni "1.04/ SHR")
NUMERO = re.compile(r"(?<![\d.,:/\-\w])(-?)(\d+)([.,]\d+)?(?![\d.,:/\-]|\w)")
POR_ACCION = re.compile(r"\d+(?:[.,]\d+)?\s*/\s*SHR", re.I)


def _cambiar(m):
    signo, entero, decimales = m.group(1), m.group(2), m.group(3) or ""
    if len(entero) >= 6 and not decimales:                 # ID de operacion: mismos digitos, al azar
        return signo + str(random.randint(10 ** (len(entero) - 1), 10 ** len(entero) - 1))
    valor = float(entero + decimales.replace(",", ".")) * random.uniform(0.3, 1.7)
    sep = decimales[:1] or "."
    if decimales:
        texto = ("%." + str(len(decimales) - 1) + "f") % valor
    else:
        texto = str(max(1, round(valor)))
    return signo + texto.replace(".", sep)


def anonimizar_linea(linea):
    protegidos = {}

    def guardar(m):                                          # protege "1.0433/ SHR"
        clave = "\x00" + "QWERTYUIOPASDFGHJKLZ"[len(protegidos) % 20] * (len(protegidos) // 20 + 1) + "\x00"
        protegidos[clave] = m.group()
        return clave

    linea = POR_ACCION.sub(guardar, linea)
    linea = NUMERO.sub(_cambiar, linea)
    for clave, texto in protegidos.items():
        linea = linea.replace(clave, texto)
    return linea


ETIQUETA_PERSONAL = re.compile(r"^\s*(name|nombre|cliente|client|titular|owner|e-?mail|correo|address|direcci[oó]n)\b", re.I)


def ocultar_personal(texto):
    """'Name: el usuario ...' -> 'Name: OCULTO'."""
    m = ETIQUETA_PERSONAL.match(texto)
    return (m.group(1) + ": OCULTO") if m else texto


def _numero_al_azar(valor):
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, int) and abs(valor) >= 100000:         # ID
        return random.randint(10 ** (len(str(abs(valor))) - 1), 10 ** len(str(abs(valor))) - 1)
    nuevo = valor * random.uniform(0.3, 1.7)
    return round(nuevo) if isinstance(valor, int) else round(nuevo, 2)


def anonimizar_excel(origen, copia):
    """Cambia numeros y textos con numeros en TODAS las hojas; las fechas (celdas de fecha) quedan igual."""
    from datetime import date as _date, datetime as _dt, time as _time
    import openpyxl
    libro = openpyxl.load_workbook(origen)
    filas = 0
    for hoja in libro.worksheets:
        for fila in hoja.iter_rows():
            filas += 1
            anterior = None
            for celda in fila:
                v = celda.value
                if isinstance(anterior, str) and ETIQUETA_PERSONAL.match(anterior) and v is not None \
                        and not ETIQUETA_PERSONAL.match(str(v)) and len(anterior.strip()) < 25 and ":" not in anterior[:-1]:
                    celda.value, anterior = "OCULTO", v      # celda al lado de "Nombre"
                    continue
                anterior = v
                if v is None or isinstance(v, (_dt, _date, _time)):
                    continue
                if isinstance(v, (int, float)):
                    if celda.is_date:
                        continue
                    celda.value = _numero_al_azar(v)
                elif isinstance(v, str) and not v.startswith("="):
                    celda.value = anonimizar_linea(ocultar_personal(v))
    libro.save(copia)
    return filas


def vista_excel(ruta):
    import openpyxl
    libro = openpyxl.load_workbook(ruta, read_only=True)
    lineas = []
    for hoja in libro.worksheets:
        lineas.append("[hoja " + hoja.title + "]")
        for fila in hoja.iter_rows(max_row=6, values_only=True):
            lineas.append(" | ".join("" if v is None else str(v) for v in fila))
    return lineas


def leer(ruta):
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return ruta.read_text(encoding=cod), cod
        except UnicodeDecodeError:
            continue
    raise SystemExit("No pude leer el archivo.")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python anonimizar_xtb.py ARCHIVO.csv")
    origen = Path(sys.argv[1])
    if not origen.exists():
        raise SystemExit("No existe: " + str(origen))
    excel = origen.suffix.lower() in (".xlsx", ".xlsm")
    if not excel:
        texto, cod = leer(origen)

    PRIVADO.mkdir(parents=True, exist_ok=True)
    sello = datetime.now().strftime("%Y-%m-%d_%H%M")
    privado = PRIVADO / ("xtb_operaciones_" + sello + origen.suffix.lower())
    shutil.copy2(origen, privado)

    copia = DESCARGAS / ("xtb_EJEMPLO_anonimo" + origen.suffix.lower())
    if excel:
        n = anonimizar_excel(origen, copia)
        vista, cod = vista_excel(copia), "excel"
    else:
        lineas = texto.splitlines()
        copia.write_text("\n".join(anonimizar_linea(";".join(ocultar_personal(x) for x in l.split(";")))
                                   for l in lineas) + "\n", encoding="utf-8")
        n, vista = len(lineas), copia.read_text(encoding="utf-8").splitlines()[:8]

    origen.unlink()                                          # el original ya no queda en Descargas
    print("ORIGINAL (privado, no lo envie):", privado)
    print("COPIA ANONIMA para enviar a Claude:", copia)
    print("Filas:", n, "| formato:", cod)
    print("\nAsi quedo el comienzo de la copia (revise que no haya su nombre ni su numero de cuenta):\n")
    for l in vista:
        print("  " + l[:160])


if __name__ == "__main__":
    main()
