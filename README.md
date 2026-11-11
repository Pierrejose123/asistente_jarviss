# JARVIS — asistente personal local (Telegram + voz + IA en su PC)

Asistente personal en español que corre **en su propia PC con Windows**. Le escribe y le responde por **Telegram**,
le escucha con **«Hey Jarvis»** y usa una **IA local con Ollama**: sus datos no salen a servicios de IA en la nube.

Lo hizo un estudiante de diseño para organizar estudio, trabajo, dinero e inversiones en un solo lugar. Puede
copiarlo y adaptarlo a su vida.

> Proyecto personal, sin garantía. No es asesoría financiera: lo que dice de bolsa es información, no recomendación.

## Qué hace

| Área | Funciones |
|---|---|
| **Agenda** | Plan del día y la semana, tareas y deberes con fecha, recordatorios en lenguaje natural («recuérdame mañana a las 8…»), sincronización con **Google Calendar**, avisos de clases (abre Teams), bloques de estudio propuestos en los huecos libres |
| **Estudio** | Deberes y avisos de **Moodle**, descarga de materiales, tarjetas de repaso, vocabulario de inglés con repaso espaciado y práctica de conversación |
| **Dinero** | Gastos e ingresos escritos o leídos de correos del banco (**Gmail**, solo lectura), presupuesto, ahorros, deudas («Juan me debe 50»), perfil de gasto mes a mes |
| **Bolsa** | Portafolio desde el informe de **XTB** (en porcentajes, sin montos por Telegram), «compré / vendí» por chat, alertas de precio, calendario de resultados y dividendos, diario de decisiones, notas del analista que siga |
| **Noticias** | Resumen de la mañana por secciones (mundo, su país, petróleo, tecnología, cripto, leyes, sus acciones), cruce con los análisis de XTB Latam, «cuéntame más de la 3» |
| **Biblioteca** | Aprende de sus PDF, Word, PowerPoint y transcripciones, y responde con esa información |
| **Voz** | «Hey Jarvis» con Whisper (en la tarjeta gráfica si tiene NVIDIA) y voz de Edge, notas de voz por Telegram |
| **PC** | Chequeo diario del asistente, revisión semanal de la PC (antivirus, Windows Update, discos, tarjeta gráfica, programas nuevos que arrancan solos), respaldo diario, «modo juego» que libera la tarjeta gráfica |

**Qué no hace:** no compra ni vende acciones, no paga nada, no envía correos en su nombre, no borra sus archivos y
no manda montos de su dinero a Google ni a Telegram. La IA solo redacta: los cálculos (saldos, porcentajes,
fechas) los hace el código.

## Requisitos

- Windows 10 u 11 y **Python 3.11 o más nuevo** (https://www.python.org, marque «Add python.exe to PATH»).
- **Ollama** (https://ollama.com) con un modelo de unos 9B para el chat; con 16 GB de RAM o una tarjeta gráfica de
  8 GB funciona bien. Hay un modelo chico para cuando juega o diseña.
- Una cuenta de **Telegram** y un bot propio (se crea gratis con @BotFather).
- Opcionales: cuenta de Google (Calendar y Gmail), Moodle de su instituto, cuenta de XTB, micrófono para la voz.

## Instalación

En PowerShell:

```powershell
git clone https://github.com/pierrejose123/asistente_jarviss.git
cd asistente_jarviss
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe instalar.py
```

`instalar.py` crea su `.env`, copia la configuración de ejemplo (`config\*.ejemplo.json` → `config\*.json`) y le
dice los siguientes pasos:

1. **Modelos de IA:** `ollama pull qwen3.5:9b`, `ollama pull qwen3.5:2b` y `ollama pull nomic-embed-text`
   (puede usar otros: se cambian en `config\ia.json` y `config\modos.json`).
2. **Telegram:** escríbale cualquier cosa a su bot y ejecute
   `.\.venv\Scripts\python.exe modulos\telegram\obtener_user_id.py`. El asistente solo le responde a usted.
3. **Revisar:** `.\.venv\Scripts\python.exe modulos\comun\revisar_entorno.py`
4. **Arrancar:** `.\.venv\Scripts\python.exe modulos\comun\control.py iniciar`
   (también `estado`, `detener` y `reiniciar`). En Telegram escriba `/ayuda`.

Para que arranque solo con Windows, cree una tarea programada que ejecute
`.venv\Scripts\pythonw.exe modulos\comun\supervisor.py` al iniciar sesión.

## Configuración

**`.env`** (secretos y datos suyos; nunca se sube a GitHub):

| Clave | Para qué |
|---|---|
| `NOMBRE_USUARIO`, `PERFIL_USUARIO` | Cómo se llama y a qué se dedica (la IA le habla con eso) |
| `ZONA_HORARIA` | Su zona horaria, ej. `America/Bogota` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID` | Su bot y su usuario de Telegram |
| `MOODLE_SITIO` | Su aula virtual, ej. `https://campus.su-instituto.edu` (opcional) |

**`config\`** (comportamiento; cada archivo tiene su `.ejemplo.json`):

| Archivo | Qué ajusta |
|---|---|
| `rutas.json` | Carpeta de archivos pesados y privados (`pesado`) y carpeta que lee la biblioteca (`informacion_ia`) |
| `horario_clases.json` | Sus materias, días, horas y enlaces de Teams |
| `finanzas.json` | Tarjetas, categorías y palabras clave de gastos; remitentes de correos de su banco |
| `noticias.json` | Fuentes, secciones y cuántas noticias por sección (cambie «Ecuador» por su país) |
| `portafolio.json`, `cava.json` | Bolsa: moneda, carpetas de descarga del informe de XTB, analista que sigue |
| `habitos.json` | Un hábito diario con nombre, días y hora |
| `ia.json`, `modos.json`, `voz.json` | Modelo de IA, programas de «modo juego/diseño», micrófono y voz |
| `memoria_inicial.json` | Datos suyos que la IA debe saber desde el primer día |

## Google (Calendar y Gmail, opcional)

1. En https://console.cloud.google.com cree un proyecto, active **Google Calendar API** y **Gmail API**.
2. Pantalla de consentimiento: tipo «Externo», agréguese como usuario de prueba (o publíquela).
3. Credenciales → «ID de cliente OAuth» → «App de escritorio». Descargue el JSON como
   `credenciales\client_secret.json`.
4. Ejecute `modulos\calendario\conectar.py` (Calendar) y `modulos\finanzas\conectar_gmail.py` (Gmail, solo lectura).

## Moodle (opcional)

Ponga `MOODLE_SITIO` en el `.env` y ejecute `modulos\estudio\conectar_moodle.py` (usuario y clave: la clave no se
guarda) o `conectar_moodle_navegador.py` si su instituto entra con Microsoft/Google.

## Privacidad y seguridad

- Todo vive en su PC: base SQLite en `datos\`, respaldos en la carpeta `pesado`.
- La IA corre en Ollama, en su PC. La búsqueda web usa DuckDuckGo y las noticias son RSS públicos.
- Google: permisos mínimos (Calendar del asistente; Gmail solo lectura). Telegram: solo responde a su usuario.
- El texto que viene de afuera (correos, Moodle, páginas web) se trata como **datos, nunca como órdenes** para la IA.
- `.gitignore` deja fuera `.env`, `credenciales\`, `datos\`, `logs\` y su `config\*.json` real.

## Pruebas

Las pruebas usan una base temporal y bloquean Google y Telegram (no tocan sus datos):

```powershell
.\.venv\Scripts\python.exe modulos\portafolio\pruebas\prueba_cambios.py
.\.venv\Scripts\python.exe modulos\noticias\pruebas\prueba_secciones.py
.\.venv\Scripts\python.exe modulos\tareas\pruebas\prueba_recordatorios.py
```

## Estructura

```
modulos/
  telegram/   bot y notas de voz          ia/         cerebro (Ollama) y memoria
  agenda/     actividades con hora        tareas/     tareas, recordatorios y consultas
  calendario/ Google Calendar             clases/     horario y avisos de clases
  estudio/    Moodle y tarjetas           ingles/     vocabulario y conversación
  finanzas/   gastos, deudas, ahorros     portafolio/ XTB y cambios del portafolio
  alertas/    precios, calendario, diario noticias/   resumen, XTB Latam
  cava/       notas de análisis           biblioteca/ y aprendizaje/ (sus documentos)
  proactivo/  planificador                resumen/    resumen de la mañana y la noche
  voz/        «Hey Jarvis»                comun/      base, salud, PC, respaldo, modos
config/       configuración (*.ejemplo.json)
```

## Licencia

MIT: puede usarlo, copiarlo y modificarlo, manteniendo el aviso de autor. Vea `LICENSE`.
