# Despliegue de un modelo nuevo en la Jetson

> **Requiere aprobación.** Nada de esto se ejecutó en la rama `mejora/reentrenamiento-eficiente`. El responsable del sistema debe aprobar explícitamente **dos** veces: antes de compilar y antes de activar.

Diagrama: [`diagramas/05_despliegue_rollback.mmd`](diagramas/05_despliegue_rollback.mmd).

## Datos del equipo (verificados el 18 nov 2026)

| Dato | Valor |
|---|---|
| Carpeta de producción | `~/Documents/ProyectoVisionCISA_R` (**no** `ProyectoVisionCISA` ni `proyectoiapruebas`) |
| Arranque | `cisa.service` (systemd) levanta los 3 contenedores al encender |
| Modelos en uso | `modelos/engine_nx/{bus_v3,modelo_vista_v3,modelo_digitos_v3}.engine` |
| Variables del `.env` | `AUTOBUS_MODEL_PATH` (M1), `MODEL_PATH` (M2), `DIGITS_MODEL_PATH` (M3) |
| `modelos/` en el contenedor | Montado **de solo lectura** |
| Horario de menor tráfico (tablero, 3-18 nov) | 17:00-19:00 (las salidas se concentran a las 4-5 a.m. y las entradas de las 21 a la 1 a.m.) |

## Pasos

### 0. Antes
1. `evaluacion.md` del candidato dice **ACEPTAR** → **aprobación #1**.
2. Respaldo: `cp .env .env.antes_<version>` y copia de `modelos/engine_nx/`.

### 1. Compilar en la Jetson
```bash
scp best.pt jetson@<ip>:~/modelo_digitos_v4.pt
ssh jetson@<ip>
cd ~/Documents/ProyectoVisionCISA_R
bash scripts/exportar_engine.sh m3 ~/modelo_digitos_v4.pt v4
```
El script verifica el orden de las clases, compila en FP16 con el imgsz de producción (M2 = 1280), mide la velocidad y deja `modelos/engine_nx/modelo_digitos_v4.engine` **junto** al v3, sin reemplazarlo.

> **Nunca** se copia un `.engine` compilado en Colab o en otra Jetson: TensorRT solo garantiza el funcionamiento en el mismo equipo y la misma versión (por eso hoy aparece la advertencia "Using an engine plan file across different models of devices").

| Si falla… | Qué hacer |
|---|---|
| "Clases fuera de orden" | El `.pt` salió de un dataset con otro orden: volver a P3 |
| Error de TensorRT o CUDA, o falta de memoria | Repetir fuera de horario; si persiste, revisar que la imagen `cisa-vision:v1` tenga TRT 10.16.2 (`Dockerfile`) |
| Velocidad menor a la de v3 | No desplegar: el modelo es más pesado o el imgsz no coincide |

### 2. Canary con video grabado
Correr el candidato en **modo prueba** con el video de canary (ver [EVALUACION_MODELOS.md](EVALUACION_MODELOS.md) §3), sin tocar la cámara real. Comparar conteo, lectura, tracking y FPS contra v3 → **aprobación #2**.

### 3. Activar
```bash
cp .env .env.antes_v4
sed -i 's|^DIGITS_MODEL_PATH=.*|DIGITS_MODEL_PATH=modelos/engine_nx/modelo_digitos_v4.engine|' .env
docker compose up -d --force-recreate cisa-vision
docker compose logs -f --tail 50 cisa-vision     # deben salir las "Clases M3" 0-9 y "✓ M3 listo en la GPU"
```

### 4. Vigilar 48 h
`/api/estado` (`yolo_fps`, `m2_fps`, `descartadas`), "Desconocida" del día, alternancia entrada/salida y errores nuevos en el log.

### 5. Rollback (en cualquier momento)
```bash
cp .env.antes_v4 .env
docker compose up -d --force-recreate cisa-vision
```
El `.engine` de v3 nunca se borra, así que el regreso toma menos de un minuto.

### 6. Registrar
`CHANGELOG.md` (fecha, modelo, versión, métricas, commit) y la línea de `experimentos/registro.jsonl`.
