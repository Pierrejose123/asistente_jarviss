"""Diagnóstico (solo lectura): qué correos mandó el Banco Pichincha en los últimos días y qué hizo el asistente con cada uno.
    python modulos\\finanzas\\diag_pichincha.py [dias]
"""
import sys
from contextlib import closing
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from modulos.finanzas import correos, cuentas  # noqa: E402


def main(dias=6):
    srv = correos.servicio()
    res = srv.users().messages().list(userId="me", q="from:pichincha.com newer_than:%dd" % dias, maxResults=60).execute()
    items = res.get("messages", [])
    print("Correos de pichincha.com en %d días: %d" % (dias, len(items)))
    for item in items:
        msg = srv.users().messages().get(userId="me", id=item["id"], format="full").execute()
        cab = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        try:
            fecha = parsedate_to_datetime(cab.get("date")).astimezone(cuentas.ZONA).strftime("%d/%m %H:%M")
        except Exception:
            fecha = "?"
        with closing(cuentas._con()) as con:
            v = con.execute("SELECT tipo FROM cuenta_vistos WHERE ref=?", ("gmail:" + item["id"],)).fetchone()
        plano = " ".join((correos._cuerpo(msg["payload"]) or "").split())
        banco = correos.banco_del_remitente(cab.get("from", ""))
        lectura = cuentas.LECTORES.get(banco, lambda p: None)(plano) if banco in cuentas.LECTORES else None
        print("\n--- %s | de: %s | asunto: %s" % (fecha, cab.get("from", ""), cab.get("subject", "")))
        print("    visto por el asistente: %s | banco detectado: %s | lectura: %s" % (v["tipo"] if v else "NO", banco, lectura))
        if not lectura or lectura.get("ignorar"):
            print("    texto: " + plano[:700])
    print("\nSaldo estimado Pichincha:", cuentas.saldo("Pichincha"))
    with closing(cuentas._con()) as con:
        for f in con.execute("SELECT cuando, sentido, monto, clase, decision, descripcion FROM cuenta_movs WHERE cuenta='Pichincha' "
                             "ORDER BY cuando DESC LIMIT 15"):
            print("   ", dict(f))


if __name__ == "__main__":
    import traceback
    salida = Path(__file__).resolve().parents[2] / "para_claude_salida.txt"
    with open(salida, "w", encoding="utf-8") as f:             # escribe su propio archivo (no depende de cmd)
        sys.stdout = sys.stderr = f
        print("Diagnóstico Pichincha iniciado")
        try:
            main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
        except Exception:
            traceback.print_exc()
        print("FIN")
