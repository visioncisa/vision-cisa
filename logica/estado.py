"""
logica/estado.py
================================================================
ESTADO COMPARTIDO entre TODOS los hilos y módulos.

Este archivo NO importa de ningún otro módulo del proyecto
(solo de la librería estándar). Es la "única fuente de verdad"
de los datos que varios hilos leen y escriben a la vez.
Todos los demás módulos importan DE AQUÍ; nunca al revés.
Eso evita las importaciones circulares.
================================================================
"""
import threading

# ── Estado del pipeline (lo leen el dashboard y /health) ──────────────────────
STATE = {
    "numero":            None,
    "ts":                None,
    "yolo_fps":          0.0,
    "frame_count":       0,
    "total_detecciones": 0,
    "descartadas":       0,
    "conexion":          "desconectado",
}
state_lock = threading.Lock()

# ── Frame más reciente (lo comparten cámara, video en vivo y /api/snapshot) ────
_latest_frame      = None
_latest_frame_lock = threading.Lock()


def set_frame(frame):
    global _latest_frame
    with _latest_frame_lock:
        _latest_frame = frame


def get_frame():
    with _latest_frame_lock:
        return _latest_frame.copy() if _latest_frame is not None else None


# ── Referencias de runtime (las rellena pipe_stream_v2.py al arrancar) ────────
ACTIVE_CAMERA = 1
cam           = None   # instancia de CameraStream; el arranque la asigna