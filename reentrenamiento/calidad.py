"""
Calidad de un recorte: nitidez, brillo, contraste, tamaño y tipo de luz.

Todo con OpenCV y sin modelos, para correr rápido sobre miles de
recortes. La nitidez se mide con el recorte llevado a una altura fija
(`alto_normalizado`) para que un recorte grande no parezca más nítido
solo por tener más píxeles.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np


@dataclass
class Calidad:
    nitidez: float          # varianza del Laplaciano (más = más nítido)
    brillo: float           # media del gris, 0-255
    contraste: float        # desviación estándar del gris
    ancho: int
    alto: int
    luz: str                # "dia" | "noche" | "contraluz"

    def como_dict(self) -> Dict:
        return asdict(self)


def leer_imagen(ruta) -> Optional[np.ndarray]:
    """cv2.imread no abre rutas con acentos en algunos sistemas; esto sí."""
    try:
        datos = np.fromfile(str(ruta), dtype=np.uint8)
        if datos.size == 0:
            return None
        return cv2.imdecode(datos, cv2.IMREAD_COLOR)
    except (OSError, ValueError):
        return None


def medir(img_bgr: np.ndarray, umbrales: Dict) -> Calidad:
    alto, ancho = img_bgr.shape[:2]
    gris = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    h_norm = int(umbrales.get("alto_normalizado", 96))
    escala = h_norm / max(1, alto)
    gris_n = cv2.resize(gris, (max(1, int(round(ancho * escala))), h_norm),
                        interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_LINEAR)
    nitidez = float(cv2.Laplacian(gris_n, cv2.CV_64F).var())
    brillo = float(gris.mean())
    contraste = float(gris.std())
    claros = float((gris > 235).mean())
    oscuros = float((gris < 40).mean())
    if claros >= umbrales.get("contraluz_claros", 0.15) and oscuros >= umbrales.get("contraluz_oscuros", 0.25):
        luz = "contraluz"
    elif brillo < umbrales.get("noche_brillo", 70.0):
        luz = "noche"
    else:
        luz = "dia"
    return Calidad(round(nitidez, 2), round(brillo, 2), round(contraste, 2), int(ancho), int(alto), luz)


def medir_archivo(ruta, umbrales: Dict) -> Optional[Calidad]:
    img = leer_imagen(Path(ruta))
    return None if img is None else medir(img, umbrales)


def problemas(c: Optional[Calidad], umbrales: Dict) -> List[str]:
    """Problemas que hacen DESCARTAR el recorte (no se puede etiquetar bien)."""
    if c is None:
        return ["ilegible"]
    p = []
    if min(c.ancho, c.alto) < umbrales.get("lado_min_px", 20):
        p.append("pequena")
    if c.nitidez < umbrales.get("nitidez_descartar", 15.0):
        p.append("borrosa")
    if c.brillo < umbrales.get("brillo_min", 25.0):
        p.append("oscura")
    if c.brillo > umbrales.get("brillo_max", 235.0):
        p.append("sobreexpuesta")
    if c.contraste < umbrales.get("contraste_min", 12.0):
        p.append("sin_contraste")
    return p


def es_dudosa(c: Optional[Calidad], umbrales: Dict) -> bool:
    """Calidad aceptable pero baja: se usa solo si el caso es difícil."""
    return c is not None and c.nitidez < umbrales.get("nitidez_revisar", 40.0)
