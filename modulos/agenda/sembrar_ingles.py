"""Crea (una sola vez) los bloques de estudio e ingles segun el perfil del usuario.

Lunes y martes 19:00-20:00 (flexible) y sabado y domingo 10:00-11:00.
Se pueden cambiar o borrar despues desde Telegram o desde Google Calendar.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modulos.agenda import eventos  # noqa: E402
from modulos.comun.base import ahora  # noqa: E402

BLOQUES = [
    ("Estudio e inglés", "lunes,martes", "19:00", "20:00",
     "Hora flexible: empiece cuando haya comido y descansado."),
    ("Estudio e inglés (fin de semana)", "sabado,domingo", "10:00", "11:00",
     "Bloque de fin de semana; ajuste la hora si lo prefiere."),
]

existentes = {e["titulo"] for e in eventos.activos()}
for titulo, dias, ini, fin, nota in BLOQUES:
    if titulo in existentes:
        print("Ya existe: " + titulo)
        continue
    eid = eventos.crear(titulo, ahora().date(), ini, fin, dias, None, 0, nota)
    try:
        eventos.subir(eid)
        print("Creado y subido a Google: " + eventos.descripcion(eventos.obtener(eid)))
    except Exception as exc:
        print("Creado (sin Google por ahora: " + str(exc)[:80] + "): " + titulo)
