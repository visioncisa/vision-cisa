# Evaluación de la selección automática con los 6,852 recortes de M3

**Prioridad:** siguiente etapa (P1.4), antes de cualquier entrenamiento real.
**Pregunta:** de los 6,852 recortes "delantero" de M3 sin etiquetar, ¿cuántos conserva la selección, cuántos descarta, cuántos de los descartados eran útiles y cuánto trabajo manual se ahorra?
**Estado:** protocolo listo · **sin ejecutar** (falta copiar los recortes) · todos los resultados: *por medir*.

## 1. Datos

| Opción | Cómo | Pros | Contras |
|---|---|---|---|
| **A. Desde la Jetson (recomendada)** | `scp -r jetson@<ip>:Documents/Jetson8/crops_dataset/delantero ./recortes_m3/` (solo lectura: no cambia nada en la Jetson) | Nombres originales con fecha, número leído y **track**: la agrupación por pasada funciona completa | Trae todos los "delantero" (13,452 según `/api/crops/stats`), no solo los 6,852; requiere la contraseña de la Jetson |
| B. Desde Roboflow | Exportar o descargar el trabajo sin etiquetar de M3 | Exactamente los 6,852 | Roboflow puede renombrar archivos; las imágenes sin etiquetar no siempre se exportan en una versión |

Con la opción A, el subconjunto de los 6,852 se identifica por nombre (la lista de nombres se saca de Roboflow) y se evalúan **los dos**: el subconjunto (para comparar con lo que se iba a etiquetar) y el total (para dimensionar).

## 2. Corridas

| # | Dónde | Comando | Mide |
|---|---|---|---|
| 1 | Mac (sin GPU) | `python -m reentrenamiento seleccionar --entrada recortes_m3 --modelo m3 --salida lote_sin_modelo` | Reducción solo por calidad, pasada y hash |
| 2 | Colab (GPU) | `python -m reentrenamiento preanotar --entrada recortes_m3 --modelo m3 --pesos modelo_digitos_v3.pt --padron padron.csv --salida lote_con_modelo` | Reducción completa, más los casos difíciles por razón |

De cada corrida se anotan, desde `manifiesto.json`: `total`, `pasadas`, `conservar`, `revisar`, `descartar`, `porc_a_etiquetar` y el conteo por razón.

## 3. Auditoría humana de una muestra

La selección **no puede medirse sola**: hay que revisar a mano una muestra para saber si los descartes eran prescindibles.

| Grupo | Tamaño de muestra | Pregunta para quien revisa |
|---|---|---|
| Descartados `redundante` / `cupo_pasada` | 100 | ¿Aporta algo que **no** tenga el recorte elegido de su misma pasada? (verlos lado a lado) |
| Descartados `pasada_facil_fuera_de_muestra` | 50 | ¿Es un caso difícil que la selección no detectó? |
| Descartados `mala_calidad:*` | 50 | ¿Un humano podría etiquetarlo con seguridad? |
| Elegidos `revisar` | 50 | ¿De verdad es un caso difícil o útil? |
| Elegidos `conservar` | 30 | ¿La pre-etiqueta ya es correcta? (mide cuánta corrección hace falta) |

Muestreo al azar dentro de cada grupo, con semilla fija, sobre el `resumen.csv`:
```python
import pandas as pd
r = pd.read_csv("lote_con_modelo/resumen.csv")
muestra = (r.assign(grupo=r.razones.str.split("|").str[-1])
             .groupby("grupo", group_keys=False)
             .apply(lambda g: g.sample(min(len(g), 100), random_state=7)))
muestra.to_csv("auditoria.csv", index=False)   # agregar columna 'util' (sí/no) al revisar
```

## 4. Cálculos

| Medida | Fórmula |
|---|---|
| % a etiquetar | `(conservar + revisar) / total` |
| Tasa de falsos descartes (por grupo) | `útiles en la muestra / tamaño de la muestra`, con intervalo de Wilson al 95 % |
| Útiles perdidos (estimado) | `tasa × descartados del grupo`, sumado por grupo |
| Horas de revisión ahorradas | `(total − elegidos) × t_revisar_1` |
| Horas de etiquetado ahorradas | `total × t_poligono − elegidos × t_con_preetiqueta` |

Tiempos:
- `t_poligono`: ~60-90 s por recorte (una observación en video, 19 nov). **Hay que medirlo** cronometrando 50 recortes.
- `t_con_preetiqueta`: **por medir**, con 50 recortes del lote con cajas ya dibujadas.
- `t_revisar_1`: segundos para decidir si un recorte sirve (por medir, 50 recortes).

## 5. Criterio de aceptación de la selección

- Límite superior del intervalo de Wilson de falsos descartes **< 5 %** en `redundante`/`cupo_pasada`, y **< 10 %** en `mala_calidad`.
- Si no se cumple, se ajusta `config_reentrenamiento.yaml` (`hash_distancia_min`, `max_por_pasada`, `nitidez_descartar`, `porc_faciles`) y se repite la corrida 2 y la auditoría solo del grupo que falló.
- Los ajustes y sus resultados se anotan en este documento y en `CHANGELOG.md`.

## 6. Resultados (llenar al ejecutar)

| Medida | Sin modelo (corrida 1) | Con modelo (corrida 2) |
|---|---|---|
| Recortes evaluados | por medir | por medir |
| Pasadas | por medir | por medir |
| Elegidos (conservar + revisar) | por medir | por medir |
| Descartados por calidad / redundancia / fácil | por medir | por medir |
| % a etiquetar | por medir | por medir |
| Falsos descartes (IC 95 %) | — | por medir |
| Horas ahorradas (revisión + etiquetado) | — | por medir |

## 7. Herramientas pendientes (para la siguiente iteración)

- Subcomando `auditar`: muestreo estratificado + página HTML local con cada recorte descartado **al lado** del elegido de su pasada y botones sí/no, que exporte `auditoria.csv` y calcule los intervalos de Wilson. Hoy se hace con el fragmento de pandas de arriba.
