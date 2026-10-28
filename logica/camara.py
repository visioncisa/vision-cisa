"""
logica/camara.py
================================================================
Lectura de la cámara en su propio hilo.
  - Cámara RTSP: GStreamer con decodificación por hardware (NVDEC);
    si no abre, plan B con FFmpeg (CPU). CAM_BACKEND=ffmpeg lo fuerza.
  - Video grabado (RTSP_URL = ruta a un .mp4): modo prueba. Si hay varios
    (VIDEOS_PRUEBA) se reproducen uno tras otro y se puede adelantar o
    pasar al siguiente. Con la cámara real nada de esto aplica.
Si pierdes conexión con la cámara o quieres meter una segunda,
este es el archivo que tocas.

NOTA: importa el estado compartido desde logica/estado.py.
================================================================
"""
import cv2
import threading
import os
import time

from config import CAM_BACKEND, VIDEOS_PRUEBA
from logica import estado


def _lista_videos(url):
    """Videos del modo prueba. Vacía si la fuente es la cámara."""
    if not os.path.isfile(str(url)):
        return []
    lista = []
    for parte in VIDEOS_PRUEBA:
        if os.path.isdir(parte):
            lista += sorted(os.path.join(parte, f) for f in os.listdir(parte)
                            if f.lower().endswith(".mp4"))
        elif os.path.isfile(parte):
            lista.append(parte)
    if url not in lista:
        lista.insert(0, url)
    return lista


class CameraStream:
    def __init__(self, url):
        self.url     = url
        self.cap     = None
        self.running = True
        self.lock    = threading.Lock()
        self.frame   = None
        self.lista   = _lista_videos(url)   # videos del modo prueba (vacía con cámara)
        self.cmd     = None                 # orden pendiente: ("saltar", seg), ("ir", seg) o ("siguiente", 0)
        self.pos_seg = 0.0                  # segundo actual del video (modo prueba)
        self.dur_seg = 0.0                  # duración del video (modo prueba)

    def _build_pipeline(self):
        # Decodificación por hardware (NVDEC) en vez de FFmpeg/CPU.
        # rtph265depay porque RTSP_URL usa subtype=0 (stream principal, H.265).
        # Si algún día cambian a subtype=1 (H.264), cambiar por rtph264depay.
        return (
            f"rtspsrc location={self.url} latency=100 protocols=tcp ! "
            "rtph265depay ! h265parse ! nvv4l2decoder ! "
            "nvvidconv ! video/x-raw,format=BGRx ! "
            "videoconvert ! video/x-raw,format=BGR ! "
            "appsink sync=false max-buffers=1 drop=true"
        )

    def _conectar(self):
        print("[CAM1] Conectando...")
        if self.cap:
            try: self.cap.release()
            except: pass
        self.es_archivo = os.path.isfile(self.url)
        if self.es_archivo:   # MODO PRUEBA: un video grabado en lugar de la cámara
            self.cap = cv2.VideoCapture(self.url)
            self.fps_archivo = self.cap.get(cv2.CAP_PROP_FPS) or 15
            self.dur_seg = (self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / self.fps_archivo
            self.pos_seg = 0.0
            print(f"[CAM1] Modo prueba: video {self.url} a {self.fps_archivo:.0f} FPS")
        else:
            forzar = CAM_BACKEND == "ffmpeg"
            if not forzar:
                self.cap = cv2.VideoCapture(self._build_pipeline(), cv2.CAP_GSTREAMER)
            if forzar or not self.cap.isOpened():
                if not forzar:
                    print("[CAM1] GStreamer no abrió la cámara; probando con FFmpeg (CPU)")
                os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
                self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok = self.cap.isOpened()
        with estado.state_lock:
            estado.STATE["conexion"] = "conectado" if ok else "fallo"
        print(f"[CAM1] {'✓ Conectado' if ok else '✗ Fallo'}")
        return ok

    # ── Control del modo prueba (solo videos grabados) ────────────────────────
    def pedir(self, orden, valor=0):
        """Deja una orden para el hilo de lectura. False si la fuente es la cámara."""
        if not getattr(self, 'es_archivo', False):
            return False
        self.cmd = (orden, valor)
        return True

    def _vecino(self, paso):
        i = self.lista.index(self.url) if self.url in self.lista else 0
        return self.lista[(i + paso) % len(self.lista)]

    def _abrir_video(self, ruta):
        self.url = ruta
        self._conectar()

    def _atender_orden(self):
        """Se llama desde el hilo de lectura, para no tocar el video desde otro hilo."""
        orden, self.cmd = self.cmd, None
        if not orden or not getattr(self, 'es_archivo', False):
            return
        nombre, valor = orden
        if nombre == "saltar":
            pos   = self.cap.get(cv2.CAP_PROP_POS_FRAMES) + valor * self.fps_archivo
            total = self.cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if total and pos >= total - 1:      # se pasó del final: siguiente video
                if len(self.lista) > 1:
                    self._abrir_video(self._vecino(1))
                else:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            else:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, pos))
            print(f"[CAM1] Prueba: salto de {valor:+.0f} s")
        elif nombre == "ir":                    # ir a un segundo exacto (barra de tiempo)
            total = self.cap.get(cv2.CAP_PROP_FRAME_COUNT)
            pos   = max(0, valor * self.fps_archivo)
            if total:
                pos = min(pos, total - 2)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        elif nombre == "siguiente":
            if len(self.lista) > 1:
                self._abrir_video(self._vecino(1))
            else:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def update(self):
        self._conectar()
        while self.running:
            if not self.cap or not self.cap.isOpened():
                time.sleep(2)
                self._conectar()
                continue
            self._atender_orden()
            ret, frame = self.cap.read()
            if getattr(self, 'es_archivo', False):
                if not ret:   # terminó el video: pasa al siguiente (o vuelve a empezar)
                    if len(self.lista) > 1:
                        self._abrir_video(self._vecino(1))
                    else:
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                time.sleep(1.0 / self.fps_archivo)   # a la velocidad real del video
                self.pos_seg = self.cap.get(cv2.CAP_PROP_POS_FRAMES) / self.fps_archivo
            if ret:
                with self.lock:
                    self.frame = frame
                estado.set_frame(frame)
                with estado.state_lock:
                    estado.STATE["conexion"]     = "conectado"
                    estado.STATE["frame_count"] += 1
            else:
                with estado.state_lock:
                    estado.STATE["conexion"] = "fallo"
                time.sleep(2)
                self._conectar()

    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
