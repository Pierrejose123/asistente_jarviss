"""Revisión de la PC (11-11): seguridad, problemas de Windows, discos y tarjeta gráfica.

Qué hace (SOLO LECTURA, sin permiso de administrador; nada se cambia sin su «sí»):
  - Seguridad: antivirus encendido y al día (Centro de seguridad de Windows: Avast/Defender), firewall, actualizaciones
    de Windows pendientes, reinicio pendiente.
  - Cambios raros desde la última revisión: programas que arrancan con Windows, tareas programadas y servicios
    nuevos, programas nuevos escuchando conexiones. La primera vez solo guarda la «foto» de la PC.
  - Problemas: errores graves de Windows de la semana (apagones bruscos, pantallazos azules, disco, hardware,
    driver de video), salud de los discos (M.2 y mecánico) y espacio libre, RAM y procesos que más consumen.
  - Tarjeta gráfica (nvidia-smi): temperatura (también la máxima de la semana, medida cada 10 min), si bajó la
    velocidad por calor, conexión PCIe x16, antigüedad del driver, programación de GPU y Modo de juego.
  - Temporales: cuánto se puede liberar; se borra solo con el botón «🧹 Limpiar» (solo %TEMP% con más de 2 días).

Cuándo avisa (pocos mensajes):
  - Domingo 17:00 (o al encender la PC si se saltó la semana): UN mensaje, «todo bien» o solo lo que falla.
  - Al momento, solo si es GRAVE (una vez al día por tipo): antivirus apagado, disco con fallas, tarjeta ≥ 88 °C,
    disco C: casi lleno.
  - /pc: revisión completa ahora.
Opcional con administrador (revision_admin.ps1): archivos del sistema (SFC/DISM), desgaste del disco e intentos de
inicio de sesión fallidos. Si no está instalado, el resto funciona igual.

Desde la PC:  .\\.venv\\Scripts\\python.exe modulos\\comun\\pc_salud.py
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modulos.comun import db  # noqa: E402
from modulos.comun.base import CONFIG, PESADO, ahora, registro  # noqa: E402

log = registro("pc")
OK, AVISO, MAL = "✅", "⚠️", "❌"
PREDETERMINADO = {"dia_semana": 6, "hora": "17:00", "temp_gpu_alerta": 88, "temp_gpu_aviso": 83,
                  "dias_driver_viejo": 120, "c_minimo_gb": 15, "c_critico_gb": 5,
                  "chequeo_diario_solo_si_falla": True, "carpeta_admin": str(PESADO / "pc")}
_listo = []


def ajustes():
    datos = dict(PREDETERMINADO)
    try:
        datos.update(json.loads((CONFIG / "pc.json").read_text(encoding="utf-8-sig")))
    except Exception:
        pass
    return datos


def _con():
    con = sqlite3.connect(db.ARCHIVO, timeout=30)
    con.row_factory = sqlite3.Row
    if not _listo:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS pc_inventario (tipo TEXT, nombre TEXT, detalle TEXT, visto TEXT,
                PRIMARY KEY (tipo, nombre));
            CREATE TABLE IF NOT EXISTS pc_muestras (fecha TEXT, temp_gpu REAL, cuando TEXT);
            CREATE TABLE IF NOT EXISTS pc_estado (clave TEXT PRIMARY KEY, valor TEXT);
        """)
        _listo.append(True)
    return con


def _estado(clave, valor=None):
    with _con() as con:
        if valor is None:
            f = con.execute("SELECT valor FROM pc_estado WHERE clave=?", (clave,)).fetchone()
            return f["valor"] if f else None
        con.execute("INSERT OR REPLACE INTO pc_estado VALUES (?,?)", (clave, str(valor)))


# ------------------------------------------------------------------ ejecutar comandos FIJOS (nunca texto del usuario) ---
def _ps(comando, timeout=60):
    """Ejecuta un comando de PowerShell FIJO del código y devuelve el JSON que imprime (o None)."""
    completo = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ErrorActionPreference='SilentlyContinue'; " + comando
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", completo],
                       capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    salida = r.stdout.decode("utf-8", errors="ignore").strip()
    if not salida:
        return None
    try:
        return json.loads(salida)
    except Exception:
        return salida


def _lista(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _nvidia(argumentos, timeout=15):
    r = subprocess.run(["nvidia-smi"] + argumentos, capture_output=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout.decode("utf-8", errors="ignore")


def _prueba(nombre, funcion):
    try:
        estado, detalle = funcion()
    except Exception as exc:
        log.info("%s falló: %s", nombre, exc)
        estado, detalle = AVISO, "no pude revisarlo (" + str(exc)[:80] + ")"
    return {"nombre": nombre, "estado": estado, "detalle": detalle}


# ------------------------------------------------------------------ seguridad ---
def decodificar_antivirus(estado):
    """productState del Centro de seguridad: (encendido, al_dia)."""
    h = "%06x" % int(estado)
    return h[2:4] in ("10", "11"), h[4:6] == "00"


def antivirus():
    datos = _lista(_ps("Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | "
                       "Select-Object displayName, productState | ConvertTo-Json -Compress"))
    if not datos:
        return MAL, "Windows no reporta ningún antivirus"
    activos, viejos = [], []
    for a in datos:
        encendido, al_dia = decodificar_antivirus(a["productState"])
        if encendido:
            (activos if al_dia else viejos).append(a["displayName"])
    if activos:
        return OK, ", ".join(activos) + " encendido y al día"
    if viejos:
        return AVISO, ", ".join(viejos) + " encendido pero SIN actualizar: ábralo y actualice"
    return MAL, "ningún antivirus encendido (" + ", ".join(a["displayName"] for a in datos) + " apagado)"


def firewall():
    datos = _lista(_ps("Get-NetFirewallProfile | Select-Object Name, Enabled | ConvertTo-Json -Compress"))
    if not datos:
        return AVISO, "no pude leer el firewall"
    apagados = [d["Name"] for d in datos if not d.get("Enabled")]
    if apagados:
        return MAL, "firewall apagado en: " + ", ".join(apagados)
    return OK, "encendido"


def actualizaciones():
    pendientes = _ps("$s=(New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher(); "
                     "$r=$s.Search(\"IsInstalled=0 and Type='Software' and IsHidden=0\"); "
                     "@($r.Updates | ForEach-Object { $_.Title }) | ConvertTo-Json -Compress", timeout=240)
    reinicio = _ps("(Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired') -or "
                   "(Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component Based Servicing\\RebootPending') "
                   "| ConvertTo-Json")
    titulos = [t for t in _lista(pendientes) if isinstance(t, str)]
    partes = []
    seguridad = [t for t in titulos if re.search(r"security|seguridad|acumulativa|cumulative|defender", t, re.I)]
    if titulos:
        partes.append(str(len(titulos)) + " pendiente" + ("s" if len(titulos) > 1 else "") +
                      (" (" + str(len(seguridad)) + " de seguridad)" if seguridad else ""))
    if reinicio is True:
        partes.append("falta reiniciar para terminar de instalar")
    if not partes:
        return OK, "Windows al día"
    return (AVISO if seguridad or reinicio is True else OK), "; ".join(partes) + ": Configuración → Windows Update"


# ------------------------------------------------------------------ cambios raros desde la última vez ---
def _inventario_actual():
    items = []
    for s in _lista(_ps("Get-CimInstance Win32_StartupCommand | Select-Object Name, Command | ConvertTo-Json -Compress")):
        if s.get("Name"):
            items.append(("inicio", s["Name"], s.get("Command") or ""))
    for t in _lista(_ps("Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\\Microsoft\\*' -and $_.State -ne 'Disabled' } | "
                        "Select-Object TaskName, TaskPath | ConvertTo-Json -Compress")):
        if t.get("TaskName"):
            items.append(("tarea", (t.get("TaskPath") or "") + t["TaskName"], ""))
    for s in _lista(_ps("Get-CimInstance Win32_Service -Filter \"StartMode='Auto'\" | Select-Object Name, PathName | "
                        "ConvertTo-Json -Compress")):
        if s.get("Name"):
            items.append(("servicio", s["Name"], s.get("PathName") or ""))
    try:
        import psutil
        for c in psutil.net_connections(kind="inet"):
            if c.status == psutil.CONN_LISTEN and c.pid:
                try:
                    items.append(("red", psutil.Process(c.pid).name(), ""))
                except Exception:
                    pass
    except Exception as exc:
        log.info("Sin conexiones: %s", exc)
    return items


ETIQUETA = {"inicio": "arranca con Windows", "tarea": "tarea programada", "servicio": "servicio", "red": "escucha conexiones"}


def cambios_raros(items=None):
    items = _inventario_actual() if items is None else items
    if not items:
        return AVISO, "no pude leer los programas de inicio"
    with _con() as con:
        primera = not con.execute("SELECT 1 FROM pc_inventario LIMIT 1").fetchone()
        nuevos = []
        for tipo, nombre, detalle in set(items):
            if con.execute("SELECT 1 FROM pc_inventario WHERE tipo=? AND nombre=?", (tipo, nombre)).fetchone():
                continue
            con.execute("INSERT INTO pc_inventario VALUES (?,?,?,?)", (tipo, nombre, detalle[:300],
                                                                     datetime.now().isoformat(timespec="minutes")))
            nuevos.append((tipo, nombre))
    if primera:
        return OK, "guardé la foto de su PC (" + str(len(set(items))) + " elementos); desde la próxima le aviso de lo nuevo"
    if not nuevos:
        return OK, "nada nuevo desde la última revisión"
    lista = "; ".join(n.split("\\")[-1] + " (" + ETIQUETA[t] + ")" for t, n in sorted(nuevos)[:6])
    return AVISO, "nuevo: " + lista + (" y " + str(len(nuevos) - 6) + " más" if len(nuevos) > 6 else "") + \
        ". Si no lo instaló usted, revíselo"


# ------------------------------------------------------------------ problemas de Windows ---
GRAVES = [  # (proveedor, ids o None, explicación)
    ("Microsoft-Windows-Kernel-Power", {41}, "apagones o reinicios bruscos"),
    ("Microsoft-Windows-WER-SystemErrorReporting", {1001}, "pantallazos azules"),
    ("BugCheck", None, "pantallazos azules"),
    ("disk", {7, 11, 51, 153}, "errores de lectura del disco"),
    ("Ntfs", {55, 98}, "errores del sistema de archivos"),
    ("Microsoft-Windows-WHEA-Logger", None, "errores de hardware (procesador, RAM o PCIe)"),
    ("nvlddmkm", None, "fallas del driver de NVIDIA"),
    ("Display", {4101}, "el driver de video dejó de responder y se recuperó"),
]


def errores_windows(eventos=None):
    if eventos is None:
        eventos = _lista(_ps("$d=(Get-Date).AddDays(-7); Get-WinEvent -FilterHashtable @{LogName='System'; Level=1,2,3; "
                             "StartTime=$d} -MaxEvents 3000 | Select-Object ProviderName, Id, Level | ConvertTo-Json -Compress",
                             timeout=90))
    cuenta = {}
    errores = 0
    for e in eventos:
        if not isinstance(e, dict):
            continue
        if e.get("Level") in (1, 2):
            errores += 1
        for prov, ids, texto in GRAVES:
            if e.get("ProviderName") == prov and (ids is None or e.get("Id") in ids):
                cuenta[texto] = cuenta.get(texto, 0) + 1
    if cuenta:
        detalle = "; ".join(str(n) + " × " + t for t, n in sorted(cuenta.items(), key=lambda x: -x[1]))
        grave = any(t in cuenta for t in ("pantallazos azules", "errores de lectura del disco",
                                          "errores de hardware (procesador, RAM o PCIe)"))
        return (MAL if grave else AVISO), detalle + " (últimos 7 días)"
    return OK, "sin errores graves en 7 días" + (" (" + str(errores) + " errores menores, normales)" if errores else "")


def discos_salud():
    datos = _lista(_ps("Get-PhysicalDisk | Select-Object FriendlyName, MediaType, HealthStatus, OperationalStatus | "
                       "ConvertTo-Json -Compress"))
    malos = [d["FriendlyName"] for d in datos if str(d.get("HealthStatus")) not in ("Healthy", "0")]
    import shutil
    partes = []
    peor = OK
    for letra in sorted({"C:\\", PESADO.anchor} - {""}):
        if Path(letra).exists():
            libre = shutil.disk_usage(letra).free / 1e9
            partes.append(letra[0] + ": " + ("%.0f" % libre) + " GB libres")
            if letra.startswith("C") and libre < ajustes()["c_minimo_gb"]:
                peor = AVISO
    if malos:
        return MAL, "¡disco con fallas: " + ", ".join(malos) + "! Haga un respaldo YA · " + " · ".join(partes)
    if not datos:
        return AVISO, "no pude leer la salud de los discos · " + " · ".join(partes)
    return peor, str(len(datos)) + " discos sanos · " + " · ".join(partes)


def recursos():
    import psutil
    ram = psutil.virtual_memory()
    procesos = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procesos.append((p.info["memory_info"].rss, p.info["name"]))
        except Exception:
            pass
    suma = {}
    for rss, nombre in procesos:
        suma[nombre] = suma.get(nombre, 0) + rss
    top = sorted(suma.items(), key=lambda x: -x[1])[:3]
    texto = "RAM al " + "%.0f" % ram.percent + " % · más usan: " + ", ".join(n + " " + "%.1f" % (b / 1e9) + " GB" for n, b in top)
    return (AVISO if ram.percent >= 90 else OK), texto


# ------------------------------------------------------------------ tarjeta gráfica ---
def lectura_gpu():
    """{'nombre','driver','temp','ancho','ancho_max','gen','gen_max','potencia','limite'} o None."""
    salida = _nvidia(["--query-gpu=name,driver_version,temperature.gpu,pcie.link.width.current,pcie.link.width.max,"
                      "pcie.link.gen.current,pcie.link.gen.max,power.draw,power.limit", "--format=csv,noheader,nounits"])
    partes = [p.strip() for p in salida.strip().split("\n")[0].split(",")] if salida.strip() else []
    if len(partes) < 9:
        return None
    num = lambda x: float(x) if re.match(r"^[\d.]+$", x) else None
    return {"nombre": partes[0], "driver": partes[1], "temp": num(partes[2]), "ancho": num(partes[3]),
            "ancho_max": num(partes[4]), "gen": num(partes[5]), "gen_max": num(partes[6]),
            "potencia": num(partes[7]), "limite": num(partes[8])}


def contadores_calor(texto=None):
    """Microsegundos acumulados con la velocidad bajada por calor (desde que arrancó el driver)."""
    texto = _nvidia(["-q", "-d", "PERFORMANCE"]) if texto is None else texto
    bloque = texto.split("Clocks Event Reasons Counters")[-1] if "Counters" in texto else ""
    total = 0
    for m in re.finditer(r"(SW Thermal Slowdown|HW Thermal Slowdown)\s*:\s*(\d+)\s*us", bloque):
        total += int(m.group(2))
    return total


def muestrear_gpu():
    """Cada 10 min: guarda la temperatura (para la máxima de la semana). Devuelve la lectura."""
    g = lectura_gpu()
    if g and g["temp"] is not None:
        with _con() as con:
            con.execute("INSERT INTO pc_muestras VALUES (?,?,?)", (ahora().date().isoformat(), g["temp"],
                                                                 ahora().isoformat(timespec="minutes")))
            con.execute("DELETE FROM pc_muestras WHERE fecha < ?", ((ahora() - timedelta(days=30)).date().isoformat(),))
    return g


def maxima_semana():
    with _con() as con:
        f = con.execute("SELECT MAX(temp_gpu) AS m FROM pc_muestras WHERE fecha >= ?",
                        ((ahora() - timedelta(days=7)).date().isoformat(),)).fetchone()
    return f["m"] if f else None


def tarjeta(g=None, calor_us=None, fecha_driver=None):
    a = ajustes()
    g = lectura_gpu() if g is None else g
    if not g:
        return AVISO, "no pude leer la tarjeta (¿nvidia-smi?)"
    partes, peor = [g["nombre"].replace("NVIDIA GeForce ", "")], OK
    maxima = maxima_semana()
    t = "%.0f °C ahora" % g["temp"] if g["temp"] is not None else ""
    if maxima:
        t += ", máx. semana %.0f °C" % maxima
        if maxima >= a["temp_gpu_aviso"]:
            peor = AVISO
            t += " (alta: revise polvo y ventilación)"
    partes.append(t)
    if g["ancho"] and g["ancho_max"] and g["ancho"] < g["ancho_max"]:
        peor = AVISO
        partes.append("conectada a x%.0f de x%.0f (revise la ranura PCIe)" % (g["ancho"], g["ancho_max"]))
    else:
        partes.append("PCIe x%.0f completo" % (g["ancho"] or 16))
    calor_us = contadores_calor() if calor_us is None else calor_us
    anterior = _estado("gpu_calor_us")
    _estado("gpu_calor_us", calor_us)
    if anterior is not None and calor_us > int(anterior) and calor_us - int(anterior) > 60_000_000:
        peor = AVISO
        partes.append("bajó su velocidad por calor %.0f min esta semana" % ((calor_us - int(anterior)) / 6e7))
    else:
        partes.append("nunca bajó la velocidad por calor" if calor_us == 0 else "sin bajones por calor recientes")
    fecha_driver = _fecha_driver() if fecha_driver is None else fecha_driver
    texto_driver = "driver " + g["driver"]
    if fecha_driver:
        dias = (datetime.now() - fecha_driver).days
        texto_driver += " (%d días)" % dias
        if dias > a["dias_driver_viejo"]:
            peor = AVISO
            texto_driver += ": hay uno más nuevo seguro, actualícelo con la app de NVIDIA"
    partes.append(texto_driver)
    return peor, " · ".join(partes)


def _fecha_driver():
    d = _ps("(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -like '*NVIDIA*' } | "
            "Select-Object -First 1).DriverDate.ToString('yyyy-MM-dd') | ConvertTo-Json")
    try:
        return datetime.strptime(str(d).strip('"'), "%Y-%m-%d")
    except Exception:
        return None


def ajustes_juego(datos=None):
    datos = datos if datos is not None else _ps(
        "$g=(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\GraphicsDrivers').HwSchMode; "
        "$m=(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\GameBar').AutoGameModeEnabled; "
        "$p=(powercfg /getactivescheme) -join ' '; @{gpu=$g; modo=$m; plan=$p} | ConvertTo-Json -Compress") or {}
    partes, peor = [], OK
    gpu = datos.get("gpu")
    if gpu == 1:
        peor = AVISO
        partes.append("programación de GPU acelerada APAGADA (Configuración → Pantalla → Gráficos)")
    else:
        partes.append("programación de GPU " + ("encendida" if gpu == 2 else "en lo predeterminado de Windows"))
    if datos.get("modo") == 0:
        peor = AVISO
        partes.append("Modo de juego APAGADO (Configuración → Juegos)")
    else:
        partes.append("Modo de juego encendido")
    plan = str(datos.get("plan") or "")
    m = re.search(r"\(([^)]+)\)\s*$", plan)
    if m:
        partes.append("energía: " + m.group(1))
    return peor, " · ".join(partes)


# ------------------------------------------------------------------ temporales ---
def _temporales(dias=2):
    carpeta = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "")
    limite = time.time() - dias * 86400
    archivos, total = [], 0
    if not carpeta.exists():
        return carpeta, [], 0
    for raiz, _, nombres in os.walk(carpeta):
        for n in nombres:
            p = Path(raiz) / n
            try:
                st = p.stat()
                if st.st_mtime < limite:
                    archivos.append(p)
                    total += st.st_size
            except Exception:
                pass
    return carpeta, archivos, total


def temporales():
    _, archivos, total = _temporales()
    gb = total / 1e9
    if gb >= 1:
        return AVISO, "%.1f GB de archivos temporales viejos que se pueden borrar (botón 🧹)" % gb
    return OK, "%.1f GB de temporales viejos (poco)" % gb


def limpiar_temporales():
    """Borra SOLO archivos de %TEMP% con más de 2 días; los que están en uso se saltan. Devuelve GB liberados."""
    carpeta, archivos, _ = _temporales()
    liberado = 0
    for p in archivos:
        try:
            if carpeta in p.parents:                       # nunca fuera de la carpeta de temporales
                tam = p.stat().st_size
                p.unlink()
                liberado += tam
        except Exception:
            pass
    for raiz, dirs, _ in os.walk(carpeta, topdown=False):  # carpetas que quedaron vacías
        for d in dirs:
            try:
                (Path(raiz) / d).rmdir()
            except Exception:
                pass
    log.info("Limpieza de temporales: %.2f GB", liberado / 1e9)
    return liberado / 1e9


# ------------------------------------------------------------------ revisión con administrador (opcional) ---
def admin():
    """Lee lo que dejó revision_admin.ps1 (tarea de Windows con administrador, opcional). None si no está."""
    archivo = Path(ajustes()["carpeta_admin"]) / "revision_admin.json"
    if not archivo.exists():
        return None
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8-sig"))
    except Exception:
        return AVISO, "no pude leer la revisión con administrador"
    fecha = datetime.fromtimestamp(archivo.stat().st_mtime)
    if (datetime.now() - fecha).days > 9:
        return AVISO, "la revisión con administrador no corre desde el " + fecha.strftime("%d/%m")
    partes, peor = [], OK
    imagen = str(datos.get("imagen") or "")
    if imagen in ("Healthy", "0"):
        partes.append("archivos de Windows sanos")
    elif imagen:
        peor = AVISO
        partes.append("archivos de Windows dañados (" + imagen + "): en PowerShell de administrador ejecute "
                      "«DISM /Online /Cleanup-Image /RestoreHealth» y luego «sfc /scannow»")
    for d in _lista(datos.get("discos")):
        nombre = str(d.get("FriendlyName") or "disco")
        if (d.get("ReadErrorsUncorrected") or 0) > 0:
            peor = MAL
            partes.append(nombre + " con errores de lectura sin corregir: haga un respaldo")
        if (d.get("Wear") or 0) >= 80:
            peor = AVISO if peor == OK else peor
            partes.append(nombre + " gastado al %s %%" % d["Wear"])
        elif d.get("Temperature"):
            partes.append(nombre.split()[0] + " %s °C" % d["Temperature"])
    fallidos = datos.get("inicios_fallidos")
    if isinstance(datos.get("externos"), int):         # desde 11-11: solo preocupa lo que viene de fuera de su casa
        if datos["externos"] >= 3:
            peor = AVISO if peor == OK else peor
            partes.append(str(datos["externos"]) + " intentos de entrar desde FUERA de su casa o por escritorio remoto: "
                          "revise que el escritorio remoto esté apagado")
        locales = [l for l in _lista(datos.get("locales")) if (l.get("veces") or 0) >= 3]
        conocidos = set(ajustes().get("equipos_conocidos", []))
        nuevos = [l for l in locales if l.get("ip") not in conocidos]
        if nuevos:
            partes.append("un equipo de su casa (" + ", ".join(l["ip"] + " ×" + str(l["veces"]) for l in nuevos) +
                          ") falla al conectarse a esta PC (contraseña vieja guardada; no es un ataque)")
        if not datos["externos"] and not nuevos:
            partes.append("sin intentos raros de entrar")
    elif isinstance(fallidos, int):
        if fallidos >= 10:
            peor = AVISO if peor == OK else peor
            partes.append(str(fallidos) + " intentos fallidos de entrar a Windows en 7 días")
        else:
            partes.append("sin intentos raros de entrar")
    return peor, " · ".join(partes) or "sin novedades"


# ------------------------------------------------------------------ revisión completa y mensajes ---
PRUEBAS = [("Antivirus", antivirus), ("Firewall", firewall), ("Windows Update", actualizaciones),
           ("Cambios raros", cambios_raros), ("Errores de Windows", errores_windows), ("Discos", discos_salud),
           ("Tarjeta gráfica", tarjeta), ("Ajustes de juego", ajustes_juego), ("Memoria", recursos),
           ("Temporales", temporales)]


def revisar():
    res = [_prueba(n, f) for n, f in PRUEBAS]
    a = admin()
    res.append({"nombre": "Revisión de administrador", "estado": a[0], "detalle": a[1]} if a else
               {"nombre": "Revisión de administrador", "estado": OK, "detalle": "no instalada (opcional)", "opcional": True})
    _estado("ultima_revision", datetime.now().isoformat(timespec="minutes"))
    log.info("Revisión de la PC: %s", ", ".join(r["nombre"] + "=" + r["estado"] for r in res))
    return res


def texto(res, completo=False):
    malos = [r for r in res if r["estado"] != OK]
    if not malos and not completo:
        return "🖥 <b>Revisión semanal de la PC</b>: todo bien ✅ (" + str(len(res)) + " de " + str(len(res)) + \
            "). Detalle con /pc."
    lineas = ["🖥 <b>Revisión " + ("de la PC" if completo else "semanal de la PC") + "</b>" +
              (" — todo bien ✅" if not malos else "")]
    for r in (res if completo else malos):
        lineas.append(r["estado"] + " <b>" + escape(r["nombre"]) + "</b>: " + escape(r["detalle"]))
    if not completo:
        lineas.append("\n" + str(len(res) - len(malos)) + " revisiones más están bien. Detalle: /pc")
    return "\n".join(lineas)


def hay_temporales(res):
    return any(r["nombre"] == "Temporales" and r["estado"] != OK for r in res)


def toca_semanal(momento=None):
    """¿Corresponde la revisión semanal ahora? Domingo desde la hora fijada, o si pasó más de una semana."""
    a = ajustes()
    momento = momento or datetime.now()
    if not 8 <= momento.hour < 22:
        return False
    ultima = _estado("ultima_semanal")
    ultima = datetime.fromisoformat(ultima) if ultima else None
    if ultima and momento - ultima < timedelta(days=6):
        return False
    if ultima is None or momento - ultima >= timedelta(days=7, hours=12):
        return True                                     # se saltó la semana (PC apagada el domingo)
    return momento.weekday() == int(a["dia_semana"]) and momento.strftime("%H:%M") >= a["hora"]


def marcar_semanal(momento=None):
    _estado("ultima_semanal", (momento or datetime.now()).isoformat(timespec="minutes"))


def vigilar_grave(g=None):
    """Cada 10 min: solo lo GRAVE, una vez al día por tipo. Devuelve textos (normalmente [])."""
    a = ajustes()
    hoy = ahora().date().isoformat()
    avisos = []

    def una_vez(tipo, mensaje):
        clave = hoy + "|pc_grave|" + tipo
        if not db.aviso_enviado(clave):
            db.marcar_aviso(clave)
            avisos.append(mensaje)

    g = muestrear_gpu() if g is None else g
    if g and g["temp"] is not None and g["temp"] >= a["temp_gpu_alerta"]:
        previa = _estado("gpu_caliente")
        _estado("gpu_caliente", g["temp"])
        if previa and float(previa) >= a["temp_gpu_alerta"]:     # dos lecturas seguidas: no es un pico
            una_vez("gpu", "🔥 Su tarjeta gráfica está a %.0f °C (muy caliente). Revise que los ventiladores giren y "
                           "que no esté tapada; si sigue así, conviene limpiarla de polvo." % g["temp"])
    elif g:
        _estado("gpu_caliente", "")
    minuto = datetime.now().minute
    if minuto < 10 or _estado("grave_primera") is None:         # lo demás, una vez por hora
        _estado("grave_primera", "1")
        r = _prueba("Antivirus", antivirus)
        if r["estado"] == MAL:
            una_vez("antivirus", "🛡 " + r["detalle"] + ". Abra Avast y enciéndalo, señor.")
        import shutil
        if Path("C:\\").exists() and shutil.disk_usage("C:\\").free / 1e9 < a["c_critico_gb"]:
            una_vez("disco_lleno", "💾 El disco C: está casi lleno (menos de %d GB). Windows y el asistente pueden "
                                   "fallar; escriba /pc y use 🧹 para liberar temporales." % a["c_critico_gb"])
        r = _prueba("Discos", discos_salud)
        if r["estado"] == MAL and "fallas" in r["detalle"]:
            una_vez("disco", "💽 " + r["detalle"])
    return avisos


def chequeo_diario_silencioso():
    return bool(ajustes().get("chequeo_diario_solo_si_falla", True))


if __name__ == "__main__":
    for r in revisar():
        print(r["estado"], r["nombre"].ljust(26), r["detalle"])
