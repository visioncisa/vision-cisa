"""
metricas/metricas.py
================================================================
LÓGICA de métricas para el dashboard.
Los datos que consumen las gráficas, pero NO sabe dónde se
guardan: solo habla con metricas/storage.py. Por eso, cuando
conectes la base de datos, este archivo no se toca.

Si una detección no aparece en el dashboard o un número sale mal
clasificado por empresa, el problema está aquí o en storage.py.

── DÍA OPERATIVO ───────────────────────────────────────────────
Mismo criterio que storage.py: el patio tiene turno nocturno
(entradas ~23:00, movimiento hasta 1-2am). Se usa HORA_CORTE_DIA
como frontera del "día" en vez de la medianoche del calendario,
para no partir el turno nocturno en dos. Ver storage.py para más
detalle.
─────────────────────────────────────────────────────────────────
"""
import time
import datetime as _dt

from config import HORA_CORTE_DIA
from metricas import storage

_DIAS_ES  = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
_MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
             "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


# El día operativo tiene una sola implementación: storage.dia_operativo()
_dia_operativo = storage.dia_operativo


def cargar():
    """Se llama una vez al arrancar (pipe_stream_v2.py). Ya no carga el
    histórico completo en memoria: cada consulta lee de la base."""
    return None


def registrar_deteccion(numero, direccion, zona_raw, conf, frame_name=None):
    """Se llama 1 vez por alerta confirmada. Nunca debe romper el pipeline."""
    try:
        ev = {
            "numero":    str(numero) if numero else None,
            "zona":      zona_raw,          # código del modelo; storage guarda el código
            "direccion": direccion,
            "conf":      round(float(conf or 0), 3),
            "ts":        float(time.time()),
            "frame":     str(frame_name) if frame_name else None,
        }
        storage.guardar_evento(ev)
    except Exception as e:
        print(f"[METRICAS] registrar error: {e}")


def ultima():
    """Última detección (para /api/estado)."""
    return storage.ultima()


# ════════════════════════════════════════════════════════════
# Agregaciones por periodo — Día / Semana / Mes / Año
# ════════════════════════════════════════════════════════════

def _flujo_por_hora(eventos, hoy_operativo):
    """
    Conteo entradas/salidas por hora del día operativo actual.
    El eje empieza en HORA_CORTE_DIA y da la vuelta, para que el
    turno nocturno se vea como una franja continua en vez de
    partido en los dos extremos de la gráfica.
    """
    horas_orden = [f"{h:02d}" for h in
                   list(range(HORA_CORTE_DIA, 24)) + list(range(0, HORA_CORTE_DIA))]
    flujo = {h: {"entradas": 0, "salidas": 0} for h in horas_orden}

    for ev in eventos:
        dt = _dt.datetime.fromtimestamp(ev["ts"])
        if _dia_operativo(dt) != hoy_operativo:
            continue
        hk = f"{dt.hour:02d}"
        if hk in flujo and ev["direccion"] in ("entrada", "salida"):
            flujo[hk][ev["direccion"] + "s"] += 1

    return {
        "horas":    horas_orden,
        "entradas": [flujo[h]["entradas"] for h in horas_orden],
        "salidas":  [flujo[h]["salidas"]  for h in horas_orden],
    }


def _flujo_por_semana(eventos, hoy_operativo):
    """Últimos 7 días operativos, en orden cronológico (el más viejo primero)."""
    dias = [hoy_operativo - _dt.timedelta(days=i) for i in range(6, -1, -1)]
    flujo = {d: {"entradas": 0, "salidas": 0} for d in dias}

    for ev in eventos:
        dt = _dt.datetime.fromtimestamp(ev["ts"])
        d  = _dia_operativo(dt)
        if d in flujo and ev["direccion"] in ("entrada", "salida"):
            flujo[d][ev["direccion"] + "s"] += 1

    labels = [_DIAS_ES[d.weekday()] for d in dias]
    return {
        "horas":    labels,
        "entradas": [flujo[d]["entradas"] for d in dias],
        "salidas":  [flujo[d]["salidas"]  for d in dias],
    }


def _flujo_por_mes(eventos, hoy_operativo):
    """
    Últimas 4 semanas (28 días operativos) agrupadas en buckets de 7
    días: S1 = hace 22-28 días … S4 = últimos 7 días (incluye hoy).
    """
    inicio = hoy_operativo - _dt.timedelta(days=27)
    buckets = [{"entradas": 0, "salidas": 0} for _ in range(4)]

    for ev in eventos:
        dt = _dt.datetime.fromtimestamp(ev["ts"])
        d  = _dia_operativo(dt)
        if d < inicio or d > hoy_operativo:
            continue
        idx = min(3, (d - inicio).days // 7)
        if ev["direccion"] in ("entrada", "salida"):
            buckets[idx][ev["direccion"] + "s"] += 1

    labels = ["S1", "S2", "S3", "S4"]
    return {
        "horas":    labels,
        "entradas": [b["entradas"] for b in buckets],
        "salidas":  [b["salidas"]  for b in buckets],
    }


def _flujo_por_anio():
    """
    Últimos 12 meses calendario, en orden cronológico.

    A diferencia de _flujo_por_hora/semana/mes (que trabajan sobre
    los `eventos` ya cargados en memoria vía leer_eventos()), este
    usa storage.flujo_por_anio() que agrega DIRECTO EN SQL sobre toda
    la tabla — leer_eventos() solo trae ~5,000 filas recientes, que
    no alcanzan para cubrir un año completo con el volumen actual.
    """
    meses = storage.flujo_por_anio()
    return {
        "horas":    [_MESES_ES[m["mes"] - 1] for m in meses],
        "entradas": [m["entradas"] for m in meses],
        "salidas":  [m["salidas"]  for m in meses],
    }


def datos_dashboard():
    """Arma el JSON completo del dashboard a partir de lo persistido."""
    now           = _dt.datetime.now()
    hoy_operativo = _dia_operativo(now)
    ayer_operativo = hoy_operativo - _dt.timedelta(days=1)

    eventos    = storage.leer_eventos()
    total_acum = storage.total_acumulado()
    u          = storage.ultima()

    det_hoy = det_ayer = entradas = salidas = 0
    por_empresa = {"CISA": 0, "COPATSA": 0, "CCISA": 0, "Desconocida": 0}
    por_zona    = {"Delantero": 0, "Trasero": 0, "Lateral": 0}
    unidades, horas_hoy = {}, set()

    for ev in eventos:
        dt = _dt.datetime.fromtimestamp(ev["ts"])
        d  = _dia_operativo(dt)
        if d == hoy_operativo:
            det_hoy += 1
            horas_hoy.add(dt.hour)
            if ev["direccion"] == "entrada": entradas += 1
            elif ev["direccion"] == "salida": salidas += 1
            por_empresa[ev["empresa"]] = por_empresa.get(ev["empresa"], 0) + 1
            por_zona[ev["zona"]]       = por_zona.get(ev["zona"], 0) + 1
            n = ev["numero"]
            if n:
                uu = unidades.setdefault(n, {"numero": n, "empresa": ev["empresa"], "count": 0})
                uu["count"] += 1
        elif d == ayer_operativo:
            det_ayer += 1

    promedio = round(det_hoy / max(1, len(horas_hoy)))
    top = sorted(unidades.values(), key=lambda x: x["count"], reverse=True)[:5]

    return {
        "detecciones_hoy":  det_hoy,
        "detecciones_ayer": det_ayer,
        "entradas":         entradas,
        "salidas":          salidas,
        "promedio_hora":    promedio,
        "total_acumulado":  total_acum,
        "telegram_hoy":     det_hoy,
        "ultima": ({
            "numero":     u["numero"],
            "empresa":    u["empresa"],
            "zona":       u["zona"],
            "movimiento": u["direccion"].capitalize(),
            "conf":       u["conf"],
            "ts":         _dt.datetime.fromtimestamp(u["ts"]).strftime("%H:%M:%S"),
        } if u else None),
        "por_hora":     _flujo_por_hora(eventos, hoy_operativo),
        "por_semana":   _flujo_por_semana(eventos, hoy_operativo),
        "por_mes":      _flujo_por_mes(eventos, hoy_operativo),
        "por_anio":     _flujo_por_anio(),
        "por_empresa":  por_empresa,
        "por_zona":     por_zona,
        "top_unidades": top,
    }


def detecciones_recientes(n=30):
    """Lista para el panel en vivo (/api/detecciones-recent)."""
    eventos = storage.leer_eventos(n)          # solo las que se muestran
    out = []
    for ev in reversed(eventos):
        out.append({
            "numero":    ev["numero"],
            "estado":    "VERIFICADO",
            "conf":      ev["conf"],
            "ts":        _dt.datetime.fromtimestamp(ev["ts"]).strftime("%Y-%m-%d %H:%M:%S"),
            "cls":       "numero_" + ev["zona"].lower(),
            "thumb_url": ("/thumb/" + ev["frame"]) if ev.get("frame") else None,
            "frame_url": ("/frames/" + ev["frame"]) if ev.get("frame") else None,
        })
    return out