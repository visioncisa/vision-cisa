"""
Revisa un dataset YOLO ANTES de entrenar. Acepta las dos formas:

  plano:     <raiz>/images, <raiz>/labels                  (un lote)
  dividido:  <raiz>/{train,valid,test}/{images,labels}     (export de Roboflow)

ERRORES (bloquean el entrenamiento):
  - data.yaml falta o sus clases no están en el orden oficial
  - clase fuera de rango, coordenadas fuera de 0-1, caja de tamaño 0
  - línea mal formada
  - la misma pasada (track) o la misma imagen en dos splits  → fuga
ADVERTENCIAS (se reportan, no bloquean):
  - imagen sin .txt (se toma como "sin objetos") o .txt sin imagen
  - imagen con .txt vacío (negativo)
  - clase con muy pocos ejemplos
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .clases import comparar_clases
from .nombres import leer_recorte, limpiar_stem
from .redundancia import distancia, hash_archivo

EXT_IMG = {".jpg", ".jpeg", ".png", ".bmp"}
SPLITS = ("train", "valid", "test")


@dataclass
class Reporte:
    errores: List[str] = field(default_factory=list)
    advertencias: List[str] = field(default_factory=list)
    estadisticas: Dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errores

    def texto(self, max_lineas: int = 30) -> str:
        lineas = [f"Resultado: {'OK' if self.ok else 'CON ERRORES'}",
                  f"Estadísticas: {self.estadisticas}"]
        for titulo, lista in (("ERRORES", self.errores), ("ADVERTENCIAS", self.advertencias)):
            if lista:
                lineas.append(f"{titulo} ({len(lista)}):")
                lineas += [f"  - {x}" for x in lista[:max_lineas]]
                if len(lista) > max_lineas:
                    lineas.append(f"  … y {len(lista) - max_lineas} más")
        return "\n".join(lineas)


def _partes(raiz: Path) -> Dict[str, Path]:
    divididas = {s: raiz / s for s in SPLITS if (raiz / s / "images").is_dir()}
    if divididas:
        return divididas
    if (raiz / "images").is_dir():
        return {"todo": raiz}
    return {}


def validar(raiz: Path, clases_esperadas: Optional[List[str]] = None,
            min_por_clase: int = 20, revisar_fuga: bool = True,
            hash_fuga_max: int = 2) -> Reporte:
    raiz = Path(raiz)
    rep = Reporte()
    data = raiz / "data.yaml"
    nombres: List[str] = []
    if not data.exists():
        rep.errores.append("Falta data.yaml")
    else:
        contenido = yaml.safe_load(data.read_text(encoding="utf-8")) or {}
        nombres = contenido.get("names") or []
        if isinstance(nombres, dict):
            nombres = [nombres[k] for k in sorted(nombres)]
        if clases_esperadas is not None:
            rep.errores += [f"data.yaml: {p}" for p in comparar_clases(clases_esperadas, nombres)]
    nc = len(clases_esperadas or nombres)

    partes = _partes(raiz)
    if not partes:
        rep.errores.append("No encontré images/ ni train|valid|test/images")
        return rep

    conteo_clases: Counter = Counter()
    imagenes_por_split: Dict[str, List[Path]] = {}
    for split, base in partes.items():
        imgs = sorted(p for p in (base / "images").iterdir() if p.suffix.lower() in EXT_IMG)
        imagenes_por_split[split] = imgs
        labels_dir = base / "labels"
        stems = {p.stem for p in imgs}
        for txt in (labels_dir.glob("*.txt") if labels_dir.is_dir() else []):
            if txt.stem not in stems:
                rep.advertencias.append(f"{split}: etiqueta sin imagen {txt.name}")
        vacias = 0
        for img in imgs:
            txt = labels_dir / f"{img.stem}.txt"
            if not txt.exists():
                rep.advertencias.append(f"{split}: imagen sin etiqueta {img.name}")
                continue
            lineas = [l for l in txt.read_text(encoding="utf-8").splitlines() if l.strip()]
            if not lineas:
                vacias += 1
            for n, linea in enumerate(lineas, 1):
                p = linea.split()
                donde = f"{split}/{txt.name}:{n}"
                if len(p) != 5:
                    rep.errores.append(f"{donde} tiene {len(p)} columnas (se esperan 5; ¿polígono?)")
                    continue
                try:
                    c = int(float(p[0])); cx, cy, w, h = map(float, p[1:])
                except ValueError:
                    rep.errores.append(f"{donde} no es numérica: '{linea}'")
                    continue
                if not 0 <= c < max(1, nc):
                    rep.errores.append(f"{donde} clase {c} fuera de rango (0-{nc - 1})")
                if not all(0.0 <= v <= 1.0 for v in (cx, cy, w, h)):
                    rep.errores.append(f"{donde} coordenadas fuera de 0-1")
                if w <= 0 or h <= 0:
                    rep.errores.append(f"{donde} caja de tamaño cero")
                conteo_clases[c] += 1
        rep.estadisticas[f"{split}_imagenes"] = len(imgs)
        rep.estadisticas[f"{split}_negativas"] = vacias

    rep.estadisticas["cajas_por_clase"] = {
        (nombres[c] if c < len(nombres) else str(c)): n for c, n in sorted(conteo_clases.items())}
    for c in range(nc):
        if conteo_clases[c] < min_por_clase:
            nombre = nombres[c] if c < len(nombres) else str(c)
            rep.advertencias.append(f"Clase '{nombre}' con solo {conteo_clases[c]} cajas (< {min_por_clase})")

    if revisar_fuga and len(imagenes_por_split) > 1:
        _revisar_fuga(imagenes_por_split, rep, hash_fuga_max)
    return rep


def _revisar_fuga(imagenes_por_split: Dict[str, List[Path]], rep: Reporte, hash_max: int) -> None:
    pasadas = defaultdict(set)
    for split, imgs in imagenes_por_split.items():
        for img in imgs:
            info = leer_recorte(img.with_name(limpiar_stem(img.name) + img.suffix))
            if info.track is not None:
                pasadas[info.clave_pasada()].add(split)
    for clave, splits in pasadas.items():
        if len(splits) > 1:
            rep.errores.append(f"Fuga: la pasada {clave} está en {sorted(splits)}")
    hashes = []
    for split, imgs in imagenes_por_split.items():
        for img in imgs:
            try:
                hashes.append((split, img.name, hash_archivo(img)))
            except ValueError:
                rep.advertencias.append(f"{split}: no se pudo leer {img.name}")
    for i in range(len(hashes)):
        for j in range(i + 1, len(hashes)):
            if hashes[i][0] != hashes[j][0] and distancia(hashes[i][2], hashes[j][2]) <= hash_max:
                rep.errores.append(
                    f"Fuga: {hashes[i][0]}/{hashes[i][1]} y {hashes[j][0]}/{hashes[j][1]} son casi idénticas")
