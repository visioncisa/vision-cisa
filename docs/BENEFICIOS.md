# Medición de beneficios

**Regla:** aquí solo se anota lo medido. Lo que todavía no se mide dice **"por medir"** y explica cómo medirlo. Los ahorros "estimados" son cálculos sobre los datos medidos, no resultados.

## 1. Antes / Propuesta / Resultado

| Aspecto | Antes (medido o verificado) | Propuesta | Resultado medido | Ahorro estimado | Riesgo |
|---|---|---|---|---|---|
| Revisar capturas | Todas a ojo: 6,852 recortes de M3 "delantero" en un solo trabajo de Roboflow, con 15+ casi iguales por pasada | `seleccionar` agrupa por pasada, deduplica y descarta mala calidad | **Por medir** (P1.4). Con datos sintéticos: 24 recortes de 6 pasadas → ≤ 6 elegidos | Si se conserva ~1 de cada 4 a 8 recortes (lo que sugieren las pasadas de 15+ recortes), se revisaría entre 12 % y 25 % del total | Descartar un caso útil → se mitiga revisando 100 descartes al azar (P1.4) |
| Etiquetar | ~1-1.5 min por recorte, polígono por dígito, desde cero (una observación en video, 19 nov) | Cajas (tecla B) sobre pre-etiquetas de v3; solo se corrige | **Por medir** (P2.3): cronometrar 50 imágenes `revisar` y 50 `conservar` | Si baja a ~20 s por imagen: ~70 % menos por imagen, multiplicado por la reducción anterior | Que la gente acepte cajas malas sin mirar → control de calidad del 10 % |
| Preparar el dataset | Split aleatorio de Roboflow, sin revisar la fuga | `validar` + `dividir` por pasada con test congelado | Verificado en pruebas: una pasada nunca queda en dos splits | Menos tiempo y **métricas confiables** | Ninguno nuevo |
| Entrenar | Notebook manual, sin registro (los v3 solo dejaron metadatos en el `.pt`) | `entrenar` desde YAML + `registro.jsonl` | **Por medir** en Colab (P3.5) | Reproducible; el tiempo de GPU no cambia por esto | Desconexiones de Colab → queda el estado `fallido` |
| Evaluar | Métricas de Ultralytics del propio split; sin comparar contra v3 | `evaluar` vs v3 sobre el test congelado, con veto por olvido y exactitud del número | Verificado en pruebas (ACEPTAR/RECHAZAR) | De horas de criterio manual a un reporte automático | Que el test congelado no represente un caso nuevo → crear un congelado adicional |
| Desplegar | `.engine` compilado en otro equipo, FP32, sin canary documentado | `exportar_engine.sh` en la Jetson (FP16) + canary + rollback por `.env` | **Por medir** (P4.2): FPS antes y después | Menos riesgo de bloqueos; posible aumento de FPS por FP16 | Exportar en horario de tráfico → hacerlo en el horario bajo |
| Intervenciones humanas | Revisar todo, etiquetar todo, decidir "a ojo" si el modelo es mejor | Corregir solo lo marcado; 2 aprobaciones explícitas (reporte y activación) | **Por medir** | — | — |
| Almacenamiento | Recortes sin límite (148,508 acumulados; `crops_dataset` 3.5 GB) | Solo se sube a Drive o Roboflow el lote elegido | **Por medir** | Proporcional a la reducción de la selección | — |
| Calidad final | Exactitud del número en CCA: **12/16 (75 %)** en una muestra chica; 340 "Desconocida", 293 de ellas por padrón incompleto | Reentrenar con casos difíciles + quitar la corrección silenciosa (P4.3) | **Por medir** con el test congelado y el canary | — | Sobreajustar a los casos difíciles → 20 % de control de casos fáciles |

## 2. Cómo obtener la línea base que falta

1. **Selección (P1.4):** `python -m reentrenamiento seleccionar --entrada <6,852 recortes> --modelo m3 --salida /tmp/lote`. Anotar `porc_a_etiquetar` de `manifiesto.json`. Revisar 100 descartes al azar y contar cuántos eran útiles.
2. **Tiempo de etiquetado (P2.3):** cronometrar a la misma persona con 50 recortes en el método viejo (polígono desde cero) y 50 en el nuevo (cajas sobre pre-etiqueta). Anotar los minutos por imagen.
3. **Exactitud de v3 (P0.4):** etiquetar el test congelado y correr `evaluar` con v3 como "actual" y como "candidato" para obtener las métricas base.
4. **Conteo y lectura en producción (P0.3):** video de canary con tabla de verdad; correr v3 y anotar cruces omitidos, duplicados y números mal leídos.
5. **Rendimiento (P4.2):** `yolo_fps` y `m2_fps` de `/api/estado` durante 1 hora, antes y después de recompilar en FP16.

Cuando estén los números, llenar la columna "Resultado medido" y anotar la fecha en `CHANGELOG.md`.
