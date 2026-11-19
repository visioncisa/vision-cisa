import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from reentrenamiento import extraer_video as ev
from reentrenamiento.__main__ import main
from reentrenamiento.predicciones import escribir_yolo
from conftest import guardar, placa


def _video(ruta: Path, segundos=10, fps=10):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    w = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), fps, (160, 120))
    if not w.isOpened():
        pytest.skip("OpenCV de este equipo no puede escribir mp4")
    for k in range(segundos * fps):
        img = np.full((120, 160, 3), (k * 2) % 255, np.uint8)
        cv2.putText(img, str(k), (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        w.write(img)
    w.release()
    return ruta


def test_grabacion_que_contiene_el_evento(tmp_path):
    for h in ("100000", "110000", "120000"):
        (tmp_path / f"cam1_20261118_{h}.mp4").write_bytes(b"")
    grabs = ev.indice_grabaciones(tmp_path)
    assert ev.grabacion_de(datetime(2026, 11, 18, 11, 30), grabs).inicio.hour == 11
    assert ev.grabacion_de(datetime(2026, 11, 18, 9, 59), grabs) is None
    assert ev.grabacion_de(datetime(2026, 11, 18, 15, 0), grabs) is None   # más de 1 h después


def test_extraer_por_eventos(tmp_path):
    _video(tmp_path / "grab" / "cam1_20261118_120000.mp4")
    eventos_json = tmp_path / "eventos.json"
    eventos_json.write_text(json.dumps({"items": [
        {"id": 1, "ts": "2026-11-18 12:00:05", "numero": "5051"},
        {"id": 2, "ts": "2026-11-18 08:00:00", "numero": "544"},     # sin grabación
    ]}))
    r = ev.por_eventos(ev.cargar_eventos(eventos_json), tmp_path / "grab", tmp_path / "salida",
                       antes=2, despues=2, paso=1)
    assert r["con_video"] == 1 and r["sin_video"] == 1 and r["cuadros"] == 5
    assert len(list((tmp_path / "salida").glob("evt1_20261118_120005_5051_*.jpg"))) == 5


def test_extraer_periodico(tmp_path):
    video = _video(tmp_path / "v.mp4", segundos=6)
    assert ev.periodico(video, tmp_path / "p", cada_seg=2) == 3


# ── CLI de punta a punta ──────────────────────────────────────────────────────
def test_cli_seleccionar_validar_dividir(tmp_path, capsys):
    for t in range(6):
        for s in range(4):
            guardar(tmp_path / "crops" / "lateral" / f"20261118_1000{s:02d}_000_5051_t{t}.jpg",
                    placa("5051", ruido=15, semilla=t * 10 + s, desplazar=t))
    assert main(["seleccionar", "--entrada", str(tmp_path / "crops"), "--modelo", "m3",
                 "--salida", str(tmp_path / "lote")]) == 0
    man = json.loads((tmp_path / "lote" / "manifiesto.json").read_text())
    assert man["resumen"]["total"] == 24 and man["resumen"]["pasadas"] == 6
    elegidas = man["resumen"]["conservar"] + man["resumen"]["revisar"]
    assert 0 < elegidas <= 6        # como máximo 1 por pasada fácil

    # simular que en Roboflow etiquetaron el lote
    for img in (tmp_path / "lote" / "images").iterdir():
        escribir_yolo(tmp_path / "lote" / "labels" / f"{img.stem}.txt",
                      [(int(d), 0.15 + 0.2 * i, 0.5, 0.12, 0.6, 1.0) for i, d in enumerate("5051")])
    assert main(["validar", "--dataset", str(tmp_path / "lote"), "--modelo", "m3", "--min-por-clase", "0"]) == 0
    assert main(["dividir", "--origen", str(tmp_path / "lote"), "--destino", str(tmp_path / "ds"),
                 "--modelo", "m3", "--congelado", str(tmp_path / "congelado.txt")]) == 0
    assert (tmp_path / "congelado.txt").exists()


def test_cli_preanotar_sin_pesos_falla(tmp_path):
    assert main(["preanotar", "--entrada", str(tmp_path), "--modelo", "m3", "--salida", str(tmp_path / "x")]) == 1


def test_cli_evaluar_codigos(tmp_path, crear_dataset):
    verdad = crear_dataset({"todo": {"a.jpg": [(5, 0.2, 0.5, 0.12, 0.6), (0, 0.4, 0.5, 0.12, 0.6)]}})
    escribir_yolo(tmp_path / "pa" / "a.txt", [(5, 0.2, 0.5, 0.12, 0.6, 0.9)], con_conf=True)
    escribir_yolo(tmp_path / "pc" / "a.txt", [(5, 0.2, 0.5, 0.12, 0.6, 0.9), (0, 0.4, 0.5, 0.12, 0.6, 0.9)],
                  con_conf=True)
    args = ["evaluar", "--verdad", str(verdad), "--modelo", "m3", "--salida", str(tmp_path / "r")]
    assert main(args + ["--pred-actual", str(tmp_path / "pa"), "--pred-candidato", str(tmp_path / "pc")]) == 0
    assert main(args + ["--pred-actual", str(tmp_path / "pc"), "--pred-candidato", str(tmp_path / "pa")]) == 3
