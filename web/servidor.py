"""
web/servidor.py
================================================================
Instancia ÚNICA de Flask.
================================================================
"""
import logging
import os
from flask import Flask

# El tablero consulta /api/estado, /api/prueba/estado... cada segundo: sin esto,
# cada consulta sale en el log y tapa los mensajes de detección. Los errores sí salen.
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# Carpeta raíz del proyecto = un nivel arriba de web/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)