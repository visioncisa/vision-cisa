# -*- coding: utf-8 -*-
"""
validar_llm.py — Motor de validación con LLM (Gemini Flash)
Proyecto CISA — versión adaptada a la arquitectura modular v2.


Prueba standalone en la Jetson (sin tocar el servicio):
  docker compose exec cisa-vision python3 validar_llm.py <ruta_del_frame>.jpg 5038
"""

import base64
import json
import time

import requests

# ---------------------------------------------------------------------------
# Configuración: la clave y el modelo vienen del .env (GEMINI_API_KEY,
# GEMINI_MODEL) a través de config.py. La clave va en un encabezado, no en
# la URL, para que no aparezca en los mensajes de error.
# ---------------------------------------------------------------------------
try:
    from config import GEMINI_API_KEY, GEMINI_MODEL
except Exception:                       # prueba suelta sin config.py
    import os
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
LLM_TIMEOUT = 20
LLM_REINTENTOS = 2
LLM_MAX_CANDIDATOS = 6

APROBADO = "APROBADO"
NO_CONFIRMADO = "NO_CONFIRMADO"
FALLBACK = "FALLBACK"


def _construir_prompt(candidatos, con_crop=False):
    intro_crop = (
        "Recibes DOS imagenes: la PRIMERA es un acercamiento (zoom) de la zona "
        "del numero; la SEGUNDA es la escena completa. Lee el numero "
        "principalmente del acercamiento.\n\n" if con_crop else "")
    lista = ", ".join(sorted(candidatos)) if candidatos else "ninguno"
    return (
        intro_crop +
        "Eres un sistema de control de calidad de un patio de autobuses "
        "(Metrobús, CDMX). En la imagen aparece un autobús con su número "
        "económico pintado (normalmente 4 dígitos que inician con 5, "
        "p. ej. 5038).\n\n"
        f"Números candidatos registrados en el padrón: {lista}.\n\n"
        "Instrucciones:\n"
        "1. Lee el número económico que VES en la imagen. No asumas que "
        "algún candidato es el correcto: reporta lo que ves.\n"
        "2. Si el número es claramente legible, responde con él.\n"
        "3. Si está borroso, tapado, cortado o no aparece, marca "
        "legible=false.\n\n"
        "Responde ÚNICAMENTE este JSON, sin markdown ni texto adicional:\n"
        '{"numero": "XXXX", "legible": true}\n'
        'o bien {"numero": null, "legible": false}'
    )


def _llamar_gemini(ruta_imagen, candidatos, ruta_crop=None):
    with open(ruta_imagen, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    partes = [{"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}]
    if ruta_crop:
        try:
            with open(ruta_crop, "rb") as f:
                crop_b64 = base64.b64encode(f.read()).decode("utf-8")
            partes.insert(0, {"inline_data": {"mime_type": "image/jpeg", "data": crop_b64}})
        except Exception as e:
            print(f"[LLM] crop no disponible: {e}")
    partes.append({"text": _construir_prompt(candidatos, con_crop=bool(ruta_crop))})
    payload = {
        "contents": [{"parts": partes}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2048},
    }

    ultimo_error = None
    for intento in range(1, LLM_REINTENTOS + 2):
        try:
            r = requests.post(GEMINI_URL, json=payload, timeout=LLM_TIMEOUT,
                              headers={"x-goog-api-key": GEMINI_API_KEY or ""})
            r.raise_for_status()
            partes = r.json()["candidates"][0]["content"]["parts"]
            texto = "".join(p.get("text", "") for p in partes)
            texto = texto.replace("```json", "").replace("```", "").strip()
            resp = json.loads(texto)
            numero = resp.get("numero")
            if numero is not None:
                numero = "".join(c for c in str(numero) if c.isdigit())
            return {"numero": numero or None, "legible": bool(resp.get("legible"))}
        except Exception as e:
            ultimo_error = e
            print(f"[LLM] intento {intento} falló: {e}")
            time.sleep(1.5 * intento)

    raise RuntimeError(f"Gemini no respondió: {ultimo_error}")


def _lev(a, b):
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        cur = [i + 1]
        for j, cb in enumerate(b):
            cur.append(min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (ca != cb)))
        prev = cur
    return prev[-1]


def _candidatos_cercanos(lectura, padron):
    if not lectura:
        return sorted(padron)[:LLM_MAX_CANDIDATOS]
    return sorted(padron, key=lambda u: _lev(str(lectura), u))[:LLM_MAX_CANDIDATOS]


def validar_con_llm(ruta_frame, lectura_ocr, unidades_validas, ruta_crop=None):
    """
    Args:
        ruta_frame: path al frame de la detección (el mismo que va a Telegram).
        lectura_ocr: número confirmado por votos de M3 (str) o None.
        unidades_validas: config.UNIDADES_VALIDAS (set del padrón).

    Returns:
        (resultado, numero, detalle)
        APROBADO      -> numero legible y existe en el padrón
        NO_CONFIRMADO -> ilegible o sin match en padrón
        FALLBACK      -> API caída/timeout: usar flujo humano
    """
    if not GEMINI_API_KEY:
        return FALLBACK, lectura_ocr, "falta GEMINI_API_KEY en el .env"
    padron = set(str(u) for u in unidades_validas)
    candidatos = _candidatos_cercanos(lectura_ocr, padron)

    try:
        resp = _llamar_gemini(ruta_frame, candidatos, ruta_crop)
    except Exception as e:
        return FALLBACK, lectura_ocr, f"API no disponible: {e}"

    numero, legible = resp["numero"], resp["legible"]

    if legible and numero and numero in padron:
        if numero == str(lectura_ocr):
            return APROBADO, numero, "LLM y OCR coinciden"
        return APROBADO, numero, f"LLM corrigió OCR ({lectura_ocr} → {numero})"

    if legible and numero:
        return NO_CONFIRMADO, numero, f"LLM leyó {numero}, sin match en padrón"

    return NO_CONFIRMADO, lectura_ocr, "Número ilegible en la imagen"


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python validar_llm.py <ruta_imagen> [lectura_ocr]")
        sys.exit(1)
    try:
        from config import UNIDADES_VALIDAS as PADRON
        print(f"[TEST] Padrón cargado de config.py: {len(PADRON)} unidades")
    except Exception:
        PADRON = {"5004", "5005", "5009", "5018", "5025", "5038",
                  "5055", "5057", "5060", "5063"}
        print("[TEST] config.py no disponible, usando padrón demo")
    res, num, det = validar_con_llm(sys.argv[1],
                                    sys.argv[2] if len(sys.argv) > 2 else None,
                                    PADRON)
    print(f"\nResultado: {res}\nNúmero:    {num}\nDetalle:   {det}")
