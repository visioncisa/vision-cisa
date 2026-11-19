#!/usr/bin/env bash
# =============================================================================
# scripts/exportar_engine.sh — compila un modelo .pt a TensorRT (.engine)
# EN LA MISMA JETSON donde va a correr, sin tocar el modelo en producción.
#
#   bash scripts/exportar_engine.sh <m1|m2|m3> <ruta/al/modelo.pt> <version>
#   ej: bash scripts/exportar_engine.sh m3 ~/modelo_digitos_v4.pt v4
#
# Qué hace:
#   1. Copia el .pt a modelos/pt/ con el nombre de la versión.
#   2. Compila el .engine dentro de la imagen cisa-vision (mismo TensorRT que
#      producción), en FP16 y con el imgsz de producción (M2 = 1280).
#   3. Verifica que las clases estén en el orden oficial y mide la velocidad.
#   4. Deja el .engine en modelos/engine_nx/ JUNTO al actual (no lo reemplaza).
#   5. Imprime cómo activarlo y cómo regresar (rollback).
#
# Qué NO hace: no cambia el .env ni reinicia cisa-vision. Eso es un paso
# aparte que requiere aprobación (docs/DESPLIEGUE.md).
#
# Compilar usa la GPU: hacerlo en horario de poco tráfico.
# =============================================================================
set -euo pipefail

MODELO="${1:-}"; PT="${2:-}"; VERSION="${3:-}"
if [[ -z "$MODELO" || -z "$PT" || -z "$VERSION" ]]; then
    sed -n '3,8p' "$0"; exit 1
fi
case "$MODELO" in
    m1) BASE="bus";             IMGSZ=640;  CLASES="['Autobus', 'Unidades']";            VAR="AUTOBUS_MODEL_PATH" ;;
    m2) BASE="modelo_vista";    IMGSZ=1280; CLASES="['delantero', 'lateral', 'trasera']"; VAR="MODEL_PATH" ;;
    m3) BASE="modelo_digitos";  IMGSZ=640;  CLASES="['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']"; VAR="DIGITS_MODEL_PATH" ;;
    *)  echo "Modelo debe ser m1, m2 o m3"; exit 1 ;;
esac

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"
[[ -f docker-compose.yml ]] || { echo "No estoy en la carpeta del proyecto ($RAIZ)"; exit 1; }
[[ -f "$PT" ]] || { echo "No existe $PT"; exit 1; }

NOMBRE="${BASE}_${VERSION}"
DESTINO="modelos/engine_nx/${NOMBRE}.engine"
TMP="modelos/_exportar"
[[ -e "$DESTINO" ]] && { echo "Ya existe $DESTINO: usa otra versión"; exit 1; }

echo "== Modelo $MODELO → $DESTINO (imgsz $IMGSZ, FP16)"
read -r -p "¿Continuar? Usa la GPU unos minutos [s/N] " ok
[[ "$ok" == "s" || "$ok" == "S" ]] || exit 1

mkdir -p modelos/pt "$TMP"
cp -n "$PT" "modelos/pt/${NOMBRE}.pt"
cp "$PT" "$TMP/${NOMBRE}.pt"

# modelos/ está montado de solo lectura en el servicio: se monta otra carpeta con escritura
docker compose run --rm --no-deps -T -v "$RAIZ/$TMP:/exportar" cisa-vision python3 - <<PY
import time, numpy as np
from ultralytics import YOLO
pt = "/exportar/${NOMBRE}.pt"
m = YOLO(pt)
nombres = [m.names[i] for i in sorted(m.names)]
assert nombres == ${CLASES}, f"Clases fuera de orden: {nombres}"
print("Clases OK:", nombres)
ruta = m.export(format="engine", half=True, imgsz=${IMGSZ}, device=0, batch=1)
print("Engine:", ruta)
e = YOLO(ruta, task="detect")
img = np.zeros((720, 1280, 3), np.uint8)
for _ in range(5):
    e.predict(img, imgsz=${IMGSZ}, device=0, verbose=False)
t = time.time()
for _ in range(50):
    e.predict(img, imgsz=${IMGSZ}, device=0, verbose=False)
print(f"Velocidad: {50 / (time.time() - t):.1f} inferencias/s (imagen vacía, sin otros hilos)")
PY

mv "$TMP/${NOMBRE}.engine" "$DESTINO"
rm -rf "$TMP"
ACTUAL=$(grep -E "^${VAR}=" .env | cut -d= -f2- || true)
echo
echo "== Listo: $DESTINO (el actual sigue siendo: ${ACTUAL:-?})"
echo "Para PROBARLO (después de aprobar, ver docs/DESPLIEGUE.md):"
echo "  1. Respaldar:  cp .env .env.antes_${NOMBRE}"
echo "  2. Cambiar en .env:  ${VAR}=${DESTINO}"
echo "  3. docker compose up -d --force-recreate cisa-vision"
echo "  4. docker compose logs -f cisa-vision   (deben salir las 'Clases M' correctas)"
echo "ROLLBACK:  cp .env.antes_${NOMBRE} .env && docker compose up -d --force-recreate cisa-vision"
