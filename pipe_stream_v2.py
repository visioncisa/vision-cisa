"""
CISA - Arranque del sistema
================================================================
Este archivo NO tiene lógica: solo crea la cámara y los hilos,
los lanza y levanta el servidor web.

La lógica vive en las carpetas:
    config.py  -> toda la configuración (lee el .env)
    logica/    -> estado compartido + cámara
    ml/        -> modelos YOLO, lectura de dígitos, línea virtual, hilos M1/M2M3
    metricas/  -> registro de eventos, estancias y datos del dashboard (SQLite)
    web/       -> Flask: páginas, API y video en vivo (MJPEG)
La grabación cada hora corre aparte (servicio cisa-grabacion, scripts/grabar.sh).
================================================================
"""
import threading

from config import (
    RTSP_URL, FLASK_HOST, FLASK_PORT,
    CONF_AUTOBUS, CONF_VISTA, CONF_DIGITO, N_VOTOS, PAD_RATIO, BBOX_MIN_AUTOBUS,
    LINEA_P1, LINEA_P2, LADO_ENTRADA, MANIOBRA_SEG, DEBOUNCE_SEG,
    ESPERA_FIN_SEG, ESPERA_MAX_SEG, YOLO_FPS_MAX,
    SIN_TELEGRAM, VALIDAR_CON_GEMINI, CROPS_DIR, CLASE_M2_IDX,
)

from logica import estado
from logica.camara import CameraStream
from metricas import metricas, storage
from ml import hilos
from web.servidor import app
import web.rutas  # noqa: F401  (registra las rutas en la app)


def main():
    # 1) base de datos (crea o migra el esquema y sincroniza el padrón)
    storage.inicializar()
    metricas.cargar()

    # 2) cámara compartida (las rutas la ven vía estado.cam)
    estado.cam = CameraStream(RTSP_URL)
    hilo_m1 = hilos.HiloM1(estado.cam)
    hilo_m2 = hilos.HiloM2M3()

    # 3) hilos de visión + cámara
    threading.Thread(target=estado.cam.update, daemon=True, name="CamStream").start()
    threading.Thread(target=hilo_m1.update,     daemon=True, name="HiloM1").start()
    threading.Thread(target=hilo_m2.update,     daemon=True, name="HiloM2M3").start()

    # 4) info de arranque
    modo = "video grabado (prueba)" if not str(RTSP_URL).startswith("rtsp") else "cámara RTSP"
    print(f"\n[INFO] Fuente: {modo}")
    print(f"[INFO] CONF_AUTOBUS={CONF_AUTOBUS}  CONF_VISTA={CONF_VISTA}  CONF_DIGITO={CONF_DIGITO}")
    print(f"[INFO] N_VOTOS={N_VOTOS}  PAD={PAD_RATIO}  BBOX_MIN_AUTOBUS={BBOX_MIN_AUTOBUS}")
    print(f"[INFO] YOLO_FPS_MAX={YOLO_FPS_MAX or 'sin límite'}  ESPERA={ESPERA_FIN_SEG}s/{ESPERA_MAX_SEG}s")
    print(f"[INFO] LINEA_P1={LINEA_P1}  LINEA_P2={LINEA_P2}  LADO_ENTRADA={LADO_ENTRADA}")
    print(f"[INFO] MANIOBRA_SEG={MANIOBRA_SEG}  DEBOUNCE_SEG={DEBOUNCE_SEG}")
    print(f"[INFO] Telegram={'apagado' if SIN_TELEGRAM else 'activo'}  Gemini={'activo' if VALIDAR_CON_GEMINI else 'apagado'}")
    print(f"[INFO] CROPS_DIR={CROPS_DIR}")
    print(f"[INFO] Clases M2: {CLASE_M2_IDX}")
    print(f"[INFO] http://{FLASK_HOST}:{FLASK_PORT}\n")

    try:
        app.run(host=FLASK_HOST, port=FLASK_PORT, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        print("\n[INFO] Deteniendo...")
        estado.cam.stop()
        hilo_m1.stop()
        hilo_m2.stop()


if __name__ == '__main__':
    main()
