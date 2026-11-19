# Arquitectura

Diagrama de bloques editable: [`diagramas/06_bloques_arquitectura.mmd`](diagramas/06_bloques_arquitectura.mmd), que se ve en [DIAGRAMAS.md](DIAGRAMAS.md).
Leyenda: **[E]** existe en el repo o en la Jetson · **[N]** nuevo en esta rama · **[P]** propuesto, no implementado.

---

## 1. Infraestructura física

| Bloque | Estado | Entradas → salidas | Notas |
|---|---|---|---|
| Cámara IP Cam 1 | [E] | Escena → RTSP H.265, stream principal | Cuadros de 1920×1080 en la evidencia. La resolución de 704×576 citada en documentos viejos no se usa en el código |
| Cámara 2 | [E] | RTSP opcional (`RTSP_URL_CAM2`) | Solo se ve en vivo con el botón "Cam 2"; no se graba |
| Red del patio + Tailscale | [E] | Cámara ↔ Jetson; acceso remoto | El patio filtra `api.telegram.org` |
| Jetson Orin NX Super 16 GB | [E] | Video → registros, web, grabaciones | JetPack 7.2, CUDA 13.2, TensorRT 10.16.2; NVMe de 915 GB |
| Google Colab Pro | [N] | Dataset → `best.pt` | Solo entrenamiento y evaluación offline |
| Google Drive | [N] | Recortes, lotes, pesos, registro | Almacén de trabajo del reentrenamiento |
| Roboflow (workspace "cisas") | [E] | Lote YOLO → etiquetas corregidas, versiones | Proyectos M1, M2 y M3 |

## 2. Inferencia (contenedor `cisa-vision`)

| Bloque | Archivo | Entrada → salida | Formato / interfaz |
|---|---|---|---|
| Captura | `logica/camara.py` `CameraStream` | RTSP o `.mp4` → cuadro BGR | GStreamer NVDEC; FFmpeg de respaldo; `get_frame()` |
| Detección + tracking | `ml/hilos.py` `HiloM1` | Cuadro → autobuses con `track_id` | YOLO `.engine` imgsz 640 + ByteTrack; cola `_m2_queue` (tamaño 1) |
| Zona + dígitos | `ml/hilos.py` `HiloM2M3` + `ml/reconocimiento.py` | Cuadro + buses → número por camión | M2 imgsz 1280; M3 imgsz 640; CLAHE; votos |
| Línea virtual | `ml/linea_virtual.py` | Centro del bus por track → entrada/salida | Margen, maniobra 20 s, debounce 60 s |
| Validación | `avisos/gemini.py`, `avisos/telegram.py` | Foto + número → aprobado / corregido / no confirmado | HTTP a Gemini; botones de Telegram |
| Avisos | `avisos/whatsapp.py` + servicio `cisa-whatsapp` | Foto + texto → WhatsApp | HTTP local `127.0.0.1:5002` |
| Registro | `metricas/storage.py` | Evento → `evento_paso`, `estancia` | PostgreSQL `patio_cca` (fuera de Docker) |
| Web | `web/rutas.py` | BD + cuadros → tablero, MJPEG, API JSON | Flask :5001 (servidor de desarrollo) |
| Grabación | servicio `cisa-grabacion`, `scripts/grabar.sh` | RTSP → `cam1_AAAAMMDD_HHMMSS.mp4` | FFmpeg sin recodificar; 72 h |
| Datos | `Jetson8/` | Recortes (`crops_dataset`), cuadros (`cisa_frames`), grabaciones, errores | JPG con fecha, número y track en el nombre |

## 3. Procesamiento para reentrenamiento (`reentrenamiento/`) [N]

| Bloque | Entrada → salida | Detalle |
|---|---|---|
| `extraer_video.py` | Eventos (JSON de `/api/detecciones` o CSV) + grabaciones → JPG | Ventana ±N s por evento o 1 cuadro cada N s; OpenCV con FFmpeg de respaldo |
| `nombres.py` | Ruta → fecha, número leído, track, zona | Entiende los nombres de producción y los renombres de Roboflow |
| `calidad.py` | Imagen → nitidez, brillo, contraste, tamaño, luz | Solo CPU |
| `redundancia.py` | Recortes → pasadas + dHash/pHash | Usa el track de ByteTrack |
| `predicciones.py` | `.pt` + imágenes → cajas, lectura, confianza | Ultralytics opcional; misma regla anti-encimados que producción |
| `seleccion.py` | Todo lo anterior → conservar / revisar / descartar + razones | Umbrales en `config_reentrenamiento.yaml` |
| `preanotacion.py` | Decisiones + cajas → lote YOLO | `images/`, `labels/`, `data.yaml`, `resumen.csv`, `manifiesto.json` |
| `validar_etiquetas.py` | Dataset YOLO → reporte con errores y advertencias | Clases, coordenadas, polígonos, huérfanos, fuga |
| `dividir.py` | Dataset plano → train/valid/test por pasada | Test congelado (`congelado_mX.txt`) |
| `entrenar.py` | YAML de experimento → `best.pt` + `registro.jsonl` | Fine-tuning; registra commit, hash del dataset y versiones |
| `evaluar.py` | Verdad + predicciones de 2 modelos → `evaluacion.md/.json` | Criterios de aceptación; código de salida 0 o 3 |
| `__main__.py` | CLI | `python -m reentrenamiento <paso>` |

Regla de diseño: **no importa `config.py` ni `ml/`**, que exigen `.env`, padrón, modelos y GPU. Por eso corre igual en Mac, Colab y Jetson, y se prueba con `pytest`.

## 4. Administración

| Bloque | Estado | Qué hace |
|---|---|---|
| `config.py` + `.env` | [E] | Configuración de producción |
| `config_reentrenamiento.yaml` | [N] | Umbrales de selección y criterios de aceptación, separados de producción |
| `experimentos/*.yaml` + `registro.jsonl` | [N] | Experimentos reproducibles y su historial |
| `tests/` | [N] | 45 pruebas del paquete de reentrenamiento + 15 de caracterización de `validar_numero` (producción) |
| `scripts/exportar_engine.sh` | [N] | Compila el `.engine` en la Jetson (FP16), verifica clases y velocidad, e imprime el rollback |
| `cisa.service` (systemd) | [E] en la Jetson, **no en el repo** | Arranca los contenedores al encender |
| Monitoreo de indicadores | [P] | Alternancia, descartadas, FPS → alerta |
| Respaldos | [P] | `pg_dump` diario de `patio_cca` + copia de `padron.csv` y `.env` |
| `CHANGELOG.md` | [N] | Historial de cambios y de versiones de modelos |

## 5. Comunicación entre componentes

| De → a | Medio | Local / remoto |
|---|---|---|
| Cámara → Jetson | RTSP/TCP | Local (red del patio) |
| HiloM1 → HiloM2M3 | `queue.Queue(maxsize=1)` | Mismo proceso |
| Hilos → PostgreSQL | psycopg2, `localhost:5432` | Local |
| cisa-vision → cisa-whatsapp | HTTP `127.0.0.1:5002` | Local |
| cisa-vision → Gemini / Telegram | HTTPS | Remoto (Telegram bloqueado en el patio) |
| Navegador → Flask | HTTP :5001 vía Tailscale | Remoto |
| Jetson → Drive | `scp` a una PC o subida manual | Remoto, manual |
| Colab ↔ Roboflow | API Roboflow (`ROBOFLOW_API_KEY` en Secrets) | Remoto |
| Colab → Jetson | `best.pt` por `scp` | Remoto, manual y con aprobación |
