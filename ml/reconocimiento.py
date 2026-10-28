"""
ml/reconocimiento.py
================================================================
Recorte con padding, lectura de dígitos (M3), validación contra
el padrón de unidades y guardado de crops.
================================================================
"""
import cv2
from datetime import datetime

from config import PAD_RATIO, CONF_DIGITO, UNIDADES_VALIDAS, CROPS_DIR
from ml import modelos
from ml.preprocesamiento import aplicar_preprocesamiento


def crop_con_padding(frame, x1, y1, x2, y2, ratio=PAD_RATIO):
    h_img, w_img = frame.shape[:2]
    pad_x = int((x2 - x1) * ratio)
    pad_y = int((y2 - y1) * ratio)
    return frame[
        max(0, y1 - pad_y): min(h_img, y2 + pad_y),
        max(0, x1 - pad_x): min(w_img, x2 + pad_x),
    ]


def leer_digitos(crop_bgr):
    if crop_bgr is None or crop_bgr.size == 0:
        return None
    h, w = crop_bgr.shape[:2]
    if h < 80:
        escala   = 80 / h
        crop_bgr = cv2.resize(crop_bgr, (int(w * escala), 80),
                              interpolation=cv2.INTER_LANCZOS4)
    crop_bgr = aplicar_preprocesamiento(crop_bgr)
    try:
        res = modelos.model_digitos.predict(
            crop_bgr, conf=CONF_DIGITO, device=0, verbose=False, imgsz=640)
    except Exception as e:
        print(f"[DIGITOS ERROR] {e}")
        return None

    if not res or len(res[0].boxes) == 0:
        return None

    digitos = []
    for box in res[0].boxes:
        x1, _, x2, _ = map(int, box.xyxy[0])
        digito = modelos.CLASE_A_DIGITO.get(
            modelos.model_digitos.names[int(box.cls[0])])
        if digito is not None:
            digitos.append(((x1 + x2) / 2, digito))

    if not digitos:
        return None

    digitos.sort(key=lambda d: d[0])
    numero = ''.join(d[1] for d in digitos)
    return numero if numero.isdigit() else None


def validar_numero(numero):
    if not numero or not numero.isdigit() or len(numero) not in (3, 4):
        return None
    if numero in UNIDADES_VALIDAS:
        return numero
    if len(numero) == 3 and numero[0] == '5':
        c = numero[0] + '0' + numero[1:]
        if c in UNIDADES_VALIDAS:
            print(f"[CORREGIDO] {numero} → {c}"); return c
    if len(numero) == 3 and numero[0] != '5':
        c = '5' + numero
        if c in UNIDADES_VALIDAS:
            print(f"[CORREGIDO] {numero} → {c}"); return c
    if len(numero) == 4 and numero[0] != '5':
        c = '5' + numero[1:]
        if c in UNIDADES_VALIDAS:
            print(f"[CORREGIDO] {numero} → {c}"); return c
    return None


def guardar_crop_autobus(frame, bx1, by1, bx2, by2, track_id):
    """Guarda el crop del autobús completo — 1 vez por track_id."""
    try:
        h_f, w_f = frame.shape[:2]
        crop = frame[max(0, by1):min(h_f, by2), max(0, bx1):min(w_f, bx2)]
        if crop.size == 0:
            return
        dest = CROPS_DIR / 'autobus'
        dest.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        cv2.imwrite(str(dest / f"{ts_str}_t{track_id}.jpg"), crop)
    except Exception as e:
        print(f"[CROP BUS ERROR] {e}")


def guardar_crop_numero(crop_bgr, cls_id, numero_raw, numero_val, track_id):
    """Guarda el crop de la zona del número — siempre, con o sin número."""
    if crop_bgr is None or crop_bgr.size == 0:
        return
    try:
        tipo    = modelos.tipo_zona(cls_id)
        dest    = CROPS_DIR / tipo
        dest.mkdir(parents=True, exist_ok=True)
        ts_str  = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        num_str = numero_val or numero_raw or 'unk'
        cv2.imwrite(str(dest / f"{ts_str}_{num_str}_t{track_id}.jpg"), crop_bgr)
    except Exception as e:
        print(f"[CROP NUM ERROR] {e}")