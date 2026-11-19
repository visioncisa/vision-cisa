"""
Imágenes repetidas.

1. Agrupar por PASADA: mismos zona y track, y recortes separados por
   menos de `ventana_seg`. Así se aprovecha el ID del tracking (ByteTrack)
   que producción ya pone en el nombre del archivo.
2. Dentro de la pasada, comparar con hash perceptual (dHash o pHash,
   64 bits). Distancia de Hamming baja = casi la misma imagen.

Por qué hash y no SSIM ni embeddings: ver docs/PIPELINE_REENTRENAMIENTO.md
(el hash cuesta microsegundos, no necesita GPU y, combinado con el
track, alcanza para recortes de la misma cámara fija).
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Sequence, Tuple

import cv2
import numpy as np

from .nombres import InfoRecorte


def _gris(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def dhash(img: np.ndarray, tam: int = 8) -> int:
    """Hash de diferencias: compara cada píxel con el de su derecha."""
    peq = cv2.resize(_gris(img), (tam + 1, tam), interpolation=cv2.INTER_AREA)
    bits = (peq[:, 1:] > peq[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def phash(img: np.ndarray, tam: int = 8) -> int:
    """Hash perceptual (DCT): más tolerante a cambios de brillo que dHash."""
    peq = cv2.resize(_gris(img), (tam * 4, tam * 4), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(peq)[:tam, :tam]
    mediana = np.median(dct.flatten()[1:])
    bits = (dct > mediana).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def distancia(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def agrupar_pasadas(infos: Iterable[InfoRecorte], ventana_seg: float) -> List[List[InfoRecorte]]:
    """Agrupa recortes de la misma pasada. Los que no traen track quedan solos."""
    con_track, sueltos = [], []
    for i in infos:
        (con_track if i.track is not None and i.momento is not None else sueltos).append(i)
    con_track.sort(key=lambda i: (i.zona or "", i.dia, i.track, i.timestamp))
    grupos: List[List[InfoRecorte]] = []
    actual: List[InfoRecorte] = []
    for i in con_track:
        if actual:
            prev = actual[-1]
            misma = (i.zona == prev.zona and i.dia == prev.dia and i.track == prev.track
                     and i.timestamp - prev.timestamp <= ventana_seg)
            if not misma:
                grupos.append(actual)
                actual = []
        actual.append(i)
    if actual:
        grupos.append(actual)
    grupos.extend([[s] for s in sorted(sueltos, key=lambda s: s.ruta.name)])
    return grupos


def quitar_repetidas(hashes: Sequence[Tuple[str, int]], dist_min: int,
                     ya_elegidas: Sequence[int] = ()) -> Tuple[List[str], Dict[str, str]]:
    """Recorre en orden y conserva una imagen solo si se aleja al menos `dist_min`
    de todas las conservadas. Devuelve (conservadas, {repetida: a_quien_se_parece})."""
    conservadas: List[Tuple[str, int]] = []
    repetidas: Dict[str, str] = {}
    previas = list(ya_elegidas)
    for clave, h in hashes:
        parecida = next((c for c, h0 in conservadas if distancia(h, h0) < dist_min), None)
        if parecida is None and any(distancia(h, h0) < dist_min for h0 in previas):
            parecida = "(elegida antes)"
        if parecida is None:
            conservadas.append((clave, h))
        else:
            repetidas[clave] = parecida
    return [c for c, _ in conservadas], repetidas


def hash_archivo(ruta, funcion: Callable[[np.ndarray], int] = dhash) -> int:
    from .calidad import leer_imagen
    img = leer_imagen(ruta)
    if img is None:
        raise ValueError(f"No se pudo leer {ruta}")
    return funcion(img)
