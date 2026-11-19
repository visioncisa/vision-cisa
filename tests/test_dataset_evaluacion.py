import json
from pathlib import Path

import pytest
import yaml

from reentrenamiento import evaluar as ev
from reentrenamiento.dividir import clave_de, dividir
from reentrenamiento.entrenar import entrenar, hash_dataset
from reentrenamiento.predicciones import escribir_yolo
from reentrenamiento.validar_etiquetas import validar

DIG = [str(d) for d in range(10)]
C = (5, 0.3, 0.5, 0.1, 0.5)


# ── validar ───────────────────────────────────────────────────────────────────
def test_dataset_correcto(crear_dataset):
    raiz = crear_dataset({"train": {"20261118_100000_000_5_t1.jpg": [C]},
                          "valid": {"20261118_100000_000_5_t2.jpg": [C]}})
    rep = validar(raiz, DIG, min_por_clase=0)
    assert rep.ok, rep.texto()


def test_errores_de_etiquetas(crear_dataset):
    raiz = crear_dataset({"todo": {
        "a.jpg": [(12, 0.5, 0.5, 0.1, 0.1)],                 # clase fuera de rango
        "b.jpg": [(1, 1.5, 0.5, 0.1, 0.1)],                  # coordenada > 1
        "c.jpg": [(1, 0.5, 0.5, 0.0, 0.1)],                  # caja de tamaño 0
        "d.jpg": [(1, 0.1, 0.1, 0.2, 0.1, 0.3, 0.3)],        # polígono (7 columnas)
    }})
    rep = validar(raiz, DIG, min_por_clase=0)
    texto = " ".join(rep.errores)
    assert not rep.ok
    for esperado in ("fuera de rango", "fuera de 0-1", "tamaño cero", "columnas"):
        assert esperado in texto


def test_clases_en_otro_orden(crear_dataset):
    raiz = crear_dataset({"todo": {"a.jpg": [(0, 0.5, 0.5, 0.2, 0.2)]}}, names=["lateral", "delantero", "trasera"])
    rep = validar(raiz, ["delantero", "lateral", "trasera"], min_por_clase=0)
    assert any("se esperaba 'delantero'" in e for e in rep.errores)


def test_fuga_misma_pasada_en_dos_splits(crear_dataset):
    raiz = crear_dataset({"train": {"lateral_20261118_100000_000_5051_t7.jpg": [C],
                                    "20261118_100000_000_5051_t7.jpg": [C]},
                          "test": {"20261118_100002_000_5051_t7.jpg": [C]}})
    rep = validar(raiz, DIG, min_por_clase=0)
    assert any("Fuga: la pasada" in e for e in rep.errores)


def test_advertencias_huerfanas(crear_dataset):
    raiz = crear_dataset({"todo": {"a.jpg": [C]}})
    (raiz / "labels" / "sin_imagen.txt").write_text("1 0.5 0.5 0.1 0.1\n")
    (raiz / "labels" / "a.txt").unlink()
    rep = validar(raiz, DIG, min_por_clase=0)
    assert rep.ok and len(rep.advertencias) == 2


# ── dividir ───────────────────────────────────────────────────────────────────
def test_misma_pasada_mismo_split_y_test_congelado(crear_dataset, tmp_path):
    archivos = {f"20261118_10{t:02d}{s:02d}_000_5051_t{t}.jpg": [C] for t in range(40) for s in range(3)}
    origen = crear_dataset({"todo": archivos})
    congelado = tmp_path / "congelado.txt"
    r1 = dividir(origen, tmp_path / "v1", {"train": 0.7, "valid": 0.2, "test": 0.1}, "cisa", congelado, DIG)
    assert r1["congelado_creado"] and r1["imagenes"].get("test", 0) > 0
    splits_por_pasada = {}
    for split in ("train", "valid", "test"):
        for img in (tmp_path / "v1" / split / "images").iterdir():
            splits_por_pasada.setdefault(clave_de(img), set()).add(split)
    assert all(len(s) == 1 for s in splits_por_pasada.values())

    # datos nuevos: el test NO cambia
    nuevos = {f"20261119_11{t:02d}00_000_5051_t{t}.jpg": [C] for t in range(20)}
    origen2 = crear_dataset({"todo": {**archivos, **nuevos}}, raiz=tmp_path / "ds2")
    r2 = dividir(origen2, tmp_path / "v2", {"train": 0.7, "valid": 0.2, "test": 0.1}, "cisa", congelado, DIG)
    assert r2["congelado_usado"] and r2["imagenes"]["test"] == r1["imagenes"]["test"]
    assert yaml.safe_load((tmp_path / "v2" / "data.yaml").read_text())["names"] == DIG


# ── evaluar ───────────────────────────────────────────────────────────────────
def test_iou_y_levenshtein():
    a = (0, 0.5, 0.5, 0.2, 0.2, 1.0)
    assert ev.iou(a, a) == pytest.approx(1.0)
    assert ev.iou(a, (0, 0.9, 0.9, 0.1, 0.1, 1.0)) == 0.0
    assert ev.levenshtein("5051", "505") == 1 and ev.levenshtein("5063", "0063") == 1


def _escenario(crear_dataset, tmp_path, lecturas_actual, lecturas_cand):
    reales = {f"img{k}.jpg": [(int(d), 0.15 + 0.2 * i, 0.5, 0.12, 0.6) for i, d in enumerate(n)]
              for k, n in enumerate(["5051", "544", "5063", "522"])}
    verdad = crear_dataset({"todo": reales})
    for nombre, lecturas in (("actual", lecturas_actual), ("cand", lecturas_cand)):
        for k, n in enumerate(lecturas):
            escribir_yolo(tmp_path / nombre / f"img{k}.txt",
                          [(int(d), 0.15 + 0.2 * i, 0.5, 0.12, 0.6, 0.8) for i, d in enumerate(n)], con_conf=True)
    base = ev.metricas(verdad, tmp_path / "actual", DIG)
    cand = ev.metricas(verdad, tmp_path / "cand", DIG)
    return base, cand


def test_metricas_ocr(crear_dataset, tmp_path):
    base, _ = _escenario(crear_dataset, tmp_path, ["5051", "544", "0063", ""], ["5051"] * 4)
    assert base["exactitud_numero"] == 0.5
    assert base["lecturas_fallidas"] == 1
    assert base["cer"] == pytest.approx((0 + 0 + 1 + 3) / 14, abs=1e-3)
    assert base["fn"] == 4 and base["fp"] == 1


def test_comparar_acepta_mejora(crear_dataset, tmp_path, cfg):
    base, cand = _escenario(crear_dataset, tmp_path, ["5051", "544", "0063", ""], ["5051", "544", "5063", "522"])
    v = ev.comparar(base, cand, cfg["evaluacion"]["criterios"])
    assert v["decision"] == "ACEPTAR" and v["mejoras"]


def test_comparar_rechaza_regresion(crear_dataset, tmp_path, cfg):
    base, cand = _escenario(crear_dataset, tmp_path, ["5051", "544", "5063", "522"], ["5051", "544", "0063", ""])
    v = ev.comparar(base, cand, cfg["evaluacion"]["criterios"])
    assert v["decision"] == "RECHAZAR"
    assert any("Exactitud" in m for m in v["motivos_rechazo"])


def test_comparar_rechaza_si_no_mejora(cfg):
    m = {"precision": 0.9, "recall": 0.9, "por_clase": {}}
    v = ev.comparar(m, dict(m), cfg["evaluacion"]["criterios"])
    assert v["decision"] == "RECHAZAR"


def test_reporte(tmp_path, crear_dataset, cfg):
    base, cand = _escenario(crear_dataset, tmp_path, ["5051"] * 4, ["5051", "544", "5063", "522"])
    v = ev.comparar(base, cand, cfg["evaluacion"]["criterios"])
    ev.guardar(tmp_path / "rep", base, cand, v, "Prueba")
    md = (tmp_path / "rep" / "evaluacion.md").read_text()
    assert "Decisión: ACEPTAR" in md and "| exactitud_numero |" in md
    assert json.loads((tmp_path / "rep" / "evaluacion.json").read_text())["veredicto"]["decision"] == "ACEPTAR"


# ── entrenar (simulado: sin GPU) ──────────────────────────────────────────────
def test_entrenar_simulado_registra(crear_dataset, tmp_path):
    ds = crear_dataset({"train": {"a.jpg": [C]}})
    exp = tmp_path / "exp.yaml"
    exp.write_text(yaml.safe_dump({"nombre": "prueba", "modelo": "m3", "base": "v3.pt",
                                   "data": str(ds / "data.yaml"), "args": {"epochs": 1}}))
    fila = entrenar(exp, tmp_path / "registro.jsonl", tmp_path / "corridas", simular=True)
    assert fila["estado"] == "simulado" and len(fila["hash_dataset"]) == 16
    assert json.loads((tmp_path / "registro.jsonl").read_text().splitlines()[0])["experimento"] == "prueba"
    h1 = hash_dataset(ds / "data.yaml")
    (ds / "train" / "labels" / "a.txt").write_text("6 0.3 0.5 0.1 0.5\n")   # corrigen una etiqueta
    assert hash_dataset(ds / "data.yaml") != h1


def test_entrenar_rechaza_clases_mal_ordenadas(crear_dataset, tmp_path):
    ds = crear_dataset({"train": {"a.jpg": [C]}}, names=["1", "0", "2", "3", "4", "5", "6", "7", "8", "9"])
    exp = tmp_path / "exp.yaml"
    exp.write_text(yaml.safe_dump({"nombre": "x", "modelo": "m3", "base": "v3.pt", "data": str(ds / "data.yaml")}))
    with pytest.raises(ValueError, match="orden oficial"):
        entrenar(exp, tmp_path / "r.jsonl", tmp_path / "c", simular=True)
