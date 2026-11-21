"""Prueba del filtro de noticias de la empresa (19-11): que no entren deportes ni noticias que no son de IA, y que
«IA en Ecuador» sea de Ecuador. Base TEMPORAL, sin internet.
    .\\.venv\\Scripts\\python.exe modulos\\empresa\\pruebas\\prueba_filtro_empresa.py
"""
import sys
import tempfile
from contextlib import closing
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
CONSOLA = sys.__stdout__

from modulos.comun import db  # noqa: E402

db.ARCHIVO = Path(tempfile.mkdtemp()) / "prueba_filtro_empresa.db"
from modulos.comun import modo_prueba  # noqa: E402

assert modo_prueba.activo(), "La protección de pruebas no está activa: no sigo."
from modulos.empresa import empresa as E  # noqa: E402

fallos, total = [], 0


def ok(cond, que):
    global total
    total += 1
    if not cond:
        fallos.append(que)


CASOS = [  # (titulo, resumen, categoria de la búsqueda, esperado)
    ("Ecuador vence a Nueva Caledonia en su debut en el Mundial Sub-17 de Qatar 2026", "", "ia_ecuador", None),
    ("AI Business Forum 2027: Claves de la IA estratégica en la empresa española", "", "ia_ecuador", "ia_mundo"),
    ("Inteligencia artificial: seis recomendaciones para proteger los datos de las empresas", "", "ia_ecuador", "ia_mundo"),
    ("La Audiencia Provincial de Madrid confirma la condena a un despacho de abogados que no pagó a un detective "
     "privado por investigar a sus propios letrados", "", "publico", None),
    ("El uso de IA en los bufetes de abogados centra la primera edición de Legal Tech Expo", "", "publico", "publico"),
    ("Generative AI in Family Law: California Puts a Lawyer's AI", "", "publico", "publico"),
    ("Ricoh: automatización e IA redefinirán la industria gráfica", "", "oportunidad", "oportunidad"),
    ("Marketing, negocios digitales e IA: una nueva carrera apuesta por perfiles híbridos", "", "oportunidad", "oportunidad"),
    ("Ecuador lanza su primer ‘Sandbox’ de IA", "", "ia_ecuador", "ia_ecuador"),
    ("Kampi busca impulsar el negocio acuícola con la inteligencia artificial", "<a>Startup de Guayaquil</a>",
     "ia_ecuador", "ia_ecuador"),
    ("Colombia aprueba su política de inteligencia artificial", "", "ia_ecuador", "ia_latam"),
    ("Quito acoge el primer mundial de robótica con IA", "", "ia_ecuador", "ia_ecuador"),
    ("Precio del dólar hoy en Ecuador", "", "ia_ecuador", None),
    ("La IA llega a las pymes de España", "", "ia_latam", "ia_mundo"),
    ("Chatbots para restaurantes en México crecen 40 %", "", "ia_latam", "ia_latam"),
    ("Daleki Lab abre oficina en Guayaquil", "", "competidor", "competidor"),
    ("Partido de la Liga Pro termina en empate", "", "competidor", "competidor"),
    ("Día del abogado: los retos de la profesión", "", "publico", None),
]
for titulo, resumen, cat, esperado in CASOS:
    r = E.filtrar({"titulo": titulo, "resumen": resumen, "categoria": cat})
    ok(r == esperado, "%s [%s] -> %s (esperaba %s)" % (titulo[:60], cat, r, esperado))

# lo ya guardado se limpia
filas = [("f1", "Ecuador vence a Nueva Caledonia en el Mundial Sub-17", "ia_ecuador"),
         ("f2", "Claves de la IA en la empresa española", "ia_ecuador"),
         ("f3", "Ecuador lanza su primer Sandbox de IA", "ia_ecuador"),
         ("f4", "Partido raro", "competidor")]
with closing(E._con()) as con, con:
    for clave, titulo, cat in filas:
        con.execute("INSERT INTO emp_hallazgos (clave, titulo, enlace, fuente, fecha, resumen, categoria, competidor, "
                    "relevancia, creado) VALUES (?, ?, '', '', NULL, '', ?, NULL, 10, ?)",
                    (clave, titulo, cat, E.ahora().isoformat(timespec="seconds")))
borrados, movidos = E.limpiar_guardados()
ok((borrados, movidos) == (1, 1), "limpiar guardados: %s" % ((borrados, movidos),))
with closing(E._con()) as con:
    quedan = {f["clave"]: f["categoria"] for f in con.execute("SELECT clave, categoria FROM emp_hallazgos")}
ok(quedan == {"f2": "ia_mundo", "f3": "ia_ecuador", "f4": "competidor"}, "quedan: %s" % quedan)
ok(E.limpiar_guardados() == (0, 0), "la segunda vez no cambia nada")

if fallos:
    CONSOLA.write("FILTRO EMPRESA: FALLOS %d\n" % len(fallos) + "".join(" - %s\n" % f for f in fallos))
    sys.exit(1)
CONSOLA.write("FILTRO EMPRESA: TODO BIEN %d de %d\n" % (total, total))
