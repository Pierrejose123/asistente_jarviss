"""
Respaldo automatico del asistente.

Guarda en la carpeta de respaldos (rutas.json → pesado\\respaldos) un .zip con:
  - las bases de datos de datos\\ (copiadas en caliente con la API de SQLite,
    asi no importa que el bot este escribiendo en ese momento)
  - config\\, credenciales\\, el resto de datos\\ y el archivo .env
Comprueba que la copia de la base este sana y que el zip se pueda leer.
Conserva los ultimos 30 respaldos y borra los mas viejos.
Si algo falla, avisa por Telegram.

Uso:
  python modulos\\comun\\respaldo.py            -> respalda si hoy aun no hay respaldo
  python modulos\\comun\\respaldo.py --forzar   -> respalda aunque ya haya uno de hoy
  python modulos\\comun\\respaldo.py --lista    -> muestra los respaldos guardados
"""
import argparse
import datetime as dt
import logging
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # carpeta del proyecto
sys.path.insert(0, str(RAIZ))

from modulos.comun.base import PESADO  # noqa: E402

DESTINO = PESADO / "respaldos"
GUARDAR = 30                                        # cuantos respaldos conservar
ESPACIO_MINIMO = 1024 ** 3                          # 1 GB libre en el disco de respaldos
CARPETAS = ["config", "credenciales", "datos"]
ARCHIVOS = [".env"]
EXT_BD = {".db", ".sqlite", ".sqlite3"}
IGNORAR = ("-wal", "-shm", "-journal")              # archivos temporales de SQLite

# ---------- registro ----------
(RAIZ / "logs").mkdir(exist_ok=True)
log = logging.getLogger("respaldo")
log.setLevel(logging.INFO)
_f = logging.FileHandler(RAIZ / "logs" / "respaldo.log", encoding="utf-8")
_f.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_f)
if sys.stdout is not None:                          # con pythonw no hay consola
    log.addHandler(logging.StreamHandler(sys.stdout))


def avisar(texto: str) -> None:
    """Manda un mensaje por Telegram; si no se puede, solo lo anota."""
    try:
        from modulos.comun.base import enviar_telegram
        enviar_telegram(texto)
    except Exception as e:
        log.warning("No se pudo avisar por Telegram: %s", e)


def tamano_legible(n: float) -> str:
    for unidad in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unidad}"
        n /= 1024
    return f"{n:.1f} TB"


def copiar_bd(origen: Path, destino: Path) -> None:
    """Copia una base SQLite en caliente y verifica que la copia este sana."""
    fuente = sqlite3.connect(origen, timeout=30)
    copia = sqlite3.connect(destino)
    try:
        fuente.backup(copia)
        estado = copia.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        fuente.close()
        copia.close()
    if estado != "ok":
        raise RuntimeError(f"La copia de {origen.name} no paso la revision: {estado}")


def respaldos_guardados() -> list[Path]:
    # El nombre lleva fecha y hora, asi que ordenar por nombre = ordenar por fecha
    return sorted(DESTINO.glob("respaldo_*.zip"))


def ya_hay_de_hoy() -> bool:
    hoy = dt.date.today().strftime("%Y-%m-%d")
    return any(DESTINO.glob(f"respaldo_{hoy}_*.zip"))


def hacer_respaldo() -> tuple[Path, int, int]:
    if not Path(DESTINO.anchor).exists():
        raise RuntimeError("El disco " + DESTINO.anchor + " no esta disponible")
    DESTINO.mkdir(parents=True, exist_ok=True)
    libre = shutil.disk_usage(DESTINO).free
    if libre < ESPACIO_MINIMO:
        raise RuntimeError(f"Queda poco espacio en I: ({tamano_legible(libre)})")

    for viejo in DESTINO.glob("*.parcial"):         # restos de un intento cortado
        viejo.unlink(missing_ok=True)

    nombre = f"respaldo_{dt.datetime.now():%Y-%m-%d_%H%M}.zip"
    parcial = DESTINO / (nombre + ".parcial")
    n_archivos = n_bd = 0

    with tempfile.TemporaryDirectory() as tmp, \
            zipfile.ZipFile(parcial, "w", zipfile.ZIP_DEFLATED) as z:
        for carpeta in CARPETAS:
            base = RAIZ / carpeta
            if not base.exists():
                continue
            for f in base.rglob("*"):
                if not f.is_file() or f.name.endswith(IGNORAR):
                    continue
                rel = f.relative_to(RAIZ)
                if f.suffix.lower() in EXT_BD:
                    copia = Path(tmp) / "_".join(rel.parts)
                    copiar_bd(f, copia)
                    z.write(copia, rel)
                    n_bd += 1
                else:
                    z.write(f, rel)
                    n_archivos += 1
        for nombre_archivo in ARCHIVOS:
            f = RAIZ / nombre_archivo
            if f.exists():
                z.write(f, nombre_archivo)
                n_archivos += 1

    with zipfile.ZipFile(parcial) as z:             # comprobar que se puede leer
        malo = z.testzip()
        if malo:
            parcial.unlink(missing_ok=True)
            raise RuntimeError(f"El zip salio danado en {malo}")

    final = DESTINO / nombre
    parcial.rename(final)

    for viejo in respaldos_guardados()[:-GUARDAR]:  # dejar solo los ultimos 30
        viejo.unlink(missing_ok=True)
        log.info("Borrado respaldo viejo: %s", viejo.name)

    return final, n_archivos, n_bd


def mostrar_lista() -> None:
    lista = respaldos_guardados()
    if not lista:
        print("Aun no hay respaldos en", DESTINO)
        return
    print(f"Respaldos en {DESTINO} ({len(lista)}):")
    for r in lista:
        print(f"  {r.name}  {tamano_legible(r.stat().st_size)}")


def main() -> None:
    p = argparse.ArgumentParser(description="Respaldo del asistente")
    p.add_argument("--forzar", action="store_true", help="respaldar aunque ya haya uno de hoy")
    p.add_argument("--lista", action="store_true", help="mostrar los respaldos guardados")
    args = p.parse_args()

    if args.lista:
        mostrar_lista()
        return

    try:
        if not args.forzar and DESTINO.exists() and ya_hay_de_hoy():
            log.info("Ya hay un respaldo de hoy; no se hace otro.")
            return
        final, n_archivos, n_bd = hacer_respaldo()
        log.info("Respaldo listo: %s (%s, %d bases de datos, %d archivos)",
                 final.name, tamano_legible(final.stat().st_size), n_bd, n_archivos)
    except Exception as e:
        log.exception("Fallo el respaldo")
        avisar(f"⚠️ Respaldo del asistente\nNo se pudo hacer: {e}\nDetalle en logs\\respaldo.log")
        sys.exit(1)


if __name__ == "__main__":
    main()
