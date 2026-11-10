"""
web/rutas.py
================================================================
TODAS las rutas HTTP (API + páginas).
Aquí no hay lógica de visión ni de almacenamiento: estas
funciones solo LEEN de logica/estado.py y metricas/, y devuelven
JSON, el video en vivo (MJPEG) o archivos.
================================================================
"""
import os
import time
import datetime as _dt

import cv2
from flask import jsonify, send_from_directory, make_response, render_template, request, Response

from config import (
    RTSP_URL, RTSP_URL_CAM2, UNIDADES_VALIDAS, FRAMES_DIR, CROPS_DIR, GRABACIONES_DIR,
    MJPEG_FPS, MJPEG_ANCHO, MJPEG_CALIDAD, LISTA_DETECCIONES, THUMB_ANCHO,
    HORA_CORTE_DIA,
)
from web.servidor import app
from logica import estado
from metricas import metricas, storage


# ── Estado en vivo ────────────────────────────────────────────────────────────
@app.route('/api/estado')
def api_estado():
    with estado.state_lock:
        st = dict(estado.STATE)
    u = metricas.ultima()

    # Estancias abiertas y unidades fuera de padrón (para panel BD en vista dev)
    try:
        estancias_abiertas = storage.unidades_dentro_count()
    except Exception:
        estancias_abiertas = None

    try:
        no_padron = storage.no_registrados_hoy()
    except Exception:
        no_padron = None

    st.update({
        "pipeline":             st.get("conexion") == "conectado",
        "yolo_fps":             st.get("yolo_fps", 0),
        "pg_conectada":         True,
        "unidades_registradas": len(UNIDADES_VALIDAS),
        "active_camera":        estado.ACTIVE_CAMERA,
        "switching":            False,
        "snapshot_url":         "/api/snapshot",
        "estancias_abiertas":   estancias_abiertas,
        "no_padron_hoy":        no_padron,
    })
    if u:
        st.update({
            "numero":     u["numero"],
            "empresa":    u["empresa"],
            "zona":       u["zona"],
            "movimiento": u["direccion"].capitalize(),
            "conf":       u["conf"],
            "ts":         _dt.datetime.fromtimestamp(u["ts"]).strftime("%H:%M:%S"),
        })
    return jsonify(st)


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route('/api/dashboard')
def api_dashboard():
    return jsonify(metricas.datos_dashboard())


@app.route('/api/detecciones-recent')
def api_detecciones_recent():
    return jsonify({"pending": [], "approved": metricas.detecciones_recientes(LISTA_DETECCIONES)})


def _fecha_detecciones(nombre):
    """Parámetro YYYY-MM-DD del panel; None si viene vacío, ValueError si es inválido."""
    valor = (request.args.get(nombre) or "").strip()
    if not valor:
        return None
    try:
        return _dt.datetime.strptime(valor, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValueError(f"{nombre} debe tener formato YYYY-MM-DD")


@app.route('/api/detecciones/empresas')
def api_detecciones_empresas():
    """Empresas que aparecen en las detecciones, para el selector del panel."""
    return jsonify({"empresas": storage.empresas_eventos()})


@app.route('/api/detecciones')
def api_detecciones():
    """
    Detecciones paginadas para /livevideo.

    Query params:
        q            número económico o empresa (varias palabras = AND)
        empresa      empresa exacta
        desde/hasta  rango de días operativos (YYYY-MM-DD, inclusivo)
        limit        tamaño de página (default LISTA_DETECCIONES)
        cursor_hora  cursor de paginación (hora_paso del último item)
        cursor_id    cursor de paginación (id_evento del último item)
    """
    q       = (request.args.get('q') or "").strip()[:100]
    empresa = (request.args.get('empresa') or "").strip()[:100]

    try:
        desde = _fecha_detecciones('desde')
        hasta = _fecha_detecciones('hasta')
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if desde and hasta and desde > hasta:
        desde, hasta = hasta, desde

    try:
        limite = int(request.args.get('limit') or LISTA_DETECCIONES)
    except ValueError:
        limite = LISTA_DETECCIONES
    limite = max(1, min(100, limite))

    cursor_hora = (request.args.get('cursor_hora') or "").strip() or None
    try:
        cursor_id = int(request.args.get('cursor_id'))
    except (TypeError, ValueError):
        cursor_id = None
    if cursor_hora:
        try:
            _dt.datetime.strptime(cursor_hora, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            cursor_hora, cursor_id = None, None
    else:
        cursor_id = None
    if cursor_hora and cursor_id is None:
        cursor_hora = None

    datos = metricas.listar_detecciones(
        q=q, empresa=empresa, desde=desde, hasta=hasta,
        cursor_hora=cursor_hora, cursor_id=cursor_id, limite=limite,
    )
    datos.update({
        "limit":      limite,
        "hora_corte": HORA_CORTE_DIA,
        "filtros":    {"q": q, "empresa": empresa, "desde": desde, "hasta": hasta},
    })
    return jsonify(datos)


# ── Snapshot (miniatura del dashboard) ────────────────────────────────────────
@app.route('/api/snapshot')
def api_snapshot():
    frame = estado.get_frame()
    if frame is None:
        return '', 404
    ok, buf = cv2.imencode('.jpg', cv2.resize(frame, (480, 270)))
    if not ok:
        return '', 500
    resp = make_response(buf.tobytes())
    resp.headers['Content-Type']  = 'image/jpeg'
    resp.headers['Cache-Control'] = 'no-store'
    return resp


# ── Video en vivo MJPEG (dashboard y /livevideo, sin ffmpeg) ───────────────────

@app.route('/api/video.mjpeg')
def api_video_mjpeg():
    def generar():
        intervalo = 1.0 / MJPEG_FPS
        while True:
            t0 = time.time()
            frame = estado.get_frame()
            if frame is not None:
                h, w = frame.shape[:2]
                if w > MJPEG_ANCHO:
                    frame = cv2.resize(frame, (MJPEG_ANCHO, int(h * MJPEG_ANCHO / w)))
                ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, MJPEG_CALIDAD])
                if ok:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                           + buf.tobytes() + b'\r\n')
            espera = intervalo - (time.time() - t0)
            if espera > 0:
                time.sleep(espera)
    return Response(generar(), mimetype='multipart/x-mixed-replace; boundary=frame',
                    headers={'Cache-Control': 'no-store'})


# ── Cambio de cámara (solo si RTSP_URL_CAM2 está en el .env) ──────────────────
@app.route('/api/switch-camera', methods=['POST'])
def api_switch_camera():
    num = int((request.get_json(silent=True) or {}).get('camera', 1))
    if num == 2 and not RTSP_URL_CAM2:
        return jsonify({"ok": False, "error": "RTSP_URL_CAM2 no configurada"})
    if estado.cam:
        estado.cam.url = RTSP_URL if num == 1 else RTSP_URL_CAM2
        if estado.cam.cap:
            try: estado.cam.cap.release()
            except: pass
            estado.cam.cap = None
    estado.ACTIVE_CAMERA = num
    return jsonify({"ok": True, "camera": num})


# ── Salud ─────────────────────────────────────────────────────────────────────
@app.route('/health')
def health():
    with estado.state_lock:
        return jsonify({
            "status":            "ok",
            "conexion":          estado.STATE["conexion"],
            "yolo_fps":          estado.STATE["yolo_fps"],
            "m2_fps":            estado.STATE["m2_fps"],
            "m3_por_seg":        estado.STATE["m3_por_seg"],
            "total_detecciones": estado.STATE["total_detecciones"],
            "descartadas":       estado.STATE["descartadas"],
            "ultimo_numero":     estado.STATE["numero"],
        })


# ── Fotos de las detecciones ──────────────────────────────────────────────────
@app.route('/frames/<path:filename>')
def serve_frame(filename):
    # send_from_directory rechaza rutas con "../": solo sirve lo que está en FRAMES_DIR
    return send_from_directory(str(FRAMES_DIR), filename, mimetype='image/jpeg')


# ── Miniaturas chicas para la lista de detecciones ────────────────────────────
_THUMBS = {}   # caché en memoria (máx. 200)

@app.route('/thumb/<path:filename>')
def serve_thumb(filename):
    base = os.path.realpath(str(FRAMES_DIR))
    filepath = os.path.realpath(os.path.join(base, filename))
    if not filepath.startswith(base + os.sep) or not os.path.exists(filepath):
        return '', 404
    jpg = _THUMBS.get(filename)
    if jpg is None:
        img = cv2.imread(filepath)
        if img is None:
            return '', 404
        h, w = img.shape[:2]
        if w > THUMB_ANCHO:
            img = cv2.resize(img, (THUMB_ANCHO, int(h * THUMB_ANCHO / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            return '', 500
        jpg = buf.tobytes()
        if len(_THUMBS) >= 200:
            _THUMBS.pop(next(iter(_THUMBS)), None)
        _THUMBS[filename] = jpg
    resp = make_response(jpg)
    resp.headers['Content-Type']  = 'image/jpeg'
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


# ── Páginas ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard_v3.html")

@app.route("/livevideo")
def livevideo():
    return render_template("Livevideo.html")

@app.route("/home")
def home():
    return render_template("home.html")

@app.route("/grabaciones")
def grabaciones():
    return render_template("grabaciones.html")


# ── Grabaciones ───────────────────────────────────────────────────────────────
def _dir_grabacion(cam_id):
    return os.path.join(str(GRABACIONES_DIR), f"cam{int(cam_id)}_grabacion")


@app.route('/api/grabaciones')
def api_grabaciones():
    import glob as g
    cam_id  = request.args.get('cam', '1')
    rec_dir = _dir_grabacion(cam_id)
    pattern = os.path.join(rec_dir, f'cam{cam_id}_*.mp4')
    files, total_size = [], 0
    for fp in sorted(g.glob(pattern)):
        try:
            sz = os.path.getsize(fp)
            if sz < 1_000_000: continue
            files.append({"name": os.path.basename(fp), "size": sz})
            total_size += sz
        except OSError:
            pass
    return jsonify({"cam": cam_id, "files": files,
                    "total_size": total_size, "count": len(files)})


@app.route('/grabaciones/file/<int:cam_id>/<filename>')
def grabaciones_file(cam_id, filename):
    # Igual que /frames: solo archivos dentro de la carpeta de grabaciones
    return send_from_directory(_dir_grabacion(cam_id), filename, mimetype='video/mp4')


@app.route('/api/crops/stats')
def api_crops_stats():
    stats = {}
    for tipo in ['autobus', 'delantero', 'lateral', 'trasera']:
        d = CROPS_DIR / tipo
        count = len(list(d.glob('*.jpg'))) if d.exists() else 0
        stats[tipo] = count
    stats['total'] = sum(stats.values())
    return jsonify(stats)


# ── Control de unidades ───────────────────────────────────────────────────────
@app.route('/api/estancias')
def api_estancias():
    """
    Movimientos del periodo con tiempos calculados (una fila por unidad).
    Llamado cada 10 s por el dashboard (tabla de control de unidades).

    Query param opcional:
        ?rango=hoy|semana|mes|anio   (default: hoy)

    Response JSON:
    {
      "estancias": [
        {
          "no_economico":           "585",
          "empresa":                "CISA",
          "ultimo_ingreso":         "14:20:05",
          "ultima_salida":          null,      <- null si sigue dentro
          "minutos_dentro":         null,      <- null si dentro (JS calcula en vivo)
          "minutos_dentro_previos": 45.0,      <- tramos cerrados previos del periodo
          "minutos_fuera":          32.0,
          "viajes":                 2,
          "status":                 "dentro"
        },
        ...
      ],
      "dentro_ahora":  { "CISA": 10, "COPATSA": 2, "CCISA": 0 },
      "prom_estancia": { "CISA": 102.5, "COPATSA": 87.3 }
    }

    dentro_ahora y prom_estancia siempre reflejan el día operativo
    ACTUAL sin importar el rango pedido (no tiene sentido un "dentro
    ahora" de hace un mes).
    """
    rango = request.args.get('rango', 'hoy')
    try:
        if rango == 'hoy':
            estancias = storage.estancias_del_dia()
        else:
            fecha_inicio, fecha_fin = storage._rango_fechas(rango)
            estancias = storage.estancias_rango(fecha_inicio, fecha_fin)

        return jsonify({
            'estancias':     estancias,
            'dentro_ahora':  storage.conteo_dentro_por_empresa(),
            'prom_estancia': storage.promedio_estancia_por_empresa(),
        })
    except Exception as e:
        app.logger.error('api_estancias error: %s', e)
        return jsonify({'error': str(e)}), 500


# ── Trayectoria detallada de una unidad ───────────────────────────────────────
@app.route('/api/trayectoria/<no_economico>')
def api_trayectoria(no_economico):
    """
    Bitácora SIN agregar de una unidad: cada tramo entrada→salida por
    separado, para el timeline/Gantt de detalle en el frontend.

    Query param opcional:
        ?rango=hoy|semana|mes|anio   (default: hoy)

    Response: ver docstring de storage.trayectoria_unidad()
    """
    rango = request.args.get('rango', 'hoy')
    try:
        return jsonify(storage.trayectoria_unidad(no_economico, rango))
    except Exception as e:
        app.logger.error('api_trayectoria error: %s', e)
        return jsonify({'error': str(e)}), 500

# ── Modo prueba: adelantar y cambiar de video (solo con video grabado) ─────────
@app.route('/api/prueba/estado')
def api_prueba_estado():
    cam = estado.cam
    activo = bool(cam and getattr(cam, 'es_archivo', False))
    return jsonify({
        "prueba": activo,
        "video":  os.path.basename(cam.url) if activo else None,
        "videos": len(cam.lista) if activo else 0,
        "indice": (cam.lista.index(cam.url) + 1) if activo and cam.url in cam.lista else 0,   # 1 = el más reciente
        "pos":    round(cam.pos_seg, 1) if activo else 0,
        "dur":    round(cam.dur_seg, 1) if activo else 0,
    })


@app.route('/api/prueba/saltar', methods=['POST'])
def api_prueba_saltar():
    try:
        seg = float((request.get_json(silent=True) or {}).get('seg', 10))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "seg no es un número"})
    seg = max(-600.0, min(600.0, seg))
    if not (estado.cam and estado.cam.pedir("saltar", seg)):
        return jsonify({"ok": False, "error": "Solo disponible con video grabado (modo prueba)"})
    return jsonify({"ok": True, "seg": seg})


@app.route('/api/prueba/siguiente', methods=['POST'])
def api_prueba_siguiente():
    if not (estado.cam and estado.cam.pedir("siguiente")):
        return jsonify({"ok": False, "error": "Solo disponible con video grabado (modo prueba)"})
    return jsonify({"ok": True})


@app.route('/api/prueba/anterior', methods=['POST'])
def api_prueba_anterior():
    if not (estado.cam and estado.cam.pedir("anterior")):
        return jsonify({"ok": False, "error": "Solo disponible con video grabado (modo prueba)"})
    return jsonify({"ok": True})


@app.route('/api/prueba/ir', methods=['POST'])
def api_prueba_ir():
    try:
        seg = float((request.get_json(silent=True) or {}).get('seg', 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "seg no es un número"})
    if not (estado.cam and estado.cam.pedir("ir", max(0.0, seg))):
        return jsonify({"ok": False, "error": "Solo disponible con video grabado (modo prueba)"})
    return jsonify({"ok": True, "seg": seg})
