"""Da permiso de SOLO LECTURA de Gmail al asistente (una vez; en modo Prueba de Google, cada 7 dias).

Abre el navegador con la pantalla oficial de Google. El permiso pedido es "gmail.readonly":
ver correos, sin poder enviar, borrar ni modificar nada. Se guarda en credenciales/token_gmail.json
(fuera de Git). Para quitarlo: https://myaccount.google.com/permissions -> "Asistente personal" -> Quitar acceso.

Ejecutar:  .\\.venv\\Scripts\\python.exe modulos\\finanzas\\conectar_gmail.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modulos.finanzas import correos  # noqa: E402


def main():
    print("Abriendo Google en su navegador para dar permiso de SOLO LECTURA de Gmail...")
    print("Si aparece 'Google no verifico esta app': Configuracion avanzada -> Ir a Asistente personal (es su propio proyecto).\n")
    try:
        srv = correos.servicio(interactivo=True)
    except Exception as exc:
        texto = str(exc)
        if "accessNotConfigured" in texto or "has not been used" in texto or "disabled" in texto:
            print("Falta activar la API de Gmail en su proyecto de Google Cloud (vea las instrucciones de Claude).")
        raise
    try:
        perfil = srv.users().getProfile(userId="me").execute()
    except Exception as exc:
        if "accessNotConfigured" in str(exc) or "has not been used" in str(exc) or "disabled" in str(exc):
            sys.exit("\nPermiso dado, pero la API de Gmail esta desactivada en su proyecto. Activela y vuelva a ejecutar.")
        raise
    print("Conectado a Gmail (" + str(perfil.get("messagesTotal", "?")) + " correos). Solo lectura.")
    res = srv.users().messages().list(userId="me", q=correos.BUSQUEDA + " newer_than:45d", maxResults=50).execute()
    n = len(res.get("messages", []))
    print("Correos de consumo encontrados en los ultimos 45 dias: " + str(n))
    print("\nReinicie el asistente:  .\\.venv\\Scripts\\python.exe modulos\\comun\\control.py reiniciar")
    print("Al arrancar importara esos consumos y le enviara un resumen por Telegram.")


if __name__ == "__main__":
    main()
