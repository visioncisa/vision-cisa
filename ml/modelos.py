"""
ml/modelos.py
================================================================
Carga de los 3 modelos YOLO (autobús, zona, dígitos) y los
helpers para interpretar la clase de zona.
Los modelos se cargan al importar este archivo (una sola vez).
================================================================
"""
from ultralytics import YOLO

from config import (
    MODEL_PATH, DIGITS_MODEL_PATH, AUTOBUS_MODEL_PATH, CLASE_M2_IDX,
)

print("[INFO] Cargando Modelo 1 — Autobús...")
model_autobus = YOLO(AUTOBUS_MODEL_PATH, task="detect")
print(f"[INFO] ✓ Clases M1      : {model_autobus.names}")

print("[INFO] Cargando Modelo 2 — Zona número...")
model_zona = YOLO(MODEL_PATH, task="detect")
print(f"[INFO] ✓ Clases M2 raw  : {model_zona.names}")
print(f"[INFO] ✓ Clases M2 mapa : {CLASE_M2_IDX}")

print("[INFO] Cargando Modelo 3 — Dígitos...")
model_digitos = YOLO(DIGITS_MODEL_PATH, task="detect")
print(f"[INFO] ✓ Clases M3      : {model_digitos.names}")

CLASE_A_DIGITO = {
    nombre: nombre
    for nombre in model_digitos.names.values()
    if str(nombre).isdigit()
}
print(f"[INFO] ✓ Mapeo dígitos  : {CLASE_A_DIGITO}")


# ── Calentamiento: cada modelo se inicializa en la GPU AHORA, uno por uno ─────
# TensorRT carga el motor la primera vez que se usa. Si eso pasa con los hilos
# ya corriendo (p. ej. M3 al leer el primer número mientras M1 usa la GPU),
# los dos chocan: "CUDA error ... stream capture". Al importar este archivo
# todavía no hay hilos, así que aquí no puede pasar.
def _calentar():
    import numpy as np
    negro = np.zeros((720, 1280, 3), dtype=np.uint8)
    for nombre, modelo, imgsz in (("M1", model_autobus, 640),
                                  ("M2", model_zona, 1280),
                                  ("M3", model_digitos, 640)):
        try:
            modelo.predict(negro, device=0, verbose=False, imgsz=imgsz)
            print(f"[INFO] ✓ {nombre} listo en la GPU")
        except Exception as e:
            print(f"[INFO] ✗ {nombre} no se pudo calentar: {e}")


_calentar()


# ── Helpers de zona — usan el índice de clase, no el nombre ───────────────────
def tipo_zona(cls_id: int) -> str:
    """Devuelve 'delantero', 'lateral' o 'trasera' según el índice de clase."""
    return CLASE_M2_IDX.get(cls_id, 'lateral')

def es_lateral(cls_id: int) -> bool:
    return tipo_zona(cls_id) == 'lateral'

def es_trasera(cls_id: int) -> bool:
    return tipo_zona(cls_id) == 'trasera'

def es_delantero(cls_id: int) -> bool:
    return tipo_zona(cls_id) == 'delantero'