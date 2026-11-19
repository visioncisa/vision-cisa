"""
Captura INTELIGENTE desde las grabaciones (en vez de revisar video a mano).

1. Por EVENTOS: se toman los cruces que ya registró el sistema
   (export JSON de /api/detecciones o CSV con columna `ts`) y de la
   grabación de esa hora se sacan cuadros de `antes` a `despues`
   segundos alrededor del cruce, uno cada `paso` segundos.
2. PERIÓDICO: un cuadro cada N segundos de un video (para conocer
   condiciones nuevas: lluvia, noche, obras, cámara movida).

Las grabaciones son cam1_AAAAMMDD_HHMMSS.mp4, una por hora
(scripts/grabar.sh). Se conservan 72 h: hay que extraer antes.

Decodifica con OpenCV; si OpenCV no abre el video (p. ej. H.265 sin
soporte), usa el comando `ffmpeg` si está instalado.
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
from bisect import bisect_right
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import cv2

from .nombres import InfoGrabacion, leer_grabacion


def cargar_eventos(ruta: Path) -> List[Dict]:
    """Acepta el JSON de /api/detecciones ({"items": [...]} o lista) o un CSV con `ts`."""
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".json":
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        items = datos.get("items", datos) if isinstance(datos, dict) else datos
    else:
        with open(ruta, encoding="utf-8", newline="") as fh:
            items = list(csv.DictReader(fh))
    eventos = []
    for it in items:
        ts = it.get("ts") or it.get("hora") or it.get("timestamp")
        if not ts:
            continue
        eventos.append({**it, "_momento": datetime.fromisoformat(str(ts).replace("T", " "))})
    return sorted(eventos, key=lambda e: e["_momento"])


def indice_grabaciones(carpeta: Path, camara: str = "cam1") -> List[InfoGrabacion]:
    grabs = [g for g in (leer_grabacion(p) for p in Path(carpeta).glob(f"{camara}_*.mp4")) if g]
    return sorted(grabs, key=lambda g: g.inicio)


def grabacion_de(momento: datetime, grabs: Sequence[InfoGrabacion],
                 duracion_max: timedelta = timedelta(hours=1, minutes=5)) -> Optional[InfoGrabacion]:
    inicios = [g.inicio for g in grabs]
    i = bisect_right(inicios, momento) - 1
    if i < 0:
        return None
    g = grabs[i]
    return g if momento - g.inicio <= duracion_max else None


def _cuadro_opencv(cap: cv2.VideoCapture, seg: float):
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seg) * 1000.0)
    ok, frame = cap.read()
    return frame if ok else None


def _cuadro_ffmpeg(video: Path, seg: float, destino: Path) -> bool:  # pragma: no cover
    if not shutil.which("ffmpeg"):
        return False
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{max(0.0, seg):.3f}",
                        "-i", str(video), "-frames:v", "1", "-q:v", "2", str(destino)],
                       capture_output=True)
    return r.returncode == 0 and destino.exists()


def extraer_cuadros(video: Path, segundos: Iterable[float], destino: Path, prefijo: str) -> List[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    salida: List[Path] = []
    cap = cv2.VideoCapture(str(video))
    usar_cv = cap.isOpened()
    for seg in segundos:
        ruta = destino / f"{prefijo}_{seg:07.1f}s.jpg"
        if usar_cv:
            frame = _cuadro_opencv(cap, seg)
            if frame is not None and cv2.imwrite(str(ruta), frame):
                salida.append(ruta)
                continue
        if _cuadro_ffmpeg(Path(video), seg, ruta):
            salida.append(ruta)
    cap.release()
    return salida


def por_eventos(eventos: Sequence[Dict], carpeta_grabaciones: Path, destino: Path,
                antes: float = 3.0, despues: float = 3.0, paso: float = 1.0,
                camara: str = "cam1") -> Dict:
    grabs = indice_grabaciones(carpeta_grabaciones, camara)
    hechos, sin_video, cuadros = 0, [], 0
    n = int(round((antes + despues) / paso)) + 1
    for ev in eventos:
        g = grabacion_de(ev["_momento"], grabs)
        if g is None:
            sin_video.append(str(ev["_momento"]))
            continue
        centro = (ev["_momento"] - g.inicio).total_seconds()
        segs = [centro - antes + k * paso for k in range(n)]
        prefijo = f"evt{ev.get('id', hechos)}_{ev['_momento']:%Y%m%d_%H%M%S}_{ev.get('numero', 'x')}"
        cuadros += len(extraer_cuadros(g.ruta, segs, Path(destino), prefijo))
        hechos += 1
    return {"eventos": len(eventos), "con_video": hechos, "sin_video": len(sin_video),
            "cuadros": cuadros, "ejemplos_sin_video": sin_video[:5]}


def periodico(video: Path, destino: Path, cada_seg: float) -> int:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    cap.release()
    dur = total / fps if fps else 0
    if dur <= 0:
        raise ValueError(f"No pude leer la duración de {video} (¿OpenCV sin soporte del códec?)")
    segs = [k * cada_seg for k in range(int(dur // cada_seg) + 1) if k * cada_seg < dur]
    return len(extraer_cuadros(Path(video), segs, Path(destino), Path(video).stem))
