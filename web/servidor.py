"""
web/servidor.py
================================================================
Instancia ÚNICA de Flask.
================================================================
"""
import os
from flask import Flask

# Carpeta raíz del proyecto = un nivel arriba de web/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)