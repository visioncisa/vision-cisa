"""
Pruebas del paquete reentrenamiento/. NO necesitan .env, GPU, modelos
ni ultralytics: usan imágenes sintéticas.

    pip install -r requirements-reentrenamiento.txt pytest
    pytest tests/
"""
import sys
import zlib
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reentrenamiento import configuracion  # noqa: E402


def placa(texto="5051", ancho=160, alto=64, fondo=200, desplazar=0, ruido=0, semilla=0):
    """Recorte sintético parecido a la zona del número: placa clara con dígitos oscuros."""
    rng = np.random.default_rng(semilla)
    img = np.full((alto, ancho, 3), 60, np.uint8)
    cv2.rectangle(img, (8 + desplazar, 8), (ancho - 8 + desplazar, alto - 8), (fondo,) * 3, -1)
    cv2.putText(img, texto, (16 + desplazar, alto - 18), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 3)
    if ruido:
        img = np.clip(img.astype(int) + rng.integers(-ruido, ruido, img.shape), 0, 255).astype(np.uint8)
    return img


def guardar(ruta: Path, img) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(ruta), img)
    return ruta


@pytest.fixture
def cfg():
    return configuracion.cargar()


@pytest.fixture
def crear_dataset(tmp_path):
    """crear_dataset({"train": {"nombre.jpg": [(c,cx,cy,w,h), ...]}, ...}, names=[...])"""
    def _crear(splits, names=None, raiz=None):
        raiz = Path(raiz or tmp_path / "ds")
        for split, archivos in splits.items():
            base = raiz if split == "todo" else raiz / split
            for nombre, cajas in archivos.items():
                n = zlib.crc32(nombre.encode())       # estable entre corridas (hash() no lo es)
                guardar(base / "images" / nombre, placa(texto=str(n % 10000), semilla=n % 1000,
                                                        desplazar=n % 7, ruido=25))
                txt = base / "labels" / (Path(nombre).stem + ".txt")
                txt.parent.mkdir(parents=True, exist_ok=True)
                txt.write_text("".join(" ".join(str(v) for v in c) + "\n" for c in cajas))
        (raiz / "data.yaml").write_text(yaml.safe_dump(
            {"nc": len(names or []), "names": names or [str(d) for d in range(10)]}))
        return raiz
    return _crear
