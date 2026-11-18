"""
ml/linea_virtual.py
================================================================
Línea virtual (polilínea FINITA): decide de qué lado está el bus,
detecta el cruce, distingue entrada/salida y filtra maniobras.

La línea ya no es una recta infinita entre P1 y P2: es una
polilínea con varios puntos (LINEA_PUNTOS en config.py) que
termina en su primer y último punto. Un cambio de lado solo
cuenta como cruce si la trayectoria del camión atraviesa de
verdad algún tramo de la línea; si el camión la "rodea" por un
extremo, no se registra nada.

Si las entradas/salidas salen invertidas o no se detecta el
cruce, el problema (o las coordenadas de LINEA_PUNTOS) está aquí.
================================================================
"""
import math
import threading

import config as _cfg
from config import LADO_ENTRADA, MANIOBRA_SEG, DEBOUNCE_SEG, MARGEN_LINEA_PX

# ── Geometría de la línea ─────────────────────────────────────
# LINEA_PUNTOS = [(x, y), (x, y), ...] en píxeles del frame.
# Si no existe, se usa la línea vieja LINEA_P1 → LINEA_P2.
LINEA_PUNTOS = [tuple(map(float, p)) for p in
                (getattr(_cfg, 'LINEA_PUNTOS', None)
                 or [_cfg.LINEA_P1, _cfg.LINEA_P2])]
if len(LINEA_PUNTOS) < 2:
    raise ValueError("LINEA_PUNTOS necesita al menos 2 puntos")

# Tolerancia (px) para alargar un poco cada extremo de la línea.
# 0 = la línea termina exactamente en el primer/último punto.
LINEA_EXTENSION_PX = float(getattr(_cfg, 'LINEA_EXTENSION_PX', 0))


LINEA_PUNTO_BUS = getattr(_cfg, 'LINEA_PUNTO_BUS', 'centro')


def punto_bus(bus):
    """Punto del camión que se compara con la línea (ver LINEA_PUNTO_BUS)."""
    if LINEA_PUNTO_BUS == 'abajo':
        x1, _, x2, y2 = bus["bbox"]
        return (x1 + x2) // 2, y2
    return bus["cx"], bus["cy"]


def _extender(p, q, px):
    """Devuelve q movido `px` píxeles más allá, en la dirección p → q."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    L = math.hypot(dx, dy) or 1.0
    return (q[0] + dx / L * px, q[1] + dy / L * px)


def _construir_puntos_limite():
    pts = list(LINEA_PUNTOS)
    if LINEA_EXTENSION_PX > 0:
        pts[0]  = _extender(pts[1], pts[0], LINEA_EXTENSION_PX)
        pts[-1] = _extender(pts[-2], pts[-1], LINEA_EXTENSION_PX)
    return pts


_PUNTOS_LIMITE = _construir_puntos_limite()
_SEGMENTOS     = list(zip(_PUNTOS_LIMITE[:-1], _PUNTOS_LIMITE[1:]))


def _info_segmento(cx, cy, p, q):
    """(distancia al tramo, producto cruz) para el punto (cx, cy)."""
    (x1, y1), (x2, y2) = p, q
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy or 1.0
    t  = max(0.0, min(1.0, ((cx - x1) * dx + (cy - y1) * dy) / L2))
    dist = math.hypot(cx - (x1 + t * dx), cy - (y1 + t * dy))
    cruz = dx * (cy - y1) - dy * (cx - x1)
    return dist, cruz


def _tramo_cercano(cx, cy):
    return min((_info_segmento(cx, cy, p, q) for p, q in _SEGMENTOS),
               key=lambda r: r[0])


def lado_actual(cx, cy):
    """Lado respecto al tramo más cercano (misma convención que antes)."""
    _, cruz = _tramo_cercano(cx, cy)
    return 'izquierda' if cruz > 0 else 'derecha'


def distancia_linea(cx, cy):
    """Distancia (px) del centro del camión a la línea (finita)."""
    return _tramo_cercano(cx, cy)[0]


def _orient(a, b, c):
    v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (v > 0) - (v < 0)


def _se_cortan(a, b, c, d):
    """¿El segmento a-b corta al segmento c-d?"""
    o1, o2 = _orient(a, b, c), _orient(a, b, d)
    o3, o4 = _orient(c, d, a), _orient(c, d, b)
    if o1 != o2 and o3 != o4:
        return True

    def _sobre(p, q, r):  # r colineal y dentro de p-q
        return (min(p[0], q[0]) <= r[0] <= max(p[0], q[0]) and
                min(p[1], q[1]) <= r[1] <= max(p[1], q[1]))
    return ((o1 == 0 and _sobre(a, b, c)) or (o2 == 0 and _sobre(a, b, d)) or
            (o3 == 0 and _sobre(c, d, a)) or (o4 == 0 and _sobre(c, d, b)))


def cruza_linea(desde, hasta):
    """True si el movimiento desde → hasta atraviesa algún tramo de la línea."""
    return any(_se_cortan(desde, hasta, p, q) for p, q in _SEGMENTOS)


def dibujar_linea(frame, color=(0, 255, 0), grosor=3):
    """Dibuja la polilínea sobre el frame (sustituye al cv2.line de P1→P2)."""
    import cv2
    import numpy as np
    pts = np.array(LINEA_PUNTOS, dtype=np.int32).reshape(-1, 1, 2)
    cv2.polylines(frame, [pts], isClosed=False, color=color, thickness=grosor)
    return frame


# ── Estado de los tracks ──────────────────────────────────────
_estado_tracks = {}
_debounce_nums = {}
_tracks_lock   = threading.Lock()


def evaluar_cruce(track_id, cx, cy, numero, timestamp):
    lado = lado_actual(cx, cy)
    tid  = str(track_id)

    with _tracks_lock:
        if tid not in _estado_tracks:
            _estado_tracks[tid] = {
                'lado': lado, 'pos': (cx, cy), 'ultimo_cruce': None,
                'numero': numero, 'eventos': []
            }
            print(f"[CRUCE] track={track_id} primer avistamiento — lado inicial={lado}")
            return None

        estado_t = _estado_tracks[tid]
        if numero and not estado_t['numero']:
            estado_t['numero'] = numero

        if distancia_linea(cx, cy) < MARGEN_LINEA_PX:
            return None        # dentro del margen: todavía no cambia de lado

        if lado == estado_t['lado']:
            estado_t['pos'] = (cx, cy)   # última posición "segura" de este lado
            return None

        lado_anterior    = estado_t['lado']
        pos_anterior     = estado_t.get('pos')
        estado_t['lado'] = lado
        estado_t['pos']  = (cx, cy)

        # Línea finita: el cambio de lado solo cuenta si la trayectoria
        # atraviesa la línea; si la rodeó por un extremo, se ignora.
        if pos_anterior is not None and not cruza_linea(pos_anterior, (cx, cy)):
            print(f"[FUERA] track={track_id} n={numero} — cambió de lado "
                  f"fuera de los límites de la línea, no cuenta")
            return None

        if estado_t['ultimo_cruce'] is not None:
            elapsed = timestamp - estado_t['ultimo_cruce']
            if elapsed < MANIOBRA_SEG:
                print(f"[MANIOBRA] track={track_id} n={numero} — regreso en {elapsed:.1f}s")
                estado_t['ultimo_cruce'] = timestamp
                return 'maniobra'

        estado_t['ultimo_cruce'] = timestamp
        direccion = 'salida' if lado_anterior == LADO_ENTRADA else 'entrada'
        print(f"[CRUCE] track={track_id} n={numero} — {lado_anterior} → {lado} = {direccion.upper()}")

        num_key = numero or f'track_{track_id}'
        ultimo  = _debounce_nums.get(num_key, 0)
        if timestamp - ultimo < DEBOUNCE_SEG:
            print(f"[DEBOUNCE] {num_key} — {int(timestamp-ultimo)}s < {DEBOUNCE_SEG}s")
            return None
        _debounce_nums[num_key] = timestamp

        estado_t['eventos'].append({
            'track_id':  track_id,
            'numero':    numero or '???',
            'direccion': direccion,
            'timestamp': timestamp,
        })
        return direccion


def olvidar(track_id, ahora):
    """Borra un camión que ya no se ve y los bloqueos (debounce) ya vencidos."""
    with _tracks_lock:
        _estado_tracks.pop(str(track_id), None)
        for k in [k for k, t in _debounce_nums.items() if ahora - t > DEBOUNCE_SEG]:
            del _debounce_nums[k]


def reasociar_numero(numero, track_id):
    tid = str(track_id)
    with _tracks_lock:
        for prev_tid, estado_t in _estado_tracks.items():
            if prev_tid != tid and estado_t.get('numero') == numero:
                if tid not in _estado_tracks:
                    _estado_tracks[tid] = {
                        'lado':         estado_t['lado'],
                        'pos':          estado_t.get('pos'),
                        'ultimo_cruce': estado_t['ultimo_cruce'],
                        'numero':       numero,
                        'eventos':      estado_t['eventos'],
                    }
                    print(f"[REASOC] track {prev_tid} → {track_id} ({numero})")
                break
