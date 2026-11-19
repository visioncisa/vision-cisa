"""
Orden oficial de las clases de cada modelo.

El .engine de TensorRT pierde los nombres de clase (ver config.py,
CLASE_M2_IDX), así que producción se guía por el NÚMERO de clase.
Un dataset con las clases en otro orden produce un modelo que
confunde zonas o dígitos sin dar ningún error. Por eso todo el
paquete valida contra esta tabla.
"""
from __future__ import annotations

from typing import Dict, List

CLASES: Dict[str, List[str]] = {
    "m1": ["Autobus", "Unidades"],                    # bus_v3
    "m2": ["delantero", "lateral", "trasera"],        # modelo_vista_v3 (= CLASE_M2_IDX)
    "m3": [str(d) for d in range(10)],                # modelo_digitos_v3
}


def clases_de(modelo: str) -> List[str]:
    clave = modelo.lower()
    if clave not in CLASES:
        raise ValueError(f"Modelo desconocido '{modelo}'. Usa uno de: {', '.join(CLASES)}")
    return list(CLASES[clave])


def comparar_clases(esperadas: List[str], encontradas) -> List[str]:
    """Devuelve una lista de problemas (vacía si el orden coincide).

    `encontradas` puede ser una lista o un dict {indice: nombre}
    (como `model.names` de Ultralytics).
    """
    if isinstance(encontradas, dict):
        encontradas = [encontradas[i] for i in sorted(encontradas)]
    encontradas = [str(x) for x in encontradas]
    problemas = []
    if len(encontradas) != len(esperadas):
        problemas.append(f"Se esperaban {len(esperadas)} clases y hay {len(encontradas)}: {encontradas}")
    for i, (e, f) in enumerate(zip(esperadas, encontradas)):
        if e != f:
            problemas.append(f"Clase {i}: se esperaba '{e}' y está '{f}'")
    return problemas
