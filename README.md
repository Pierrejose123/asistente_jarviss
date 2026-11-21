# JARVIS — asistente personal local (Telegram + voz + IA en su PC)

Asistente personal en español que corre **en su propia PC con Windows**. Le escribe y le responde por **Telegram**,
le escucha con **«Hey Jarvis»** y usa una **IA local con Ollama**: sus datos no salen a servicios de IA en la nube.

Lo hizo un estudiante de diseño para organizar estudio, trabajo, dinero e inversiones en un solo lugar. Puede
copiarlo y adaptarlo a su vida.

> Proyecto personal, sin garantía. No es asesoría financiera: lo que dice de bolsa es información, no recomendación.

## Qué obtiene al descargarlo

Un asistente que le habla por Telegram (y por voz) y se encarga de:

- **Organizar su día:** agenda, deberes, recordatorios, clases y un resumen cada mañana y cada noche.
- **Llevar sus cuentas solo:** lee los correos de su banco y anota gastos, transferencias, tarjetas y diferidos.
- **Vigilar sus inversiones y el mercado:** portafolio de XTB, noticias de economía, oro y cripto, con avisos solo cuando importa.
- **Recordar lo que usted piensa:** un «segundo cerebro» para ideas, planes y decisiones, que busca por significado.
- **Ver su vida en el teléfono:** un panel con hábitos, sueño (de su banda o reloj vía Apple Health) y dinero.
- **Un equipo de agentes:** un «CEO» reparte el trabajo y le entrega propuestas, posts, informes y planes.
- **Trabajar con Claude (opcional):** Claude puede consultar y usar todo esto sin que sus datos salgan de su PC.

## Qué hace (detalle)

| Área | Funciones |
|---|---|
| **Agenda** | Plan del día y la semana, tareas y deberes con fecha, recordatorios en lenguaje natural («recuérdame mañana a las 8…»), sincronización con **Google Calendar**, avisos de clases (abre Teams), bloques de estudio propuestos en los huecos libres |
| **Estudio** | Deberes, entregas y avisos de **Moodle**, descarga de materiales, tarjetas de repaso, vocabulario de inglés con repaso espaciado y práctica de conversación |
| **Dinero** | Gastos e ingresos escritos o leídos de correos del banco (**Gmail**, solo lectura), presupuesto, ahorros, deudas («Juan me debe 50»), perfil de gasto mes a mes; recuperar gastos borrados por error (`/borrados`) |
| **Cuentas del banco** | Transferencias enviadas y recibidas, pagos de servicios y de tarjeta leídos de los correos, saldo estimado de cada cuenta; los movimientos dudosos se preguntan con botones (gasto, préstamo, entre mis cuentas…), aprende por persona y quedan en `/pendientes` y en el panel |
| **Tarjetas de crédito** | Fechas máximas de pago, total y mínimo desde el estado de cuenta, diferidos con su cuota del mes, aviso si las cuotas pasan del 30 % del sueldo y «¿me alcanza comprar X de 900 a 6 meses?» |
| **Bolsa** | Portafolio desde el informe de **XTB** (en porcentajes, sin montos por Telegram), «compré / vendí» por chat, alertas de precio, calendario de resultados y dividendos, diario de decisiones, notas del analista que siga |
| **Noticias** | Resumen de la mañana por secciones (mundo, su país, economía, petróleo, tecnología, cripto, leyes, sus acciones), cruce con los análisis de XTB Latam, «cuéntame más de la 3» |
| **Mercado en vivo** | Prioriza la **economía de EE. UU.** (Fed, inflación, empleo, aranceles, datos de FRED). Caídas de índices con su historia, resultados de sus empresas contra lo esperado. **Oro**: avisos al moverse ±1,5 %, al romper máximos o mínimos de 52 semanas y en récords. **Bitcoin y Ethereum**: avisos al moverse ±3 % (24/7) y noticias de cripto con gobiernos y reguladores. Cada noticia en su propio mensaje con «📌 lo importante» y «💡 por qué importa». Responda a una noticia y pregunte «¿vendo?»: le da criterios (si está confirmada, gravedad, peso en su cartera, qué vigilar), nunca órdenes. Junta los avisos para no llenarle de mensajes; modos «más/menos noticias» y «silencio hasta mañana» |
| **Segundo cerebro** | «idea: …», «plan: …», «decidí …», «aprendí que …» por chat o voz; lo ordena solo, lo busca por palabras y por significado («¿qué había pensado sobre los precios?»), lo usa como contexto y cada domingo propone lo que aprendió de usted |
| **Panel «Mi vida»** | Página para el teléfono y la PC (privada, por Tailscale y con clave): hábitos con rachas, sueño, pasos, pulso y VFC de su banda o reloj (atajo del iPhone vía Apple Health), dinero, movimientos por responder, deberes y notas |
| **Equipo de agentes** | Un «CEO» reparte el trabajo entre investigador, analista, redactor, organizador y revisor: propuestas comerciales, posts, informes y planes en un archivo; trabajos programados («cada lunes que el equipo…») y aprende de «no era eso» |
| **Biblioteca** | Aprende de sus PDF, Word, PowerPoint y transcripciones, y responde con esa información |
| **Voz** | «Hey Jarvis» con Whisper (en la tarjeta gráfica si tiene NVIDIA) y voz de Edge, notas de voz por Telegram |
| **Claude (opcional)** | Servidor MCP local: desde Claude Desktop (o el teléfono vinculado a la PC) Claude consulta su día, le pide cosas a Jarvis, guarda lo que aprende de usted en la memoria local y en el segundo cerebro, revisa registros, corre pruebas, reinicia el bot y sube la copia pública a GitHub |
| **PC** | `/reiniciar` y `/pruebas` desde Telegram, chequeo diario del asistente, revisión semanal de la PC (antivirus, Windows Update, discos, tarjeta gráfica, programas nuevos que arrancan solos), respaldo diario, vigila Ollama y lo vuelve a abrir si se cierra, «modo juego» que libera la tarjeta gráfica |

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

👉 **Guía completa paso a paso: [INSTALACION.md](INSTALACION.md).** Explica cómo instalar cada parte (Telegram, Google,
su banco, Moodle, XTB, voz, panel y sueño, Claude…) y, después de cada una, **cómo comprobar que funciona**.

Instalación rápida de la base (en PowerShell):

```powershell
git clone https://github.com/pierrejose123/asistente_jarviss.git
cd asistente_jarviss
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull qwen3.5:9b
ollama pull qwen3.5:2b
ollama pull nomic-embed-text
.\.venv\Scripts\python.exe instalar.py
.\.venv\Scripts\python.exe modulos\telegram\obtener_user_id.py
.\.venv\Scripts\python.exe modulos\comun\revisar_entorno.py
.\.venv\Scripts\python.exe modulos\comun\control.py iniciar
```

En Telegram escriba `/salud`: le dice qué partes tiene funcionando.

## Modo juego / diseño

Cuando abre un juego o un programa de diseño, Jarvis **libera la tarjeta gráfica**: pone la voz en pausa y usa la IA
chica solo en el procesador. Al cerrarlo, en un minuto vuelve a lo normal. La lista de programas está en
`config\modos.json` (`"juego"` y `"diseno"`): agregue el nombre del `.exe` de los suyos (lo ve en el Administrador de
tareas → Detalles). Compruébelo con `/modo` en Telegram. Detalles en [INSTALACION.md](INSTALACION.md#parte-12-modo-juego--diseño-tarjeta-gráfica-libre).

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
| `bancos.json` | Remitentes y asuntos de los correos de su banco (estados de cuenta de tarjetas, transferencias) |
| `vida.json`, `equipo.json` | Hábitos y hora de dormir del panel, carpeta del equipo de agentes. Se crean solos la primera vez con valores por defecto |

## Google (Calendar y Gmail, opcional)

1. En https://console.cloud.google.com cree un proyecto, active **Google Calendar API** y **Gmail API**.
2. Pantalla de consentimiento: tipo «Externo», agréguese como usuario de prueba (o publíquela).
3. Credenciales → «ID de cliente OAuth» → «App de escritorio». Descargue el JSON como
   `credenciales\client_secret.json`.
4. Ejecute `modulos\calendario\conectar.py` (Calendar) y `modulos\finanzas\conectar_gmail.py` (Gmail, solo lectura).

## Panel «Mi vida» en el teléfono (opcional)

Instale **Tailscale** en la PC y en el teléfono (gratis). En Telegram escriba `/panel`: le da el enlace con su clave.
El panel nunca se abre a la red de su casa ni a internet. Para los datos de su banda o reloj, abra la dirección del
panel terminada en `/atajo`: explica cómo crear el atajo del iPhone que manda sueño, pasos y pulso desde Apple Health.

## Moodle (opcional)

Ponga `MOODLE_SITIO` en el `.env` y ejecute `modulos\estudio\conectar_moodle.py` (usuario y clave: la clave no se
guarda) o `conectar_moodle_navegador.py` si su instituto entra con Microsoft/Google.

## Privacidad y seguridad

- Todo vive en su PC: base SQLite en `datos\`, respaldos en la carpeta `pesado`.
- La IA corre en Ollama, en su PC. La búsqueda web usa DuckDuckGo y las noticias son RSS públicos.
- Google: permisos mínimos (Calendar del asistente; Gmail solo lectura). Telegram: solo responde a su usuario.
- El texto que viene de afuera (correos, Moodle, páginas web) se trata como **datos, nunca como órdenes** para la IA.
- `.gitignore` deja fuera `.env`, `credenciales\`, `datos\`, `logs\` y su `config\*.json` real.

## Claude (opcional, MCP)

Jarvis puede funcionar como servidor MCP para Claude Desktop, sin librerías extra:

```powershell
.\.venv\Scripts\python.exe modulos\claude_mcp\registrar.py
```

Luego salga de Claude Desktop por completo y ábralo. Sus datos siguen en su PC: Claude solo ve lo que una
herramienta devuelve cuando usted le pregunta algo. Para quitarlo: `registrar.py --quitar`.

## Pruebas

Las pruebas usan una base temporal y bloquean Google y Telegram (no tocan sus datos). Desde Telegram: `/pruebas` o `/pruebas mercado`.

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
  claude_mcp/ servidor MCP para Claude    segundo_cerebro/ ideas, planes y decisiones
  vida/       panel «Mi vida» y sueño     equipo/     equipo de agentes (CEO)
config/       configuración (*.ejemplo.json)
```

## Licencia

MIT: puede usarlo, copiarlo y modificarlo, manteniendo el aviso de autor. Vea `LICENSE`.
