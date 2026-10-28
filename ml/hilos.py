"""
ml/hilos.py
================================================================
Los dos hilos de visión que trabajan en paralelo:

  HiloM1   : detecta el autobús, lo trackea (ByteTrack), guarda
             el crop del bus y manda el frame a la cola.
  HiloM2M3 : lee la zona del número (M2), los dígitos (M3),
             acumula votos y decide el cruce. Cuando el camión cruza
             espera a que termine de pasar (ESPERA_FIN_SEG / ESPERA_MAX_SEG),
             elige el mejor número y lo registra UNA sola vez
             (validación Gemini/Telegram + registro en métricas).

Si un autobús se detecta mal, el OCR falla o no se confirma el
número, el problema está en este archivo (junto con modelos.py,
reconocimiento.py y linea_virtual.py).
================================================================
"""
import time
import queue
from collections import Counter, defaultdict
from datetime import datetime

import cv2

from config import (
    CONF_AUTOBUS, CONF_VISTA, N_VOTOS,
    PAD_RATIO, PAD_RATIO_LATERAL, DEBOUNCE_SEG, FRAMES_DIR,
    BBOX_MIN_POR_TIPO, BBOX_MIN_AUTOBUS,
    YOLO_FPS_MAX, ESPERA_FIN_SEG, ESPERA_MAX_SEG,
)
from logica import estado
from ml import modelos, reconocimiento, linea_virtual
from metricas import metricas
from alertas import validar_y_enviar, APROBADO, NO_CONFIRMADO, FALLBACK

# ── Cola entre M1 y M2M3 (solo la usan estos dos hilos) ───────────────────────
_m2_queue = queue.Queue(maxsize=1)

_last_m1_print = 0.0
_last_m2_print = 0.0
_LOG_INTERVAL  = 2.0


# ══════════════════════════════════════════════════════════════════════════════
# HILO M1 — Detección + ByteTrack + Crop del autobús completo
# ══════════════════════════════════════════════════════════════════════════════
class HiloM1:
    def __init__(self, cam):
        self.cam               = cam
        self.running           = True
        self._cnt              = 0
        self._t                = time.time()
        self._tracks_guardados = set()
        self._ultimo_frame     = -1    # número del último cuadro analizado
        self._t_ultimo         = 0.0

    def update(self):
        global _last_m1_print
        while self.running:
            # Solo cuadros nuevos (y no más de YOLO_FPS_MAX por segundo si está definido)
            with estado.state_lock:
                n_frame = estado.STATE["frame_count"]
            ahora_m1 = time.time()
            if n_frame == self._ultimo_frame or (
                    YOLO_FPS_MAX > 0 and ahora_m1 - self._t_ultimo < 1.0 / YOLO_FPS_MAX):
                time.sleep(0.005)
                continue
            self._ultimo_frame = n_frame
            self._t_ultimo     = ahora_m1

            frame = self.cam.get_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            try:
                self._cnt += 1
                elapsed = time.time() - self._t
                if elapsed >= 1.0:
                    with estado.state_lock:
                        estado.STATE["yolo_fps"] = round(self._cnt / elapsed, 1)
                    self._cnt = 0
                    self._t   = time.time()

                res_m1 = modelos.model_autobus.track(
                    frame,
                    conf    = CONF_AUTOBUS,
                    device  = 0,
                    verbose = False,
                    imgsz   = 640,
                    tracker = 'bytetrack.yaml',
                    persist = True,
                )

                ahora = time.time()
                if res_m1[0].boxes.id is not None:
                    ids   = res_m1[0].boxes.id.int().cpu().tolist()
                    confs = [round(float(c), 2) for c in res_m1[0].boxes.conf.cpu().tolist()]
                    if ahora - _last_m1_print >= _LOG_INTERVAL:
                        print(f"[M1] Autobús detectado — tracks={ids} confs={confs} "
                              f"cola_m2={_m2_queue.qsize()}")
                        _last_m1_print = ahora
                else:
                    if ahora - _last_m1_print >= _LOG_INTERVAL * 3:
                        print("[M1] Sin detección")
                        _last_m1_print = ahora
                    continue

                track_ids = res_m1[0].boxes.id.int().cpu().tolist()
                boxes_m1  = res_m1[0].boxes.xyxy.cpu().tolist()

                mejor_track = None
                mejor_area  = 0
                mejor_bbox  = None
                for (bx1, by1, bx2, by2), tid in zip(boxes_m1, track_ids):
                    bx1, by1, bx2, by2 = map(int, (bx1, by1, bx2, by2))
                    w_bus = bx2 - bx1
                    h_bus = by2 - by1
                    if w_bus < BBOX_MIN_AUTOBUS or h_bus < BBOX_MIN_AUTOBUS:
                        print(f"[M1] track={tid} descartado por tamaño ({w_bus}x{h_bus} < {BBOX_MIN_AUTOBUS})")
                        continue
                    area = w_bus * h_bus
                    if area > mejor_area:
                        mejor_area  = area
                        mejor_track = (tid, (bx1+bx2)//2, (by1+by2)//2)
                        mejor_bbox  = (bx1, by1, bx2, by2)

                if mejor_track is None:
                    print("[M1] Todos los autobuses descartados por tamaño mínimo")
                    continue

                track_id, cx, cy   = mejor_track
                bx1, by1, bx2, by2 = mejor_bbox

                if track_id not in self._tracks_guardados:
                    reconocimiento.guardar_crop_autobus(frame, bx1, by1, bx2, by2, track_id)
                    self._tracks_guardados.add(track_id)
                    print(f"[CROP BUS] track={track_id} guardado — bbox=({bx1},{by1},{bx2},{by2})")
                    if len(self._tracks_guardados) > 500:
                        self._tracks_guardados.clear()

                item = {"track_id": track_id, "cx": cx, "cy": cy,
                        "frame": frame.copy(), "ts": time.time()}
                try:
                    _m2_queue.put_nowait(item)
                except queue.Full:
                    try: _m2_queue.get_nowait()
                    except queue.Empty: pass
                    _m2_queue.put_nowait(item)

            except Exception as e:
                print(f"[M1 ERROR] {e}")
                time.sleep(0.05)

    def stop(self):
        self.running = False


# ══════════════════════════════════════════════════════════════════════════════
# HILO M2+M3 — Zona + Dígitos + Votación + Alertas
# ══════════════════════════════════════════════════════════════════════════════
class HiloM2M3:
    def __init__(self):
        self.running         = True
        self.mejor_frame     = None
        self.mejor_conf      = 0.0
        self.mejor_bbox_area = 0
        self.mejor_crop      = None
        self._debounce_tg    = {}
        self.votos_por_track = defaultdict(list)
        self.conf_por_track  = defaultdict(float)
        self.todos_votos     = defaultdict(Counter)  # todas las lecturas de cada camión
        self.tipo_por_track  = {}     # zona de la última lectura
        self.pendientes      = {}     # cruzó y tiene número: esperando más lecturas
        self.visto           = {}     # última vez que llegó un cuadro del camión
        self.reportados      = {}     # camiones ya registrados (no se vuelven a leer)
        self._skip_impreso   = set()

    def _guardar_frame(self, frame, numero):
        try:
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            ruta   = FRAMES_DIR / f"{ts_str}_CAM1_{numero}.jpg"
            cv2.imwrite(str(ruta), frame)
            return ruta
        except Exception as e:
            print(f"[FRAME SAVE ERROR] {e}")
            return None

    def _reset_track(self, track_id):
        self.votos_por_track[track_id] = []
        self.conf_por_track[track_id]  = 0.0

    def _enviar_alerta(self, numero, direccion, confianza, ts_str, frame, zona="lateral"):
        """Centraliza el envío: validación LLM/Telegram primero, luego registro."""
        with estado.state_lock:
            estado.STATE["numero"]             = numero
            estado.STATE["ts"]                 = ts_str
            estado.STATE["total_detecciones"] += 1

        frame_path = self._guardar_frame(frame, numero)

        crop_path = None
        if self.mejor_crop is not None:
            try:
                ts2 = datetime.now().strftime("%Y%m%d_%H%M%S")
                crop_path = FRAMES_DIR / f"{ts2}_CAM1_{numero}_crop.jpg"
                cv2.imwrite(str(crop_path), self.mejor_crop)
            except Exception as e:
                print(f"[CROP SAVE ERROR] {e}")
                crop_path = None
            self.mejor_crop = None

        # ── Validación (LLM con fallback humano), aislada ──
        resultado    = FALLBACK   # si falla el guardado del frame, flujo normal
        numero_final = numero
        if frame_path:
            try:
                resultado, numero_final, msg_id = validar_y_enviar(
                    frame_path   = frame_path,
                    numero       = numero,
                    confianza    = float(confianza),
                    ts           = ts_str,
                    estado       = "DETECTADO",
                    no_detectado = numero,
                    camera_label = "Cam 1",
                    direccion    = direccion,
                    crop_path    = crop_path,
                )
                # Si el LLM corrigió el número, reflejarlo en el estado vivo
                if resultado == APROBADO and numero_final != numero:
                    with estado.state_lock:
                        estado.STATE["numero"] = numero_final
            except Exception as e:
                print(f"[TELEGRAM/LLM ERROR] {e}")
                numero_final = numero

        # ── Registro en métricas ──
        if resultado == NO_CONFIRMADO:
            # Número ilegible o sin match: NO se registra en métricas
            # (evita abrir estancias falsas). El frame queda en FRAMES_DIR
            # y la alerta ⚠️ ya se publicó en el grupo para auditoría.
            print(f"[METRICAS] '{numero}' NO registrado (SIN CONFIRMAR)")
            return

        # APROBADO: registra el número final (posiblemente corregido por LLM)
        # FALLBACK: registra como hoy; el validador humano decidirá en Telegram
        metricas.registrar_deteccion(
            numero_final, direccion, zona, confianza,
            frame_path.name if frame_path else None,
        )

    @staticmethod
    def _contiene(largo, corto):
        """True si 'corto' es 'largo' con dígitos de menos (504 dentro de 5014)."""
        it = iter(largo)
        return len(corto) < len(largo) and all(c in it for c in corto)

    def _elegir_numero(self, track_id):
        conteo = self.todos_votos[track_id]
        cands  = [n for n, v in conteo.items() if v >= N_VOTOS]
        if not cands:
            return None
        largo = max(cands, key=lambda n: (len(n), conteo[n]))
        if all(n == largo or self._contiene(largo, n) for n in cands):
            return largo
        return max(cands, key=lambda n: (conteo[n], len(n)))

    def _revisar_pendientes(self):
        ahora = time.time()
        for tid in list(self.pendientes):
            p = self.pendientes[tid]
            se_fue = ahora - self.visto.get(tid, 0) >= ESPERA_FIN_SEG
            if not (se_fue or ahora - p["t0"] >= ESPERA_MAX_SEG):
                continue
            del self.pendientes[tid]
            numero    = self._elegir_numero(tid)
            votos     = dict(self.todos_votos.pop(tid, {}))
            confianza = self.conf_por_track[tid]
            tipo      = self.tipo_por_track.pop(tid, "lateral")
            self.reportados[tid] = ahora
            self._reset_track(tid)
            if not numero:
                continue
            # Si el camión terminó del lado de donde venía, se regresó: no cuenta
            lado_entrada = linea_virtual.LADO_ENTRADA
            esperado = (lado_entrada if p["direccion"] == "entrada"
                        else ("derecha" if lado_entrada == "izquierda" else "izquierda"))
            with linea_virtual._tracks_lock:
                lado_final = linea_virtual._estado_tracks.get(str(tid), {}).get("lado", esperado)
            if lado_final != esperado:
                print(f"[MANIOBRA] {numero} track={tid} terminó del lado {lado_final} — se regresó, no se registra")
                continue
            ultimo_tg = self._debounce_tg.get(numero, 0)
            if ahora - ultimo_tg < DEBOUNCE_SEG:
                print(f"[DEBOUNCE-TG] {numero} ignorado ({int(ahora-ultimo_tg)}s < {DEBOUNCE_SEG}s)")
                continue
            self._debounce_tg[numero] = ahora

            ts_str       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            frame_enviar = self.mejor_frame if self.mejor_frame is not None else p["frame"]
            print(f"✅ {numero} | {p['direccion']} | conf={confianza:.2f} | {tipo} | "
                  f"track={tid} | votos={votos} | {ts_str}")
            self._enviar_alerta(numero, p["direccion"], confianza, ts_str, frame_enviar, tipo)
            self.mejor_frame     = None
            self.mejor_conf      = 0.0
            self.mejor_bbox_area = 0

        # Olvidar camiones que ya no se ven desde hace 5 minutos
        for d in (self.visto, self.reportados):
            for tid in [k for k, v in d.items() if ahora - v > 300]:
                d.pop(tid, None)
                self._skip_impreso.discard(tid)

    def update(self):
        global _last_m2_print
        while self.running:
            try:
                item = _m2_queue.get(timeout=1.0)
            except queue.Empty:
                self._revisar_pendientes()
                continue

            track_id = item["track_id"]
            cx       = item["cx"]
            cy       = item["cy"]
            frame    = item["frame"]
            ts_now   = item["ts"]
            self.visto[track_id] = time.time()
            self._revisar_pendientes()

            ya = self.reportados.get(track_id)
            if ya and time.time() - ya < DEBOUNCE_SEG:     # camión ya registrado: solo seguir su posición
                linea_virtual.evaluar_cruce(track_id, cx, cy, None, ts_now)
                continue

            try:
                # ── MODELO 2: frame completo ──────────────────────────────────
                res_m2 = modelos.model_zona.predict(
                    frame, conf=CONF_VISTA, device=0, verbose=False, imgsz=1280)

                n_zonas = len(res_m2[0].boxes) if res_m2 else 0
                lado_c  = linea_virtual.lado_actual(cx, cy)
                ahora   = time.time()
                if ahora - _last_m2_print >= _LOG_INTERVAL:
                    print(f"[M2] track={track_id} | zonas={n_zonas} | "
                          f"cx={cx} cy={cy} | lado={lado_c} | "
                          f"votos={list(self.votos_por_track[track_id])}")
                    if n_zonas > 0:
                        for b in res_m2[0].boxes:
                            cid  = int(b.cls[0])
                            tipo = modelos.tipo_zona(cid)
                            cf   = round(float(b.conf[0]), 2)
                            bb   = [int(x) for x in b.xyxy[0].tolist()]
                            bw   = bb[2] - bb[0]
                            bh   = bb[3] - bb[1]
                            bmin = BBOX_MIN_POR_TIPO.get(tipo, 30)
                            pasa = "OK" if (bw >= bmin and bh >= bmin) else f"FILTRADO({bw}x{bh}<{bmin})"
                            print(f"  idx={cid} tipo={tipo} conf={cf} bbox={bb} {pasa}")
                    _last_m2_print = ahora

                numero_frame = None
                best_conf    = 0.0
                best_tipo    = "numero"

                if res_m2 and len(res_m2[0].boxes) > 0:
                    boxes_sorted = sorted(
                        res_m2[0].boxes,
                        key=lambda b: (
                            0 if modelos.es_lateral(int(b.cls[0])) else 1,
                            -float(b.conf[0])
                        )
                    )

                    for box in boxes_sorted:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        conf_b  = float(box.conf[0])
                        cls_id  = int(box.cls[0])
                        tipo    = modelos.tipo_zona(cls_id)
                        bw, bh  = x2 - x1, y2 - y1

                        _pad = PAD_RATIO_LATERAL if modelos.es_lateral(cls_id) else PAD_RATIO
                        crop_zona = reconocimiento.crop_con_padding(frame, x1, y1, x2, y2, ratio=_pad)

                        numero_r = reconocimiento.leer_digitos(crop_zona)
                        numero_v = reconocimiento.validar_numero(numero_r)

                        if numero_r or numero_v:
                            print(f"  [M3] tipo={tipo} raw={numero_r} validado={numero_v}")

                        reconocimiento.guardar_crop_numero(crop_zona, cls_id, numero_r, numero_v, track_id)

                        bbox_min = BBOX_MIN_POR_TIPO.get(tipo, 30)
                        if bw < bbox_min or bh < bbox_min:
                            continue

                        if modelos.es_lateral(cls_id):
                            if conf_b > self.mejor_conf:
                                self.mejor_conf  = conf_b
                                self.mejor_frame = frame.copy()
                                self.mejor_crop  = crop_zona.copy()
                        else:
                            area = bw * bh
                            if area > self.mejor_bbox_area:
                                self.mejor_bbox_area = area
                                self.mejor_frame     = frame.copy()
                                self.mejor_crop      = crop_zona.copy()

                        if numero_v:
                            numero_frame = numero_v
                            best_conf    = conf_b
                            best_tipo    = tipo
                            break

                # ── Buffer de votos por track_id ──────────────────────────────
                if numero_frame:
                    self.votos_por_track[track_id].append(numero_frame)
                    self.todos_votos[track_id][numero_frame] += 1
                    self.tipo_por_track[track_id] = best_tipo
                    if best_conf > self.conf_por_track[track_id]:
                        self.conf_por_track[track_id] = best_conf
                    print(f"  [VOTO] track={track_id} numero={numero_frame} "
                          f"votos={list(self.votos_por_track[track_id])}")

                if len(self.votos_por_track[track_id]) > N_VOTOS * 3:
                    self.votos_por_track[track_id].pop(0)

                # ── Número confirmado (3 votos iguales) ───────────────────────
                numero_confirmado = None
                if len(self.votos_por_track[track_id]) >= N_VOTOS:
                    conteo = Counter(self.votos_por_track[track_id])
                    cand, veces = conteo.most_common(1)[0]
                    if veces >= N_VOTOS:
                        numero_confirmado = cand
                        linea_virtual.reasociar_numero(numero_confirmado, track_id)

                # ── Cruce ─────────────────────────────────────────────────────
                resultado = linea_virtual.evaluar_cruce(track_id, cx, cy,
                                                         numero_confirmado, ts_now)

                # Dirección: la del cruce de ahora, o la de un cruce reciente sin número
                direccion = resultado if resultado in ('entrada', 'salida') else None
                if direccion is None:
                    with linea_virtual._tracks_lock:
                        est     = linea_virtual._estado_tracks.get(str(track_id), {})
                        eventos = list(est.get('eventos', []))
                    if eventos and (ts_now - eventos[-1]['timestamp']) < DEBOUNCE_SEG:
                        direccion = eventos[-1]['direccion']

                if direccion is None:
                    continue                       # todavía no cruza la línea

                if track_id in self.pendientes:
                    self.pendientes[track_id]["direccion"] = direccion
                    continue                       # sigue juntando lecturas

                if self._elegir_numero(track_id) is None:
                    if track_id not in self._skip_impreso:
                        print(f"[SKIP] track={track_id} cruzó, todavía sin número")
                        self._skip_impreso.add(track_id)
                    continue

                self.pendientes[track_id] = {"direccion": direccion,
                                             "t0": time.time(), "frame": frame}
                print(f"[ESPERA] track={track_id} | {direccion} | "
                      f"votos={dict(self.todos_votos[track_id])} — esperando más lecturas")

            except Exception as e:
                print(f"[M2M3 ERROR] {e}")

    def stop(self):
        self.running = False