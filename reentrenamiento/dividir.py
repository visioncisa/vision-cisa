"""
Divide un dataset plano (images/ + labels/) en train / valid / test
POR PASADA, no por imagen: todos los recortes del mismo camión en la
misma pasada caen en el mismo split (si no, el modelo "se aprende" el
test y las métricas mienten).

El split de cada pasada sale de un hash estable de su clave: la misma
pasada cae siempre en el mismo split aunque se agreguen datos nuevos.

SET DE PRUEBA CONGELADO (`congelado.txt`, una clave de pasada por línea):
  - La primera vez se crea con las pasadas que cayeron en test.
  - Después, test = exactamente esas pasadas, y los datos nuevos solo
    van a train/valid. Así v4, v5… se comparan contra el MISMO examen.
  - Se versiona en el repo (son nombres, no imágenes).
"""
from __future__ import annotations

import hashlib
import shutil
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .nombres import leer_recorte, limpiar_stem
from .validar_etiquetas import EXT_IMG


def _fraccion(clave: str, semilla: str) -> float:
    return int(hashlib.sha1(f"{semilla}:{clave}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def clave_de(img: Path) -> str:
    info = leer_recorte(img.with_name(limpiar_stem(img.name) + img.suffix))
    return info.clave_pasada() if info.track is not None else f"suelto:{limpiar_stem(img.name)}"


def dividir(origen: Path, destino: Path, proporciones: Dict[str, float], semilla: str = "cisa",
            congelado: Optional[Path] = None, clases: Optional[List[str]] = None) -> Dict:
    origen, destino = Path(origen), Path(destino)
    imgs = sorted(p for p in (origen / "images").iterdir() if p.suffix.lower() in EXT_IMG)
    p_train = float(proporciones.get("train", 0.7))
    p_valid = float(proporciones.get("valid", 0.2))

    claves_test: Optional[set] = None
    if congelado and Path(congelado).exists():
        claves_test = {l.strip() for l in Path(congelado).read_text(encoding="utf-8").splitlines()
                       if l.strip() and not l.startswith("#")}

    asignacion: Dict[Path, str] = {}
    for img in imgs:
        clave = clave_de(img)
        f = _fraccion(clave, semilla)
        if claves_test is not None:
            if clave in claves_test:
                asignacion[img] = "test"
            else:   # sin test: se reparte en proporción train:valid
                asignacion[img] = "train" if f < p_train / (p_train + p_valid) else "valid"
        else:
            asignacion[img] = "train" if f < p_train else ("valid" if f < p_train + p_valid else "test")

    for split in ("train", "valid", "test"):
        (destino / split / "images").mkdir(parents=True, exist_ok=True)
        (destino / split / "labels").mkdir(parents=True, exist_ok=True)
    for img, split in asignacion.items():
        shutil.copy2(img, destino / split / "images" / img.name)
        txt = origen / "labels" / f"{img.stem}.txt"
        if txt.exists():
            shutil.copy2(txt, destino / split / "labels" / txt.name)

    nombres = clases
    if nombres is None and (origen / "data.yaml").exists():
        nombres = (yaml.safe_load((origen / "data.yaml").read_text(encoding="utf-8")) or {}).get("names")
    datos = {"path": str(destino.resolve()), "train": "train/images", "val": "valid/images",
             "test": "test/images", "nc": len(nombres or []), "names": list(nombres or [])}
    (destino / "data.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False),
                                       encoding="utf-8")

    creado = False
    if congelado and claves_test is None:
        claves = sorted({clave_de(i) for i, s in asignacion.items() if s == "test"})
        Path(congelado).parent.mkdir(parents=True, exist_ok=True)
        Path(congelado).write_text(
            "# Set de prueba congelado: una pasada por línea. NO editar a mano.\n"
            + "\n".join(claves) + "\n", encoding="utf-8")
        creado = True

    conteo = Counter(asignacion.values())
    return {"imagenes": dict(conteo), "pasadas_test": len({clave_de(i) for i, s in asignacion.items() if s == "test"}),
            "congelado_creado": creado, "congelado_usado": claves_test is not None}
