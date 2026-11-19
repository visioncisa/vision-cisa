from pathlib import Path

import cv2
import yaml

from reentrenamiento.calidad import medir_archivo
from reentrenamiento.nombres import leer_recorte
from reentrenamiento.preanotacion import escribir_lote
from reentrenamiento.predicciones import (Prediccion, escribir_yolo, lectura_desde_cajas, leer_yolo,
                                          quitar_encimadas)
from reentrenamiento.redundancia import hash_archivo
from reentrenamiento.seleccion import CONSERVAR, DESCARTAR, REVISAR, resumen, seleccionar
from conftest import guardar, placa

DIG = [str(d) for d in range(10)]


def caja(c, cx, conf=0.9, w=0.12):
    return (c, cx, 0.5, w, 0.6, conf)


# ── predicciones ──────────────────────────────────────────────────────────────
def test_lectura_izquierda_a_derecha():
    assert lectura_desde_cajas([caja(1, 0.8), caja(5, 0.2), caja(0, 0.4), caja(5, 0.6)], DIG) == "5051"


def test_quitar_encimadas_como_produccion():
    # un "5" y un "6" sobre el mismo dígito: se queda el de mayor confianza (evita "255555")
    cajas = [caja(2, 0.2), caja(5, 0.5, conf=0.9), caja(6, 0.51, conf=0.6), caja(5, 0.8)]
    assert [c[0] for c in quitar_encimadas(cajas)] == [2, 5, 5]
    assert lectura_desde_cajas(cajas, DIG) == "255"


def test_yolo_ida_y_vuelta(tmp_path):
    cajas = [caja(5, 0.2, 0.81), caja(0, 0.4, 0.77)]
    escribir_yolo(tmp_path / "a.txt", cajas, con_conf=True)
    leidas = leer_yolo(tmp_path / "a.txt", con_conf=True)
    assert [c[0] for c in leidas] == [5, 0] and abs(leidas[0][5] - 0.81) < 1e-3
    escribir_yolo(tmp_path / "b.txt", cajas)
    assert all(c[5] == 1.0 for c in leer_yolo(tmp_path / "b.txt"))
    assert leer_yolo(tmp_path / "no_existe.txt") == []


def test_prediccion_vacia():
    p = Prediccion()
    assert p.n == 0 and p.conf_min == 0.0 and p.lectura(DIG) == ""


# ── selección ─────────────────────────────────────────────────────────────────
def _preparar(tmp_path, cfg, archivos):
    rutas = [guardar(tmp_path / "crops" / n, img) for n, img in archivos]
    infos = [leer_recorte(r) for r in rutas]
    cal = {str(r): medir_archivo(r, cfg["calidad"]) for r in rutas}
    hs = {str(r): hash_archivo(r) for r in rutas}
    return rutas, infos, cal, hs


def pred_de(texto, conf=0.9):
    return Prediccion([caja(int(d), 0.15 + 0.2 * i, conf) for i, d in enumerate(texto)])


def test_pasada_facil_queda_un_representante(tmp_path, cfg):
    cfg["seleccion"]["porc_faciles"] = 1.0      # forzar que la pasada fácil entre a la muestra
    archivos = [(f"lateral/20261118_100000_{k:03d}_5051_t1.jpg", placa("5051", ruido=10, semilla=k))
                for k in range(8)]
    rutas, infos, cal, hs = _preparar(tmp_path, cfg, archivos)
    preds = {str(r): pred_de("5051") for r in rutas}
    dec = seleccionar(infos, cal, hs, preds, DIG, cfg["seleccion"], cfg["calidad"], padron={"5051"})
    assert sum(d.decision == CONSERVAR for d in dec) == 1
    assert sum(d.decision == DESCARTAR for d in dec) == 7


def test_pasada_facil_fuera_de_muestra_se_descarta_toda(tmp_path, cfg):
    cfg["seleccion"]["porc_faciles"] = 0.0
    archivos = [(f"lateral/20261118_100000_{k:03d}_5051_t1.jpg", placa("5051", semilla=k)) for k in range(3)]
    rutas, infos, cal, hs = _preparar(tmp_path, cfg, archivos)
    dec = seleccionar(infos, cal, hs, {str(r): pred_de("5051") for r in rutas}, DIG,
                      cfg["seleccion"], cfg["calidad"], padron={"5051"})
    assert all(d.decision == DESCARTAR for d in dec)


def test_desacuerdo_y_sistema_distinto_van_a_revision(tmp_path, cfg):
    archivos = [
        ("lateral/20261118_100000_000_5051_t1.jpg", placa("5051")),
        ("lateral/20261118_100001_000_5051_t1.jpg", placa("5051", desplazar=3)),
        ("lateral/20261118_100002_000_505_t1.jpg", placa("5O5", fondo=150, desplazar=25)),
    ]
    rutas, infos, cal, hs = _preparar(tmp_path, cfg, archivos)
    preds = {str(rutas[0]): pred_de("5051"), str(rutas[1]): pred_de("5051"),
             str(rutas[2]): pred_de("505", conf=0.4)}
    dec = {Path(d.ruta).name: d for d in seleccionar(infos, cal, hs, preds, DIG, cfg["seleccion"],
                                                      cfg["calidad"], padron={"5051"})}
    dificil = dec["20261118_100002_000_505_t1.jpg"]
    assert dificil.decision == REVISAR
    assert {"desacuerdo", "baja_conf", "fuera_padron"} <= set(dificil.razones)
    assert sum(d.decision != DESCARTAR for d in dec.values()) <= cfg["seleccion"]["max_por_pasada"]


def test_correccion_silenciosa_del_padron_se_detecta(tmp_path, cfg):
    # producción registró 5063 (corrigió "0063") pero el modelo lee 0063 → sistema_distinto
    rutas, infos, cal, hs = _preparar(tmp_path, cfg, [("lateral/20261118_100000_000_5063_t4.jpg", placa("0063"))])
    dec = seleccionar(infos, cal, hs, {str(rutas[0]): pred_de("0063")}, DIG, cfg["seleccion"],
                      cfg["calidad"], padron={"5063"})
    assert dec[0].decision == REVISAR and "sistema_distinto" in dec[0].razones


def test_mala_calidad_se_descarta(tmp_path, cfg):
    borrosa = cv2.GaussianBlur(placa(), (31, 31), 15)
    rutas, infos, cal, hs = _preparar(tmp_path, cfg, [("lateral/20261118_100000_000_unk_t5.jpg", borrosa)])
    dec = seleccionar(infos, cal, hs, None, DIG, cfg["seleccion"], cfg["calidad"])
    assert dec[0].decision == DESCARTAR and dec[0].razones[0].startswith("mala_calidad")


def test_sin_modelo_funciona(tmp_path, cfg):
    cfg["seleccion"]["porc_faciles"] = 1.0
    archivos = [(f"lateral/20261118_1000{k:02d}_000_5051_t{k}.jpg", placa("5051", semilla=k)) for k in range(4)]
    rutas, infos, cal, hs = _preparar(tmp_path, cfg, archivos)
    dec = seleccionar(infos, cal, hs, None, DIG, cfg["seleccion"], cfg["calidad"])
    r = resumen(dec)
    assert r["total"] == 4 and r["conservar"] == 4 and r["pasadas"] == 4


def test_tope_total(tmp_path, cfg):
    cfg["seleccion"].update({"porc_faciles": 1.0, "max_total": 2})
    archivos = [(f"lateral/20261118_1000{k:02d}_000_5051_t{k}.jpg", placa("5051", semilla=k)) for k in range(5)]
    rutas, infos, cal, hs = _preparar(tmp_path, cfg, archivos)
    dec = seleccionar(infos, cal, hs, None, DIG, cfg["seleccion"], cfg["calidad"])
    assert sum(d.decision != DESCARTAR for d in dec) == 2


# ── lote para Roboflow ────────────────────────────────────────────────────────
def test_escribir_lote(tmp_path, cfg):
    archivos = [("lateral/20261118_100000_000_5051_t1.jpg", placa("5051")),
                ("delantero/20261118_100000_000_5051_t1.jpg", placa("5051", fondo=170))]  # mismo nombre
    rutas, infos, cal, hs = _preparar(tmp_path, cfg, archivos)
    preds = {str(r): pred_de("5051", conf=0.4) for r in rutas}
    dec = seleccionar(infos, cal, hs, preds, DIG, cfg["seleccion"], cfg["calidad"], padron={"5051"})
    man = escribir_lote(dec, preds, tmp_path / "lote", DIG, {"pesos": "v3.pt"})
    imgs = sorted((tmp_path / "lote" / "images").iterdir())
    assert len(imgs) == 2 and imgs[0].name != imgs[1].name
    lbl = (tmp_path / "lote" / "labels" / (imgs[0].stem + ".txt")).read_text().splitlines()
    assert len(lbl) == 4 and len(lbl[0].split()) == 5          # sin conf: formato de etiqueta
    assert yaml.safe_load((tmp_path / "lote" / "data.yaml").read_text())["names"] == DIG
    assert (tmp_path / "lote" / "resumen.csv").exists()
    assert man["pesos"] == "v3.pt" and man["resumen"]["total"] == 2
