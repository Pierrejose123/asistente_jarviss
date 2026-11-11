"""Prueba de la revisión de la PC (11-11). Base TEMPORAL, comandos de Windows simulados con los datos reales de
El usuario (11-11), sin Google ni Telegram. Lo único real: borra archivos viejos en una carpeta temporal de prueba.

    .\\.venv\\Scripts\\python.exe modulos\\comun\\pruebas\\prueba_pc_salud.py
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
CARPETA = Path(tempfile.mkdtemp())
from modulos.comun import db  # noqa: E402

db.ARCHIVO = CARPETA / "prueba_pc.db"
from modulos.comun import modo_prueba  # noqa: E402

assert modo_prueba.activo(), "La protección de pruebas no está activa: no sigo."
from modulos.comun import pc_salud as pc  # noqa: E402

pc.ajustes = lambda: {**pc.PREDETERMINADO, "carpeta_admin": str(CARPETA / "admin")}
fallos, total = [], 0


def ok(cond, que):
    global total
    total += 1
    if not cond:
        fallos.append(que)


RESPUESTAS = {}


def ps_falso(comando, timeout=60):
    for clave, valor in RESPUESTAS.items():
        if clave in comando:
            return valor
    return None


pc._ps = ps_falso
NVIDIA_CSV = "NVIDIA GeForce RTX 5070, 621.14, 40, 16, 16, 5, 5, 26.17, 262.50\n"
NVIDIA_Q = """    Clocks Event Reasons Counters
        SW Power Capping                               : 1061343611 us
        Sync Boost                                     : 0 us
        SW Thermal Slowdown                            : 0 us
        HW Thermal Slowdown                            : 0 us
        HW Power Braking                               : 0 us"""
pc._nvidia = lambda args, timeout=15: NVIDIA_CSV if any(a.startswith("--query") for a in args) else NVIDIA_Q

# Antivirus: datos reales (Avast encendido y al día, Defender en pausa)
ok(pc.decodificar_antivirus(266240) == (True, True), "Avast 266240 debe ser encendido y al día")
ok(pc.decodificar_antivirus(393472)[0] is False, "Defender 393472 debe estar en pausa")
RESPUESTAS["AntiVirusProduct"] = [{"displayName": "Windows Defender", "productState": 393472},
                                  {"displayName": "Avast Antivirus", "productState": 266240}]
e, d = pc.antivirus()
ok(e == pc.OK and "Avast" in d, "antivirus real: " + d)
RESPUESTAS["AntiVirusProduct"] = [{"displayName": "Avast Antivirus", "productState": 262144}]
ok(pc.antivirus()[0] == pc.MAL, "Avast apagado debe ser grave")
RESPUESTAS["AntiVirusProduct"] = [{"displayName": "Avast Antivirus", "productState": 266256}]
ok(pc.antivirus()[0] == pc.AVISO, "Avast desactualizado debe avisar")
RESPUESTAS["AntiVirusProduct"] = [{"displayName": "Avast Antivirus", "productState": 266240}]

RESPUESTAS["NetFirewallProfile"] = [{"Name": "Domain", "Enabled": True}, {"Name": "Private", "Enabled": True},
                                    {"Name": "Public", "Enabled": False}]
ok(pc.firewall()[0] == pc.MAL, "firewall apagado")
RESPUESTAS["NetFirewallProfile"] = [{"Name": "Private", "Enabled": True}]
ok(pc.firewall()[0] == pc.OK, "firewall encendido")

RESPUESTAS["Microsoft.Update.Session"] = ["2026-11 Actualización acumulativa para Windows 11 (KB5099999)"]
RESPUESTAS["RebootRequired"] = False
e, d = pc.actualizaciones()
ok(e == pc.AVISO and "seguridad" in d, "actualización de seguridad pendiente: " + d)
RESPUESTAS["Microsoft.Update.Session"] = []
ok(pc.actualizaciones()[0] == pc.OK, "Windows al día")

# Cambios raros: la primera vez guarda la foto; luego avisa solo lo nuevo
base = [("inicio", "Discord", "x"), ("servicio", "AvastSvc", "x"), ("tarea", "\\OneDrive Update", ""), ("red", "python.exe", "")]
e, d = pc.cambios_raros(base)
ok(e == pc.OK and "foto" in d, "primera vez: " + d)
e, d = pc.cambios_raros(base)
ok(e == pc.OK and "nada nuevo" in d, "sin cambios: " + d)
e, d = pc.cambios_raros(base + [("inicio", "Actualizador raro", "C:\\Users\\usuario\\AppData\\x.exe")])
ok(e == pc.AVISO and "Actualizador raro" in d and "arranca con Windows" in d, "programa nuevo: " + d)
ok(pc.cambios_raros(base + [("inicio", "Actualizador raro", "")])[0] == pc.OK, "lo nuevo se avisa una sola vez")

# Errores de Windows
eventos = [{"ProviderName": "Microsoft-Windows-Kernel-Power", "Id": 41, "Level": 1},
           {"ProviderName": "Service Control Manager", "Id": 7000, "Level": 2}]
e, d = pc.errores_windows(eventos)
ok(e == pc.AVISO and "apagones" in d, "apagón brusco: " + d)
e, d = pc.errores_windows(eventos + [{"ProviderName": "Microsoft-Windows-WER-SystemErrorReporting", "Id": 1001, "Level": 2}])
ok(e == pc.MAL and "pantallazos" in d, "pantallazo azul: " + d)
ok(pc.errores_windows([{"ProviderName": "Service Control Manager", "Id": 7000, "Level": 2}])[0] == pc.OK, "error menor")

# Discos (datos reales: los dos sanos)
RESPUESTAS["Get-PhysicalDisk"] = [{"FriendlyName": "ST2000DM008-2UB102", "HealthStatus": "Healthy"},
                                  {"FriendlyName": "Samsung SSD 990 EVO Plus 1TB", "HealthStatus": "Healthy"}]
ok("2 discos sanos" in pc.discos_salud()[1], "discos sanos")
RESPUESTAS["Get-PhysicalDisk"] = [{"FriendlyName": "ST2000DM008-2UB102", "HealthStatus": "Warning"}]
e, d = pc.discos_salud()
ok(e == pc.MAL and "respaldo" in d, "disco con fallas: " + d)
RESPUESTAS["Get-PhysicalDisk"] = [{"FriendlyName": "Samsung SSD 990 EVO Plus 1TB", "HealthStatus": "Healthy"}]

# Tarjeta gráfica (datos reales: 40 °C, PCIe x16, nunca bajó por calor)
g = pc.lectura_gpu()
ok(g and g["temp"] == 40 and g["ancho"] == 16, "lectura de la tarjeta: " + str(g))
ok(pc.contadores_calor() == 0, "contadores de calor")
e, d = pc.tarjeta(g, 0, datetime.now() - timedelta(days=20))
ok(e == pc.OK and "x16" in d and "nunca bajó" in d, "tarjeta sana: " + d)
e, d = pc.tarjeta(dict(g, ancho=8), 0, datetime.now() - timedelta(days=20))
ok(e == pc.AVISO and "x8" in d, "PCIe a la mitad: " + d)
e, d = pc.tarjeta(g, 0 + 5 * 60_000_000, datetime.now() - timedelta(days=20))
ok(e == pc.AVISO and "calor" in d, "bajó por calor: " + d)
e, d = pc.tarjeta(g, 5 * 60_000_000, datetime.now() - timedelta(days=200))
ok(e == pc.AVISO and "actualícelo" in d, "driver viejo: " + d)
ok(pc.ajustes_juego({"gpu": 2, "modo": 1, "plan": "GUID ... (Equilibrado)"})[0] == pc.OK, "ajustes bien")
e, d = pc.ajustes_juego({"gpu": 1, "modo": 0, "plan": ""})
ok(e == pc.AVISO and "APAGADA" in d and "Modo de juego APAGADO" in d, "ajustes apagados: " + d)

# Vigilancia grave: la tarjeta caliente avisa solo con dos lecturas seguidas y una vez al día
pc.antivirus = lambda: (pc.OK, "Avast encendido")
caliente = dict(g, temp=90)
ok(pc.vigilar_grave(caliente) == [], "un pico no avisa")
avisos = pc.vigilar_grave(caliente)
ok(len(avisos) == 1 and "90 °C" in avisos[0], "dos lecturas calientes avisan: " + str(avisos))
ok(pc.vigilar_grave(caliente) == [], "solo una vez al día")
ok(pc.vigilar_grave(g) == [], "temperatura normal: sin aviso")

# Revisión semanal
pc._estado("ultima_semanal", "")
with pc._con() as con:
    con.execute("DELETE FROM pc_estado WHERE clave='ultima_semanal'")
domingo = datetime(2026, 11, 15, 17, 5)
ok(pc.toca_semanal(domingo), "primera vez toca")
pc.marcar_semanal(domingo)
ok(not pc.toca_semanal(domingo + timedelta(hours=2)), "no repite el mismo domingo")
ok(not pc.toca_semanal(domingo + timedelta(days=3)), "no a mitad de semana")
ok(pc.toca_semanal(domingo + timedelta(days=7)), "el domingo siguiente toca")
ok(not pc.toca_semanal(datetime(2026, 11, 22, 3, 0)), "nunca de madrugada")
ok(pc.toca_semanal(domingo + timedelta(days=8, hours=-1)), "si se saltó el domingo, al encender el lunes")

# Mensaje: corto si todo va bien, solo lo malo si algo falla
bien = [{"nombre": "A", "estado": pc.OK, "detalle": "x"}, {"nombre": "B", "estado": pc.OK, "detalle": "y"}]
ok("todo bien" in pc.texto(bien) and pc.texto(bien).count("\n") == 0, "mensaje corto: " + pc.texto(bien))
malo = bien + [{"nombre": "Antivirus", "estado": pc.MAL, "detalle": "apagado"}]
t = pc.texto(malo)
ok("Antivirus" in t and "<b>A</b>" not in t, "solo lo malo: " + t)

# Revisión con administrador (opcional)
ok(pc.admin() is None, "sin instalar: None")
(CARPETA / "admin").mkdir()
(CARPETA / "admin" / "revision_admin.json").write_text(json.dumps(
    {"imagen": "Healthy", "discos": [{"FriendlyName": "Samsung SSD", "Wear": 3, "Temperature": 41, "ReadErrorsUncorrected": 0}],
     "inicios_fallidos": 0}), encoding="utf-8")
e, d = pc.admin()
ok(e == pc.OK and "sanos" in d, "admin bien: " + d)
(CARPETA / "admin" / "revision_admin.json").write_text(json.dumps({"imagen": "Repairable", "discos": [],
                                                                  "inicios_fallidos": 25}), encoding="utf-8")
e, d = pc.admin()
ok(e == pc.AVISO and "RestoreHealth" in d and "25" in d, "admin con problemas: " + d)

(CARPETA / "admin" / "revision_admin.json").write_text(json.dumps({"imagen": "Healthy", "discos": [], "inicios_fallidos": 18,
    "externos": 0, "locales": [{"ip": "192.168.100.225", "veces": 16}]}), encoding="utf-8")
e, d = pc.admin()
ok(e == pc.OK and "192.168.100.225" in d and "no es un ataque" in d, "equipo de la casa: " + d)
(CARPETA / "admin" / "revision_admin.json").write_text(json.dumps({"imagen": "Healthy", "discos": [], "inicios_fallidos": 30,
    "externos": 12, "locales": []}), encoding="utf-8")
e, d = pc.admin()
ok(e == pc.AVISO and "FUERA" in d, "intentos de afuera: " + d)

# Temporales: borra SOLO lo viejo de %TEMP% de prueba; lo nuevo y lo de fuera se quedan
temp = CARPETA / "temp"
(temp / "sub").mkdir(parents=True)
afuera = CARPETA / "no_tocar.txt"
afuera.write_text("x")
viejo1, viejo2, nuevo = temp / "viejo.tmp", temp / "sub" / "viejo2.log", temp / "nuevo.tmp"
for p in (viejo1, viejo2, nuevo):
    p.write_bytes(b"x" * 1000)
hace = time.time() - 5 * 86400
for p in (viejo1, viejo2, afuera):
    os.utime(p, (hace, hace))
os.environ["TEMP"] = str(temp)
gb = pc.limpiar_temporales()
ok(not viejo1.exists() and not viejo2.exists(), "no borró los viejos")
ok(nuevo.exists() and afuera.exists(), "borró algo que no debía")
ok(abs(gb - 2000 / 1e9) < 1e-12, "GB liberados: %s" % gb)

print("Casos:", total)
if fallos:
    print("\nFALLOS:", len(fallos))
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("TODO BIEN: %d de %d (100 %%)" % (total, total))
