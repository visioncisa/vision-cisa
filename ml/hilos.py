"""
ml/hilos.py
================================================================
Los dos hilos de visión que trabajan en paralelo:

  HiloM1   : detecta los autobuses, los trackea (ByteTrack), guarda
             el crop de cada uno y manda el cuadro con TODOS los
             autobuses válidos a la cola.
  HiloM2M3 : una sola pasada de M2 por cuadro; cada zona del número
             se asigna al autobús que la contiene y M3 lee solo las
             zonas que pasan el tamaño mínimo (con un tope por cuadro).
             Acumula votos por camión y decide el cruce de cada uno.
             Cuando un camión cruza espera a que termine de pasar
             (ESPERA_FIN_SEG / ESPERA_MAX_SEG), elige el mejor número
             y lo registra UNA sola vez (validación Gemini/Telegram +
             registro en métricas).

Carga de la GPU (lo que evita que se sature con varias unidades):
  - M1 limitado por YOLO_FPS_MAX.
  - M2M3 limitado por M2_FPS_MAX.
  - M3: como máximo MAX_ZONAS_POR_BUS lecturas por camión y
    MAX_LECTURAS_M3 por cuadro, sin importar cuántos camiones haya.
  - Los camiones ya registrados no se vuelven a leer.
  - Un camión con el número ya confirmado que no ha cruzado (p. ej.
    estacionado) solo se relee cada RELECTURA_SEG. Si ningún camión
    necesita lectura, M2 no corre en ese cuadro.
  - Crops de zona a disco: como máximo uno cada CROPS_CADA_SEG por camión.

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
    CONF_AUTOBUS, CONF_VISTA, N_VOTOS, VOTOS_FUERA_PADRON, UNIDADES_VALIDAS,
    PAD_RATIO, PAD_RATIO_LATERAL, DEBOUNCE_SEG, FRAMES_DIR,
    BBOX_MIN_POR_TIPO, BBOX_MIN_AUTOBUS,
    YOLO_FPS_MAX, ESPERA_FIN_SEG, ESPERA_MAX_SEG,
    M2_FPS_MAX, MAX_LECTURAS_M3, MAX_ZONAS_POR_BUS, CROPS_CADA_SEG, RELECTURA_SEG,
)
from logica import estado
from ml import modelos, reconocimiento, linea_virtual
from metricas import metricas
from avisos.telegram import validar_y_enviar, APROBADO, NO_CONFIRMADO, FALLBACK

# ── Cola entre M1 y M2M3 (solo la usan estos dos hilos) ───────────────────────
_m2_queue = queue.Queue(maxsize=1)

_last_m1_print = 0.0
_last_m2_print = 0.0
_LOG_INTERVAL  = 2.0
_OLVIDAR_SEG   = 300      # camión que no se ve en 5 min: se borra su estado
SIN_ZONA_INTENTOS = 5     # intentos seguidos de M2 sin zona antes de espaciar la búsqueda
MOVIMIENTO_PX     = 30    # si el camión se mueve más que esto, se vuelve a buscar en cada cuadro


def _interseccion(a, b):
    """Área de intersección entre dos cajas (x1, y1, x2, y2)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0


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
        self._descartados      = set()   # tracks ya avisados como pequeños (un aviso por track)
        self._ultimo_frame     = -1      # número del último cuadro analizado
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

            frame = self.cam.get_frame()     # ya es una copia propia de este hilo
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
                if res_m1[0].boxes.id is None:
                    if ahora - _last_m1_print >= _LOG_INTERVAL * 3:
                        print("[M1] Sin detección")
                        _last_m1_print = ahora
                    continue

                track_ids = res_m1[0].boxes.id.int().cpu().tolist()
                boxes_m1  = res_m1[0].boxes.xyxy.cpu().tolist()
                if ahora - _last_m1_print >= _LOG_INTERVAL:
                    confs = [round(float(c), 2) for c in res_m1[0].boxes.conf.cpu().tolist()]
                    print(f"[M1] Autobús detectado — tracks={track_ids} confs={confs} "
                          f"cola_m2={_m2_queue.qsize()}")
                    _last_m1_print = ahora

                # Todos los autobuses válidos (antes solo se mandaba el más grande)
                buses = []
                for (bx1, by1, bx2, by2), tid in zip(boxes_m1, track_ids):
                    bx1, by1, bx2, by2 = map(int, (bx1, by1, bx2, by2))
                    w_bus, h_bus = bx2 - bx1, by2 - by1
                    if w_bus < BBOX_MIN_AUTOBUS or h_bus < BBOX_MIN_AUTOBUS:
                        if tid not in self._descartados:
                            print(f"[M1] track={tid} descartado por tamaño "
                                  f"({w_bus}x{h_bus} < {BBOX_MIN_AUTOBUS})")
                            self._descartados.add(tid)
                        continue
                    buses.append({"tid": tid,
                                  "cx": (bx1 + bx2) // 2, "cy": (by1 + by2) // 2,
                                  "bbox": (bx1, by1, bx2, by2)})

                    if tid not in self._tracks_guardados:
                        reconocimiento.guardar_crop_autobus(frame, bx1, by1, bx2, by2, tid)
                        self._tracks_guardados.add(tid)
                        print(f"[CROP BUS] track={tid} guardado — bbox=({bx1},{by1},{bx2},{by2})")

                if len(self._tracks_guardados) > 500:
                    self._tracks_guardados.clear()
                if len(self._descartados) > 500:
                    self._descartados.clear()

                if not buses:
                    continue

                item = {"buses": buses, "frame": frame, "ts": time.time()}
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
        self._debounce_tg    = {}
        # Todo el estado es POR CAMIÓN (track_id): con varias unidades a la vez
        # cada una lleva sus votos, su mejor foto y su cruce.
        self.votos_por_track = defaultdict(list)
        self.conf_por_track  = defaultdict(float)
        self.todos_votos     = defaultdict(Counter)  # todas las lecturas de cada camión
        self.crudas          = defaultdict(Counter)  # lo que leyó M3 tal cual (3-4 dígitos), esté o no en el padrón
        self.tipo_por_track  = {}     # zona de la última lectura
        self.mejor           = {}     # mejor foto de cada camión: {conf, area, frame, crop}
        self.pendientes      = {}     # cruzó y tiene número: esperando más lecturas
        self.visto           = {}     # última vez que llegó un cuadro del camión
        self.reportados      = {}     # camiones ya registrados (no se vuelven a leer)
        self._ultima_lectura = {}     # última vez que M3 leyó al camión (para turnarlos)
        self._ultimo_crop    = {}     # último crop de zona guardado por camión
        self._skip_impreso   = set()  # cruzaron sin número todavía
        self._sin_zona       = {}     # intentos seguidos de M2 sin encontrar zona del número
        self._ancla          = {}     # posición (cx, cy) donde empezaron esos intentos
        self._ultimo_intento = {}     # última vez que M2 buscó su número
        self._perdidos       = set()  # ya avisados como [PERDIDO]
        self._ult_log_m3     = {}     # última línea [M3] impresa por camión (no repetir la misma)
        # Medición de carga (se ve en el panel de desarrollo del tablero)
        self._n_ciclos       = 0
        self._n_m3           = 0
        self._t_medida       = time.time()

    # ── Registro ──────────────────────────────────────────────────────────────
    def _guardar_frame(self, frame, numero):
        try:
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            ruta   = FRAMES_DIR / f"{ts_str}_CAM1_{numero}.jpg"
            cv2.imwrite(str(ruta), frame)
            return ruta
        except Exception as e:
            print(f"[FRAME SAVE ERROR] {e}")
            return None

    def _enviar_alerta(self, numero, direccion, confianza, ts_str, frame,
                       zona="lateral", crop=None):
        """Centraliza el envío: validación LLM/Telegram primero, luego registro."""
        with estado.state_lock:
            estado.STATE["numero"]             = numero
            estado.STATE["ts"]                 = ts_str
            estado.STATE["total_detecciones"] += 1

        frame_path = self._guardar_frame(frame, numero)

        crop_path = None
        if crop is not None:
            try:
                ts2 = datetime.now().strftime("%Y%m%d_%H%M%S")
                crop_path = FRAMES_DIR / f"{ts2}_CAM1_{numero}_crop.jpg"
                cv2.imwrite(str(crop_path), crop)
            except Exception as e:
                print(f"[CROP SAVE ERROR] {e}")
                crop_path = None

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

    # ── Elección del número ───────────────────────────────────────────────────
    @staticmethod
    def _contiene(largo, corto):
        """True si 'corto' es 'largo' con dígitos de menos (504 dentro de 5014)."""
        it = iter(largo)
        return len(corto) < len(largo) and all(c in it for c in corto)

    def _fuera_padron(self, tid):
        """(numero, veces) si lo que MÁS lee M3 en este camión es un número de 4
        dígitos que no está en el padrón, leído al menos VOTOS_FUERA_PADRON veces
        (p. ej. 2508). Si no, None."""
        conteo = self.crudas.get(tid)
        if not conteo:
            return None
        numero, veces = conteo.most_common(1)[0]
        if veces >= VOTOS_FUERA_PADRON and len(numero) == 4 and numero not in UNIDADES_VALIDAS:
            return numero, veces
        return None

    def _elegir_numero(self, track_id):
        conteo = self.todos_votos[track_id]
        cands  = [n for n, v in conteo.items() if v >= N_VOTOS]
        # Si el camión se lee una y otra vez con un número fuera del padrón, ese gana
        # a cualquier número "corregido" que se haya leído menos veces.
        fuera = self._fuera_padron(track_id)
        if fuera and all(conteo[n] < fuera[1] for n in cands):
            return fuera[0]
        if not cands:
            return None
        largo = max(cands, key=lambda n: (len(n), conteo[n]))
        if all(n == largo or self._contiene(largo, n) for n in cands):
            return largo
        return max(cands, key=lambda n: (conteo[n], len(n)))

    def _olvidar(self, tid):
        """Borra todo lo que se guardó de un camión."""
        for d in (self.votos_por_track, self.conf_por_track, self.todos_votos,
                  self.crudas, self.tipo_por_track, self.mejor, self.visto,
                  self._ultima_lectura, self._ultimo_crop,
                  self._sin_zona, self._ancla, self._ultimo_intento, self._ult_log_m3):
            d.pop(tid, None)
        self._skip_impreso.discard(tid)
        self._perdidos.discard(tid)
        linea_virtual.olvidar(tid, time.time())   # también su lado de la línea (si no, crece sin fin)

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
            crudas    = dict(self.crudas.pop(tid, {}))
            confianza = self.conf_por_track.pop(tid, 0.0)
            tipo      = self.tipo_por_track.pop(tid, "lateral")
            mejor     = self.mejor.pop(tid, None) or {}
            self.votos_por_track.pop(tid, None)
            self.reportados[tid] = ahora
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
            frame_enviar = mejor.get("frame")
            if frame_enviar is None:
                frame_enviar = p["frame"]
            fuera_txt = "" if numero in UNIDADES_VALIDAS else " | FUERA DEL PADRÓN"
            print(f"✅ {numero} | {p['direccion']} | conf={confianza:.2f} | {tipo} | "
                  f"track={tid} | votos={votos or crudas} | {ts_str}{fuera_txt}")
            self._enviar_alerta(numero, p["direccion"], confianza, ts_str, frame_enviar,
                                tipo, crop=mejor.get("crop"))

        # Camión que cruzó sin juntar N_VOTOS lecturas y ya se fue: no se registra,
        # pero se avisa (log + contador "descartadas" del panel de desarrollador).
        for tid in list(self._skip_impreso):
            if (tid in self.pendientes or tid in self.reportados or tid in self._perdidos
                    or ahora - self.visto.get(tid, ahora) < ESPERA_FIN_SEG):
                continue
            self._perdidos.add(tid)
            with linea_virtual._tracks_lock:
                ev = list(linea_virtual._estado_tracks.get(str(tid), {}).get("eventos", []))
            direccion = ev[-1]["direccion"].upper() if ev else "CRUCE"
            votos  = dict(self.todos_votos.get(tid, {}))
            crudas = dict(self.crudas.get(tid, {}))
            print(f"[PERDIDO] track={tid} {direccion} sin registrar: lecturas={votos or 'ninguna'} "
                  f"leído tal cual={crudas or 'nada'} "
                  f"(hacen falta {N_VOTOS} iguales del padrón o {VOTOS_FUERA_PADRON} fuera de él)")
            with estado.state_lock:
                estado.STATE["descartadas"] += 1

        # Olvidar camiones que ya no se ven desde hace 5 minutos
        for tid in [k for k, v in self.visto.items()
                    if ahora - v > _OLVIDAR_SEG and k not in self.pendientes]:
            self._olvidar(tid)
        for tid in [k for k, v in self.reportados.items() if ahora - v > _OLVIDAR_SEG]:
            self.reportados.pop(tid, None)

    # ── M2: zonas del número, asignadas a su camión ───────────────────────────
    @staticmethod
    def _asignar_zonas(res_m2, buses):
        """{track_id: [zona, ...]} — cada zona va al camión que más la contiene.
        Zonas fuera de todo camión activo (p. ej. de uno ya registrado) se ignoran."""
        por_bus = defaultdict(list)
        if not res_m2 or len(res_m2[0].boxes) == 0:
            return por_bus
        for b in res_m2[0].boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            area_z = max(1, (x2 - x1) * (y2 - y1))
            mejor_tid, mejor_inter = None, 0
            for bus in buses:
                inter = _interseccion((x1, y1, x2, y2), bus["bbox"])
                if inter > mejor_inter:
                    mejor_tid, mejor_inter = bus["tid"], inter
            if mejor_tid is None or mejor_inter < 0.5 * area_z:
                continue
            cls_id = int(b.cls[0])
            por_bus[mejor_tid].append({
                "xyxy": (x1, y1, x2, y2), "conf": float(b.conf[0]),
                "cls": cls_id, "tipo": modelos.tipo_zona(cls_id),
            })
        return por_bus

    @staticmethod
    def _log_zonas(res_m2, buses):
        """Detalle de cada zona que encontró M2: a qué camión quedó asignada o por
        qué no (para saber por qué no se lee un número)."""
        cajas = res_m2[0].boxes if res_m2 else []
        if len(cajas) == 0:
            print("  [M2] no encontró ninguna zona de número en el cuadro")
            return
        for b in cajas:
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            area_z = max(1, (x2 - x1) * (y2 - y1))
            tipo   = modelos.tipo_zona(int(b.cls[0]))
            mejor_tid, frac = None, 0.0
            for bus in buses:
                f = _interseccion((x1, y1, x2, y2), bus["bbox"]) / area_z
                if f > frac:
                    mejor_tid, frac = bus["tid"], f
            if frac >= 0.5:
                destino = f"→ track {mejor_tid} ({frac:.0%} dentro)"
            elif mejor_tid is None:
                destino = "DESCARTADA: fuera de todo autobús detectado"
            else:
                destino = f"DESCARTADA: solo {frac:.0%} dentro de track {mejor_tid} (mínimo 50%)"
            minimo  = BBOX_MIN_POR_TIPO.get(tipo, 30)
            tamano  = "" if (x2 - x1 >= minimo and y2 - y1 >= minimo) else f" | muy chica ({x2-x1}x{y2-y1} < {minimo})"
            print(f"  [M2] zona {tipo} conf={float(b.conf[0]):.2f} bbox=({x1},{y1},{x2},{y2}) {destino}{tamano}")

    # ── M3: dígitos de un camión ──────────────────────────────────────────────
    def _leer_bus(self, frame, tid, zonas, max_lecturas):
        """Lee hasta max_lecturas zonas del camión. Devuelve (numero, conf, tipo, n_leidas)."""
        zonas = sorted(zonas, key=lambda z: (0 if modelos.es_lateral(z["cls"]) else 1,
                                             -z["conf"]))
        leidas = 0
        for z in zonas:
            if leidas >= max_lecturas:
                break
            x1, y1, x2, y2 = z["xyxy"]
            bw, bh = x2 - x1, y2 - y1
            # Filtro de tamaño ANTES de M3 (antes se leía y luego se descartaba)
            if bw < BBOX_MIN_POR_TIPO.get(z["tipo"], 30) or bh < BBOX_MIN_POR_TIPO.get(z["tipo"], 30):
                continue

            lateral   = modelos.es_lateral(z["cls"])
            _pad      = PAD_RATIO_LATERAL if lateral else PAD_RATIO
            crop_zona = reconocimiento.crop_con_padding(frame, x1, y1, x2, y2, ratio=_pad)

            numero_r = reconocimiento.leer_digitos(crop_zona)
            numero_v = reconocimiento.validar_numero(numero_r)
            leidas  += 1
            self._n_m3 += 1
            if numero_r and len(numero_r) in (3, 4):
                self.crudas[tid][numero_r] += 1

            # Corrección (508 → 5008) en un camión que se lee claramente con otro
            # número fuera del padrón (2508): la lectura corta era el mismo 2508 al
            # que le faltó un dígito, no otro camión. No cuenta.
            nota = ""
            if numero_v and numero_v != numero_r:
                fuera = self._fuera_padron(tid)
                if fuera:
                    nota = f" (corrección ignorada: el camión se lee {fuera[0]}, {fuera[1]} veces)"
                    numero_v = None
            elif numero_r and not numero_v and len(numero_r) == 4:
                nota = " (no está en el padrón)"

            if numero_r or numero_v:
                linea = f"  [M3] track={tid} tipo={z['tipo']} raw={numero_r} validado={numero_v}{nota}"
                # La misma lectura repetida se imprime una vez cada 5 s, no en cada cuadro
                ult = self._ult_log_m3.get(tid)
                if not ult or ult[0] != linea or time.time() - ult[1] >= 5.0:
                    print(linea)
                    self._ult_log_m3[tid] = (linea, time.time())

            ahora = time.time()
            if ahora - self._ultimo_crop.get(tid, 0) >= CROPS_CADA_SEG:
                reconocimiento.guardar_crop_numero(crop_zona, z["cls"], numero_r, numero_v, tid)
                self._ultimo_crop[tid] = ahora

            # Mejor foto del camión: lateral por confianza, las demás por tamaño
            m = self.mejor.setdefault(tid, {"conf": 0.0, "area": 0, "frame": None, "crop": None})
            if (lateral and z["conf"] > m["conf"]) or (not lateral and bw * bh > m["area"]):
                if lateral: m["conf"] = z["conf"]
                else:       m["area"] = bw * bh
                m["frame"] = frame               # el cuadro ya es copia propia: no se copia otra vez
                m["crop"]  = crop_zona.copy()

            if numero_v:
                return numero_v, z["conf"], z["tipo"], leidas
        return None, 0.0, "numero", leidas

    # ── Votos y cruce de un camión ────────────────────────────────────────────
    def _procesar_bus(self, bus, numero_frame, best_conf, best_tipo, frame, ts_now):
        track_id, cx, cy = bus["tid"], bus["cx"], bus["cy"]

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

        # ── Número confirmado (N_VOTOS iguales) ───────────────────────────────
        numero_confirmado = None
        if len(self.votos_por_track[track_id]) >= N_VOTOS:
            cand, veces = Counter(self.votos_por_track[track_id]).most_common(1)[0]
            if veces >= N_VOTOS:
                numero_confirmado = cand
        fuera = self._fuera_padron(track_id)
        if fuera and self.todos_votos[track_id].get(numero_confirmado, 0) < fuera[1]:
            numero_confirmado = fuera[0]
        if numero_confirmado:
            linea_virtual.reasociar_numero(numero_confirmado, track_id)

        # ── Cruce ─────────────────────────────────────────────────────────────
        resultado = linea_virtual.evaluar_cruce(track_id, cx, cy, numero_confirmado, ts_now)

        # Dirección: la del cruce de ahora, o la de un cruce reciente sin número
        direccion = resultado if resultado in ('entrada', 'salida') else None
        if direccion is None:
            with linea_virtual._tracks_lock:
                est     = linea_virtual._estado_tracks.get(str(track_id), {})
                eventos = list(est.get('eventos', []))
            if eventos and (ts_now - eventos[-1]['timestamp']) < DEBOUNCE_SEG:
                direccion = eventos[-1]['direccion']

        if direccion is None:
            return                         # todavía no cruza la línea

        if track_id in self.pendientes:
            self.pendientes[track_id]["direccion"] = direccion
            return                         # sigue juntando lecturas

        if self._elegir_numero(track_id) is None:
            if track_id not in self._skip_impreso:
                print(f"[SKIP] track={track_id} cruzó, todavía sin número")
                self._skip_impreso.add(track_id)
            return

        self.pendientes[track_id] = {"direccion": direccion,
                                     "t0": time.time(), "frame": frame}
        print(f"[ESPERA] track={track_id} | {direccion} | "
              f"votos={dict(self.todos_votos[track_id])} — esperando más lecturas")

    def _necesita_lectura(self, bus, ahora):
        tid = bus["tid"]
        if tid in self.pendientes or tid in self._skip_impreso:
            return True                    # cruzó: se lee siempre, cada lectura cuenta
        # Quieto y sin número a la vista (p. ej. estacionado en la orilla del cuadro):
        # tras SIN_ZONA_INTENTOS intentos sin zona, se busca solo cada RELECTURA_SEG.
        # En cuanto se mueve MOVIMIENTO_PX desde donde empezó, se vuelve a leer siempre.
        ax, ay = self._ancla.get(tid, (bus["cx"], bus["cy"]))
        if abs(bus["cx"] - ax) + abs(bus["cy"] - ay) > MOVIMIENTO_PX:
            self._sin_zona[tid] = 0
            self._ancla[tid] = (bus["cx"], bus["cy"])
        if (self._sin_zona.get(tid, 0) >= SIN_ZONA_INTENTOS
                and ahora - self._ultimo_intento.get(tid, 0) < RELECTURA_SEG):
            return False
        conteo = self.todos_votos.get(tid)
        fuera  = self._fuera_padron(tid)
        confirmado = ((conteo and max(conteo.values()) >= N_VOTOS * 2)
                      or (fuera and fuera[1] >= VOTOS_FUERA_PADRON * 2))
        return not confirmado or ahora - self._ultima_lectura.get(tid, 0) >= RELECTURA_SEG

    # ── Un cuadro completo ────────────────────────────────────────────────────
    def _procesar_cuadro(self, item):
        global _last_m2_print
        buses  = item["buses"]
        frame  = item["frame"]
        ts_now = item["ts"]

        ahora = time.time()
        for b in buses:
            self.visto[b["tid"]] = ahora
        self._revisar_pendientes()

        # Camiones ya registrados: solo seguir su posición, sin M2/M3
        activos = []
        for b in buses:
            ya = self.reportados.get(b["tid"])
            if ya and ahora - ya < DEBOUNCE_SEG:
                linea_virtual.evaluar_cruce(b["tid"], b["cx"], b["cy"], None, ts_now)
            else:
                activos.append(b)
        if not activos:
            return

        # Camiones que necesitan lectura en este cuadro. Uno con el número ya
        # bien confirmado (p. ej. estacionado en el patio) solo se relee cada
        # RELECTURA_SEG; si cruzó (pendiente) se lee siempre.
        a_leer = {b["tid"] for b in activos if self._necesita_lectura(b, ahora)}
        if not a_leer:
            for b in activos:                    # sin M2/M3: solo seguir el cruce
                self._procesar_bus(b, None, 0.0, "numero", frame, ts_now)
            return

        # ── MODELO 2: una sola pasada para todos los camiones ─────────────────
        res_m2  = modelos.model_zona.predict(
            frame, conf=CONF_VISTA, device=0, verbose=False, imgsz=1280)
        por_bus = self._asignar_zonas(res_m2, activos)
        for b in activos:                       # cuenta intentos sin zona (ver _necesita_lectura)
            if b["tid"] in a_leer:
                tid = b["tid"]
                self._ultimo_intento[tid] = ahora
                self._ancla.setdefault(tid, (b["cx"], b["cy"]))
                self._sin_zona[tid] = 0 if por_bus.get(tid) else self._sin_zona.get(tid, 0) + 1

        if ahora - _last_m2_print >= _LOG_INTERVAL:
            resumen = {b["tid"]: len(por_bus.get(b["tid"], [])) for b in activos}
            print(f"[M2] activos={len(activos)} a_leer={sorted(a_leer)} "
                  f"zonas_por_track={resumen} pendientes={list(self.pendientes)}")
            self._log_zonas(res_m2, activos)
            _last_m2_print = ahora

        # ── MODELO 3: turnando camiones (el que lleva más sin leerse va primero) ─
        presupuesto = MAX_LECTURAS_M3
        for b in sorted(activos, key=lambda b: self._ultima_lectura.get(b["tid"], 0)):
            numero, conf, tipo = None, 0.0, "numero"
            zonas = por_bus.get(b["tid"]) if b["tid"] in a_leer else None
            if zonas and presupuesto > 0:
                numero, conf, tipo, n = self._leer_bus(
                    frame, b["tid"], zonas, min(MAX_ZONAS_POR_BUS, presupuesto))
                presupuesto -= n
                if n:
                    self._ultima_lectura[b["tid"]] = time.time()
            # El cruce se evalúa para TODOS los camiones, se hayan leído o no
            self._procesar_bus(b, numero, conf, tipo, frame, ts_now)

    def _medir(self):
        self._n_ciclos += 1
        elapsed = time.time() - self._t_medida
        if elapsed >= 2.0:
            with estado.state_lock:
                estado.STATE["m2_fps"]     = round(self._n_ciclos / elapsed, 1)
                estado.STATE["m3_por_seg"] = round(self._n_m3 / elapsed, 1)
            self._n_ciclos = self._n_m3 = 0
            self._t_medida = time.time()

    def update(self):
        while self.running:
            try:
                item = _m2_queue.get(timeout=1.0)
            except queue.Empty:
                self._revisar_pendientes()
                with estado.state_lock:
                    estado.STATE["m2_fps"] = estado.STATE["m3_por_seg"] = 0.0
                continue

            t0 = time.time()
            try:
                self._procesar_cuadro(item)
            except Exception as e:
                print(f"[M2M3 ERROR] {e}")
            self._medir()

            # Límite de cuadros por segundo de M2M3: deja respirar a la GPU
            if M2_FPS_MAX > 0:
                resto = 1.0 / M2_FPS_MAX - (time.time() - t0)
                if resto > 0:
                    time.sleep(resto)

    def stop(self):
        self.running = False
