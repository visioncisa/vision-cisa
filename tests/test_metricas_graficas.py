"""
Pruebas de las gráficas del tablero (metricas/metricas.py).

Problema que cubren: las gráficas "Semana" y "Mes" se armaban con los
5,000 cruces más recientes (storage.leer_eventos). Con unos 250 cruces
por día, 28 días son ~7,000 cruces, así que la gráfica "Mes" perdía las
semanas más viejas sin avisar. Ahora los conteos por día salen de la base
(storage.flujo_por_dia) y no tienen límite.

No necesitan PostgreSQL: se sustituyen config y metricas/storage por
módulos de prueba.

Se corren desde la raíz del proyecto:

    python -m pytest tests/ -v
"""
import sys
import types
import datetime as dt
from pathlib import Path

import pytest

HORA_CORTE = 3


def _dia_operativo(momento=None):
    return ((momento or dt.datetime.now()) - dt.timedelta(hours=HORA_CORTE)).date()


def cargar(por_dia=None, eventos_hoy=None):
    """Importa metricas/metricas.py con config y storage de prueba.

    Devuelve (metricas, llamadas): `llamadas` registra con qué fechas se
    pidió storage.flujo_por_dia().
    """
    cfg = types.ModuleType("config")
    cfg.HORA_CORTE_DIA = HORA_CORTE
    cfg.UNIDADES_INFO = {"5001": {"empresa": "CCA"}, "7001": {"empresa": "COPATTSA"}}
    cfg.FRAMES_DIR = Path(".")
    sys.modules["config"] = cfg

    llamadas = []
    st = types.ModuleType("metricas.storage")
    st.dia_operativo = _dia_operativo

    def flujo_por_dia(inicio, fin):
        llamadas.append((inicio, fin))
        return {d: c for d, c in (por_dia or {}).items() if inicio <= d <= fin}

    def leer_eventos(limite=5000):
        raise AssertionError("el tablero ya no debe depender de leer_eventos()")

    st.flujo_por_dia = flujo_por_dia
    st.leer_eventos = leer_eventos
    st.eventos_de_hoy = lambda: list(eventos_hoy or [])
    st.total_acumulado = lambda: 9999
    st.ultima = lambda: None
    st.flujo_por_anio = lambda: []
    sys.modules["metricas.storage"] = st
    sys.modules.pop("metricas.metricas", None)

    import metricas
    metricas.storage = st
    import metricas.metricas as m
    return m, llamadas


def _ev(hora, direccion, numero="5001", empresa="CCA", zona="Delantero"):
    return {"ts": hora.timestamp(), "direccion": direccion, "numero": numero,
            "empresa": empresa, "zona": zona}


# ── Funciones puras de las gráficas ──────────────────────────────────────────

def test_semana_cuenta_los_ultimos_7_dias_en_orden():
    m, _ = cargar()
    hoy = dt.date(2026, 11, 19)                       # jueves
    por_dia = {hoy - dt.timedelta(days=i): {"entradas": i + 1, "salidas": 10 * (i + 1)}
               for i in range(7)}
    r = m._flujo_por_semana(por_dia, hoy)
    assert r["horas"] == ["Vie", "Sáb", "Dom", "Lun", "Mar", "Mié", "Jue"]
    assert r["entradas"] == [7, 6, 5, 4, 3, 2, 1]
    assert r["salidas"] == [70, 60, 50, 40, 30, 20, 10]


def test_semana_con_dias_sin_cruces_pone_cero():
    m, _ = cargar()
    hoy = dt.date(2026, 11, 19)
    r = m._flujo_por_semana({hoy: {"entradas": 3, "salidas": 1}}, hoy)
    assert r["entradas"] == [0, 0, 0, 0, 0, 0, 3]
    assert r["salidas"] == [0, 0, 0, 0, 0, 0, 1]


def test_mes_agrupa_28_dias_en_4_semanas():
    m, _ = cargar()
    hoy = dt.date(2026, 11, 19)
    por_dia = {hoy - dt.timedelta(days=i): {"entradas": 10, "salidas": 20} for i in range(28)}
    r = m._flujo_por_mes(por_dia, hoy)
    assert r["horas"] == ["S1", "S2", "S3", "S4"]
    assert r["entradas"] == [70, 70, 70, 70]
    assert r["salidas"] == [140, 140, 140, 140]


def test_mes_ignora_dias_fuera_de_las_4_semanas():
    m, _ = cargar()
    hoy = dt.date(2026, 11, 19)
    por_dia = {hoy - dt.timedelta(days=28): {"entradas": 99, "salidas": 99},   # día 29: fuera
               hoy - dt.timedelta(days=27): {"entradas": 1, "salidas": 0},     # primer día de S1
               hoy: {"entradas": 0, "salidas": 2}}
    r = m._flujo_por_mes(por_dia, hoy)
    assert r["entradas"] == [1, 0, 0, 0]
    assert r["salidas"] == [0, 0, 0, 2]


# ── Tablero completo ─────────────────────────────────────────────────────────

def test_tablero_no_depende_del_limite_de_5000_cruces():
    """28 días con 250 cruces diarios = 7,000 cruces: la semana más vieja
    tiene que salir completa (antes quedaba recortada)."""
    hoy = _dia_operativo()
    por_dia = {hoy - dt.timedelta(days=i): {"entradas": 125, "salidas": 125} for i in range(28)}
    m, llamadas = cargar(por_dia=por_dia)
    d = m.datos_dashboard()
    assert d["por_mes"]["entradas"] == [875, 875, 875, 875]
    assert d["por_mes"]["salidas"] == [875, 875, 875, 875]
    assert llamadas == [(hoy - dt.timedelta(days=27), hoy)]


def test_tablero_detecciones_de_ayer_salen_del_conteo_por_dia():
    hoy = _dia_operativo()
    ayer = hoy - dt.timedelta(days=1)
    m, _ = cargar(por_dia={ayer: {"entradas": 150, "salidas": 163}})
    assert m.datos_dashboard()["detecciones_ayer"] == 313


def test_tablero_datos_de_hoy_salen_de_los_eventos_de_hoy():
    hoy = _dia_operativo()
    mediodia = dt.datetime.combine(hoy, dt.time(12, 0))
    eventos = [_ev(mediodia, "entrada"),
               _ev(mediodia + dt.timedelta(minutes=5), "salida"),
               _ev(mediodia + dt.timedelta(minutes=9), "salida", numero="7001", empresa="COPATTSA")]
    m, _ = cargar(eventos_hoy=eventos)
    d = m.datos_dashboard()
    assert d["detecciones_hoy"] == 3
    assert (d["entradas"], d["salidas"]) == (1, 2)
    assert d["por_empresa"]["CCA"] == 2 and d["por_empresa"]["COPATTSA"] == 1
    i = d["por_hora"]["horas"].index("12")
    assert (d["por_hora"]["entradas"][i], d["por_hora"]["salidas"][i]) == (1, 2)
    assert d["top_unidades"][0] == {"numero": "5001", "empresa": "CCA", "count": 2}
