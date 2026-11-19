# Pipeline de reentrenamiento

```
video → eventos → extracción → filtrado → selección diversa → preanotación
      → revisión humana selectiva → dataset versionado → fine-tuning
      → evaluación → despliegue controlado
```

Todo se hace con `python -m reentrenamiento <paso>` (paquete `reentrenamiento/`) o con el notebook `notebooks/colab_reentrenamiento.ipynb`, que llama a esos mismos comandos. Los diagramas están en [DIAGRAMAS.md](DIAGRAMAS.md).

---

## Receta corta (M3, de punta a punta)

| # | Dónde | Comando / acción | Resultado |
|---|---|---|---|
| 1 | Jetson | Copiar `crops_dataset/{delantero,lateral,trasera}` de las fechas nuevas + `telegram_unidades_erroneas/` a Drive | Recortes crudos |
| 2 | Colab | `python -m reentrenamiento preanotar --entrada <crudas> --modelo m3 --pesos modelo_digitos_v3.pt --padron padron.csv --salida <lote>` | Lote YOLO con cajas y `resumen.csv` |
| 3 | Roboflow | Subir la carpeta del lote; corregir **solo** las marcadas `revisar` (y muestrear las `conservar`) | Etiquetas corregidas |
| 4 | Roboflow | Generar versión (sin volteos) y exportar en formato YOLO | Dataset |
| 5 | Colab | `validar` → `dividir --congelado congelado_m3.txt` → `validar` | Dataset dividido por pasada, sin fuga |
| 6 | Colab | `entrenar --experimento experimentos/m3_v4_finetune.yaml` | `best.pt` + línea en `registro.jsonl` |
| 7 | Colab | `evaluar --pesos-actual v3.pt --pesos-candidato best.pt ...` | `evaluacion.md`: ACEPTAR o RECHAZAR |
| 8 | Jetson | Con aprobación: `bash scripts/exportar_engine.sh m3 best.pt v4` → canary → activar | `.engine` FP16 compilado en la Jetson |

Código de salida de `evaluar`: `0` = aceptar, `3` = rechazar (sirve para automatizar).

---

## 1. Captura

| Modo | Cuándo | Comando |
|---|---|---|
| **Recortes de producción** (ya existen) | Siempre: es la fuente principal. Traen fecha, número leído y track en el nombre | — (se copian) |
| **Por eventos** | Para entender un cruce mal registrado o sacar cuadros completos (M1) alrededor de cada paso | `extraer --modo eventos --eventos detecciones.json --grabaciones <dir> --salida <dir>` |
| **Periódico** | Condiciones nuevas: lluvia, noche, obras, cámara movida | `extraer --modo periodico --video cam1_….mp4 --cada 30` |
| **Errores marcados por humanos** | Siempre que existan: son los casos donde el modelo falló de verdad | — (carpeta `telegram_unidades_erroneas/`) |

Las grabaciones se borran a las 72 h: un evento sin video se reporta como `sin_video` y no detiene el proceso.

## 2. Filtrado y selección (qué se conserva, qué se descarta, qué se revisa)

Criterios exactos y umbrales: [POLITICA_DATASET.md](POLITICA_DATASET.md). Resumen:

1. **Calidad** — se descarta lo borroso, oscuro, sobreexpuesto, sin contraste, demasiado chico o ilegible.
2. **Pasada** — los recortes del mismo camión (zona + track + menos de 6 s) forman un grupo. **Aquí se aprovecha el ID del tracking** que producción ya pone en el nombre del archivo.
3. **Incertidumbre** — con el modelo actual: sin dígitos, cantidad de dígitos imposible, desacuerdo con el consenso de la pasada, confianza baja, lectura distinta a la que registró producción, número fuera del padrón.
4. **Diversidad** — dentro de la pasada solo entra lo que se ve distinto (dHash ≥ 6). Luz de noche o contraluz cuenta como condición nueva.
5. **Control** — un 20 % de las pasadas fáciles entra como representante, para que el modelo no olvide lo que ya hace bien. **No se seleccionan solo los casos de alta confianza.**

### Comparación de técnicas

| Técnica | Qué detecta | Costo | Uso aquí |
|---|---|---|---|
| **Track + ventana de tiempo** | Recortes de la misma pasada | Nulo (viene en el nombre) | **Sí**: primer filtro |
| **dHash / pHash** (64 bits) | Imágenes casi idénticas | Microsegundos, CPU | **Sí**: dentro de la pasada y para detectar fuga entre splits |
| SSIM | Similitud estructural exacta | ~100× más que un hash; comparación por pares O(n²) | No: no aporta frente al hash en una cámara fija |
| Embeddings visuales (CLIP, DINOv2) | Similitud semántica (ángulo, iluminación) | GPU + modelo extra de 300 MB+ | Opcional (P5): solo si el hash deja pasar demasiados parecidos entre pasadas distintas |
| Clustering (k-means sobre embeddings) | Cubrir variedad global | Requiere embeddings | Opcional (P5): para muestrear las pasadas fáciles por grupos y no al azar |
| **Muestreo por incertidumbre** (active learning) | Lo que el modelo no sabe | Una pasada de inferencia | **Sí**: razones `baja_conf`, `desacuerdo`, `sin_digitos`… |
| **Muestreo por diversidad** | Condiciones poco vistas | Medir luz (CPU) | **Sí**: `condicion_nueva` |
| **Casos difíciles con verdad externa** | Errores reales | Gratis: ya existen | **Sí**: `sistema_distinto` y `telegram_unidades_erroneas` |

## 3. Preanotación y revisión humana

- El modelo actual dibuja las cajas con `conf=0.25` (bajo a propósito: es más rápido borrar una caja que dibujarla).
- En Roboflow se trabaja por prioridad: `sistema_distinto` → `desacuerdo` → `baja_conf`/`fuera_padron`/`condicion_nueva` → muestreo de `conservar`.
- **Roboflow** se queda como herramienta (decisión del equipo): ya tiene M1, M2 y M3. CVAT y Label Studio se comparan en [HERRAMIENTAS.md](HERRAMIENTAS.md).
- Control de calidad: una segunda persona revisa el 10 % al azar; con más de 5 % de errores se devuelve el lote completo.

## 4. Dataset versionado

- **Roboflow versions** guarda cada versión etiquetada. El repo guarda el **hash del dataset** (nombres de imagen + contenido de etiquetas) en `experimentos/registro.jsonl`.
- `dividir` reparte **por pasada** con un hash estable: la misma pasada cae siempre en el mismo split.
- **Set de prueba congelado** (`congelado_m3.txt`): se crea una vez y no cambia. Así v4, v5… se comparan contra el mismo examen. Se versiona en el repo (son nombres, no imágenes).
- `validar` detiene el proceso si hay clases fuera de orden, coordenadas inválidas, polígonos o fuga entre splits.

## 5. Entrenamiento

Se entrena en **Google Colab Pro**. La Jetson queda solo para inferencia y para compilar el `.engine`.

### Comparación de estrategias

| Estrategia | Cuándo conviene | Riesgo | Decisión |
|---|---|---|---|
| **1. Fine-tuning desde los pesos actuales (v3)** | Mismas clases, misma cámara, datos nuevos de casos difíciles | Olvido si solo se entrena con lo nuevo | **Por defecto**, siempre con datos anteriores + nuevos (estrategia 5) |
| 2. Desde pesos preentrenados (COCO, `yolo26s.pt`) | Si v3 tiene un sesgo que el fine-tuning no corrige, o cambian las clases | Más épocas y más datos | Experimento de control 1 de cada N versiones |
| 3. Desde cero | Solo si cambia la arquitectura de forma radical | Necesita muchos más datos | **No justificado** hoy |
| 4. Congelar capas (`freeze: 10` = backbone) | Pocos datos nuevos (< 500 imágenes) | Menos capacidad de adaptarse | Probar como variante cuando el lote es chico |
| **5. Incremental (anteriores + nuevos)** | Siempre | Dataset más grande → entrenamiento más largo | **Sí**: el dataset de Roboflow acumula versiones |
| 6. Hiperparámetros | `lr0` bajo (0.002 con SGD) para fine-tuning; `optimizer: auto` ignora `lr0` | Sobreajuste al buscar demasiado | Solo `lr0`, `freeze` y épocas; sin búsqueda grande |
| 7. Early stopping (`patience: 30`) | Siempre | Cortar demasiado pronto | Sí |
| 8. Batch y resolución | `imgsz` **igual a producción** (M1/M3 = 640). M2 entrenado a 640 y corre a 1280: decidir en v4 | Cambiar el imgsz cambia la velocidad en la Jetson | Batch 16 en L4 o A100; `-1` (auto) si falta memoria |

**No se asume que lo incremental sea mejor**: cada candidato pasa por `evaluar` contra v3 en el set congelado, con un criterio explícito de **olvido por clase** (ninguna clase puede perder más de 3 puntos de recall). Ver [EVALUACION_MODELOS.md](EVALUACION_MODELOS.md).

### Registro de cada experimento

`experimentos/registro.jsonl` (una línea por corrida): fecha, nombre, modelo, pesos base, `data.yaml`, **hash del dataset**, **commit de git** (con la marca `-con-cambios` si había cambios sin guardar), versiones (Python, ultralytics, torch, GPU), args, métricas finales, ruta y **sha256** de `best.pt`, y estado (`terminado` / `fallido` + error). Los pesos se guardan en Drive, no en git.

## 6. Evaluación y despliegue

- `evaluar` → `evaluacion.md` y `evaluacion.json`. ACEPTAR solo si no hay regresiones **y** mejora al menos una métrica principal.
- Las métricas de tracking, conteo y rendimiento se miden en la Jetson con video grabado (modo prueba): [EVALUACION_MODELOS.md](EVALUACION_MODELOS.md).
- Exportación, canary, activación y rollback: [DESPLIEGUE.md](DESPLIEGUE.md).
