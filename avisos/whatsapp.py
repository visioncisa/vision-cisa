"""
avisos/whatsapp.py
================================================================
Manda por WhatsApp los mismos avisos que se publican en el grupo
de Telegram (fotos + texto), al número WHATSAPP_NUMERO del .env.
Si el aviso trae varias fotos, la primera lleva el texto y las
demás van enseguida.

El envío lo hace el servicio cisa-whatsapp (whatsapp/puente.js).
Aquí solo se forman los avisos en una cola y un hilo aparte los
entrega, para que la detección NUNCA espere a WhatsApp. Si el
puente está apagado o sin sesión, el aviso se descarta y queda
anotado en el log; la detección y el registro siguen normales.
================================================================
"""
import base64
import queue
import threading

import requests

from config import WHATSAPP_NUMERO, WHATSAPP_URL

_cola = queue.Queue(maxsize=50)


def enviar(texto, foto_path=None, extras=()):
    """Deja el aviso en la cola y regresa de inmediato. extras = otras fotos del
    mismo aviso; van después de la principal, numeradas (2/3, 3/3)."""
    if not WHATSAPP_NUMERO:
        return
    total = 1 + len(extras)
    envios = [(texto, foto_path)] + [(f"📷 {i}/{total}", ruta)
                                     for i, ruta in enumerate(extras, start=2)]
    try:
        for envio in envios:
            _cola.put_nowait(envio)
    except queue.Full:
        print("[WHATSAPP] cola llena (¿puente caído?); aviso descartado")


def _datos(texto, foto_path):
    datos = {"numero": WHATSAPP_NUMERO, "texto": texto}
    if foto_path:
        with open(foto_path, "rb") as f:
            datos["foto_b64"] = base64.b64encode(f.read()).decode("ascii")
    return datos


def _trabajador():
    while True:
        texto, foto_path = _cola.get()
        try:
            r = requests.post(f"{WHATSAPP_URL}/enviar", json=_datos(texto, foto_path), timeout=60)
            if r.status_code != 200:
                print(f"[WHATSAPP] no se envió ({r.status_code}): {r.text[:150]}")
        except Exception as e:
            print(f"[WHATSAPP] puente no disponible: {e}")


if WHATSAPP_NUMERO:
    threading.Thread(target=_trabajador, daemon=True, name="WhatsApp").start()
    print(f"[WHATSAPP] Avisos activos → {WHATSAPP_NUMERO} (puente {WHATSAPP_URL})")
