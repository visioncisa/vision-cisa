from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from reentrenamiento import calidad, redundancia
from reentrenamiento.nombres import leer_grabacion, leer_recorte, limpiar_stem
from conftest import placa


# ── nombres ───────────────────────────────────────────────────────────────────
def test_recorte_de_numero_como_lo_guarda_produccion():
    i = leer_recorte(Path("crops/delantero/20261015_133952_289_505_t9.jpg"))
    assert i.momento == datetime(2026, 10, 15, 13, 39, 52, 289000)
    assert (i.numero_sistema, i.track, i.zona) == ("505", 9, "delantero")
    assert i.clave_pasada() == "delantero:20261015:t9"


def test_recorte_sin_lectura_unk():
    i = leer_recorte(Path("lateral/20261118_041500_007_unk_t120.jpg"))
    assert i.numero_sistema is None and i.track == 120 and i.zona == "lateral"


def test_recorte_de_autobus():
    i = leer_recorte(Path("autobus/20261118_041500_007_t3.jpg"))
    assert i.track == 3 and i.zona == "autobus" and i.numero_sistema is None


def test_nombre_renombrado_por_roboflow():
    assert limpiar_stem("20261015_133952_289_505_t9_jpg.rf.a1b2c3d4e5.jpg") == "20261015_133952_289_505_t9"
    i = leer_recorte(Path("x/20261015_133952_289_505_t9_jpg.rf.a1b2c3d4e5.jpg"))
    assert i.track == 9 and i.numero_sistema == "505"


def test_nombre_desconocido_no_truena():
    i = leer_recorte(Path("foto_cualquiera.jpg"))
    assert i.track is None and i.momento is None
    assert i.clave_pasada().startswith("suelto:")


def test_grabacion():
    g = leer_grabacion(Path("cam1_20261115_170001.mp4"))
    assert g.camara == "cam1" and g.inicio == datetime(2026, 11, 15, 17, 0, 1)
    assert leer_grabacion(Path("otro.mp4")) is None


# ── calidad ───────────────────────────────────────────────────────────────────
def test_nitida_mas_que_borrosa(cfg):
    nitida = placa()
    borrosa = cv2.GaussianBlur(nitida, (15, 15), 6)
    assert calidad.medir(nitida, cfg["calidad"]).nitidez > 3 * calidad.medir(borrosa, cfg["calidad"]).nitidez


def test_problemas_de_calidad(cfg):
    u = cfg["calidad"]
    negra = np.full((60, 160, 3), 5, np.uint8)
    assert "oscura" in calidad.problemas(calidad.medir(negra, u), u)
    chica = placa(ancho=40, alto=12)
    assert "pequena" in calidad.problemas(calidad.medir(chica, u), u)
    muy_borrosa = cv2.GaussianBlur(placa(), (31, 31), 15)
    assert "borrosa" in calidad.problemas(calidad.medir(muy_borrosa, u), u)
    assert calidad.problemas(calidad.medir(placa(), u), u) == []
    assert calidad.problemas(None, u) == ["ilegible"]


def test_luz(cfg):
    u = cfg["calidad"]
    assert calidad.medir(placa(), u).luz == "dia"
    noche = (placa() * 0.3).astype(np.uint8)
    assert calidad.medir(noche, u).luz == "noche"
    contraluz = np.zeros((60, 160, 3), np.uint8)
    contraluz[:, :50] = 255
    assert calidad.medir(contraluz, u).luz == "contraluz"


def test_leer_imagen_inexistente(tmp_path):
    assert calidad.leer_imagen(tmp_path / "no.jpg") is None


# ── redundancia ───────────────────────────────────────────────────────────────
def test_hash_iguales_parecidas_distintas():
    a = placa("5051")
    for f in (redundancia.dhash, redundancia.phash):
        assert redundancia.distancia(f(a), f(a.copy())) == 0
        assert redundancia.distancia(f(a), f(placa("5051", desplazar=1))) <= 8
        assert redundancia.distancia(f(a), f(placa("0063", fondo=120, desplazar=20))) > 8


def test_agrupar_pasadas_por_track_y_ventana():
    nombres = [
        "lateral/20261118_100000_000_5051_t1.jpg",
        "lateral/20261118_100001_000_5051_t1.jpg",
        "lateral/20261118_100003_000_5051_t1.jpg",
        "lateral/20261118_100030_000_5051_t1.jpg",   # mismo track, 27 s después: otra pasada
        "lateral/20261118_100001_000_544_t2.jpg",    # otro track
        "delantero/20261118_100001_000_5051_t1.jpg", # otra zona
        "suelta.jpg",
    ]
    grupos = redundancia.agrupar_pasadas([leer_recorte(Path(n)) for n in nombres], ventana_seg=6)
    tamanos = sorted(len(g) for g in grupos)
    assert tamanos == [1, 1, 1, 1, 3]


def test_quitar_repetidas():
    h = redundancia.dhash
    lista = [("a", h(placa("5051"))), ("b", h(placa("5051"))), ("c", h(placa("0063", fondo=120, desplazar=20)))]
    conservadas, repetidas = redundancia.quitar_repetidas(lista, dist_min=6)
    assert conservadas == ["a", "c"] and repetidas == {"b": "a"}
