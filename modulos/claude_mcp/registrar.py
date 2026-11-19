"""Registra a Jarvis como servidor MCP en Claude Desktop (agrega mcpServers.jarvis a claude_desktop_config.json,
guarda respaldo y no toca nada más). Luego hay que cerrar Claude Desktop por completo y abrirlo de nuevo.
    .\\.venv\\Scripts\\python.exe modulos\\claude_mcp\\registrar.py          registrar
    .\\.venv\\Scripts\\python.exe modulos\\claude_mcp\\registrar.py --quitar quitar
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def configuraciones():
    """Rutas posibles del archivo (instalador normal y versión de Microsoft Store)."""
    rutas = []
    if os.getenv("APPDATA"):
        rutas.append(Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json")
    if os.getenv("LOCALAPPDATA"):
        local = Path(os.environ["LOCALAPPDATA"])
        for paquete in (local / "Packages").glob("Claude_*"):
            rutas.append(paquete / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json")
        for carpeta in local.glob("Claude-Data/*"):           # versiones nuevas (6.x) guardan aquí la configuración
            if (carpeta / "claude_desktop_config.json").exists():
                rutas.append(carpeta / "claude_desktop_config.json")
    vistas, unicas = set(), []
    for r in rutas:
        if r.parent.exists() and str(r).lower() not in vistas:
            vistas.add(str(r).lower())
            unicas.append(r)
    return unicas


def entrada():
    python = RAIZ / ".venv" / "Scripts" / "python.exe"
    return {"command": str(python if python.exists() else sys.executable),
            "args": [str(RAIZ / "modulos" / "claude_mcp" / "servidor_mcp.py")],
            "env": {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}}


def registrar(archivo, quitar=False):
    datos = {}
    if archivo.exists():
        texto = archivo.read_text(encoding="utf-8-sig").strip()
        datos = json.loads(texto) if texto else {}
        shutil.copy2(archivo, archivo.with_name(archivo.name + ".antes_jarvis_" + time.strftime("%Y%m%d%H%M%S")))
    servidores = datos.setdefault("mcpServers", {})
    if quitar:
        servidores.pop("jarvis", None)
    else:
        servidores["jarvis"] = entrada()
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return datos


def diagnostico():
    lineas = ["APPDATA=" + str(os.getenv("APPDATA")), "LOCALAPPDATA=" + str(os.getenv("LOCALAPPDATA"))]
    for base in filter(None, [os.getenv("APPDATA"), os.getenv("LOCALAPPDATA")]):
        for c in sorted(Path(base).glob("Claude*")) + sorted((Path(base) / "Packages").glob("*Claude*")):
            lineas.append("carpeta: " + str(c))
            for f in sorted(c.rglob("claude_desktop_config.json"))[:5]:
                lineas.append("   config: " + str(f) + " (" + str(f.stat().st_size) + " bytes)")
    return lineas


def main():
    quitar = "--quitar" in sys.argv
    rutas = configuraciones()
    salida = diagnostico()
    if not rutas:
        salida.append("No encontré la carpeta de Claude Desktop (%APPDATA%\\Claude).")
    for r in rutas:
        datos = registrar(r, quitar)
        salida.append(("Quitado de " if quitar else "Registrado en ") + str(r) + " -> servidores: " +
                      ", ".join(datos.get("mcpServers", {})))
    salida.append("Ahora cierre Claude Desktop por completo (también el ícono junto al reloj) y ábralo de nuevo.")
    texto = "\n".join(salida)
    print(texto)
    try:                                       # copia para Claude (por si la consola no queda guardada)
        (RAIZ / "para_claude_salida.txt").write_text(texto + "\nFIN\n", encoding="utf-8")
    except Exception:
        pass
    return 0 if rutas else 1


if __name__ == "__main__":
    sys.exit(main())
