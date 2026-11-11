import asyncio, base64, io, json, os, queue, re, subprocess, sys, threading, time

# ---------------- ajustes ----------------
MODELO_LLM = "qwen3.5:2b"     # modelo de Ollama
USAR_OPENJARVIS = False       # False = rapido (directo a Ollama); True = pasa por OpenJarvis (mas lento)
AGENTE = ""                   # solo con USAR_OPENJARVIS = True; ej. "orchestrator" para usar herramientas
MEMORIA_TURNOS = 10           # cuantas preguntas anteriores recuerda (modo rapido)
NOMBRE = os.getenv("NOMBRE_USUARIO", "Usuario")   # como te llamas (NOMBRE_USUARIO en el .env)
CONVERSACION_FLUIDA = True    # tras responder sigue escuchando sin decir "hey Jarvis"
SEGUNDOS_SEGUIMIENTO = 6      # cuanto espera a que sigas hablando antes de volver a dormir
OLLAMA_URL = "http://localhost:11434"
MICROFONO = "razer"           # parte del nombre del microfono a usar
MODELO_WHISPER = "small"      # tiny / base / small / medium  (base = mas rapido, entiende algo peor)
IDIOMA = "es"
UMBRAL_ACTIVACION = 0.5       # sube a 0.6-0.7 si se activa solo; baja a 0.3-0.4 si no te oye
HABLAR_RESPUESTA = True
MAX_CARACTERES_VOZ = 1500

# Voz (Microsoft neural, necesita internet; si falla usa la voz de Windows)
VOZ = "es-ES-AlvaroNeural"    # otras: es-MX-JorgeNeural, es-US-AlonsoNeural, es-CO-GonzaloNeural
VELOCIDAD = "-5%"             # mas lento: "-15%"   mas rapido: "+10%"
TONO = "-6Hz"                 # mas grave: "-12Hz"  normal: "+0Hz"

PERSONALIDAD = (
    "Eres JARVIS, el asistente personal de " + NOMBRE + ": elegante, sereno, leal y muy eficiente, "
    "con un toque sutil de humor seco, como un mayordomo britanico de confianza. "
    "Esto es una conversacion hablada y continua: responde de forma natural y fluida, "
    "recuerda lo que se dijo antes, y si viene al caso termina con una pregunta breve o un comentario "
    "que invite a seguir conversando, sin forzarlo. "
    "Dirigete a el como \"se\u00f1or " + NOMBRE + "\" en los momentos oportunos, por ejemplo al saludar, "
    "al dar una noticia importante o al despedirte; el resto del tiempo usa solo \"se\u00f1or\" o nada, "
    "para que no suene repetitivo. "
    "Responde siempre en espa\u00f1ol, normalmente en una a tres frases, "
    "sin listas, sin emojis y sin formato markdown, porque tu respuesta se leera en voz alta."
)
DESPEDIDAS = ("eso es todo", "nada mas", "nada m\u00e1s", "adios", "adi\u00f3s", "hasta luego",
              "gracias jarvis", "puedes descansar", "terminamos", "chao", "chau")
ALUCINACIONES = ("subtitulos", "subt\u00edtulos", "gracias por ver", "amara.org", "suscribete",
                 "suscr\u00edbete")
# -----------------------------------------

FRAME = 1280
SAMPLE_RATE = 16000
HISTORIAL = []
FIN_FRASE = re.compile(r"(.+?[.!?\u2026:;])(\s+|$)", re.S)


def log(msg):
    print(msg, flush=True)


def pitido(freq=880, ms=150):
    try:
        import winsound
        winsound.Beep(freq, ms)
    except Exception:
        pass


# ---------------- microfono y activacion ----------------
def elegir_microfono():
    import sounddevice as sd
    entradas = [(i, d) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    candidatos = [(i, d) for i, d in entradas if MICROFONO.lower() in d["name"].lower()]
    if not candidatos:
        log("No encontre un microfono que contenga '" + MICROFONO + "'. Disponibles:")
        for i, d in entradas:
            log("  " + d["name"])
        log("Usando el microfono predeterminado de Windows.")
        return
    for i, d in candidatos:
        try:
            sd.check_input_settings(device=i, samplerate=16000, channels=1, dtype="int16")
        except Exception:
            continue
        sd.default.device = (i, sd.default.device[1])
        log("Microfono: " + d["name"])
        return
    log("El microfono '" + MICROFONO + "' no acepta 16 kHz; usando el predeterminado.")


def cargar_detector():
    import openwakeword.utils
    from openwakeword.model import Model
    log("Preparando la palabra de activacion 'hey Jarvis'...")
    openwakeword.utils.download_models(model_names=["hey_jarvis"])
    return Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")


def esperar_hey_jarvis(detector):
    import numpy as np
    import sounddevice as sd
    detector.reset()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME) as stream:
        for _ in range(6):
            stream.read(FRAME)
        while True:
            data, _ = stream.read(FRAME)
            puntajes = detector.predict(np.squeeze(data).astype(np.int16))
            if max(puntajes.values(), default=0.0) >= UMBRAL_ACTIVACION:
                return


# ---------------- voz a texto ----------------
def cargar_whisper():
    from faster_whisper import WhisperModel
    log("Cargando Whisper '" + MODELO_WHISPER + "'...")
    return WhisperModel(MODELO_WHISPER, device="cpu", compute_type="int8")


def grabar_orden(espera=5.0):
    from openjarvis.speech.voice_io import record_until_silence
    return record_until_silence(startup_silence_seconds=espera)


def transcribir(whisper, wav):
    try:
        segmentos, _ = whisper.transcribe(io.BytesIO(wav), language=IDIOMA,
                                          vad_filter=True, beam_size=1)
        texto = " ".join(s.text.strip() for s in segmentos).strip()
        bajo = texto.lower()
        if len(bajo.strip(" .,!?\u00bf\u00a1")) < 2 or any(a in bajo for a in ALUCINACIONES):
            return ""
        return texto
    except Exception as exc:
        log("Error al transcribir: " + str(exc))
        return ""


# ---------------- modo rapido: directo a Ollama ----------------
def precargar_modelo():
    import requests
    try:
        requests.post(OLLAMA_URL + "/api/generate",
                      json={"model": MODELO_LLM, "keep_alive": -1}, timeout=120)
        log("Modelo " + MODELO_LLM + " cargado en memoria.")
    except Exception as exc:
        log("No pude conectar con Ollama (" + str(exc)[:80] + "). Abre la app de Ollama.")


def _stream_ollama(mensajes, pensar):
    import requests
    cuerpo = {"model": MODELO_LLM, "messages": mensajes, "stream": True,
              "keep_alive": -1, "options": {"num_predict": 300}}
    if pensar is not None:
        cuerpo["think"] = pensar
    r = requests.post(OLLAMA_URL + "/api/chat", json=cuerpo, stream=True, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(r.text[:200])
    for linea in r.iter_lines():
        if not linea:
            continue
        dato = json.loads(linea)
        if dato.get("error"):
            raise RuntimeError(dato["error"])
        trozo = (dato.get("message") or {}).get("content") or ""
        if trozo:
            yield trozo
        if dato.get("done"):
            break


def responder_rapido(texto, decir):
    """Pide la respuesta en streaming y llama decir(frase) en cuanto cada frase esta lista."""
    mensajes = [{"role": "system", "content": PERSONALIDAD}] + HISTORIAL[-2 * MEMORIA_TURNOS:]
    mensajes.append({"role": "user", "content": texto})
    try:
        trozos = _stream_ollama(mensajes, False)   # sin razonamiento interno
        primero = next(trozos, "")
    except RuntimeError as exc:
        if "think" not in str(exc).lower():
            raise
        trozos = _stream_ollama(mensajes, None)    # el modelo no admite la opcion
        primero = next(trozos, "")

    def todos():
        if primero:
            yield primero
        yield from trozos

    completo, pendiente, en_think = "", "", False
    for trozo in todos():
        completo += trozo
        pendiente += trozo
        if "<think>" in pendiente:
            en_think = True
        if en_think:
            if "</think>" not in pendiente:
                continue
            pendiente = pendiente.split("</think>", 1)[1]
            en_think = False
        while True:
            m = FIN_FRASE.match(pendiente)
            if not m:
                break
            decir(m.group(1))
            pendiente = pendiente[m.end():]
    if pendiente.strip() and not en_think:
        decir(pendiente)

    completo = re.sub(r"<think>.*?</think>", "", completo, flags=re.S).strip()
    HISTORIAL.append({"role": "user", "content": texto})
    HISTORIAL.append({"role": "assistant", "content": completo})
    return completo


# ---------------- modo OpenJarvis ----------------
def preguntar_a_jarvis(texto):
    consulta = PERSONALIDAD + "\n\nEl usuario dice: " + texto if PERSONALIDAD else texto
    cmd = [sys.executable, "-c", "from openjarvis.cli import main; main()", "ask", "--json", "-m", MODELO_LLM]
    if AGENTE:
        cmd += ["--agent", AGENTE]
    cmd.append(consulta)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", NO_COLOR="1")
    try:
        proc = subprocess.run(cmd, capture_output=True, env=env, timeout=600, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "Disculpe, se\u00f1or, OpenJarvis tardo demasiado en responder."
    salida = proc.stdout.decode("utf-8", errors="replace")
    inicio, fin = salida.find("{"), salida.rfind("}")
    if inicio != -1 and fin > inicio:
        try:
            datos = json.loads(salida[inicio:fin + 1])
            respuesta = datos.get("content") or datos.get("answer") or ""
            if respuesta:
                return respuesta
        except json.JSONDecodeError:
            pass
    error = proc.stderr.decode("utf-8", errors="replace").strip()
    return salida.strip() or ("No pude obtener respuesta de OpenJarvis. " + error[-300:])


# ---------------- texto a voz ----------------
def limpiar_para_voz(texto):
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S | re.I)
    texto = re.sub(r"```.*?```", " (bloque de codigo) ", texto, flags=re.S)
    texto = re.sub(r"[*_#`>|]", "", texto)
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto[:MAX_CARACTERES_VOZ]


def sintetizar_neural(texto):
    import edge_tts
    import soundfile as sf

    async def generar():
        audio = b""
        async for parte in edge_tts.Communicate(texto, VOZ, rate=VELOCIDAD, pitch=TONO).stream():
            if parte["type"] == "audio":
                audio += parte["data"]
        return audio

    mp3 = asyncio.run(generar())
    return sf.read(io.BytesIO(mp3), dtype="float32")


def hablar_windows(texto):
    b64 = base64.b64encode(texto.encode("utf-8")).decode("ascii")
    script = (
        "$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + b64 + "'));"
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$v=$s.GetInstalledVoices()|Where-Object{$_.VoiceInfo.Culture.Name -like 'es*'}|Select-Object -First 1;"
        "if($v){$s.SelectVoice($v.VoiceInfo.Name)};"
        "$s.Speak($t)"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True)


class Locutor:
    """Prepara el audio de la siguiente frase mientras reproduce la actual."""

    def __init__(self):
        self.frases = queue.Queue()
        self.audios = queue.Queue()
        threading.Thread(target=self._sintetizar, daemon=True).start()
        threading.Thread(target=self._reproducir, daemon=True).start()

    def decir(self, frase):
        frase = limpiar_para_voz(frase)
        if frase:
            self.frases.put(frase)

    def esperar(self):
        self.frases.join()
        self.audios.join()

    def _sintetizar(self):
        while True:
            frase = self.frases.get()
            try:
                self.audios.put(("neural", sintetizar_neural(frase)))
            except Exception as exc:
                log("(Voz neural no disponible: " + str(exc)[:100] + " - uso la voz de Windows)")
                self.audios.put(("windows", frase))
            finally:
                self.frases.task_done()

    def _reproducir(self):
        import sounddevice as sd
        while True:
            tipo, dato = self.audios.get()
            try:
                if tipo == "neural":
                    sd.play(dato[0], dato[1])
                    sd.wait()
                else:
                    hablar_windows(dato)
            except Exception as exc:
                log("Error de audio: " + str(exc)[:100])
            finally:
                self.audios.task_done()


# ---------------- programa principal ----------------
def main():
    elegir_microfono()
    try:
        detector = cargar_detector()
        whisper = cargar_whisper()
    except ImportError as exc:
        log("Falta una dependencia: " + str(exc))
        return
    locutor = Locutor()
    if not USAR_OPENJARVIS:
        precargar_modelo()
    log("")
    log("Listo. Di 'hey Jarvis' y luego tu orden. (Ctrl + C para salir)")
    en_conversacion = False
    while True:
        if not en_conversacion:
            log("")
            log("Escuchando... di 'hey Jarvis'")
            esperar_hey_jarvis(detector)
            pitido()
            log("Te escucho, habla ahora.")
            texto = transcribir(whisper, grabar_orden())
            if not texto:
                log("No entendi nada, intenta de nuevo.")
                pitido(440, 200)
                continue
        else:
            time.sleep(0.3)   # evita captar el final de su propia voz
            log("(sigo escuchando...)")
            texto = transcribir(whisper, grabar_orden(SEGUNDOS_SEGUIMIENTO))
            if not texto:
                en_conversacion = False
                pitido(520, 120)
                log("(en espera; di 'hey Jarvis' para volver a hablar)")
                continue
        log("Tu: " + texto)
        bajo = texto.lower()
        if en_conversacion and any(d in bajo for d in DESPEDIDAS):
            locutor.decir("Muy bien, se\u00f1or " + NOMBRE + ". Aqui estare si me necesita.")
            locutor.esperar()
            en_conversacion = False
            log("(en espera; di 'hey Jarvis' para volver a hablar)")
            continue
        en_conversacion = CONVERSACION_FLUIDA
        t0 = time.monotonic()

        if USAR_OPENJARVIS:
            log("Pensando...")
            respuesta = preguntar_a_jarvis(texto)
            log("Jarvis (%.0fs): %s" % (time.monotonic() - t0, respuesta))
            if HABLAR_RESPUESTA:
                locutor.decir(respuesta)
                locutor.esperar()
            continue

        inicio = []

        def decir(frase):
            if not inicio:
                inicio.append(time.monotonic() - t0)
            if HABLAR_RESPUESTA:
                locutor.decir(frase)

        try:
            respuesta = responder_rapido(texto, decir)
        except Exception as exc:
            respuesta = "Error con Ollama: " + str(exc)[:200]
            locutor.decir("Disculpe, se\u00f1or, tuve un problema con el modelo.")
        demora = (" (respuesta en %.1fs)" % inicio[0]) if inicio else ""
        log("Jarvis" + demora + ": " + respuesta)
        locutor.esperar()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Hasta luego.")
