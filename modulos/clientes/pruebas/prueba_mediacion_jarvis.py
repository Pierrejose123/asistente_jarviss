"""Prueba de la demo de mediación dentro de Jarvis (sin Telegram real, IA simulada, datos temporales).
python modulos\\clientes\\pruebas\\prueba_mediacion_jarvis.py"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from modulos.clientes import telegram_mediacion as T  # noqa: E402

TMP = Path(tempfile.mkdtemp())
T.ARCHIVO = TMP / "clientes.json"
real = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"I:\Clientes\centro_mediacion")
T.ARCHIVO.write_text(json.dumps({"mediacion": str(real)}), encoding="utf-8")
M = T.modulo()
M.DB, M.DOCS, M.CONFIG = TMP / "m.db", TMP / "docs", TMP / "config.json"
M.ia = lambda *a, **k: {"hechos": "Hechos.", "obligaciones": ["María pagará 600."], "pendientes": []} if k.get("esquema") or (len(a) > 2 and a[2]) else "Traiga su cédula."


class Msg:
    def __init__(self):
        self.textos, self.docs = [], []

    async def reply_text(self, t, **k):
        self.textos.append(t)

    async def reply_document(self, f, filename=None, **k):
        self.docs.append(filename)


class Bot:
    async def send_chat_action(self, *a, **k):
        pass


class Upd:
    def __init__(self):
        self.effective_message = Msg()
        self.effective_chat = type("C", (), {"id": 1})()

    def get_bot(self):
        return Bot()


BIEN, MAL = 0, 0


def ver(n, c):
    global BIEN, MAL
    BIEN, MAL = (BIEN + 1, MAL) if c else (BIEN, MAL + 1)
    if not c:
        print("MAL:", n)


def enviar(t):
    u = Upd()
    r = asyncio.run(T.intentar(u, t))
    return r, u.effective_message


r, m = enviar("agenda de hoy")
ver("fuera del modo no se mete", r is False)
r, m = enviar("resumen del mes")
ver("fuera del modo: resumen es de Jarvis", r is False)
r, m = enviar("mediación: casos abiertos")
ver("una sola frase", r is True and "No hay casos abiertos" in m.textos[0] and not T.activo())
r, m = enviar("modo mediación")
ver("entrar", r is True and T.activo())
r, m = enviar("carga la demo")
ver("demo", "Cargué 5" in m.textos[0])
r, m = enviar("agenda de la semana")
ver("agenda semana en modo", r is True and "Audiencias de la semana" in m.textos[0])
r, m = enviar("invitación del caso 1")
ver("invitación manda archivo y texto", m.docs and m.docs[0].endswith(".docx") and any("WhatsApp" in x for x in m.textos))
r, m = enviar("caso 1 acuerdo total: María pagará 600 dólares en 3 cuotas de 200")
ver("acta", m.docs and "acta_total" in m.docs[0])
r, m = enviar("cuánto gasté este mes en comida xyz")
ver("pregunta que no es del centro pasa a Jarvis", r is False)
r, m = enviar("¿qué documentos debo traer a la audiencia?")
ver("pregunta del centro la responde el centro", r is True and "cédula" in m.textos[0])
r, m = enviar("asdf qwer zxcv")
ver("lo no entendido pasa a Jarvis", r is False)
r, m = enviar("compré 20 de gasolina")
ver("frase de Jarvis pasa", r is False)
r, m = enviar("salir de mediación")
ver("salir", r is True and not T.activo())
r, m = enviar("agenda de la semana")
ver("después de salir, Jarvis", r is False)
enviar("modo mediación")
T.ESTADO["ultimo"] -= T.VENCE + 1
ver("se apaga solo", not T.activo())
print("MEDIACION EN JARVIS: " + str(BIEN + MAL) + " | BIEN: " + str(BIEN) + " | MAL: " + str(MAL))
