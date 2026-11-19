"""
Escribe un LOTE listo para subir a Roboflow, en formato YOLO:

  <salida>/
    data.yaml          nc + names en el orden oficial (clases.py)
    images/            recortes elegidos (conservar + revisar)
    labels/            pre-etiquetas del modelo actual (una caja por línea)
    resumen.csv        decisión, razones y lecturas de cada recorte
    manifiesto.json    de dónde salió el lote: modelo, umbrales, conteos

En Roboflow: Upload Data → arrastrar la carpeta completa. Roboflow
reconoce data.yaml + images/ + labels/ y muestra las cajas ya dibujadas.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import yaml

from .predicciones import Prediccion, escribir_yolo
from .seleccion import DESCARTAR, Decision, resumen


def _nombre_unico(ruta: Path, usados: set) -> str:
    """Dos carpetas (delantero/lateral) pueden tener el mismo nombre de archivo."""
    nombre = ruta.name
    if nombre in usados:
        sufijo = hashlib.md5(str(ruta).encode()).hexdigest()[:6]
        nombre = f"{ruta.stem}_{sufijo}{ruta.suffix}"
    usados.add(nombre)
    return nombre


def escribir_lote(decisiones: Sequence[Decision],
                  predicciones: Optional[Dict[str, Prediccion]],
                  salida: Path,
                  clases: List[str],
                  info_extra: Optional[Dict] = None,
                  incluir_descartadas_en_csv: bool = True) -> Dict:
    salida = Path(salida)
    (salida / "images").mkdir(parents=True, exist_ok=True)
    (salida / "labels").mkdir(parents=True, exist_ok=True)
    predicciones = predicciones or {}
    usados: set = set()
    filas = []
    for d in decisiones:
        fila = d.fila()
        if d.decision != DESCARTAR:
            origen = Path(d.ruta)
            nombre = _nombre_unico(origen, usados)
            shutil.copy2(origen, salida / "images" / nombre)
            pred = predicciones.get(d.ruta)
            escribir_yolo(salida / "labels" / (Path(nombre).stem + ".txt"), pred.cajas if pred else [])
            fila["archivo_lote"] = nombre
        else:
            fila["archivo_lote"] = ""
        if d.decision != DESCARTAR or incluir_descartadas_en_csv:
            filas.append(fila)

    with open(salida / "data.yaml", "w", encoding="utf-8") as fh:
        yaml.safe_dump({"nc": len(clases), "names": list(clases)}, fh, allow_unicode=True, sort_keys=False)

    columnas = ["archivo_lote", "decision", "razones", "prioridad", "lectura_modelo", "consenso",
                "numero_sistema", "conf_min", "nitidez", "luz", "pasada", "ruta"]
    with open(salida / "resumen.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        for f in sorted(filas, key=lambda f: (f["decision"] == DESCARTAR, -float(f["prioridad"]))):
            w.writerow(f)

    manifiesto = {
        "creado": datetime.now().isoformat(timespec="seconds"),
        "clases": list(clases),
        "con_preetiquetas": bool(predicciones),
        "resumen": resumen(decisiones),
    }
    manifiesto.update(info_extra or {})
    (salida / "manifiesto.json").write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
    return manifiesto
