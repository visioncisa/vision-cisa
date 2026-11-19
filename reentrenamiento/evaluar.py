"""
Evaluación de un modelo candidato contra el actual, sobre el MISMO set
de prueba congelado, y decisión ACEPTAR / RECHAZAR.

Métricas propias (no dependen de Ultralytics, se pueden probar):
  - por clase: verdaderos positivos, falsos positivos, falsos negativos,
    precisión y recall con emparejamiento por IoU (greedy, por confianza)
  - M3: exactitud del NÚMERO COMPLETO, CER (errores de carácter /
    largo real) y lecturas fallidas (no se leyó nada)
mAP50 y mAP50-95 se toman de `model.val()` de Ultralytics cuando está
disponible (`metricas_ultralytics`), porque su cálculo es el estándar.

Criterios (config_reentrenamiento.yaml → evaluacion.criterios):
el candidato se RECHAZA si empeora el recall o la precisión global
más de lo permitido, si alguna clase pierde recall más de lo permitido
(olvido de escenarios), o si en M3 baja la exactitud o sube el CER.
Se ACEPTA solo si además mejora al menos una métrica principal.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .predicciones import Caja, leer_yolo, lectura_desde_cajas
from .validar_etiquetas import EXT_IMG


def iou(a: Caja, b: Caja) -> float:
    ax1, ay1, ax2, ay2 = a[1] - a[3] / 2, a[2] - a[4] / 2, a[1] + a[3] / 2, a[2] + a[4] / 2
    bx1, by1, bx2, by2 = b[1] - b[3] / 2, b[2] - b[4] / 2, b[1] + b[3] / 2, b[2] + b[4] / 2
    iw, ih = max(0.0, min(ax2, bx2) - max(ax1, bx1)), max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = a[3] * a[4] + b[3] * b[4] - inter
    return inter / union if union > 0 else 0.0


def emparejar(reales: Sequence[Caja], pred: Sequence[Caja], umbral: float) -> Tuple[int, int, int, Dict]:
    """Devuelve (tp, fp, fn, por_clase{clase: [tp, fp, fn]})."""
    por_clase = defaultdict(lambda: [0, 0, 0])
    usadas = set()
    for p in sorted(pred, key=lambda c: -c[5]):
        mejor, mejor_iou = None, umbral
        for i, r in enumerate(reales):
            if i in usadas or r[0] != p[0]:
                continue
            v = iou(r, p)
            if v >= mejor_iou:
                mejor, mejor_iou = i, v
        if mejor is None:
            por_clase[p[0]][1] += 1
        else:
            usadas.add(mejor)
            por_clase[p[0]][0] += 1
    for i, r in enumerate(reales):
        if i not in usadas:
            por_clase[r[0]][2] += 1
    tp = sum(v[0] for v in por_clase.values())
    fp = sum(v[1] for v in por_clase.values())
    fn = sum(v[2] for v in por_clase.values())
    return tp, fp, fn, por_clase


def levenshtein(a: str, b: str) -> int:
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + (ca != cb)))
        previa = actual
    return previa[-1]


def _div(a: float, b: float) -> float:
    return round(a / b, 4) if b else 0.0


def metricas(dir_reales: Path, dir_pred: Path, nombres: List[str], iou_umbral: float = 0.5,
             es_digitos: Optional[bool] = None) -> Dict:
    """dir_reales: carpeta con images/ y labels/ (verdad). dir_pred: .txt del modelo (con conf)."""
    dir_reales, dir_pred = Path(dir_reales), Path(dir_pred)
    es_digitos = list(nombres) == [str(d) for d in range(10)] if es_digitos is None else es_digitos
    imgs = sorted(p for p in (dir_reales / "images").iterdir() if p.suffix.lower() in EXT_IMG)
    tot = defaultdict(lambda: [0, 0, 0])
    tp = fp = fn = 0
    exactas = fallidas = 0
    err_car = car_total = 0
    errores_lectura: List[Dict] = []
    for img in imgs:
        reales = leer_yolo(dir_reales / "labels" / f"{img.stem}.txt")
        pred = leer_yolo(dir_pred / f"{img.stem}.txt", con_conf=True)
        a, b, c, pc = emparejar(reales, pred, iou_umbral)
        tp, fp, fn = tp + a, fp + b, fn + c
        for k, v in pc.items():
            for i in range(3):
                tot[k][i] += v[i]
        if es_digitos and reales:
            real = lectura_desde_cajas(reales, nombres)
            leida = lectura_desde_cajas(pred, nombres)
            if not leida:
                fallidas += 1
            if leida == real:
                exactas += 1
            elif len(errores_lectura) < 50:
                errores_lectura.append({"imagen": img.name, "real": real, "leida": leida})
            err_car += levenshtein(real, leida)
            car_total += len(real)
    salida = {
        "imagenes": len(imgs),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": _div(tp, tp + fp),
        "recall": _div(tp, tp + fn),
        "por_clase": {
            (nombres[k] if k < len(nombres) else str(k)): {
                "tp": v[0], "fp": v[1], "fn": v[2],
                "precision": _div(v[0], v[0] + v[1]), "recall": _div(v[0], v[0] + v[2])}
            for k, v in sorted(tot.items())},
    }
    if es_digitos:
        con_numero = sum(1 for img in imgs if leer_yolo(dir_reales / "labels" / f"{img.stem}.txt"))
        salida.update({
            "numeros_evaluados": con_numero,
            "exactitud_numero": _div(exactas, con_numero),
            "cer": _div(err_car, car_total),
            "lecturas_fallidas": fallidas,
            "ejemplos_errores": errores_lectura,
        })
    return salida


def comparar(base: Dict, candidato: Dict, criterios: Dict) -> Dict:
    motivos_rechazo, mejoras = [], []

    def caida(metrica: str, limite: float, etiqueta: str):
        if metrica in base and metrica in candidato:
            d = candidato[metrica] - base[metrica]
            if d < -limite:
                motivos_rechazo.append(f"{etiqueta}: {base[metrica]:.4f} → {candidato[metrica]:.4f} (baja {-d:.4f})")
            if d >= criterios.get("mejora_minima", 0.005):
                mejoras.append(f"{etiqueta} +{d:.4f}")

    caida("recall", criterios.get("recall_caida_max", 0.01), "Recall global")
    caida("precision", criterios.get("precision_caida_max", 0.01), "Precisión global")
    caida("map50", criterios.get("recall_caida_max", 0.01), "mAP50")
    caida("map50_95", criterios.get("recall_caida_max", 0.01), "mAP50-95")
    caida("exactitud_numero", criterios.get("exactitud_numero_caida_max", 0.0), "Exactitud del número")

    for clase, vb in base.get("por_clase", {}).items():
        vc = candidato.get("por_clase", {}).get(clase)
        if vc is None:
            motivos_rechazo.append(f"Clase '{clase}' ya no aparece en el candidato")
            continue
        if vc["recall"] - vb["recall"] < -criterios.get("recall_clase_caida_max", 0.03):
            motivos_rechazo.append(f"Olvido en clase '{clase}': recall {vb['recall']:.3f} → {vc['recall']:.3f}")

    if "cer" in base and "cer" in candidato:
        d = candidato["cer"] - base["cer"]
        if d > criterios.get("cer_aumento_max", 0.0):
            motivos_rechazo.append(f"CER sube {base['cer']:.4f} → {candidato['cer']:.4f}")
        if -d >= criterios.get("mejora_minima", 0.005):
            mejoras.append(f"CER -{-d:.4f}")

    if not mejoras and not motivos_rechazo:
        motivos_rechazo.append("No mejora ninguna métrica principal lo suficiente (mejora_minima)")
    return {"decision": "ACEPTAR" if not motivos_rechazo else "RECHAZAR",
            "motivos_rechazo": motivos_rechazo, "mejoras": mejoras}


def reporte_markdown(base: Dict, candidato: Dict, veredicto: Dict, titulo: str) -> str:
    claves = ["imagenes", "precision", "recall", "map50", "map50_95", "fp", "fn",
              "exactitud_numero", "cer", "lecturas_fallidas"]
    lineas = [f"# {titulo}", "", f"**Decisión: {veredicto['decision']}**", "",
              "| Métrica | Actual | Candidato | Diferencia |", "|---|---|---|---|"]
    for k in claves:
        if k in base or k in candidato:
            b, c = base.get(k, "—"), candidato.get(k, "—")
            dif = f"{c - b:+.4f}" if isinstance(b, (int, float)) and isinstance(c, (int, float)) else "—"
            lineas.append(f"| {k} | {b} | {c} | {dif} |")
    lineas += ["", "## Por clase (recall)", "", "| Clase | Actual | Candidato |", "|---|---|---|"]
    for clase, vb in base.get("por_clase", {}).items():
        vc = candidato.get("por_clase", {}).get(clase, {})
        lineas.append(f"| {clase} | {vb['recall']} | {vc.get('recall', '—')} |")
    if veredicto["motivos_rechazo"]:
        lineas += ["", "## Motivos de rechazo", ""] + [f"- {m}" for m in veredicto["motivos_rechazo"]]
    if veredicto["mejoras"]:
        lineas += ["", "## Mejoras", ""] + [f"- {m}" for m in veredicto["mejoras"]]
    ejemplos = candidato.get("ejemplos_errores") or []
    if ejemplos:
        lineas += ["", "## Ejemplos de lecturas equivocadas del candidato", "",
                   "| Imagen | Real | Leída |", "|---|---|---|"]
        lineas += [f"| {e['imagen']} | {e['real']} | {e['leida'] or '(nada)'} |" for e in ejemplos[:20]]
    lineas += ["", "> Métricas de tracking, conteo y rendimiento (FPS, RAM, GPU) se miden en la Jetson "
               "con video grabado: ver docs/EVALUACION_MODELOS.md."]
    return "\n".join(lineas) + "\n"


def metricas_ultralytics(modelo: Path, data_yaml: Path, imgsz: int, split: str = "test") -> Dict:  # pragma: no cover
    from ultralytics import YOLO
    r = YOLO(str(modelo)).val(data=str(data_yaml), imgsz=imgsz, split=split, verbose=False, plots=False)
    return {"map50": round(float(r.box.map50), 4), "map50_95": round(float(r.box.map), 4)}


def predecir_a_carpeta(modelo: Path, dir_imagenes: Path, salida: Path, imgsz: int,
                       conf: float = 0.25, clases: Optional[List[str]] = None) -> None:  # pragma: no cover
    from .predicciones import PredictorUltralytics, escribir_yolo
    pred = PredictorUltralytics(modelo, imgsz=imgsz, conf=conf, half=False, clases_esperadas=clases)
    imgs = sorted(p for p in Path(dir_imagenes).iterdir() if p.suffix.lower() in EXT_IMG)
    for ruta, p in pred.predecir(imgs).items():
        escribir_yolo(Path(salida) / f"{Path(ruta).stem}.txt", p.cajas, con_conf=True)


def guardar(salida: Path, base: Dict, candidato: Dict, veredicto: Dict, titulo: str) -> None:
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "evaluacion.json").write_text(json.dumps(
        {"actual": base, "candidato": candidato, "veredicto": veredicto}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (salida / "evaluacion.md").write_text(reporte_markdown(base, candidato, veredicto, titulo), encoding="utf-8")
