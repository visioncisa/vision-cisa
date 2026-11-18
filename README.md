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
2. **Detección** (`ml/hilos.py`, `HiloM1`): YOLO detecta los autobuses y los
   sigue (ByteTrack). Limitado a `YOLO_FPS_MAX` cuadros por segundo.
3. **Lectura** (`ml/hilos.py`, `HiloM2M3`): un modelo encuentra las zonas del
   número y cada zona se asigna a su autobús; otro lee los dígitos. Hacen falta
   2 lecturas iguales (`N_VOTOS`) para confirmar. Limitado a `M2_FPS_MAX` cuadros por
   segundo y a un tope de lecturas por cuadro, así varias unidades a la vez no
   saturan la GPU. Cada autobús en cuadro lleva su propio número y cruce.
4. **Cruce** (`ml/linea_virtual.py`): decide entrada o salida y descarta
   maniobras. Alrededor de la línea hay un margen (`MARGEN_LINEA_PX`) donde el
   lado no cambia, para que un camión parado encima no cuente como cruces.
5. **Un solo registro por camión**: al cruzar, espera a que termine de pasar
   (`ESPERA_FIN_SEG` / `ESPERA_MAX_SEG`) y elige el mejor número. Si un número
   es otro con dígitos de menos (504 dentro de 5014), gana el largo.
   Si el número que más se lee no está en el padrón (p. ej. 2508, leído
   `VOTOS_FUERA_PADRON` veces o más), se registra tal cual como "fuera del
   padrón" en vez de "corregirlo" a uno parecido (508 → 5008).
6. **Validación** (`avisos/telegram.py`, `avisos/gemini.py`): Gemini revisa la foto y,
   si hay duda, la manda a un validador por Telegram. En pruebas se apaga con
   `SIN_TELEGRAM=1`.
7. **Registro** (`metricas/`): base PostgreSQL `patio_cca` de la Jetson, con
   unidades, pasos, estancias y el catálogo `cat` (VIN, marca, modelo, año).
   El padrón se edita en `padron.csv` y se copia a la base al arrancar.
8. **Web** (`web/`): tablero, video en vivo (MJPEG), lista de detecciones con
   búsqueda por número/empresa, filtro por fechas y paginación fija de 10, y
   tabla de unidades ordenada y paginada.
9. **Grabación** (`scripts/grabar.sh`, servicio `cisa-grabacion`): copia el
   video tal cual llega de la cámara (Full HD, H.265), sin recodificar.
10. **WhatsApp** (`avisos/whatsapp.py`, servicio `cisa-whatsapp`): manda al número
    `WHATSAPP_NUMERO` los mismos avisos (foto y texto) que se publican en el grupo
    de Telegram, desde una cuenta de WhatsApp vinculada con QR.

## Estructura

```
config.py            toda la configuración (el ÚNICO archivo que lee el .env)
pipe_stream_v2.py    arranque: crea la cámara, los hilos y el servidor web
whatsapp/            servicio cisa-whatsapp (Node + Baileys): sesión de WhatsApp Web
padron.csv           unidades válidas: no_economico, empresa, tipo (electrica, diesel o gasolina)
logica/              estado compartido y cámara
ml/                  modelos, lectura de dígitos, línea virtual, hilos de visión
avisos/              Telegram (telegram.py), Gemini (gemini.py) y WhatsApp (whatsapp.py)
metricas/            base de datos (storage.py, schema.sql) y datos del tablero (metricas.py)
web/                 Flask: páginas, API, video en vivo, fotos y grabaciones
templates/, static/  páginas: tablero, video en vivo, grabaciones
scripts/             herramientas de operación (ver abajo)
Dockerfile           imagen para JetPack 7.2 (CUDA 13.2, TensorRT 10.16)
docker-compose.yml   servicios cisa-vision (detección), cisa-grabacion y cisa-whatsapp
```

Afuera de la imagen, en la Jetson:

- `.env`: configuración y contraseñas.
- PostgreSQL (servicio de la Jetson, fuera de Docker): la base `patio_cca`.
- `datos/`: la base SQLite anterior (`detecciones.db`), solo como respaldo.
- `modelos/`: los `.engine`.
- `~/Documents/Jetson8/`: fotos, recortes, grabaciones y el video de prueba.

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

## Base de datos (PostgreSQL)

La base es `patio_cca`, en el PostgreSQL de la Jetson. El contenedor usa la red
de la Jetson, así que se conecta a `localhost:5432`. La conexión va en el `.env`:

```
DATABASE_URL=postgresql://usuario:contraseña@localhost:5432/patio_cca
```

Tablas (el esquema completo está en `metricas/schema.sql` y se aplica solo al arrancar):

| Tabla | Qué guarda |
|---|---|
| `unidad` | Cada número económico: empresa, tipo y si está en el padrón |
| `evento_paso` | Cada cruce de la línea: entrada o salida, hora, zona, confianza y foto |
| `estancia` | Cada visita: hora de entrada y de salida, minutos dentro |
| `cat` | Catálogo: VIN, empresa, marca, modelo, año, motor y serie del motor |
| `tipo_unidad`, `puerta` | Catálogos chicos |

Las vistas `v_evento`, `v_estancia`, etc. juntan esas tablas para el tablero.

**Catálogo de unidades**: `python3 scripts/cargar_cat.py ~/catalogo.csv`. Se puede
correr las veces que se quiera: si la unidad ya existe, actualiza sus datos.

**Unidades nuevas o de otra empresa** (p. ej. COPATTSA): se agregan a `padron.csv`
y se reinicia `cisa-vision`. Los números de 2 dígitos (31, 13…) se aceptan solo si
están en el padrón y se leen al menos `VOTOS_FUERA_PADRON` veces, porque pueden ser
un pedazo de otro número.

**Histórico anterior**: lo que estaba en `datos/detecciones.db` (SQLite) se pasa
una sola vez con `scripts/migrar_sqlite_a_postgres.py`. Si se vuelve a correr, no
hace nada.

## WhatsApp

1. Pon en el `.env` el número que recibe los avisos: `WHATSAPP_NUMERO=525512345678`
   (52 + 10 dígitos).
2. `docker compose up -d` y luego `docker compose logs -f cisa-whatsapp`.
3. Con el teléfono que va a **mandar** los avisos: WhatsApp → Dispositivos
   vinculados → Vincular un dispositivo → escanea el QR del log.
4. Listo: la sesión queda en `whatsapp/sesion/` y no vuelve a pedir el QR.
   Para cambiar de teléfono, borra esa carpeta y reinicia el servicio.

No es la API oficial de WhatsApp: el número que manda puede ser bloqueado si
WhatsApp lo considera spam. Usa un número dedicado, guárdalo en los contactos
del teléfono que recibe y contéstale una vez. `whatsapp/sesion/` equivale a la
contraseña de esa cuenta: no se comparte ni se sube a GitHub.

## Herramientas (`scripts/`)

| Script | Para qué |
|---|---|
| `fuente.py` | `python3 scripts/fuente.py camara` o `video`: cambia entre la cámara y el video de prueba. Sin argumento, muestra cuál está activa. |
| `grabar.sh` | `bash scripts/grabar.sh estado`: dice si graba, qué archivos hay y cuánto ocupan. Avisa si no se guarda nada. |
| `check_tailscale.py` | Monitor de cámaras por ping: avisa por Telegram si una se cae (para cron). |
| `configurar_site.sh` | Red del patio: puerto de la placa para internet, adaptador USB para las cámaras. |
| `cargar_cat.py` | `python3 scripts/cargar_cat.py ~/catalogo.csv`: carga o actualiza el catálogo `cat`. |
| `migrar_sqlite_a_postgres.py` | Una sola vez: pasa el histórico de `datos/detecciones.db` a PostgreSQL. |

## Configuración (`.env`)

Todas las variables están en `.env.example`, con su explicación. Las más usadas:

| Variable | Qué hace |
|---|---|
| `RTSP_URL` | Fuente activa: cámara o `.mp4` de prueba (se cambia con `fuente.py`) |
| `YOLO_FPS_MAX` | Cuadros por segundo que analiza YOLO (M1); bajarlo reduce el consumo |
| `M2_FPS_MAX` | Cuadros por segundo de la lectura del número (M2+M3). Con varias unidades a la vez M3 tiene tope por cuadro, así que la carga no crece con el número de camiones |
| `SIN_TELEGRAM` | `1` = no manda nada a Telegram |
| `VALIDAR_CON_GEMINI` | `1` = Gemini revisa la foto aunque Telegram esté apagado |
| `GEMINI_API_KEY` | Clave de Gemini (solo en el `.env`, nunca en el código) |
| `LINEA_P1`, `LINEA_P2`, `LADO_ENTRADA` | Línea virtual y lado de adentro del patio |
| `LINEA_PUNTOS` | Línea de varios puntos `x,y;x,y;...` (reemplaza a P1/P2); termina en sus extremos. Revisar con `scripts/ver_linea.py` |
| `LINEA_PUNTO_BUS` | `abajo` (base del recuadro, para línea en el piso) o `centro` |
| `MARGEN_LINEA_PX` | Margen alrededor de la línea (px) donde el camión no cambia de lado |
| `VOTOS_FUERA_PADRON` | Lecturas iguales para registrar un número que no está en el padrón (4) |
| `FOTOS_POR_AVISO` | Fotos que se guardan y se mandan por aviso: las mejores, de momentos distintos (3) |
| `FOTOS_SEPARACION_SEG` | Segundos mínimos entre una foto y otra del mismo aviso (1.0) |
| `WHATSAPP_NUMERO` | Número que recibe por WhatsApp los avisos del grupo (vacío = apagado) |
| `GRABACIONES_DIR` | Dónde se guardan las grabaciones (`<dir>/cam1_grabacion`) |
| `DATABASE_URL` | Conexión a PostgreSQL (`postgresql://usuario:contraseña@localhost:5432/patio_cca`) |
| `DB_PATH` | Base SQLite anterior; solo la usa la migración |

## Consumo medido (Jetson Orin, modo 25 W, cámara Full HD)

- Sin autobús: unos 11 W.
- Con autobús: 14 a 19 W.
- La grabación no sube el consumo.
- Grabación: unos 0.9 GB por hora, unos 65 GB por 72 horas.
