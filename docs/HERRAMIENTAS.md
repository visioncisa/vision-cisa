# Matriz de herramientas

Prioridad: **P0** ya se usa o es indispensable · **P1** se adopta ahora · **P2** opcional más adelante · **—** no recomendada hoy.
Versiones: las de producción salen del `Dockerfile` (verificadas en la Jetson el 18 nov 2026). Los costos son aproximados y conviene revisar los precios vigentes.

**No se instaló nada nuevo en la Jetson.** El paquete `reentrenamiento/` solo necesita numpy, OpenCV y PyYAML, y Ultralytics en Colab.

## 1. Video y extracción

| Herramienta | Función | Versión | Compatibilidad / dependencias | Costo | Recursos | Ventajas | Desventajas | Alternativas | Prioridad | Integración |
|---|---|---|---|---|---|---|---|---|---|---|
| **GStreamer + NVDEC** | Decodificar RTSP H.265 por hardware | La de JetPack 7.2 | Solo Jetson; OpenCV de Ubuntu | Gratis | GPU/NVDEC | Casi no usa CPU | Pipeline frágil de configurar | FFmpeg | P0 (ya existe) | `logica/camara.py` |
| **FFmpeg** | Grabar sin recodificar; sacar cuadros | El de Ubuntu 24.04 (en la imagen) | Cualquier SO | Gratis | CPU | Abre H.265 aunque OpenCV no pueda; `-ss` rápido | Un proceso por llamada | PyAV | P0 | `scripts/grabar.sh`; respaldo en `extraer_video.py` |
| **OpenCV** | Leer video y medir calidad (Laplaciano, brillo) | 4.6 (Ubuntu, Jetson) / ≥4.8 headless (Mac, Colab) | numpy | Gratis | CPU | Ya está en todo el proyecto | `VideoCapture` sin H.265 en algunas compilaciones | scikit-image | P0 | `calidad.py`, `extraer_video.py` |
| PyAV | Decodificar con bindings de FFmpeg | 12+ | libav | Gratis | CPU | Acceso cuadro a cuadro preciso | Otra dependencia nativa | FFmpeg CLI | — | No necesaria |

## 2. Filtrado y selección inteligente

| Herramienta | Función | Versión | Dependencias | Costo | Recursos | Ventajas | Desventajas | Alternativas | Prioridad | Integración |
|---|---|---|---|---|---|---|---|---|---|---|
| **dHash / pHash propios** | Detectar imágenes casi iguales | `redundancia.py` | OpenCV, numpy | Gratis | Microsegundos por imagen | Sin dependencias extra; probado | No entiende semántica | `imagehash` | P1 (hecho) | `redundancia.py` |
| imagehash | Lo mismo, como librería | 4.3 | Pillow, scipy | Gratis | CPU | Varias variantes de hash | Dependencia extra para algo de 10 líneas | dHash propio | — | Usada solo en el notebook viejo |
| SSIM (scikit-image) | Similitud estructural | 0.24 | scipy | Gratis | ~100× un hash | Más fino | Lento en O(n²) | Hash | — | — |
| CLIP / DINOv2 (embeddings) | Similitud semántica; agrupar por condición | open_clip 2.x / torch hub | torch, GPU | Gratis | GPU + ~300 MB | Encuentra "mismo tipo de escena" | Pesado; hay que calibrarlo | — | P2 | Nuevo módulo `embeddings.py` en Colab |
| FiftyOne | Explorar datasets, duplicados, errores del modelo | 1.x | MongoDB embebido | Gratis (código abierto) | RAM moderada | Visualiza errores y "mistakenness" | Otra herramienta que aprender | Roboflow analytics | P2 | Leer lotes YOLO |
| cleanlab | Encontrar etiquetas probablemente mal | 2.x | sklearn | Gratis | CPU | Prioriza la revisión de calidad | Necesita probabilidades por imagen | Revisión al 10 % | P2 | Sobre `evaluacion.json` |

## 3. Anotación

| Herramienta | Función | Versión | Dependencias | Costo | Recursos | Ventajas | Desventajas | Alternativas | Prioridad | Integración |
|---|---|---|---|---|---|---|---|---|---|---|
| **Roboflow** | Etiquetar, versionar, aumentar, exportar YOLO | SaaS | Navegador; `roboflow` (pip) | Plan gratuito con límites; los proyectos privados pueden requerir plan de pago | Ninguno local | El equipo ya lo usa; acepta lotes YOLO con cajas; versiones | Límites del plan; datos en la nube; proyectos hoy públicos | CVAT, Label Studio | P0 (decisión del equipo) | Lote de `preanotacion.py`; descarga en el notebook |
| CVAT | Etiquetado avanzado (código abierto) | 2.x | Docker en un servidor | Gratis self-hosted | PC con 8 GB+ de RAM | Sin límites; pre-anotación con modelos | Hay que instalarlo y mantenerlo; migrar lo de Roboflow | Roboflow | — (P2 si crecen los límites) | Importa YOLO 1.1 |
| Label Studio | Etiquetado general | 1.x | Docker o pip | Gratis | Ligero | Flexible, ML backend | Menos cómodo para cajas en volumen | CVAT | — | Importa YOLO |

## 4. Versionado de datasets

| Herramienta | Función | Versión | Dependencias | Costo | Recursos | Ventajas | Desventajas | Alternativas | Prioridad | Integración |
|---|---|---|---|---|---|---|---|---|---|---|
| **Roboflow versions** | Versión inmutable de cada dataset | SaaS | — | Incluido | — | Ya está ahí | Atado a Roboflow | DVC | P0 | Número de versión en el notebook |
| **Hash del dataset + `congelado_mX.txt`** | Saber exactamente con qué se entrenó y evaluó | `entrenar.py`, `dividir.py` | — | Gratis | — | Funciona con cualquier origen | No guarda las imágenes | DVC | P1 (hecho) | `registro.jsonl` |
| DVC | Versionar datos grandes junto a git | 3.x | git + almacenamiento remoto (Drive/S3) | Gratis | Disco remoto | Estándar; reproducible | Curva de aprendizaje; duplica lo de Roboflow | Roboflow versions | P2 | `dvc.yaml` por etapa |

## 5. Entrenamiento y seguimiento de experimentos

| Herramienta | Función | Versión | Dependencias | Costo | Recursos | Ventajas | Desventajas | Alternativas | Prioridad | Integración |
|---|---|---|---|---|---|---|---|---|---|---|
| **Ultralytics YOLO** | Entrenar, validar y exportar | **8.4.171** (igual que la Jetson) | torch | AGPL-3.0 (revisar licencia para uso comercial) | GPU | Los v3 ya son YOLO26s; misma API en todos lados | Versiones nuevas cambian valores por defecto | — | P0 | `entrenar.py`, `evaluar.py` |
| **Google Colab Pro** | GPU para entrenar | — | Cuenta del proyecto | ~USD 10/mes | GPU L4/A100 por cuota | Ya lo tienen; sin hardware | Sesiones que se cortan; cuota | PC con GPU NVIDIA | P0 (decisión del equipo) | `notebooks/colab_reentrenamiento.ipynb` |
| **Registro JSONL propio** | Historial de experimentos | `entrenar.py` | — | Gratis | — | Cero infraestructura; en git | Sin gráficas | MLflow | P1 (hecho) | `experimentos/registro.jsonl` |
| MLflow | Seguimiento con interfaz web | 2.x | Servidor o carpeta local | Gratis | Ligero | Compara corridas con gráficas | Hay que alojarlo | W&B | P2 | Ultralytics lo soporta (`mlflow` en settings) |
| Weights & Biases | Seguimiento en la nube | SaaS | Cuenta | Gratis para uso personal o académico | — | Integrado con Ultralytics | Datos en la nube; cuenta | MLflow | — | — |
| pytest | Pruebas del pipeline | 8.x | — | Gratis | — | 60 pruebas sin GPU | — | — | P1 (hecho) | `tests/` |

## 6. Optimización y despliegue

| Herramienta | Función | Versión | Dependencias | Costo | Recursos | Ventajas | Desventajas | Alternativas | Prioridad | Integración |
|---|---|---|---|---|---|---|---|---|---|---|
| **TensorRT (export de Ultralytics)** | `.pt` → `.engine` FP16 | TRT **10.16.2** en la Jetson | CUDA 13.2 | Gratis | GPU de la Jetson | Una línea; guarda metadatos | **Debe compilarse en la misma Jetson** | `trtexec` | P1 | `scripts/exportar_engine.sh` |
| trtexec | Compilar y perfilar con más control | El de TRT | ONNX | Gratis | GPU | Perfilado de latencia por capa | Pierde metadatos de Ultralytics | Export de Ultralytics | P2 | Diagnóstico |
| INT8 (TensorRT) | Más velocidad con calibración | — | Set de calibración | Gratis | — | Hasta 2× sobre FP16 | Puede bajar la exactitud de dígitos | FP16 | P2 | Solo con evaluación completa |
| Docker Compose + systemd | Ejecutar, arrancar y reiniciar | Docker de la Jetson | — | Gratis | — | Ya existe | `restart: "no"` hoy | — | P0 | `docker-compose.yml`, `cisa.service` |
| Mermaid | Diagramas versionables | 11 | — | Gratis | — | GitHub los muestra en los `.md` | Diseños complejos difíciles | draw.io | P1 (hecho) | `docs/diagramas/` |
