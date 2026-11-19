"""
Entrena (o hace fine-tuning) desde un YAML de experimento y deja
registro de TODO lo necesario para repetirlo.

Ejemplo de experimento: experimentos/m3_v4_finetune.yaml

  nombre: m3_v4_finetune
  modelo: m3
  base: /content/drive/MyDrive/CISA_Reentrenamiento/modelos/modelo_digitos_v3.pt
  data: /content/datasets/m3_v4/data.yaml
  args:                     # se pasan tal cual a YOLO.train()
    imgsz: 640
    epochs: 150
    patience: 30            # early stopping
    batch: 16
    freeze: 0               # 10 = congela el backbone (útil con pocos datos nuevos)
    lr0: 0.002              # más bajo que el defecto: fine-tuning, no desde cero
    seed: 0
    deterministic: true

Cada corrida agrega una línea a experimentos/registro.jsonl con:
fecha, commit de git, versiones, hash del dataset, args, métricas,
ruta y sha256 de los pesos. Los pesos NO se suben a git.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import yaml

from .clases import clases_de, comparar_clases


def sha256(ruta: Path, bloque: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        while True:
            datos = fh.read(bloque)
            if not datos:
                break
            h.update(datos)
    return h.hexdigest()


def hash_dataset(data_yaml: Path) -> str:
    """Hash de los NOMBRES de imagen y del CONTENIDO de las etiquetas.
    Cambia si se agrega, quita o corrige cualquier etiqueta."""
    data_yaml = Path(data_yaml)
    raiz = data_yaml.parent
    h = hashlib.sha256()
    for txt in sorted(raiz.rglob("labels/*.txt")):
        h.update(str(txt.relative_to(raiz)).encode())
        h.update(txt.read_bytes())
    for img in sorted(raiz.rglob("images/*")):
        h.update(str(img.relative_to(raiz)).encode())
    return h.hexdigest()[:16]


def commit_git() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
        sucio = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                               text=True, check=True).stdout.strip()
        return sha + ("-con-cambios" if sucio else "")
    except (OSError, subprocess.CalledProcessError):
        return "desconocido"


def versiones() -> Dict[str, str]:
    v = {"python": platform.python_version()}
    for mod in ("ultralytics", "torch"):
        try:
            v[mod] = __import__(mod).__version__
        except ImportError:
            v[mod] = "no instalado"
    try:
        import torch
        v["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "sin GPU"
    except ImportError:
        pass
    return v


def cargar_experimento(ruta: Path) -> Dict:
    exp = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    faltan = [k for k in ("nombre", "modelo", "base", "data") if k not in exp]
    if faltan:
        raise ValueError(f"{ruta}: faltan claves {faltan}")
    return exp


def entrenar(experimento: Path, registro: Path, proyecto: Path,
             simular: bool = False) -> Dict:
    exp = cargar_experimento(experimento)
    data_yaml = Path(exp["data"])
    nombres = (yaml.safe_load(data_yaml.read_text(encoding="utf-8")) or {}).get("names", [])
    problemas = comparar_clases(clases_de(exp["modelo"]), nombres)
    if problemas:
        raise ValueError("El dataset no tiene las clases en el orden oficial:\n  " + "\n  ".join(problemas))

    fila = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "experimento": exp["nombre"],
        "modelo": exp["modelo"],
        "base": str(exp["base"]),
        "data": str(data_yaml),
        "hash_dataset": hash_dataset(data_yaml),
        "commit": commit_git(),
        "versiones": versiones(),
        "args": exp.get("args", {}),
        "estado": "simulado" if simular else "iniciado",
    }
    if not simular:  # pragma: no cover - requiere GPU y ultralytics
        from ultralytics import YOLO
        try:
            modelo = YOLO(str(exp["base"]))
            resultado = modelo.train(data=str(data_yaml), project=str(proyecto), name=exp["nombre"],
                                     exist_ok=False, **exp.get("args", {}))
            pesos = Path(resultado.save_dir) / "weights" / "best.pt"
            fila.update({
                "estado": "terminado",
                "metricas": {k: round(float(v), 4) for k, v in (resultado.results_dict or {}).items()},
                "pesos": str(pesos),
                "sha256_pesos": sha256(pesos) if pesos.exists() else None,
            })
        except Exception as e:
            fila.update({"estado": "fallido", "error": f"{type(e).__name__}: {e}"})
    Path(registro).parent.mkdir(parents=True, exist_ok=True)
    with open(registro, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(fila, ensure_ascii=False) + "\n")
    if fila["estado"] == "fallido":
        raise RuntimeError(f"El entrenamiento falló: {fila['error']} (quedó en {registro})")
    return fila
