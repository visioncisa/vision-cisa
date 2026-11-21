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

## 6. Resultados

### Corrida 1 — sin modelo (19 nov 2026, Mac, 16 s)
Datos: **toda** la carpeta `Jetson8/crops_dataset/delantero` copiada de la Jetson (solo lectura): **13,989 recortes**, 27 días entre el 11 jun y el 19 nov 2026, 172 MB. Los 6,852 de Roboflow son un subconjunto, pero **no se pudieron aislar** porque falta la lista de nombres del trabajo de Roboflow.

| Medida | Sin modelo (corrida 1) | Con modelo (corrida 2) |
|---|---|---|
| Recortes evaluados | 13,989 (100 % con nombre válido: fecha + track) | por medir |
| Pasadas | 2,448 (mediana: 2 recortes; máximo: 745; 557 de un solo recorte) | por medir |
| Elegidos (conservar + revisar) | **858** (536 representantes + 322 a revisar) | por medir |
| Descartados | 13,131: 7,947 pasada fácil fuera de la muestra · 5,144 cupo por pasada · 27 mala calidad · 14 repetidos | por medir |
| % a etiquetar | **6.1 %** (11 jun: 1.1 % de 3,918 · oct-nov: 8.1 % de 10,071) | por medir |
| Luz de los elegidos | día 559 · noche 205 · contraluz 94 (de 12,790 / 908 / 291 en el total) | por medir |
| Falsos descartes (IC 95 %) | por medir (auditoría humana, §3) | por medir |
| Horas de etiquetado (a 60-90 s por recorte, una observación) | todo: 233-350 h → elegidos: 14-21 h | por medir |

### Hallazgo: la corrida sin modelo pierde casos difíciles
Sin predicciones, solo cuentan como difíciles la luz y la nitidez. Por eso se descartaron completas pasadas que sí tenían señales de dificultad, **disponibles sin modelo en el nombre del archivo**:
- **339** pasadas descartadas en las que **producción leyó números distintos** para el mismo camión (de 515 pasadas así en total).
- **137** pasadas descartadas con al menos una lectura fallida de producción (`unk`).

Conclusión: el 6.1 % era un **mínimo**. Se corrigió con la opción (b): usar la lectura de producción como señal (corrida 1b).

### Corrida 1b — sin modelo + lecturas de producción (20 nov 2026, Mac)
`seleccion.py` agrega dos razones, controladas por `seleccion.usar_lectura_sistema` (activado por defecto):
- `sistema_minoria`: en la pasada, producción leyó un número distinto al más repetido (p. ej. `505` contra `5051`).
- `sistema_sin_lectura`: producción vio la zona pero no leyó nada (`unk`).

| Medida | Corrida 1 | **Corrida 1b** |
|---|---|---|
| Elegidos (conservar + revisar) | 858 (536 + 322) | **1,793** (679 + 1,114) |
| % a etiquetar | 6.1 % | **12.8 %** (11 jun: 128 · oct-nov: 1,665) |
| Pasadas descartadas con lecturas distintas de producción | 339 | **0** |
| Pasadas descartadas con `unk` | 137 | **2** (una borrosa y una demasiado chica: descarte correcto) |
| Descartados | 13,131 | 12,196: 8,199 cupo por pasada · 3,497 pasada fácil · 474 repetidos · 27 mala calidad |
| Recortes marcados por señal de producción | — | `sistema_minoria` 2,539 · `sistema_sin_lectura` 1,241 (antes del cupo de 3 por pasada) |
| Horas de etiquetado (60-90 s por recorte) | 14-21 h | **30-45 h** (contra 233-350 h si se etiqueta todo: **≈ 87 % menos**) |

Se cumplió lo esperado: menos del 15 % del total. La estimación de horas usa el tiempo con polígonos desde cero; con pre-etiquetas debería ser menor (por medir).

### Lo que todavía no se sabe
- **Cuántos descartes eran útiles**: requiere la auditoría humana (§3).
- **Cifras exactas para los 6,852 de Roboflow**: requiere la lista de nombres de ese trabajo.
- **Tiempo real de etiquetado con pre-etiquetas**: requiere cronometrar (§4).

## 7. Herramientas pendientes (para la siguiente iteración)

- Subcomando `auditar`: muestreo estratificado + página HTML local con cada recorte descartado **al lado** del elegido de su pasada y botones sí/no, que exporte `auditoria.csv` y calcule los intervalos de Wilson. Hoy se hace con el fragmento de pandas de arriba.
