"""
ml/linea_virtual.py
================================================================
Línea virtual diagonal: decide de qué lado está el bus, detecta
el cruce, distingue entrada/salida y filtra maniobras.
Si las entradas/salidas salen invertidas o no se detecta el
cruce, el problema (o las coordenadas LINEA_P1/P2) está aquí.

================================================================
"""
import threading

from config import LINEA_P1, LINEA_P2, LADO_ENTRADA, MANIOBRA_SEG, DEBOUNCE_SEG

_estado_tracks = {}
_debounce_nums = {}
_tracks_lock   = threading.Lock()


def lado_actual(cx, cy):
    x1, y1 = LINEA_P1
    x2, y2 = LINEA_P2
    cruz = (x2 - x1) * (cy - y1) - (y2 - y1) * (cx - x1)
    return 'izquierda' if cruz > 0 else 'derecha'


def evaluar_cruce(track_id, cx, cy, numero, timestamp):
    lado = lado_actual(cx, cy)
    tid  = str(track_id)

    with _tracks_lock:
        if tid not in _estado_tracks:
            _estado_tracks[tid] = {
                'lado': lado, 'ultimo_cruce': None,
                'numero': numero, 'eventos': []
            }
            print(f"[CRUCE] track={track_id} primer avistamiento — lado inicial={lado}")
            return None

        estado_t = _estado_tracks[tid]
        if numero and not estado_t['numero']:
            estado_t['numero'] = numero

        if lado == estado_t['lado']:
            return None

        lado_anterior   = estado_t['lado']
        estado_t['lado'] = lado

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


def reasociar_numero(numero, track_id):
    tid = str(track_id)
    with _tracks_lock:
        for prev_tid, estado_t in _estado_tracks.items():
            if prev_tid != tid and estado_t.get('numero') == numero:
                if tid not in _estado_tracks:
                    _estado_tracks[tid] = {
                        'lado':         estado_t['lado'],
                        'ultimo_cruce': estado_t['ultimo_cruce'],
                        'numero':       numero,
                        'eventos':      estado_t['eventos'],
                    }
                    print(f"[REASOC] track {prev_tid} → {track_id} ({numero})")
                break