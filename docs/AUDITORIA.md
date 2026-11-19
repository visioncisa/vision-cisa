# Auditoría técnica — Vision CISA

**Fecha:** 19 nov 2026 · **Rama auditada:** `main` @ `dbbba2a` (17 nov 2026) · **Alcance:** código del repo + observaciones en la Jetson del Patio CCA (18-19 nov, solo lectura).

Convención: **[V]** verificado en código o en la Jetson · **[P]** propuesto · **[?]** por confirmar.

---

## 1. Inventario del repositorio

| Carpeta / archivo | Responsabilidad | Líneas |
|---|---|---|
| `pipe_stream_v2.py` | Arranque: cámara, hilos y servidor web | 72 |
| `config.py` | **Único** lector del `.env`; umbrales; carga y valida el padrón | 188 |
| `logica/camara.py` | `CameraStream`: RTSP con GStreamer + NVDEC (`_build_pipeline`), FFmpeg de respaldo, modo prueba con `.mp4` | 189 |
| `logica/estado.py` | Estado compartido entre hilos y web | 46 |
| `ml/modelos.py` | Carga M1/M2/M3 y los "calienta" en la GPU **al importarse** | 68 |
| `ml/hilos.py` | `HiloM1` (detección + ByteTrack) y `HiloM2M3` (zona → dígitos → votos → cruce → registro) | 762 |
| `ml/reconocimiento.py` | Recorte con margen, CLAHE, `leer_digitos`, `quitar_encimados`, `validar_numero`, guardado de recortes | 131 |
| `ml/linea_virtual.py` | `evaluar_cruce`, maniobras, debounce, margen alrededor de la línea | 109 |
| `ml/preprocesamiento.py` | CLAHE en el canal L | 19 |
| `avisos/` | Gemini (`validar_con_llm`), Telegram (validadores humanos), WhatsApp | 682 |
| `metricas/` | PostgreSQL `patio_cca`: `schema.sql`, `storage.py`, `metricas.py` | 1,205 |
| `web/` + `templates/` + `static/` | Flask: tablero, video MJPEG, API de detecciones y grabaciones | — |
| `scripts/` | `arrancar.sh`, `fuente.py`, `grabar.sh`, `cargar_cat.py`, `migrar_sqlite_a_postgres.py` | — |
| `Dockerfile`, `docker-compose.yml` | Imagen JetPack 7.2 (CUDA 13.2, TRT 10.16.2, torch 2.14.1, ultralytics 8.4.171); servicios `cisa-vision`, `cisa-grabacion`, `cisa-whatsapp` | — |
| `whatsapp/` | Puente Node + Baileys | — |

**No existen en `main`:** código de entrenamiento, evaluación, versionado de datasets, pruebas automatizadas, `docs/` y `CHANGELOG.md`. **[V]**
Hay pruebas (`tests/test_linea_virtual.py`) solo en la rama `feat/linea-virtual-finita`, y un documento LaTeX (SARU) solo en la rama `docs/documentacion-tecnica`. **[V]**

### Dependencias (versiones fijadas en `Dockerfile` / `requirements.txt`) [V]
`ultralytics==8.4.171`, `torch==2.14.1` (cu132), `torchvision==0.29.1`, TensorRT `10.16.2.10-1+cuda13.2`, OpenCV de Ubuntu 24.04 (con GStreamer), `lap==0.5.13`, `flask==3.1.3`, `python-dotenv==1.2.4`, `psycopg2-binary==2.9.13`, `numpy<2`. **No hay dependencias obsoletas**: las versiones están fijadas y coinciden con la Jetson (comprobado el 18 nov: ultralytics 8.4.171, torch 2.14.1+cu132, TensorRT 10.16.2.10).

---

## 2. Flujo real: de la captura al registro [V]

1. **Captura** — `CameraStream` abre `RTSP_URL` con `rtspsrc ! rtph265depay ! h265parse ! nvv4l2decoder` (stream principal H.265). Los cuadros se procesan **a resolución nativa** (las fotos de evidencia de la Jetson son de 1920×1080). Si GStreamer falla, usa FFmpeg (`CAM_BACKEND=ffmpeg` lo fuerza).
2. **M1** — `HiloM1.update` → `model_autobus.track(imgsz=640, tracker='bytetrack.yaml', persist=True)` (`ml/hilos.py:114`), con `CONF_AUTOBUS=0.65` y tope `YOLO_FPS_MAX`. Guarda un recorte por track (`guardar_crop_autobus`).
3. **M2** — `HiloM2M3._procesar_cuadro` corre una sola pasada de zona por cuadro con **imgsz=1280** (`ml/hilos.py:696`) y `CONF_VISTA=0.50`. Asigna cada zona a su autobús.
4. **M3** — `_leer_bus` (`ml/hilos.py:480`) recorta con margen, `leer_digitos` (CLAHE, altura mínima de 80 px, `imgsz=640`, `CONF_DIGITO=0.45`) y `quitar_encimados`. Luego `validar_numero`.
5. **Votos** — `N_VOTOS=2` lecturas iguales del padrón, o `VOTOS_FUERA_PADRON=4` fuera de él.
6. **Cruce** — `linea_virtual.evaluar_cruce` (margen `MARGEN_LINEA_PX`, maniobra 20 s, debounce 60 s); espera a que termine de pasar (`ESPERA_FIN_SEG`/`ESPERA_MAX_SEG`).
7. **Validación** — Gemini (`avisos/gemini.py`) y, si hay duda, un validador humano por Telegram.
8. **Registro** — `evento_paso` y `estancia` en PostgreSQL. Avisos a Telegram y WhatsApp.
9. **Datos para reentrenar** — recortes en `CROPS_DIR/{delantero,lateral,trasera,autobus}` (uno cada `CROPS_CADA_SEG` por camión) y grabación continua por hora (72 h).

### Contraste con el contexto del prompt

| Elemento | Estado |
|---|---|
| Cámaras IP, OpenCV, YOLO, `bus_v3`, tracking, línea virtual, recortes | **Implementado** [V] |
| "OCR" | Implementado como **detector YOLO de dígitos (M3)**, no como un OCR de texto [V] |
| Jetson Orin NX 16 GB, CUDA, TensorRT | Implementado; equipo: *Orin NX Super (reComputer)* [V] |
| Resolución 704×576 | **No aparece en el código.** Se procesa la resolución nativa del stream principal (1920×1080). Las coordenadas por defecto de la línea (`LINEA_P1=455,479`, `LINEA_P2=292,262`, `config.py:88`) caben en 704×576: hay que confirmar si son de un substream anterior **[?]** |
| Segunda cámara | Botón "Cam 2" y `RTSP_URL_CAM2`; sin grabación (solo se graba Cam 1, por diseño) [V] |

---

## 3. Hallazgos (errores, riesgos y procesos manuales)

| # | Hallazgo | Dónde | Impacto | Recomendación |
|---|---|---|---|---|
| H1 | **Corrección silenciosa con el padrón**: a una lectura de 4 dígitos que no empieza con 5 se le cambia el primero por "5" (y a 3 dígitos se les antepone "5" o se inserta "0"). Se observó en campo: un camión de CDMX con calcomanía "0063" quedó como la unidad **5063**, en estado VERIFICADO | `ml/reconocimiento.py:83` `validar_numero` — análisis completo en [PROBLEMA_VALIDAR_NUMERO.md](PROBLEMA_VALIDAR_NUMERO.md) | Errores que nadie ve (el número sí existe en el padrón) | [P] Flag `CORREGIR_LECTURAS` y registrar la lectura cruda junto a la corregida; medir cuántas correcciones resultan falsas |
| H2 | Los recortes se guardan **sin metadatos** (conf de M2, conf mínima de M3, lectura cruda/validada). Solo el nombre trae el número y el track | `ml/reconocimiento.py:120` | La selección tiene que volver a correr el modelo para medir incertidumbre | [P] Un `.json` junto a cada recorte, detrás de un flag |
| H3 | Ruta **fija** `/media/cisa/JETSON_SD/telegram_unidades_erroneas` para las imágenes que los validadores marcan como erróneas. No pasa por `config.py` y no coincide con `Jetson8/` | `avisos/telegram.py:305` | Los errores marcados por humanos (los datos más valiosos) pueden no guardarse o quedar fuera del volumen | [P] Moverla a `config.py`/`.env` |
| H4 | Los **recortes son redundantes**: en Roboflow hay 6,852 recortes "delantero" de M3 sin etiquetar, con 15+ casi idénticos por pasada (p. ej. la 5051 en el mismo segundo) | `CROPS_CADA_SEG=1` | Horas de etiquetado sin valor | [V] Resuelto en `reentrenamiento/seleccion.py` |
| H5 | **Etiquetado con polígonos**, ~1 min por imagen (video del 19 nov), en un modelo que es de **detección con cajas** | Proceso en Roboflow | Lento; el polígono se convierte en caja al entrenar | [V] Reglas en `docs/POLITICA_DATASET.md` + pre-etiquetas |
| H6 | Los `.engine` en producción se compilaron **en otro equipo**: TensorRT avisa que eso puede bajar el rendimiento o causar errores/bloqueos. Además están en FP32 (`half` sin activar) | log de `cisa-vision` | Rendimiento y estabilidad | [V] `scripts/exportar_engine.sh` compila en la propia Jetson con FP16 |
| H7 | M2 se **entrenó a 640** y corre a **1280** | `.pt` (metadatos) vs `ml/hilos.py:696` | Puede ser intencional (zonas lejanas) pero es lo más costoso | [?] Decidir al entrenar v4 |
| H8 | `restart: "no"` en los 3 servicios. Si un contenedor se cae, queda caído. En la Jetson existe `cisa.service` (systemd) que arranca al encender, pero **no está en el repo** | `docker-compose.yml` | Caídas de madrugada sin recuperación | [P] `unless-stopped` + versionar `cisa.service` |
| H9 | **README desactualizado**: dice `cd ~/Documents/ProyectoVisionCISA` (en la Jetson es `ProyectoVisionCISA_R`), dice que "no arranca solo" (sí arranca con `cisa.service`) y lista `check_tailscale.py` y `configurar_site.sh`, que están en `.gitignore` | `README.md:74,86,143-144` | Confusión al operar (la nota de operación apuntaba a la carpeta equivocada) | [V] Corregido parcialmente en esta rama (sección Reentrenamiento y aclaraciones) |
| H10 | Importar `config.py` **truena** sin `.env`, sin padrón o sin modelos, y `ml/modelos.py` carga los modelos en la GPU al importarse | `config.py:25-30,139`, `ml/modelos.py` | No se puede probar nada de `ml/` fuera de la Jetson | [V] El paquete nuevo no los importa; [P] para probar `ml/` hace falta carga diferida |
| H11 | Errores repetidos `[CALLBACK ERROR] Connection reset by peer` (Telegram bloqueado por la red del patio) | log de `cisa-vision` | Avisos que no llegan; ruido en el log | [P] Reintentos con espera o apagar Telegram en el patio |
| H12 | Imagen Docker `cisa-vision:jp7.2` sin uso (17 GB) y carpetas viejas `cam1_grabacion`/`cam2_grabacion` (22 GB) fuera de la limpieza de 72 h | Jetson | Espacio | [P] Limpiar con aprobación |
| H13 | Sin entrenamiento reproducible: los v3 se entrenaron en Colab (`/content/...`) con datasets de Roboflow, pero no quedó registro de args ni de la versión del dataset fuera de los metadatos del `.pt` | metadatos de los `.pt` | No se puede repetir ni comparar | [V] `reentrenamiento/entrenar.py` + `experimentos/registro.jsonl` |
| H14 | Sin set de prueba fijo ni criterios para aceptar un modelo | — | Riesgo de regresiones y "olvido" | [V] `dividir.py` (test congelado) + `evaluar.py` |

### Duplicaciones
- `reentrenamiento/predicciones.py:quitar_encimadas` replica `ml/reconocimiento.py:quitar_encimados` porque este último no se puede importar sin GPU (H10). La prueba `test_quitar_encimadas_como_produccion` fija el comportamiento. **[P]** Unificar cuando `ml/` tenga carga diferida.

---

## 4. Cuellos de botella del ciclo de actualización

| Etapa | Hoy | Por qué es lento |
|---|---|---|
| Juntar imágenes | `scp` manual de carpetas enteras | Sin filtro; se mueven miles de redundantes |
| Revisar capturas | Todas a ojo en Roboflow | Sin agrupación por pasada ni hash |
| Etiquetar | Polígono por dígito, desde cero | Sin pre-etiquetas; herramienta equivocada |
| Preparar dataset | Split aleatorio de Roboflow | Fuga entre splits (la misma pasada en train y test) → métricas infladas |
| Entrenar | Notebook manual en Colab | Sin registro; no reproducible |
| Evaluar | Métricas de Ultralytics del propio split | Sin comparación contra v3 ni criterios; sin exactitud del número completo |
| Desplegar | `.engine` compilado en otro equipo | Advertencias de TensorRT; sin canary ni rollback documentado |

---

## 5. Línea base medida (18-19 nov 2026, Jetson del Patio CCA)

| Medida | Valor | Fuente |
|---|---|---|
| Detecciones registradas | 3,501 (3-19 nov) | `/api/detecciones` |
| Marcadas "Desconocida" | 340, de las que 293 eran COPATTSA 2500-2515 leídas **bien** (faltaban en el padrón; el commit `dbbba2a` agrega COPATTSA) | API + revisión de fotos |
| Exactitud del número en camiones CCA | **12 de 16 (75 %)** en una muestra aleatoria revisada a mano. Muestra chica: intervalo amplio | Fotos de evidencia |
| Recortes acumulados | 148,508 (autobús 71,911 · lateral 57,907 · delantero 13,452 · trasera 5,238) | `/api/crops/stats` |
| Imágenes en Roboflow | M1 365 · M2 666 · M3 1,247 (con 0 modelos) + 6,852 recortes de M3 sin etiquetar | Presentación del 18 nov + video del 19 nov |
| Tiempo de etiquetado | ~1-1.5 min por recorte de M3 con polígonos (una observación) | Video del 19 nov |
| Velocidad de inferencia | YOLO 18-25 fps (M1) con el sistema completo | `/api/estado` |

Lo que falta medir para comparar (procedimiento en `docs/BENEFICIOS.md`): tiempo real por imagen con cajas y pre-etiquetas, % de recortes que conserva la selección con datos reales, mAP/exactitud de v3 sobre un test congelado y FPS con `.engine` FP16.
