# Cambios

Formato: fecha · rama · qué cambió. Las versiones de modelos van en su propia sección.

## Sin publicar — rama `mejora/reentrenamiento-eficiente`

### Agregado
- Paquete `reentrenamiento/` (CLI `python -m reentrenamiento`): extracción por eventos y periódica, calidad, deduplicación por pasada y hash, selección conservar/revisar/descartar con razones, lote YOLO pre-etiquetado para Roboflow, validador de datasets con detección de fuga, división por pasada con test congelado, entrenamiento con registro reproducible y evaluación con criterios de aceptación.
- `tests/`: 45 pruebas del paquete (sin GPU, sin `.env`) + 15 pruebas de caracterización de `validar_numero` que fijan el comportamiento ACTUAL de producción sin importarla (`tests/test_validar_numero_produccion.py`).
- `docs/PROBLEMA_VALIDAR_NUMERO.md`: análisis de las correcciones silenciosas (0063 → 5063, 505 → 5005), cómo medir su impacto y propuesta de corrección **no aplicada**.
- `docs/EVALUACION_SELECCION.md`: protocolo para evaluar la selección con los 6,852 recortes de M3 (siguiente etapa, sin ejecutar).
- `notebooks/colab_reentrenamiento.ipynb`: el ciclo completo en Colab Pro, llamando a la CLI.
- `scripts/exportar_engine.sh`: compila el `.engine` FP16 en la propia Jetson, verifica clases y velocidad, e imprime el rollback. **No se ha ejecutado.**
- `experimentos/m3_v4_finetune.yaml`: experimento de ejemplo.
- `docs/`: auditoría, arquitectura, pipeline, política del dataset, evaluación, diagramas Mermaid, herramientas, plan de implementación, beneficios, despliegue y mantenimiento.
- `requirements-reentrenamiento.txt`, separado del de producción.

### Cambiado
- `.gitignore`: lotes, datasets, corridas y pesos del reentrenamiento.
- `README.md`: sección "Reentrenamiento" y avisos sobre la carpeta y el arranque reales en la Jetson.

### Sin cambios en producción
`config.py`, `ml/`, `logica/`, `avisos/`, `metricas/`, `web/`, `docker-compose.yml` y `Dockerfile` quedan igual. Las mejoras propuestas están en `docs/PLAN_IMPLEMENTACION.md` (P1.5, P1.6, P4.3, P5.2), marcadas como pendientes de aprobación.

## Versiones de modelos en producción

| Fecha | Modelo | Versión | Archivo | Entrenado | Notas |
|---|---|---|---|---|---|
| 15 oct 2026 (compilado) | M1 autobús | v3 | `engine_nx/bus_v3.engine` | 12 jun 2026, YOLO26s, 640 | Compilado en otro equipo; FP32 |
| 15 oct 2026 (compilado) | M2 zona | v3 | `engine_nx/modelo_vista_v3.engine` | 11 jun 2026, YOLO26s, 640 | Corre a 1280 |
| 15 oct 2026 (compilado) | M3 dígitos | v3 | `engine_nx/modelo_digitos_v3.engine` | 10 jun 2026, YOLO26s, 640 | Exactitud del número en CCA ≈ 75 % (muestra de 16) |
