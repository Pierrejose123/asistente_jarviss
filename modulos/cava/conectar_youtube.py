"""Conecta el canal de YouTube de José Luis Cava para avisar de videos nuevos.

Usa el canal de noticias (RSS) oficial que YouTube da para cada canal: solo título, enlace y fecha.
No descarga videos ni transcripciones.

Uso:
  .\\.venv\\Scripts\\python.exe modulos\\cava\\conectar_youtube.py https://www.youtube.com/@BolsaCava
  .\\.venv\\Scripts\\python.exe modulos\\cava\\conectar_youtube.py UCxxxxxxxxxxxxxxxxxxxxxx   (ID del canal)
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests  # noqa: E402

from modulos.cava import cava  # noqa: E402

NS = {"a": "http://www.w3.org/2005/Atom"}


def id_del_canal(entrada):
    entrada = entrada.strip().rstrip("/")
    if re.fullmatch(r"UC[\w-]{22}", entrada):
        return entrada
    m = re.search(r"/channel/(UC[\w-]{22})", entrada)
    if m:
        return m.group(1)
    if not entrada.startswith("http"):
        entrada = "https://www.youtube.com/" + (entrada if entrada.startswith("@") else "@" + entrada)
    html = requests.get(entrada, timeout=20, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "es"}).text
    m = (re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', html)
         or re.search(r'<meta itemprop="(?:channelId|identifier)" content="(UC[\w-]{22})"', html)
         or re.search(r'"externalId":"(UC[\w-]{22})"', html))
    return m.group(1) if m else None


def main():
    entrada = sys.argv[1] if len(sys.argv) > 1 else input("Pegue el enlace del canal (ej. https://www.youtube.com/@BolsaCava): ")
    try:
        cid = id_del_canal(entrada)
    except Exception as exc:
        sys.exit("No pude abrir YouTube: " + str(exc))
    if not cid:
        sys.exit("No encontré el ID del canal. En YouTube, abra el canal → «Más información» → «Compartir canal» → "
                 "«Copiar ID del canal», y ejecute este script con ese ID (empieza por UC).")
    print("ID del canal encontrado: " + cid)
    try:
        raiz = ET.fromstring(cava.leer_feed(cid))
    except Exception as exc:
        print(str(exc) + ".\nA veces YouTube da 404 a todos los canales durante unas horas; luego vuelve solo.")
        if input("¿Guardo el canal igualmente? El bot seguirá intentando cada hora (s/n): ").strip().lower() \
                in ("s", "si", "sí"):
            cava.guardar_ajustes(canal_id=cid, canal_youtube="José Luis Cava")
            print("Guardado. Cuando YouTube responda, el bot marcará los videos que ya existen y le avisará de los nuevos.")
            return
        sys.exit("No guardé nada.")
    nombre = raiz.findtext("a:title", "", NS)
    print("\nCanal: " + nombre + "  (" + cid + ")")
    print("Últimos videos:")
    for e in raiz.findall("a:entry", NS)[:3]:
        print("  • " + e.findtext("a:published", "", NS)[:10] + "  " + e.findtext("a:title", "", NS))
    if input("\n¿Es este el canal? (s/n): ").strip().lower() not in ("s", "si", "sí"):
        sys.exit("No guardé nada.")
    cava.guardar_ajustes(canal_id=cid, canal_youtube=nombre)
    cava.revisar_videos()                    # marca los existentes como vistos: solo avisará de los nuevos
    print("\nListo. Guardado en config\\cava.json. El bot revisa cada hora y le avisa de cada video nuevo.")


if __name__ == "__main__":
    main()
