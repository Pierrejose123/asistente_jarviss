"""Fase 2, voz: "hey Jarvis" conectado al MISMO cerebro que Telegram.

- Mismas herramientas (tareas, actividades, Google Calendar), agenda real y memoria que el bot.
- Lo que hace por voz (crear, cambiar, borrar) tambien llega a Telegram (regla de 2 canales);
  los borrados se confirman con botones en Telegram.
- Mide cada etapa (grabar, entender, pensar, primera palabra) y la guarda en logs/voz_tiempos.csv.

Arranca sola con Windows (supervisor.py). A mano: jarvis-voz.cmd (solo si la de fondo esta detenida).
Lo que muestra en segundo plano queda en logs/voz_salida.log.
Ajustes:   config/voz.json
"""
import asyncio
import gc
import glob
import io
import os
import queue
import re
import sys
import threading
import time
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modulos.comun.base import CONFIG, NOMBRE, RAIZ, ahora, enviar_telegram, leer_json, registro  # noqa: E402
from modulos.ingles import conversacion  # noqa: E402

log = registro("voz")

AJUSTES = {"microfono": "razer", "whisper": "auto", "whisper_dispositivo": "auto", "umbral_activacion": 0.5,
           "segundos_seguimiento": 6, "voz": "es-ES-AlvaroNeural", "velocidad": "-5%", "tono": "-6Hz",
           "copiar_a_telegram": True, "efecto": "jarvis", "intensidad_efecto": 0.6,
           "vocabulario": ["pinceles", "afiche", "Illustrator", "Photoshop", "Blender"],
           "correcciones": {"namas": "nada m\u00e1s", "na mas": "nada m\u00e1s", "hey yarvis": "hey Jarvis"}}
if (CONFIG / "voz.json").exists():
    AJUSTES.update(leer_json("voz.json"))

TASA = 16000
BLOQUE = 1280                      # 80 ms (lo que pide el detector de "hey Jarvis")
DESPEDIDAS = ("eso es todo", "nada mas", "nada más", "namas", "na mas", "es todo", "ya está", "ya esta", "adios", "adiós", "hasta luego", "gracias jarvis",
              "puedes descansar", "terminamos", "chao", "chau")
ALUCINACIONES = ("subtitulos", "subtítulos", "gracias por ver", "amara.org", "suscribete", "suscríbete",
                 "thanks for watching", "thank you for watching", "subscribe to", "subtitles by")
ACCIONES = {"crear_tarea", "crear_evento", "editar_evento", "marcar_hecha", "borrar_tarea", "borrar_evento",
            "recordar", "actualizar_recuerdo", "olvidar_recuerdo"}
TIEMPOS = RAIZ / "logs" / "voz_tiempos.csv"


def decir_pantalla(msg):
    print(msg, flush=True)


def pitido(freq=880, ms=150):
    try:
        import winsound
        winsound.Beep(freq, ms)
    except Exception:
        pass


# ------------------------------------------------------------------ microfono ---
def elegir_microfono():
    import sounddevice as sd
    entradas = [(i, d) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    for i, d in entradas:
        if AJUSTES["microfono"].lower() in d["name"].lower():
            try:
                sd.check_input_settings(device=i, samplerate=TASA, channels=1, dtype="int16")
            except Exception:
                continue
            sd.default.device = (i, sd.default.device[1])
            decir_pantalla("Microfono: " + d["name"])
            return
    decir_pantalla("No encontre el microfono '" + AJUSTES["microfono"] + "'; uso el predeterminado de Windows.")


def cargar_detector():
    import openwakeword.utils
    from openwakeword.model import Model
    openwakeword.utils.download_models(model_names=["hey_jarvis"])
    return Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")


def esperar_hey_jarvis(detector):
    """True cuando oye "hey Jarvis"; False si se abrio un juego o app de diseno (hay que pausar)."""
    import numpy as np
    import sounddevice as sd
    from modulos.comun import modos
    detector.reset()
    with sd.InputStream(samplerate=TASA, channels=1, dtype="int16", blocksize=BLOQUE) as flujo:
        for _ in range(6):
            flujo.read(BLOQUE)
        while True:
            datos, _ = flujo.read(BLOQUE)
            if max(detector.predict(np.squeeze(datos)).values(), default=0) >= AJUSTES["umbral_activacion"]:
                return True
            if modos.en_modo_ligero():          # revisa los procesos como mucho cada 5 s
                return False


def pausar_por_modo():
    """Espera (sin microfono ni tarjeta grafica) a que se cierre el juego o la app de diseno."""
    from modulos.comun import modos
    modo, programa = modos.modo_actual(0)
    decir_pantalla("\n" + modos.texto_modo(modo, programa) + ": voz en pausa, tarjeta grafica libre.")
    log.info("Voz en pausa por %s (%s)", modo, programa)
    modos.liberar_tarjeta()
    while modos.en_modo_ligero():
        time.sleep(5)
    decir_pantalla("Modo normal: vuelvo a escuchar.")
    log.info("Voz reanudada")


_RUIDO = [0.01]          # nivel de ruido de la habitacion (se va ajustando en los silencios)


def grabar(espera=5.0, silencio_fin=0.9, maximo=20.0):
    """Graba hasta que deje de hablar. Guarda 0,5 s ANTES de detectar la voz para no cortar la primera palabra."""
    import collections
    import numpy as np
    import sounddevice as sd
    trozo = int(TASA * 0.03)
    previo = collections.deque(maxlen=17)                # ~0,5 s de colchon
    partes, hablando, callado, t0 = [], False, 0.0, time.monotonic()
    with sd.InputStream(samplerate=TASA, channels=1, dtype="int16", blocksize=trozo) as flujo:
        while True:
            datos, _ = flujo.read(trozo)
            datos = np.squeeze(datos).astype(np.float32) / 32768
            nivel = float(np.sqrt(np.mean(datos ** 2)))
            umbral = max(_RUIDO[0] * 2.5, 0.006)
            if nivel > umbral:
                if not hablando:
                    partes.extend(previo)
                hablando, callado = True, 0.0
            elif hablando:
                callado += 0.03
            else:
                _RUIDO[0] = 0.95 * _RUIDO[0] + 0.05 * nivel     # aprende el ruido mientras usted calla
            if hablando:
                partes.append(datos)
                if callado >= silencio_fin or len(partes) * 0.03 >= maximo:
                    break
            else:
                previo.append(datos)
                if time.monotonic() - t0 > espera:
                    return None
    return np.concatenate(partes) if partes else None


# ------------------------------------------------------------------ voz a texto ---
def _librerias_cuda():
    """Si se instalaron nvidia-cublas-cu12 / nvidia-cudnn-cu12 con pip, Windows debe saber donde estan sus DLL."""
    import site
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        for carpeta in glob.glob(os.path.join(base, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(carpeta)
            except (AttributeError, OSError):
                pass
            os.environ["PATH"] = carpeta + os.pathsep + os.environ.get("PATH", "")


def _carpeta_modelos():
    try:
        from modulos.comun.base import PESADO as pesado
        if pesado.drive and Path(pesado.drive + "\\").exists():
            carpeta = pesado / "modelos" / "whisper"          # lo pesado va al disco I:
            carpeta.mkdir(parents=True, exist_ok=True)
            return str(carpeta)
    except Exception:
        pass
    return None


def cargar_whisper():
    """Tarjeta grafica con el modelo grande-rapido (large-v3-turbo); si no se puede, procesador con 'small'."""
    import numpy as np
    _librerias_cuda()
    from faster_whisper import WhisperModel
    elegido = AJUSTES["whisper"]
    opciones = [("cuda", "float16", "large-v3-turbo" if elegido == "auto" else elegido),
                ("cpu", "int8", "small" if elegido == "auto" else elegido)]
    if AJUSTES["whisper_dispositivo"] == "cpu":
        opciones = opciones[1:]
    for dispositivo, tipo, nombre in opciones:
        try:
            decir_pantalla("Cargando Whisper '" + nombre + "' (la primera vez se descarga)...")
            modelo = WhisperModel(nombre, device=dispositivo, compute_type=tipo, download_root=_carpeta_modelos())
            list(modelo.transcribe(np.zeros(TASA, dtype=np.float32), language="es")[0])   # prueba real
            decir_pantalla("Whisper '" + nombre + "' en " + ("tarjeta grafica" if dispositivo == "cuda" else "procesador"))
            return modelo
        except Exception as exc:
            if dispositivo == "cuda":
                decir_pantalla("(Whisper no pudo usar la tarjeta grafica: " + str(exc)[:80] + " -> uso el procesador)")
            else:
                raise


def vocabulario():
    """Palabras que Whisper debe esperar: materias, actividades, nombres propios y las que usted agregue."""
    palabras = ["Jarvis", "se\u00f1or", "Teams", "Google Calendar", "Telegram", "tarea",
                "gimnasio", "ingl\u00e9s", "recu\u00e9rdame", "agenda", "nada m\u00e1s",
                "nota Cava", "Jos\u00e9 Luis Cava", "BolsaCava", "trade", "stop", "objetivo", "resistencia", "soporte"]
    try:
        palabras += [c["materia"] for c in leer_json("horario_clases.json")["clases"]]
        from modulos.agenda import eventos
        palabras += [e["titulo"] for e in eventos.activos()]
    except Exception:
        pass
    palabras += AJUSTES.get("vocabulario", [])
    vistas = []
    for p in palabras:
        if p not in vistas:
            vistas.append(p)
    return "Conversaci\u00f3n con Jarvis, el asistente de " + NOMBRE + ". Palabras frecuentes: " + ", ".join(vistas) + "."


def transcribir(whisper, audio, idioma="es"):
    if audio is None:
        return ""
    guia = vocabulario() if idioma == "es" else "English conversation practice between " + NOMBRE + " and Jarvis."
    segmentos, _ = whisper.transcribe(audio, language=idioma, vad_filter=True, beam_size=5,
                                      initial_prompt=guia, condition_on_previous_text=False)
    texto = " ".join(s.text.strip() for s in segmentos).strip()
    if idioma == "es":
        for mal, bien in AJUSTES.get("correcciones", {}).items():       # errores que se repiten
            texto = re.sub(r"\b" + re.escape(mal) + r"\b", bien, texto, flags=re.I)
    bajo = texto.lower()
    if len(bajo.strip(" .,!?\u00bf\u00a1")) < 2 or any(a in bajo for a in ALUCINACIONES) or "palabras frecuentes" in bajo:
        return ""
    try:
        with open(RAIZ / "logs" / "voz_transcripciones.txt", "a", encoding="utf-8") as f:
            f.write(ahora().strftime("%Y-%m-%d %H:%M:%S") + "  " + texto + "\n")
    except Exception:
        pass
    return texto


# ------------------------------------------------------------------ texto a voz ---
def limpiar_para_voz(texto):
    texto = texto.replace("•", "").replace("#", " numero ")
    texto = re.sub(r"[*_`>|]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def frases(texto):
    """Parte en frases; descarta trozos sin letras (ej. un signo suelto, que rompe la voz neural)."""
    return [f.strip() for f in re.split(r"(?<=[.!?…:;])\s+|\n+", texto) if re.search(r"\w", f)]


def efecto(audio, tasa):
    """Timbre de asistente de IA: un leve brillo metalico + eco corto de sala. 'ninguno' lo apaga."""
    import numpy as np
    if AJUSTES.get("efecto") != "jarvis":
        return audio
    k = float(AJUSTES.get("intensidad_efecto", 0.6))
    x = audio if audio.ndim == 1 else audio.mean(axis=1)

    def retraso(senal, ms):
        n = int(tasa * ms / 1000)
        return np.concatenate([np.zeros(n, dtype=senal.dtype), senal[:-n]])

    y = x + k * (0.30 * retraso(x, 7) + 0.20 * retraso(x, 13))                                # brillo metalico
    y = y + k * (0.14 * retraso(y, 45) + 0.08 * retraso(y, 80) + 0.04 * retraso(y, 125))     # sala
    y = np.concatenate([y, np.zeros(int(tasa * 0.15), dtype=y.dtype)])
    return (y / max(1e-6, float(np.abs(y).max())) * 0.9).astype(np.float32)


def sintetizar(texto, voz=None):
    import edge_tts
    import soundfile as sf

    async def generar():
        audio = b""
        async for parte in edge_tts.Communicate(texto, voz or AJUSTES["voz"], rate=AJUSTES["velocidad"],
                                                pitch=AJUSTES["tono"]).stream():
            if parte["type"] == "audio":
                audio += parte["data"]
        return audio

    audio, tasa = sf.read(io.BytesIO(asyncio.run(generar())), dtype="float32")
    return efecto(audio, tasa), tasa


def hablar_windows(texto):
    import base64
    import subprocess
    b64 = base64.b64encode(texto.encode("utf-8")).decode("ascii")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + b64 + "'));"
                    "Add-Type -AssemblyName System.Speech;$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                    "$v=$s.GetInstalledVoices()|?{$_.VoiceInfo.Culture.Name -like 'es*'}|select -First 1;"
                    "if($v){$s.SelectVoice($v.VoiceInfo.Name)};$s.Speak($t)"], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))   # sin ventana negra


class Locutor:
    """Prepara el audio de la siguiente frase mientras suena la actual."""

    def __init__(self):
        self.frases, self.audios = queue.Queue(), queue.Queue()
        self.primer_sonido = None
        threading.Thread(target=self._sintetizar, daemon=True).start()
        threading.Thread(target=self._reproducir, daemon=True).start()

    def decir(self, texto, voz=None):
        for f in frases(limpiar_para_voz(texto)):
            self.frases.put((f, voz))

    def esperar(self):
        self.frases.join()
        self.audios.join()

    def _sintetizar(self):
        while True:
            f, voz = self.frases.get()
            try:
                self.audios.put(("neural", sintetizar(f, voz)))
            except Exception as exc:
                log.info("Voz neural no disponible: %s", exc)
                self.audios.put(("windows", f))
            finally:
                self.frases.task_done()

    def _reproducir(self):
        import sounddevice as sd
        while True:
            tipo, dato = self.audios.get()
            try:
                if self.primer_sonido is None:
                    self.primer_sonido = time.monotonic()
                if tipo == "neural":
                    sd.play(dato[0], dato[1])
                    sd.wait()
                else:
                    hablar_windows(dato)
            except Exception as exc:
                log.info("Error de audio: %s", exc)
            finally:
                self.audios.task_done()


# ------------------------------------------------------------------ cerebro ---
def pensar(texto):
    from modulos.ia import cerebro
    from modulos.telegram.bot import texto_dia
    respuesta, pendientes = cerebro.responder(texto, None, texto_dia, canal="voz")
    usadas = [h for h in cerebro.ULTIMAS if h in ACCIONES]
    if AJUSTES["copiar_a_telegram"] and (usadas or pendientes):
        try:
            enviar_telegram("\U0001F399 <b>Por voz</b>\n\n<i>" + escape(texto) + "</i>\n\n" + escape(respuesta))
            for accion, num in pendientes:
                datos = "borrarev:" if accion == "borrar_evento" else "borrar:"
                enviar_telegram("¿Confirma el borrado que pidió por voz? (#" + str(num) + ")",
                                [[{"text": "Sí, borrar", "callback_data": datos + str(num)},
                                  {"text": "No", "callback_data": "cancelar"}]])
        except Exception as exc:
            log.info("No pude copiar a Telegram: %s", exc)
    return respuesta


def anotar_tiempos(fila):
    nuevo = not TIEMPOS.exists()
    TIEMPOS.parent.mkdir(exist_ok=True)
    with open(TIEMPOS, "a", encoding="utf-8") as f:
        if nuevo:
            f.write("momento,hablo_s,entender_s,pensar_s,primera_palabra_s,total_hasta_oir_s\n")
        f.write(",".join([ahora().strftime("%Y-%m-%d %H:%M:%S")] + ["%.2f" % x for x in fila]) + "\n")


# ------------------------------------------------------------------ practica de ingles ---
def practicar_ingles(texto, practica, locutor):
    """Turno de la practica de ingles por voz. Devuelve si se sigue conversando."""
    voz_en = conversacion.vocab.ajustes().get("voz_ingles", "en-GB-RyanNeural")
    try:
        if not practica:                                  # "let's practice": empieza
            sid = conversacion.abrir("voz")
            respuesta = conversacion.saludo(sid)
            log.info("Practica de ingles por voz empezada (#%s)", sid)
        elif conversacion.es_fin(texto):                  # "that's all": termina y corrige
            locutor.decir("Great job, sir. Let me check your English.", voz_en)
            conversacion.cerrar(practica["id"])
            texto_html, nuevas = conversacion.texto_correcciones(practica["id"])
            try:
                enviar_telegram(texto_html, conversacion.botones_expresiones(practica["id"], nuevas) or None)
            except Exception as exc:
                log.info("No pude enviar las correcciones a Telegram: %s", exc)
            locutor.esperar()
            locutor.decir(conversacion.resumen_para_voz(practica["id"]))
            locutor.esperar()
            return False
        else:
            respuesta = conversacion.responder(practica["id"], texto)
    except Exception as exc:
        log.warning("Error en la practica de ingles: %s", exc)
        respuesta = "Sorry, sir, I lost my train of thought. Could you say that again?"
    decir_pantalla("Jarvis (EN): " + respuesta)
    locutor.decir(respuesta, voz_en)
    locutor.esperar()
    return True


# ------------------------------------------------------------------ principal ---
def otra_voz_corriendo():
    """True si ya hay OTRA voz escuchando (por ejemplo, la que arranca con Windows).
    Se ignoran el propio proceso, sus padres e hijos (el python del .venv es un lanzador)."""
    try:
        import psutil
        yo = psutil.Process()
        propios = {yo.pid} | {p.pid for p in yo.parents()} | {p.pid for p in yo.children(recursive=True)}
        for p in psutil.process_iter(["pid", "cmdline"]):
            cmd = " ".join(p.info["cmdline"] or [])
            if p.info["pid"] not in propios and ("voz\\voz.py" in cmd or "voz/voz.py" in cmd) \
                    and "python" in cmd.lower():
                return True
    except Exception:
        pass
    return False


def esperar_ollama(cerebro, minutos=5):
    """Al encender la PC, Ollama puede tardar en abrir: se espera hasta 5 minutos."""
    limite = time.monotonic() + minutos * 60
    while True:
        try:
            if cerebro.modelo_listo():
                return True
        except Exception:
            pass
        if time.monotonic() > limite:
            return False
        decir_pantalla("Esperando a Ollama...")
        time.sleep(10)


def main():
    from modulos.ia import cerebro
    if otra_voz_corriendo():
        decir_pantalla("La voz ya esta encendida en segundo plano (arranca con Windows).\n"
                       "Diga 'hey Jarvis' directamente. Para verla en esta ventana, primero:\n"
                       "  .\\.venv\\Scripts\\python.exe modulos\\comun\\control.py detener")
        return
    from modulos.comun import modos
    decir_pantalla("Preparando la voz del asistente...")
    elegir_microfono()
    detector = cargar_detector()
    if modos.en_modo_ligero():              # se encendio la PC con un juego ya abierto
        pausar_por_modo()
    whisper = cargar_whisper()
    if not esperar_ollama(cerebro):
        decir_pantalla("Ollama no esta listo. Abra la app de Ollama y vuelva a intentar.")
        log.warning("Ollama no respondio en 5 minutos; la voz se reintentara")
        sys.exit(1)
    cerebro._simple("hola")                 # deja el modelo cargado en la tarjeta grafica
    locutor = Locutor()
    decir_pantalla("\nListo. Diga 'hey Jarvis' y su orden. (Ctrl + C para salir)")
    log.info("Voz iniciada")
    conversando = False
    while True:
        if not conversando:
            decir_pantalla("\nEscuchando... diga 'hey Jarvis'")
            if not esperar_hey_jarvis(detector):
                whisper = None                      # suelta Whisper de la tarjeta grafica
                gc.collect()
                pausar_por_modo()
                whisper = cargar_whisper()
                cerebro._simple("hola")             # vuelve a cargar el modelo grande
                continue
            pitido()
            decir_pantalla("Le escucho, señor.")
            espera = 5.0
        else:
            time.sleep(0.3)
            decir_pantalla("(sigo escuchando...)")
            espera = AJUSTES["segundos_seguimiento"]
        practica = conversacion.abierta("voz")            # practica de ingles abierta (la comparte el bot)
        if practica and conversando:
            espera = max(espera, 12.0)                    # en ingles se piensa un poco mas
        t0 = time.monotonic()
        audio = grabar(espera, silencio_fin=1.4 if practica else 0.9)
        t1 = time.monotonic()
        texto = transcribir(whisper, audio, "en" if practica else "es")
        t2 = time.monotonic()
        if not texto:
            if conversando:
                conversando = False
                pitido(520, 120)
                decir_pantalla("(en espera; diga 'hey Jarvis' para volver)")
            else:
                pitido(440, 200)
                decir_pantalla("No le entendi, intente de nuevo.")
            continue
        decir_pantalla("Usted: " + texto)
        if practica or conversacion.PIDE_PRACTICA.search(texto):
            conversando = practicar_ingles(texto, practica, locutor)
            continue
        if conversando and any(d in texto.lower() for d in DESPEDIDAS):
            locutor.decir("Muy bien, señor. Aquí estaré si me necesita.")
            locutor.esperar()
            conversando = False
            continue
        conversando = True
        try:
            respuesta = pensar(texto)
        except Exception as exc:
            log.warning("Error del cerebro: %s", exc)
            respuesta = "Disculpe, señor, tuve un problema pensando la respuesta."
        t3 = time.monotonic()
        locutor.primer_sonido = None
        locutor.decir(respuesta)
        decir_pantalla("Jarvis: " + respuesta)
        locutor.esperar()
        oir = (locutor.primer_sonido or time.monotonic()) - t3
        fila = (t1 - t0, t2 - t1, t3 - t2, oir, (t2 - t1) + (t3 - t2) + oir)
        decir_pantalla("   [tiempos] usted hablo %.1fs | entender %.1fs | pensar %.1fs | primera palabra %.1fs "
                       "| espera total %.1fs" % fila)
        anotar_tiempos(fila)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        decir_pantalla("Hasta luego, señor.")
