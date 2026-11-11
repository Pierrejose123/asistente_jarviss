"""Fase 1, paso 1: comprueba el token del bot y guarda tu user_id en .env."""
import sys
import time
from pathlib import Path

import requests
from dotenv import dotenv_values, set_key

RAIZ = Path(__file__).resolve().parents[2]
ENV = RAIZ / ".env"

token = (dotenv_values(ENV).get("TELEGRAM_BOT_TOKEN") or "").strip()
if not token:
    sys.exit("No encontre TELEGRAM_BOT_TOKEN en el archivo .env")

API = "https://api.telegram.org/bot" + token + "/"

yo = requests.get(API + "getMe", timeout=15).json()
if not yo.get("ok"):
    sys.exit("Telegram rechazo el token. Revisa que lo copiaste completo en .env")
print("Token correcto. Tu bot es: @" + yo["result"]["username"])

print("Ahora, desde tu celular, escribele cualquier mensaje a tu bot (por ejemplo: hola).")
print("Esperando hasta 2 minutos...")
usuarios = {}
fin = time.time() + 120
while time.time() < fin and not usuarios:
    datos = requests.get(API + "getUpdates", params={"timeout": 20}, timeout=30).json()
    for upd in datos.get("result", []):
        msg = upd.get("message") or upd.get("edited_message")
        if msg and msg.get("chat", {}).get("type") == "private":
            u = msg["from"]
            usuarios[u["id"]] = (u.get("first_name", ""), u.get("username", ""))

if not usuarios:
    sys.exit("No llego ningun mensaje. Escribele al bot y vuelve a ejecutar este script.")

for uid, (nombre, usuario) in usuarios.items():
    print("Mensaje de: " + nombre + " (@" + (usuario or "sin usuario") + ")  user_id = " + str(uid))

if len(usuarios) != 1:
    sys.exit("Le escribio mas de una persona. Avisale a Claude antes de seguir.")

uid = next(iter(usuarios))
if input("Eres tu? (s/n): ").strip().lower() != "s":
    sys.exit("No se guardo nada.")

set_key(str(ENV), "TELEGRAM_USER_ID", str(uid), quote_mode="never")
requests.post(API + "sendMessage", timeout=15, json={
    "chat_id": uid, "text": "Conexi\u00f3n lista, se\u00f1or. Ya s\u00e9 qui\u00e9n es usted."})
print("Listo: user_id guardado en .env y mensaje de prueba enviado a tu Telegram.")