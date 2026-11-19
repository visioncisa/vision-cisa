# Plan de implementación

Estado: ✅ hecho en la rama `mejora/reentrenamiento-eficiente` · ⏳ pendiente · 🔒 requiere aprobación (toca producción o la Jetson).
Esfuerzo: S ≤ medio día · M 1-2 días · L 3-5 días.

## P0 — Auditoría y respaldo

| ID | Tarea | Dep. | Esf. | Riesgo | Archivos | Pruebas | Resultado esperado | Estado |
|---|---|---|---|---|---|---|---|---|
| P0.1 | Auditoría del repo y de la Jetson | — | M | Bajo | `docs/AUDITORIA.md` | — | Hallazgos H1-H14 con referencias | ✅ |
| P0.2 | Respaldo antes de tocar modelos: `.env`, `modelos/engine_nx/`, `padron.csv`, `pg_dump patio_cca` | — | S | Bajo | (en la Jetson) | Restaurar en una copia | Punto de regreso | ⏳ 🔒 |
| P0.3 | Video de canary + tabla de verdad (2-3 h) | — | M | Bajo | `Jetson8/prueba/`, `experimentos/canary_verdad.csv` | — | Prueba de regresión de producción | ⏳ |
| P0.4 | Línea base de v3 en el canary y en el test congelado | P0.3, P2.3 | S | Bajo | `experimentos/eval_*` | `evaluar` | Números contra los cuales comparar | ⏳ |
| P0.5 | Confirmar la resolución de `LINEA_P1/P2` (¿704×576 o 1920×1080?) | — | S | Bajo | `config.py`, `.env` | Dibujar la línea sobre un cuadro | Línea en la escala correcta | ⏳ |

## P1 — Captura inteligente

| ID | Tarea | Dep. | Esf. | Riesgo | Archivos | Pruebas | Resultado esperado | Estado |
|---|---|---|---|---|---|---|---|---|
| P1.1 | Lectura de nombres, calidad y hashes | — | M | Bajo | `reentrenamiento/{nombres,calidad,redundancia}.py` | `tests/test_nombres_calidad_redundancia.py` | Base de la selección | ✅ |
| P1.2 | Selección conservar/revisar/descartar | P1.1 | M | Medio (umbrales) | `seleccion.py`, `config_reentrenamiento.yaml` | `tests/test_predicciones_seleccion.py` | Reducción medible de imágenes a revisar | ✅ |
| P1.3 | Extracción por eventos y periódica | P1.1 | S | Bajo | `extraer_video.py` | `tests/test_extraer_y_cli.py` | Cuadros alrededor de cada cruce | ✅ |
| P1.4 | ⭐ **SIGUIENTE ETAPA** — protocolo en [EVALUACION_SELECCION.md](EVALUACION_SELECCION.md). **Calibrar umbrales con datos reales**: correr `seleccionar` sobre los 6,852 recortes de M3 y revisar 100 descartes al azar | P1.2 | S | Medio | `config_reentrenamiento.yaml` | Revisión manual de descartes | Que ningún descarte sea un caso útil | ⏳ |
| P1.5 | Metadatos junto a cada recorte (conf M2/M3, lectura cruda y validada), detrás de un flag | — | S | Medio (producción) | `ml/reconocimiento.py`, `config.py` | Prueba con `ml/` en carga diferida | Selección sin volver a correr el modelo | ⏳ 🔒 |
| P1.6 | Mover la ruta de `telegram_unidades_erroneas` a `config.py` | — | S | Bajo | `avisos/telegram.py`, `config.py`, `.env.example` | Botón ✗ en Telegram de prueba | Errores humanos guardados en `Jetson8` | ⏳ 🔒 |

## P2 — Preanotación

| ID | Tarea | Dep. | Esf. | Riesgo | Archivos | Pruebas | Resultado esperado | Estado |
|---|---|---|---|---|---|---|---|---|
| P2.1 | Lote YOLO con pre-etiquetas y razones | P1.2 | M | Bajo | `preanotacion.py`, `predicciones.py` | `test_escribir_lote` | Cajas ya dibujadas en Roboflow | ✅ |
| P2.2 | Validador de datasets (clases, coords, polígonos, fuga) | — | M | Bajo | `validar_etiquetas.py` | `tests/test_dataset_evaluacion.py` | Ningún entrenamiento con datos rotos | ✅ |
| P2.3 | Primer lote real de M3 en Roboflow (quitar antes el lote viejo sin etiquetar) | P1.4, P2.1 | M | Medio (duplicados en Roboflow) | — | Medir minutos por imagen | Tiempo real de etiquetado | ⏳ 🔒 |
| P2.4 | Pasar los proyectos de Roboflow a **privados** | — | S | Bajo | — | — | Imágenes del patio no públicas | ⏳ 🔒 |

## P3 — Reentrenamiento

| ID | Tarea | Dep. | Esf. | Riesgo | Archivos | Pruebas | Resultado esperado | Estado |
|---|---|---|---|---|---|---|---|---|
| P3.1 | División por pasada + test congelado | P2.2 | S | Bajo | `dividir.py` | `test_misma_pasada_mismo_split_y_test_congelado` | Métricas sin fuga | ✅ |
| P3.2 | Entrenamiento con registro reproducible | P3.1 | M | Medio (Colab) | `entrenar.py`, `experimentos/*.yaml` | `test_entrenar_*` (simulado) | `registro.jsonl` por corrida | ✅ (sin correr con GPU) |
| P3.3 | Evaluación con criterios de aceptación | P3.1 | M | Bajo | `evaluar.py` | `test_comparar_*`, `test_cli_evaluar_codigos` | ACEPTAR/RECHAZAR automático | ✅ |
| P3.4 | Notebook de Colab que llama a la CLI | P3.2, P3.3 | S | Bajo | `notebooks/colab_reentrenamiento.ipynb` | Correrlo completo en Colab | Proceso de un solo notebook | ✅ (sin correr en Colab) |
| P3.5 | Primer M3 v4 real (fine-tuning + variante `freeze: 10`) | P2.3, P3.4 | M | Medio | `experimentos/m3_v4_*.yaml` | `evaluar` vs v3 | Candidato aceptado o motivos de rechazo | ⏳ |
| P3.6 | Decidir el imgsz de M2 (entrenado a 640, corre a 1280) | P0.4 | S | Medio | `experimentos/m2_*.yaml` | Comparar mAP y FPS | Configuración coherente | ⏳ |

## P4 — Integración

| ID | Tarea | Dep. | Esf. | Riesgo | Archivos | Pruebas | Resultado esperado | Estado |
|---|---|---|---|---|---|---|---|---|
| P4.1 | Script de exportación en la Jetson (FP16, verifica clases y velocidad, imprime rollback) | — | S | Medio | `scripts/exportar_engine.sh` | `bash -n`; correrlo en la Jetson | `.engine` compilado en el mismo equipo | ✅ escrito, ⏳ sin ejecutar 🔒 |
| P4.2 | Recompilar los v3 actuales en la Jetson con FP16 (sin cambiar pesos) | P0.2, P4.1 | S | Medio | `modelos/engine_nx/` | Canary P0.3 | Quitar la advertencia de TRT; más FPS | ⏳ 🔒 |
| P4.3 | Flag `CORREGIR_LECTURAS` ([PROBLEMA_VALIDAR_NUMERO.md](PROBLEMA_VALIDAR_NUMERO.md)) (apagar la corrección con prefijo 5) | P0.4 | S | **Alto** (cambia registros) | `ml/reconocimiento.py`, `config.py` | Canary: comparar falsos verificados | Sin errores silenciosos tipo 0063→5063 | ⏳ 🔒 |
| P4.4 | Canary de tracking, conteo y lectura para cada candidato | P0.3 | M | Bajo | `docs/EVALUACION_MODELOS.md` | Tabla de verdad | Veto antes de producción | ⏳ |
| P4.5 | Traer las pruebas de la línea virtual (rama `feat/linea-virtual-finita`) | — | S | Bajo | `tests/test_linea_virtual.py` | pytest | Cobertura de conteo | ⏳ |

## P5 — Mantenimiento

| ID | Tarea | Dep. | Esf. | Riesgo | Archivos | Pruebas | Resultado esperado | Estado |
|---|---|---|---|---|---|---|---|---|
| P5.1 | Documentación (este conjunto) + capítulo LaTeX | — | M | Bajo | `docs/`, `CHANGELOG.md`, capítulo 09 | Revisión | Proceso documentado | ✅ |
| P5.2 | `restart: unless-stopped` y versionar `cisa.service` en el repo | — | S | Medio | `docker-compose.yml`, `deploy/cisa.service` | Matar el contenedor y ver que vuelve | Recuperación automática | ⏳ 🔒 |
| P5.3 | Monitoreo de indicadores (alternancia, descartadas, FPS) con aviso | — | M | Bajo | `metricas/`, nuevo `scripts/salud.py` | Datos históricos | Detectar regresiones sin etiquetar | ⏳ |
| P5.4 | Respaldo diario de PostgreSQL y retención de recortes | — | S | Bajo | `scripts/respaldo.sh` | Restaurar | Sin pérdida de datos ni de disco | ⏳ 🔒 |
| P5.5 | CI con GitHub Actions: `pytest tests/` en cada PR | P1-P3 | S | Bajo | `.github/workflows/pruebas.yml` | — | Nada se fusiona roto | ⏳ |
| P5.6 | Embeddings y clustering para la muestra de fáciles (si el hash no alcanza) | P1.4 | M | Bajo | `reentrenamiento/embeddings.py` | Comparar contra el muestreo al azar | Mejor diversidad | ⏳ |

## Qué se puede hacer en paralelo

- **De inmediato y en paralelo:** P0.2 · P0.3 · P0.5 · P1.4 · P2.4 · P4.5 · P5.5.
- **Después de P1.4:** P2.3 (etiquetar) en paralelo con P4.2 (recompilar los v3 en FP16).
- **Después de P2.3:** P3.5 (entrenar M3) en paralelo con P3.6 (M2).
- **P4.3** (corrección con prefijo 5) va **sola**, después de tener la línea base P0.4, porque cambia lo que se registra.

## Ruta crítica para el primer modelo nuevo

P1.4 → P2.3 → P3.5 → P4.4 → P4.1 (exportar) → activación con aprobación.
