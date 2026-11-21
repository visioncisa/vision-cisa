"""
Lee reentrenamiento/config_reentrenamiento.yaml y lo combina con los
valores por defecto de este archivo. Si el YAML no existe o le falta
una clave, se usa el valor por defecto (el código nunca truena por
configuración incompleta).
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

RUTA_DEFECTO = Path(__file__).resolve().parent / "config_reentrenamiento.yaml"

DEFECTOS: Dict[str, Any] = {
    "calidad": {
        "alto_normalizado": 96,        # la nitidez se mide con el recorte a esta altura
        "nitidez_descartar": 15.0,     # menos que esto: borrosa sin remedio → descartar
        "nitidez_revisar": 40.0,       # entre descartar y esto: dudosa → solo si es caso difícil
        "brillo_min": 25.0,            # media de gris (0-255)
        "brillo_max": 235.0,
        "contraste_min": 12.0,         # desviación estándar del gris
        "lado_min_px": 20,             # recortes más chicos no se etiquetan
        "noche_brillo": 70.0,          # media de gris por debajo = noche
        "contraluz_claros": 0.15,      # fracción de píxeles > 235 …
        "contraluz_oscuros": 0.25,     # … y fracción < 40 al mismo tiempo = contraluz
    },
    "seleccion": {
        "ventana_seg": 6.0,            # mismo track y menos de N s = misma pasada
        "max_por_pasada": 3,
        "hash_distancia_min": 6,       # dHash (0-64): menos que esto = imagen repetida
        "conf_duda": 0.50,             # conf mínima de un dígito por debajo = dudoso
        "porc_faciles": 0.20,          # % de pasadas fáciles que se conservan como control
        "digitos_validos": [3, 4],
        "usar_lectura_sistema": True,  # usar el número que leyó producción (nombre del archivo)
        "semilla": 7,
        "max_total": 0,                # 0 = sin tope
    },
    "preanotacion": {
        "imgsz": 640,
        "conf": 0.25,                  # bajo a propósito: es más rápido borrar una caja que dibujarla
        "half": True,
        "lote_gpu": 64,
    },
    "division": {
        "proporciones": {"train": 0.7, "valid": 0.2, "test": 0.1},
        "semilla": "cisa",
    },
    "evaluacion": {
        "iou": 0.5,
        # Criterios para ACEPTAR un modelo nuevo frente al actual (ver docs/EVALUACION_MODELOS.md)
        "criterios": {
            "recall_caida_max": 0.01,            # recall global no puede bajar más de 1 punto
            "precision_caida_max": 0.01,
            "recall_clase_caida_max": 0.03,      # ninguna clase puede bajar más de 3 puntos
            "exactitud_numero_caida_max": 0.0,   # M3: la exactitud del número completo no puede bajar
            "cer_aumento_max": 0.0,              # M3: el CER no puede subir
            "mejora_minima": 0.005,              # al menos una métrica principal debe mejorar esto
        },
    },
}


def _mezclar(base: Dict[str, Any], nuevo: Dict[str, Any]) -> Dict[str, Any]:
    salida = copy.deepcopy(base)
    for k, v in (nuevo or {}).items():
        if isinstance(v, dict) and isinstance(salida.get(k), dict):
            salida[k] = _mezclar(salida[k], v)
        else:
            salida[k] = v
    return salida


def cargar(ruta: Optional[Path] = None) -> Dict[str, Any]:
    ruta = Path(ruta) if ruta else RUTA_DEFECTO
    datos = {}
    if ruta.exists():
        with open(ruta, encoding="utf-8") as fh:
            datos = yaml.safe_load(fh) or {}
    return _mezclar(DEFECTOS, datos)
