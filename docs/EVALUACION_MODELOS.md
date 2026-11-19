# Evaluación de modelos

Un modelo nuevo solo reemplaza al actual si pasa **las dos** evaluaciones:

1. **Offline** (Colab): `python -m reentrenamiento evaluar` sobre el set de prueba congelado → ACEPTAR/RECHAZAR automático.
2. **En la Jetson** (canary con video grabado): tracking, conteo, lectura completa y rendimiento, comparados con v3 sobre **el mismo video**.

---

## 1. Métricas

| Grupo | Métrica | Cómo se mide | Herramienta |
|---|---|---|---|
| **Detección** | Precisión, Recall | Emparejamiento por IoU ≥ 0.5, por clase | `evaluar.py` (`metricas`) |
| | mAP@50, mAP@50:95 | Estándar COCO | `model.val()` de Ultralytics (`--data-yaml`) |
| | Falsos positivos / falsos negativos | Conteo por clase | `evaluar.py` |
| **OCR (M3)** | Exactitud del número económico | Número completo leído = número real | `evaluar.py` |
| | CER | Distancia de edición / largo real | `evaluar.py` |
| | Lecturas fallidas | No se leyó nada | `evaluar.py` |
| | Asociación correcta con el autobús | El número registrado corresponde al camión de la foto | Canary: revisión de las fotos de evidencia |
| **Tracking** | Estabilidad de IDs | Cambios de `track_id` en un mismo camión | Canary: log `[M1]` + video |
| | Duplicaciones | Un camión con 2 IDs a la vez | Canary |
| | Pérdidas de seguimiento | Camión visible sin ID | Canary |
| **Conteo** | Precisión por evento | Cruces bien registrados / cruces reales | Canary: tabla de verdad del video |
| | Autobuses omitidos | Cruces reales sin registro | Canary |
| | Contados más de una vez | Registros duplicados | Canary |
| **Rendimiento** | FPS de M1 y M2/M3 | `yolo_fps`, `m2_fps` de `/api/estado` | Canary |
| | Latencia | Tiempo del cruce al registro | Log `✅ numero …` |
| | RAM, GPU | `jtop` / `tegrastats` | Jetson |
| | Estabilidad | Horas sin reinicio ni `CALLBACK ERROR` nuevos | Log, 48 h |

### Indicadores indirectos en producción (sin etiquetar nada)
- **Alternancia entrada/salida por unidad**: secuencias que no alternan revelan cruces perdidos o dirección mal detectada (línea base del 18 nov: 63 %).
- Lecturas descartadas por baja confianza (`descartadas` en `/api/estado`).
- % de "Desconocida" excluyendo empresas que faltan en el padrón.

---

## 2. Criterios de aceptación (verificables)

### Offline (`reentrenamiento/config_reentrenamiento.yaml` → `evaluacion.criterios`)

| Criterio | Valor por defecto | Rechaza si… |
|---|---|---|
| `recall_caida_max` | 0.01 | el recall global baja más de 1 punto |
| `precision_caida_max` | 0.01 | la precisión global baja más de 1 punto |
| (mAP) | 0.01 | mAP50 o mAP50-95 bajan más de 1 punto |
| `recall_clase_caida_max` | 0.03 | **cualquier clase** pierde más de 3 puntos de recall (olvido) |
| `exactitud_numero_caida_max` | 0.0 | M3: baja la exactitud del número completo |
| `cer_aumento_max` | 0.0 | M3: sube el CER |
| `mejora_minima` | 0.005 | **ninguna** métrica principal mejora al menos 0.5 puntos |

### En la Jetson (canary, mismo video para v3 y candidato)

| Criterio | Rechaza si… |
|---|---|
| Conteo | omite o duplica más cruces que v3 |
| Lectura | la exactitud del número (revisando las fotos de evidencia) es menor que con v3 |
| Tracking | más cambios de ID o duplicaciones que v3 |
| Rendimiento | FPS de M1 < 15 o de M2/M3 < `M2_FPS_MAX`, o la RAM crece de forma sostenida |
| Compatibilidad | el `.engine` no carga, imprime clases fuera de orden o hay errores CUDA/TensorRT |

## 3. Cómo armar el video de canary

1. Antes de que pase el borrado de 72 h, copiar 2 o 3 horas variadas (madrugada con salidas, noche con entradas, una hora de día) a `Jetson8/prueba/`.
2. Anotar a mano la **tabla de verdad**: hora, número económico, entrada/salida. Se hace una sola vez y se reutiliza.
3. Correr v3 en modo prueba (`python3 scripts/fuente.py video` + `VIDEOS_PRUEBA`) y guardar sus registros. Repetir con el candidato.
4. Comparar ambos contra la tabla de verdad. Ese video y su tabla se vuelven la **prueba de regresión** de producción.

## 4. Por qué no basta el mAP

El sistema no registra cajas: registra **números de camión que cruzan**. Un M3 con más mAP puede leer peor el número completo (basta un dígito cambiado), y un M1 con más mAP puede romper el tracking. Por eso la exactitud del número completo y el canary de conteo tienen poder de veto.
