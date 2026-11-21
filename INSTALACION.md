# Guía de instalación completa de JARVIS

Esta guía instala **todo** lo que trae Jarvis, paso a paso, y después de cada parte le dice **cómo comprobar que
funciona**. Así sabe con seguridad qué está usando y qué no.

Solo la **Parte 1 es obligatoria**: con ella ya tiene el asistente por Telegram con IA local. Las demás son
opcionales: instale solo las que le sirvan. Si una parte no la instala, Jarvis sigue funcionando sin ella.

Todas las órdenes se escriben en **PowerShell**, dentro de la carpeta del asistente.

| Parte | Qué obtiene | ¿Obligatoria? |
|---|---|---|
| 1. Base | Telegram + IA local, tareas, recordatorios, memoria | Sí |
| 2. Arranque con Windows | Que Jarvis se encienda solo y se reinicie si se cae | Recomendada |
| 3. Google Calendar | Su agenda sincronizada con Google | No |
| 4. Gmail y su banco | Gastos, cuentas, tarjetas y diferidos leídos de los correos | No |
| 5. Moodle | Deberes, entregas y materiales de su aula virtual | No |
| 6. Bolsa (XTB) | Portafolio, alertas, calendario de resultados | No |
| 7. Noticias y mercado en vivo | Resumen de la mañana, economía, oro, cripto | No (viene listo) |
| 8. Voz «Hey Jarvis» | Hablarle con el micrófono | No |
| 9. Panel «Mi vida» y sueño | Hábitos, sueño y dinero en el teléfono | No |
| 10. Biblioteca | Que aprenda de sus PDF, Word y PowerPoint | No |
| 11. Segundo cerebro y equipo de agentes | Ideas, planes y trabajos de los agentes | No (viene listo) |
| 12. Modo juego / diseño | Liberar la tarjeta gráfica al jugar o diseñar | No (viene listo) |
| 13. Claude (MCP) | Usar Jarvis desde Claude | No |
| 14. Respaldo y revisión de la PC | Copias diarias y chequeo semanal | No (viene listo) |

---

## Parte 1. Base (obligatoria)

**Necesita:** Windows 10 u 11, unos 15 GB libres y, de preferencia, 16 GB de RAM o una tarjeta gráfica de 8 GB.

1. **Python 3.11 o más nuevo:** descárguelo de https://www.python.org. En el instalador marque
   **«Add python.exe to PATH»**.
2. **Git:** https://git-scm.com (opciones por defecto).
3. **Ollama** (la IA local): https://ollama.com. Ábralo una vez para que quede en la bandeja.
4. **Descargue Jarvis e instale las librerías:**

   ```powershell
   git clone https://github.com/pierrejose123/asistente_jarviss.git
   cd asistente_jarviss
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

5. **Modelos de IA** (unos 8 GB en total):

   ```powershell
   ollama pull qwen3.5:9b
   ollama pull qwen3.5:2b
   ollama pull nomic-embed-text
   ```

   `qwen3.5:9b` es el del chat, `qwen3.5:2b` el chico (modo juego) y `nomic-embed-text` sirve para buscar por
   significado (biblioteca y segundo cerebro). Puede usar otros cambiándolos en `config\ia.json` y `config\modos.json`.

6. **Su bot de Telegram:** en Telegram hable con **@BotFather**, escriba `/newbot`, póngale un nombre y copie el
   **token** que le da.
7. **Primera configuración:**

   ```powershell
   .\.venv\Scripts\python.exe instalar.py
   ```

   Le pregunta su nombre y el token, crea su `.env`, copia la configuración de ejemplo y crea las carpetas.
   Abra el `.env` con el Bloc de notas y complete `PERFIL_USUARIO` (a qué se dedica) y `ZONA_HORARIA`
   (ej. `America/Bogota`).
8. **Que el bot solo le responda a usted:** escríbale cualquier cosa a su bot en Telegram y ejecute:

   ```powershell
   .\.venv\Scripts\python.exe modulos\telegram\obtener_user_id.py
   ```

9. **Datos suyos desde el primer día (opcional):** edite `config\memoria_inicial.json` con frases como
   «Trabaja de 09:00 a 17:00».
10. **Revise y arranque:**

    ```powershell
    .\.venv\Scripts\python.exe modulos\comun\revisar_entorno.py
    .\.venv\Scripts\python.exe modulos\comun\control.py iniciar
    ```

    `control.py` también acepta `estado`, `detener` y `reiniciar`.

**✅ Cómo comprobar que funciona**
- `revisar_entorno.py` termina con **TODO LISTO**.
- Al arrancar, el bot le escribe «🟢 Asistente en línea».
- En Telegram: `/ayuda` (lista de comandos), `/salud` (qué partes funcionan) y escriba
  «recuérdame en 2 minutos tomar agua»: a los 2 minutos debe llegarle el aviso.
- `/pruebas` corre las pruebas automáticas (base temporal, no tocan sus datos) y debe decir «N de N bien».

---

## Parte 2. Arranque con Windows (recomendada)

El supervisor enciende el bot (y la voz, si la instala) sin ventanas y los reinicia si se caen. Además, Jarvis vigila
Ollama y lo vuelve a abrir si se cierra.

1. Pulse `Windows + R`, escriba `shell:startup` y Enter. Se abre la carpeta **Inicio**.
2. Clic derecho → **Nuevo → Acceso directo**. En «ubicación» pegue (cambie la ruta por la de su carpeta):

   ```
   "C:\ruta\asistente_jarviss\.venv\Scripts\pythonw.exe" "C:\ruta\asistente_jarviss\modulos\comun\supervisor.py"
   ```

3. Llámelo «Jarvis». Luego clic derecho en el acceso directo → **Propiedades** → en «Iniciar en» ponga
   `C:\ruta\asistente_jarviss`.

**✅ Comprobar:** reinicie la PC sin abrir nada. En un minuto debe llegarle «🟢 Asistente en línea» por Telegram.
Si no quiere que la voz arranque sola, ponga `"arrancar_con_windows": false` en `config\voz.json`.

---

## Parte 3. Google Calendar

1. En https://console.cloud.google.com cree un proyecto y active **Google Calendar API** (y **Gmail API** si hará
   la Parte 4).
2. **Pantalla de consentimiento:** tipo «Externo» y agréguese como usuario de prueba.
3. **Credenciales → Crear → ID de cliente OAuth → App de escritorio.** Descargue el JSON y guárdelo como
   `credenciales\client_secret.json`.
4. Conecte:

   ```powershell
   .\.venv\Scripts\python.exe modulos\calendario\conectar.py
   ```

   Se abre el navegador para que dé permiso. Jarvis crea su propio calendario y no toca los demás.

**✅ Comprobar:** escriba «mañana a las 10 dentista» y mire su Google Calendar. También `/sincronizar` y `/hoy`.

---

## Parte 4. Gmail y su banco (dinero automático)

Jarvis **solo lee** los correos de su banco: nunca envía, borra ni paga nada.

1. Haga la Parte 3 (mismas credenciales, con **Gmail API** activada).
2. Conecte Gmail (permiso de solo lectura):

   ```powershell
   .\.venv\Scripts\python.exe modulos\finanzas\conectar_gmail.py
   ```

3. **Correos de consumo:** en `config\finanzas.json` ponga los remitentes de su banco, sus tarjetas, categorías y
   palabras clave (el ejemplo trae el formato).
4. **Estados de cuenta, pagos y diferidos de tarjetas:** copie `config\bancos.ejemplo.json` como
   `config\bancos.json` y ponga los remitentes y asuntos reales de su banco. Sin este archivo no se buscan estados
   de cuenta (el resto funciona igual).
5. **Saldo de sus cuentas:** los bancos no mandan el saldo, así que dígaselo una vez: «saldo produbanco 850».
   Desde ahí suma y resta cada correo, y el día 1 de cada mes le pregunta el saldo real para ajustar.

**✅ Comprobar:** `/correos` (revisa ya los correos del banco), `/gastos`, `/saldo`, `/credito`, `/diferidos`.
Los movimientos dudosos le llegan con botones (gasto, préstamo, entre mis cuentas…) y también en `/pendientes`.
Escriba «gasté 5 en almuerzo» y luego `/movimientos`: debe aparecer. Si borra uno por error, `/borrados`.

---

## Parte 5. Moodle (aula virtual)

1. En el `.env` ponga `MOODLE_SITIO=https://campus.su-instituto.edu`.
2. Conecte (la clave no se guarda):

   ```powershell
   .\.venv\Scripts\python.exe modulos\estudio\conectar_moodle.py
   ```

   Si su instituto entra con Microsoft o Google, use `conectar_moodle_navegador.py`.
3. **Horario de clases:** edite `config\horario_clases.json` con sus materias, días, horas y enlaces de Teams.

**✅ Comprobar:** `/moodle` (deberes), `/materiales` (descarga materiales a su biblioteca), `/semana` (clases).
Antes de cada clase le llega el aviso con el enlace.

---

## Parte 6. Bolsa (XTB)

1. En `config\portafolio.json` ponga su moneda y la carpeta donde se guardan sus descargas.
2. En **xStation 5 → Historial → Exportar**, descargue el Excel. Jarvis lo encuentra en su carpeta de descargas y lo
   mueve a su carpeta privada (`datos_pesados\xtb`).
3. Si sigue a José Luis Cava u otro analista, ajuste `config\cava.json` y conecte su canal:

   ```powershell
   .\.venv\Scripts\python.exe modulos\cava\conectar_youtube.py https://www.youtube.com/@SuCanal
   ```

**✅ Comprobar:** `/portafolio` (en porcentajes: los montos solo se ven en la PC con
`.\.venv\Scripts\python.exe modulos\portafolio\portafolio.py`), `/acciones`, `/calendario`, y cree una alerta:
`/alerta NVDA < 120`, luego `/alertas`.

---

## Parte 7. Noticias y mercado en vivo

Viene listo. Solo ajuste `config\noticias.json`: cambie «Ecuador» por su país y quite o agregue fuentes.

Qué recibe: resumen de la mañana por secciones; en vivo, la economía de EE. UU. primero (Fed, inflación, empleo),
oro (±1,5 %, máximos y mínimos de 52 semanas), Bitcoin y Ethereum (±3 %, 24/7), resultados de sus acciones. Cada
noticia llega en su propio mensaje con «📌 lo importante» y «💡 por qué importa».

**✅ Comprobar:** `/noticias`, `/noticia 3` (explica la tercera), `/mercado`, `/macro`, `/agenda_mercado`.
Responda (deslizar → responder) a una noticia y pregunte «¿vendo?»: le da criterios, nunca órdenes.
Escriba «menos noticias» o «silencio hasta mañana» si le llegan muchas.

---

## Parte 8. Voz «Hey Jarvis»

1. Conecte un micrófono. Si tiene varios, ponga el nombre del suyo en `"microfono"` de `config\voz.json`
   (vacío = el predeterminado de Windows).
2. Pruebe las voces y elija una (se cambia en `"voz"` de `config\voz.json`):

   ```
   probar-voces.cmd
   ```

3. Arranque la voz con `jarvis-voz.cmd` (o deje que la arranque el supervisor de la Parte 2).

El reconocimiento usa Whisper: si su tarjeta NVIDIA está lista para CUDA la usa; si no, usa el procesador (más
lento). La voz de respuesta es la de Microsoft Edge (necesita internet).

**✅ Comprobar:** diga «Hey Jarvis… ¿qué tengo hoy?». Debe responderle en voz alta y copiar la respuesta a
Telegram. También puede mandarle **notas de voz** por Telegram.

---

## Parte 9. Panel «Mi vida» y sueño en el teléfono

El panel es una página privada con sus hábitos, sueño, dinero, deberes y notas. **Nunca** se abre a la red de su
casa ni a internet: solo en la misma PC y por **Tailscale** (una red privada gratis entre sus aparatos).

1. Instale **Tailscale** en la PC y en el teléfono (https://tailscale.com) con la misma cuenta.
2. En Telegram escriba `/panel`: le da el enlace con su clave (la clave se crea sola en el `.env`).
3. **Hábitos:** se editan en `config\vida.json` (se crea solo la primera vez), junto con la hora de dormir.
4. **Sueño, pasos y pulso de su banda o reloj (iPhone):** su banda debe guardar los datos en **Apple Health**
   (por ejemplo Zepp → Apple Health). Abra en el teléfono la dirección del panel terminada en `/atajo`: le explica
   cómo crear el atajo del iPhone que manda esos datos al panel, con su dirección y clave ya puestas.

**✅ Comprobar:** abra el enlace de `/panel` en el teléfono. Escriba «agua» o «leí» en Telegram y mire cómo se marca
el hábito en el panel. Después de una noche con el atajo, `/sueno` debe mostrar cómo durmió.

---

## Parte 10. Biblioteca (sus documentos)

1. En `config\rutas.json` ponga en `"informacion_ia"` la carpeta con sus PDF, Word, PowerPoint o transcripciones.
2. Jarvis los lee en segundo plano (usa `nomic-embed-text`).

**✅ Comprobar:** `/biblioteca` (archivos leídos y en cola), `/buscar tema`, `/preguntar algo que esté en sus
archivos`, `/resumir nombre-del-archivo`.

---

## Parte 11. Segundo cerebro y equipo de agentes

Vienen listos.

- **Segundo cerebro:** escriba «idea: …», «plan: …», «decidí …», «aprendí que …». Lo ordena solo y lo busca por
  significado. Cada domingo le propone lo que aprendió de usted.
- **Equipo de agentes:** «equipo: haz una propuesta para una clínica dental». Un «CEO» reparte el trabajo entre
  investigador, analista, redactor, organizador y revisor, y le manda el resultado en un archivo. La carpeta de
  salida se cambia en `config\equipo.json`.

**✅ Comprobar:** escriba «idea: probar el panel» y luego `/ideas` o «¿qué ideas tengo?». Para el equipo:
`/equipo investiga qué es n8n` y después «estado del equipo».

---

## Parte 12. Modo juego / diseño (tarjeta gráfica libre)

Cuando abre un juego o un programa de diseño de la lista, Jarvis **libera la tarjeta gráfica**: pone la voz en pausa
y usa la IA chica solo en el procesador, con pocos hilos para no quitarle FPS. Al cerrar el programa espera
60 segundos (por si solo reinicia la partida) y vuelve a lo normal.

**Agregar sus programas:** en `config\modos.json` ponga el nombre del proceso (`.exe`) en `"juego"` o en `"diseno"`:

```json
{
  "activado": true,
  "juego": ["League of Legends.exe", "FortniteClient-Win64-Shipping.exe", "SuJuego.exe"],
  "diseno": ["Photoshop.exe", "blender.exe", "Figma.exe"],
  "modelo_liviano": "qwen3.5:2b",
  "segundos_para_volver": 60,
  "hilos_procesador": 4,
  "avisar_por_telegram": false
}
```

Para saber el nombre exacto del `.exe`: abra el programa, luego el **Administrador de tareas** (`Ctrl + Shift + Esc`)
→ pestaña **Detalles**, y busque el nombre en la columna «Nombre». Con `"avisar_por_telegram": true` le avisa cada
vez que entra y sale del modo.

**✅ Comprobar:** abra uno de los programas de la lista y escriba `/modo` en Telegram: debe decir «Voz en pausa; IA
chica en el procesador» y qué está usando la tarjeta gráfica. Al cerrarlo y pasar un minuto, `/modo` dice «Modo normal».

---

## Parte 13. Claude (opcional, MCP)

Permite que Claude Desktop (o la app del teléfono vinculada a su PC) consulte su día, le pida cosas a Jarvis, guarde
lo que aprende de usted, revise registros, corra pruebas y reinicie el bot. Sus datos siguen en su PC: Claude solo
ve lo que una herramienta le devuelve cuando usted pregunta.

```powershell
.\.venv\Scripts\python.exe modulos\claude_mcp\registrar.py
```

Cierre Claude Desktop **por completo** (también de la bandeja) y ábralo. Para quitarlo: `registrar.py --quitar`.

**✅ Comprobar:** en Claude escriba «Jarvis, ¿qué tengo hoy?»: debe usar la herramienta `jarvis_contexto`.

---

## Parte 14. Respaldo y revisión de la PC

Vienen listos.

- **Respaldo diario:** un `.zip` con sus datos, configuración y `.env` en `datos_pesados\respaldos` (guarda los
  últimos 30). A mano: `.\.venv\Scripts\python.exe modulos\comun\respaldo.py --lista`.
- **Revisión de la PC:** cada domingo revisa antivirus, Windows Update, discos, temperatura de la tarjeta gráfica y
  programas nuevos que arrancan solos. Solo lectura: no cambia nada sin su «sí».

**✅ Comprobar:** `/pc` (revisión completa ahora) y `/salud`.

---

## Lista final: ¿qué tengo funcionando?

Escriba `/salud` en Telegram: le dice parte por parte qué funciona y qué no. Y `/pruebas` debe dar «N de N bien».

| Si quiere… | Escriba | Si no responde, revise |
|---|---|---|
| Ver su día | `/hoy` | Parte 1 |
| Recordatorios | «recuérdame mañana a las 8 …» | Parte 1 |
| Agenda en Google | «mañana a las 10 dentista» | Parte 3 |
| Gastos del banco | `/correos`, `/gastos` | Parte 4 |
| Deberes | `/moodle` | Parte 5 |
| Portafolio | `/portafolio` | Parte 6 |
| Noticias | `/noticias` | Parte 7 |
| Voz | «Hey Jarvis» | Parte 8 |
| Panel | `/panel` | Parte 9 |
| Sus documentos | `/biblioteca` | Parte 10 |
| Ideas | `/ideas` | Parte 11 |
| Modo juego | abrir un juego + `/modo` | Parte 12 |
| Revisión de la PC | `/pc` | Parte 14 |

## Si algo falla

- **El bot no contesta:** `.\.venv\Scripts\python.exe modulos\comun\control.py estado`. Si está detenido, `iniciar`.
- **«Ollama no responde»:** abra la app de Ollama (o espere: Jarvis la vuelve a abrir solo en unos minutos).
- **Ver qué pasó:** los registros están en la carpeta `logs\` (por ejemplo `logs\bot.log`).
- **Después de actualizar:** `git pull`, `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` y
  `/reiniciar` en Telegram.

## Qué NO hace Jarvis (para su tranquilidad)

No compra ni vende acciones, no paga nada, no envía correos en su nombre, no borra sus archivos y no manda montos de
su dinero a Google ni a Telegram. La IA solo redacta: los cálculos (saldos, porcentajes, fechas) los hace el código.
Sus secretos (`.env`, `credenciales\`) y sus datos (`datos\`) nunca se suben a GitHub.
