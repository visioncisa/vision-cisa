"""
ml/preprocesamiento.py
================================================================
Preprocesamiento de imagen para mejorar la lectura de dígitos M3.
================================================================
"""
import cv2


def aplicar_preprocesamiento(crop_bgr):
    """Aplica CLAHE en el canal L (LAB) para mejorar el contraste local."""
    if crop_bgr is None or crop_bgr.size == 0:
        return crop_bgr
    lab = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_eq = clahe.apply(l)
    lab_eq = cv2.merge([l_eq, a, b])
    return cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)
