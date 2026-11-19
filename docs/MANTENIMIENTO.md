# Mantenimiento

## Rutina

| Frecuencia | Tarea | Cómo |
|---|---|---|
| Diaria (automático) | Grabaciones: se borran las de más de 72 h | `scripts/grabar.sh` (`RETENCION`) |
| Semanal | Revisar indicadores: % de "Desconocida" (sin contar empresas fuera del padrón), descartadas, alternancia entrada/salida, FPS | Tablero y `/api/estado`; P5.3 lo automatiza |
| Semanal | Copiar a Drive los recortes nuevos y `telegram_unidades_erroneas/` | `scp` o subida manual |
| Mensual (o cuando suben los errores) | Ciclo de reentrenamiento | [PIPELINE_REENTRENAMIENTO.md](PIPELINE_REENTRENAMIENTO.md) |
| Al cambiar el padrón | Editar `padron.csv` y recrear `cisa-vision` | README → "Unidades nuevas o de otra empresa" |
| Antes de cada cambio | `pytest tests/` | En la Mac o en CI (P5.5) |

## Cuándo reentrenar (disparadores)

- La exactitud del número en el canary baja respecto de la última medición.
- Sube el % de "Desconocida" sin que haya empresas nuevas.
- Hay una condición nueva: lluvia fuerte, obra, cámara movida, cambio de luz, modelo de autobús nuevo.
- Se juntan más de ~300 recortes marcados por los validadores como erróneos.

## Espacio en la Jetson (18 nov 2026: 915 GB, 21 % usado)

| Qué | Tamaño | Retención |
|---|---|---|
| `Jetson8/grabaciones` | ~44-47 GB | 72 h, automática |
| `Jetson8/cisa_frames` | 13 GB | Sin límite → [P] 90 días |
| `Jetson8/crops_dataset` | 3.5 GB | Sin límite → [P] borrar lo que ya está en Drive o Roboflow |
| `cam1_grabacion`, `cam2_grabacion` (viejas) | 22 GB | Fuera de la limpieza → revisar y borrar con aprobación |
| Imagen `cisa-vision:jp7.2` | 17 GB | Sin uso → `docker image rm` con aprobación |

## Respaldo y recuperación

- **Base de datos:** [P] `pg_dump patio_cca` diario a un disco aparte (P5.4).
- **Configuración:** `.env` y `padron.csv` (fuera de git) → copia cifrada fuera de la Jetson.
- **Modelos:** cada `.engine` en uso tiene su `.pt` en `modelos/pt/` y en Drive; el `.engine` se puede volver a compilar con `scripts/exportar_engine.sh`.
- **Rollback de modelo:** [DESPLIEGUE.md](DESPLIEGUE.md) §5.

## Documentación

La regla del documento SARU también aplica aquí: si cambia el comportamiento del sistema, **cambia la documentación en el mismo PR**. Cada versión de modelo se anota en `CHANGELOG.md`.
