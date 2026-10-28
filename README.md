# CISA — Control de unidades por visión

Sistema que corre en una Jetson Orin junto a la puerta del patio. Con la cámara
detecta cada autobús, lee su número económico, decide si **entra o sale**
(línea virtual) y guarda el movimiento. Un tablero web muestra el video en vivo,
las detecciones y qué unidades están dentro. La cámara se graba completa, un
archivo por hora, y se guardan las últimas 72 horas.

## Cómo funciona

1. **Cámara** (`logica/camara.py`): lee el video RTSP con decodificación por
   hardware. Si eso falla, usa FFmpeg. Con un `.mp4` en `RTSP_URL` funciona en
   modo prueba.
2. **Detección** (`ml/hilos.py`, `HiloM1`): YOLO detecta el autobús y lo sigue
   (ByteTrack). Limitado a `YOLO_FPS_MAX` cuadros por segundo.
3. **Lectura** (`ml/hilos.py`, `HiloM2M3`): un modelo encuentra la zona del
   número y otro lee los dígitos. Hacen falta 3 lecturas iguales para confirmar.
4. **Cruce** (`ml/linea_virtual.py`): decide entrada o salida y descarta
   maniobras.
5. **Un solo registro por camión**: al cruzar, espera a que termine de pasar
   (`ESPERA_FIN_SEG` / `ESPERA_MAX_SEG`) y elige el mejor número. Si un número
   es otro con dígitos de menos (504 dentro de 5014), gana el largo.
6. **Validación** (`alertas.py`, `validar_llm.py`): Gemini revisa la foto y,
   si hay duda, la manda a un validador por Telegram. En pruebas se apaga con
   `SIN_TELEGRAM=1`.
7. **Registro** (`metricas/`): base SQLite con unidades, pasos y estancias.
   El padrón sale solo de `padron.csv`.
8. **Web** (`web/`): tablero, video en vivo (MJPEG), lista de detecciones y
   tabla de unidades ordenada y paginada.
9. **Grabación** (`scripts/grabar.sh`, servicio `cisa-grabacion`): copia el
   video tal cual llega de la cámara (Full HD, H.265), sin recodificar.

## Estructura

```
config.py            toda la configuración (el ÚNICO archivo que lee el .env)
pipe_stream_v2.py    arranque: crea la cámara, los hilos y el servidor web
alertas.py           Telegram: avisos, botones y validación
validar_llm.py       validación de la foto con Gemini
schema.sql           esquema de la base (versión 1)
padron.csv           unidades válidas: no_economico, empresa, tipo
logica/              estado compartido y cámara
ml/                  modelos, lectura de dígitos, línea virtual, hilos de visión
metricas/            base de datos (storage.py) y datos del tablero (metricas.py)
web/                 Flask: páginas, API, video en vivo, fotos y grabaciones
templates/, static/  páginas: tablero, video en vivo, grabaciones
scripts/             herramientas de operación (ver abajo)
Dockerfile           imagen para JetPack 7.2 (CUDA 13.2, TensorRT 10.16)
docker-compose.yml   servicios cisa-vision (detección) y cisa-grabacion
```

Afuera de la imagen, en la Jetson:

- `.env`: configuración y contraseñas.
- `datos/`: la base de datos.
- `modelos/`: los `.engine`.
- `~/Documents/Jetson8/`: fotos, recortes, grabaciones y el video de prueba.
- `_archivo/`: código viejo y respaldos. No se usa.

## Uso diario

```bash
cd ~/Documents/ProyectoVisionCISA
docker compose up -d                 # arranca detección y grabación
docker compose ps                    # deben salir cisa-vision y cisa-grabacion en Up
docker compose logs -f --tail 30     # mensajes (Ctrl+C para salir)
docker compose down                  # detiene todo (los datos no se borran)
```

Tablero: `http://<ip-jetson>:5001/` · Video en vivo: `/livevideo` · Grabaciones: `/grabaciones`

Después de cambiar el `.env`: `docker compose up -d --force-recreate`.
Después de cambiar el código: `docker compose build && docker compose up -d --force-recreate`.

El sistema no arranca solo al prender la Jetson (`restart: "no"` en
`docker-compose.yml`). Para que sí arranque, cambia `restart` a `unless-stopped`.

## Herramientas (`scripts/`)

| Script | Para qué |
|---|---|
| `fuente.py` | `python3 scripts/fuente.py camara` o `video`: cambia entre la cámara y el video de prueba. Sin argumento, muestra cuál está activa. |
| `grabar.sh` | `bash scripts/grabar.sh estado`: dice si graba, qué archivos hay y cuánto ocupan. Avisa si no se guarda nada. |
| `check_tailscale.py` | Monitor de cámaras por ping: avisa por Telegram si una se cae (para cron). |
| `configurar_site.sh` | Red del patio: puerto de la placa para internet, adaptador USB para las cámaras. |

## Configuración (`.env`)

Todas las variables están en `.env.example`, con su explicación. Las más usadas:

| Variable | Qué hace |
|---|---|
| `RTSP_URL` | Fuente activa: cámara o `.mp4` de prueba (se cambia con `fuente.py`) |
| `YOLO_FPS_MAX` | Cuadros por segundo que analiza YOLO; bajarlo reduce el consumo |
| `SIN_TELEGRAM` | `1` = no manda nada a Telegram |
| `VALIDAR_CON_GEMINI` | `1` = Gemini revisa la foto aunque Telegram esté apagado |
| `GEMINI_API_KEY` | Clave de Gemini (solo en el `.env`, nunca en el código) |
| `LINEA_P1`, `LINEA_P2`, `LADO_ENTRADA` | Línea virtual y lado de entrada |
| `GRABACIONES_DIR` | Dónde se guardan las grabaciones (`<dir>/cam1_grabacion`) |
| `DB_PATH` | Base de datos (`datos/detecciones.db` en Docker) |

## Consumo medido (Jetson Orin, modo 25 W, cámara Full HD)

- Sin autobús: unos 11 W.
- Con autobús: 14 a 19 W.
- La grabación no sube el consumo.
- Grabación: unos 0.9 GB por hora, unos 65 GB por 72 horas.
