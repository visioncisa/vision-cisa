"""
Pruebas de la línea virtual: geometría, extremos y estados del cruce.

No necesitan cámara, Jetson, OpenCV ni la base de datos: se sustituye el
módulo config por uno de prueba y se recarga ml/linea_virtual.py.

Se corren desde la raíz del proyecto:

    python3 -m pytest tests/ -v
"""
import sys
import types

import pytest

# Línea real configurada para la cámara Full HD (LINEA_PUNTOS del .env)
PUNTOS_CAMARA = [(93, 684), (1615, 1060)]


def cargar(**cambios):
    """Importa ml/linea_virtual.py con una configuración de prueba."""
    valores = dict(
        LINEA_P1=(280, 250),
        LINEA_P2=(500, 479),
        LINEA_PUNTOS=list(PUNTOS_CAMARA),
        LINEA_EXTENSION_PX=0,
        LINEA_PUNTO_BUS='abajo',
        LADO_ENTRADA='izquierda',
        MANIOBRA_SEG=20,
        DEBOUNCE_SEG=60,
        MARGEN_LINEA_PX=30,
    )
    valores.update(cambios)

    cfg = types.ModuleType('config')
    for nombre, valor in valores.items():
        setattr(cfg, nombre, valor)
    sys.modules['config'] = cfg
    sys.modules.pop('ml.linea_virtual', None)

    import ml.linea_virtual as lv
    return lv


def evaluar(lv, puntos, tid=1, numero='5001', t0=1000, dt=1):
    """Pasa una trayectoria por evaluar_cruce y devuelve los eventos."""
    eventos = []
    for i, (x, y) in enumerate(puntos):
        r = lv.evaluar_cruce(tid, x, y, numero, t0 + i * dt)
        if r:
            eventos.append(r)
    return eventos


def test_entrada():
    lv = cargar()
    # Viene de la calle (arriba de la línea) y entra al patio
    assert evaluar(lv, [(700, 700), (700, 780), (700, 840), (700, 900)]) == ['entrada']


def test_salida():
    lv = cargar()
    assert evaluar(lv, [(700, 900), (700, 840), (700, 780), (700, 700)]) == ['salida']


def test_rodea_el_extremo_izquierdo_no_cuenta():
    lv = cargar()
    # Cambia de lado por fuera del primer punto (x < 93): no hay cruce
    assert evaluar(lv, [(40, 600), (40, 750)]) == []


def test_detenido_sobre_la_linea_no_cuenta():
    lv = cargar()
    # Temblor de la detección dentro del margen de 30 px
    assert evaluar(lv, [(800, 855), (800, 865), (800, 852), (800, 870)]) == []


def test_entra_y_regresa_es_maniobra():
    lv = cargar()
    eventos = evaluar(lv, [(700, 780), (700, 900), (700, 780)], dt=5)
    assert eventos == ['entrada', 'maniobra']


def test_mismo_numero_dos_veces_lo_filtra_el_debounce():
    lv = cargar()
    assert evaluar(lv, [(700, 780), (700, 900)], tid=1, t0=1000) == ['entrada']
    # Otro track del mismo número sale 20 s después: lo bloquea el debounce
    assert evaluar(lv, [(700, 900), (700, 780)], tid=2, numero='5001', t0=1020) == []


def test_cruce_de_una_polilinea_de_varios_puntos():
    lv = cargar(LINEA_PUNTOS=[(93, 684), (800, 850), (1615, 1060)])
    assert evaluar(lv, [(800, 790), (800, 900)]) == ['entrada']


@pytest.mark.parametrize('a,b,c,d,esperado', [
    ((0, 0), (10, 10), (0, 10), (10, 0), True),
    ((0, 0), (5, 0), (0, 10), (10, 10), False),
    ((0, 0), (10, 0), (5, 0), (5, 10), True),
])
def test_segmentos_se_cortan(a, b, c, d, esperado):
    lv = cargar()
    assert lv._se_cortan(a, b, c, d) is esperado


# ── Extremo derecho: limitación conocida, documentada ────────────────────────
def test_extremo_derecho_queda_dentro_del_margen():
    """A x=1580 la base del recuadro no logra alejarse 30 px de la línea
    (el punto final está a 20 px del borde inferior del cuadro)."""
    lv = cargar()
    assert evaluar(lv, [(1580, 900), (1580, 1070)]) == []


# ── Compatibilidad con instalaciones que no actualizaron el .env ─────────────
def test_sin_linea_puntos_se_comporta_como_recta_infinita():
    """Sin LINEA_PUNTOS se conserva el comportamiento anterior: un cruce
    lejos del tramo configurado sigue contando."""
    lv = cargar(LINEA_PUNTOS=[])
    assert lv.LINEA_FINITA is False
    # Cruza la prolongación de (280,250)-(500,479) en x=1200, fuera del tramo
    assert evaluar(lv, [(1200, 1150), (1200, 1300)]) == ['entrada']


def test_con_linea_puntos_un_cruce_lejos_no_cuenta():
    lv = cargar()
    assert lv.LINEA_FINITA is True
    assert evaluar(lv, [(1200, 1150), (1200, 1300)]) == []


def test_aviso_de_resolucion():
    lv = cargar()
    assert lv.revisar_resolucion(1920, 1080) is True
    # Coordenadas de Full HD sobre el video de prueba 704x480
    assert lv.revisar_resolucion(704, 480) is False
