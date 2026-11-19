"""Revisa que la PC pueda conectarse de forma segura (TLS) con Telegram, Google y Moodle.

Jarvis usa los certificados de Windows (paquete truststore, activado en comun/base.py), así funciona aunque un
antivirus como Avast revise las conexiones seguras. Si falta truststore, esta prueba lo instala.
Si falla, anota en logs/red.log quién firmó el certificado recibido: así se ve si un antivirus,
un proxy o la red está interceptando las conexiones. No envía nada; solo abre y cierra la conexión.
"""
import os
import socket
import ssl
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
LOG = RAIZ / "logs" / "red.log"
SITIOS = ["api.telegram.org", "www.google.com", "pypi.org"]


def _nombre(campo):
    return ", ".join("=".join(x) for par in (campo or ()) for x in par)


def revisar(host, contexto):
    try:
        with socket.create_connection((host, 443), timeout=10) as s, contexto.wrap_socket(s, server_hostname=host) as t:
            c = t.getpeercert()
            return True, "emisor: " + _nombre(c.get("issuer"))
    except ssl.SSLCertVerificationError as exc:
        detalle = str(exc.verify_message)
        try:                                   # ver quién firmó, sin confiar en él
            sin = ssl.create_default_context()
            sin.check_hostname = False
            sin.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, 443), timeout=10) as s, sin.wrap_socket(s, server_hostname=host) as t:
                der = t.getpeercert(binary_form=True)
            pem = ssl.DER_cert_to_PEM_cert(der)
            tmp = LOG.parent / ("cert_" + host + ".pem")
            tmp.write_text(pem, encoding="ascii")
            info = ssl._ssl._test_decode_cert(str(tmp))
            detalle += " | emisor: " + _nombre(info.get("issuer")) + " | para: " + _nombre(info.get("subject"))
        except Exception as e2:
            detalle += " | (no pude leer el certificado: " + str(e2) + ")"
        return False, detalle
    except Exception as exc:
        return False, type(exc).__name__ + ": " + str(exc)


def _truststore(lineas):
    try:
        import truststore
        return truststore
    except ImportError:
        pass
    import subprocess
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "truststore"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
    lineas.append("instalé truststore: " + ("bien" if r.returncode == 0 else "FALLÓ " + (r.stdout + r.stderr)[-300:]))
    try:
        import importlib
        importlib.invalidate_caches()
        import truststore
        return truststore
    except ImportError:
        return None


def main():
    LOG.parent.mkdir(exist_ok=True)
    lineas = [time.strftime("%Y-%m-%d %H:%M:%S") + " revisión de red"]
    ts = _truststore(lineas)
    variables = sorted(k for k in os.environ if any(p in k.upper() for p in ("SSL", "CERT", "PROXY", "CA_BUNDLE")))
    lineas.append("variables: " + (", ".join(variables) or "ninguna"))
    try:
        import certifi
        ruta = Path(certifi.where())
        lineas.append("certifi " + certifi.__version__ + ": " + str(ruta) + " (" + str(ruta.stat().st_size) + " bytes)")
        ctx = ssl.create_default_context(cafile=str(ruta))
    except Exception as exc:
        lineas.append("certifi: " + str(exc))
        ctx = ssl.create_default_context()
    sistema = ssl.create_default_context()
    malos = 0
    for host in SITIOS:
        ok, txt = revisar(host, ctx)
        lineas.append(("OK  " if ok else "--  ") + host + " (lista propia de Python) " + txt)
        if ts:
            ok, txt = revisar(host, ts.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
            lineas.append(("OK  " if ok else "MAL ") + host + " (Windows, como Jarvis) " + txt)
        else:
            ok, txt = revisar(host, sistema)
            lineas.append(("OK  " if ok else "MAL ") + host + " (Windows, sin truststore) " + txt)
            ok = False
        malos += not ok
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print("\n".join(lineas))
    if malos:
        print("FALLOS: %d sitio(s) sin conexión segura (ver logs/red.log)" % malos)
        sys.exit(1)
    print("RED: TODO BIEN %d de %d" % (len(SITIOS), len(SITIOS)))


if __name__ == "__main__":
    main()
