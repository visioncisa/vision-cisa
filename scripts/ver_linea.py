"""
Dibuja la línea virtual sobre un cuadro real para revisar que quedó donde va.
Se corre desde la carpeta del proyecto (no necesita pantalla):

  python3 scripts/ver_linea.py                 toma un cuadro de RTSP_URL (.env)
  python3 scripts/ver_linea.py foto.jpg        o de una imagen / video

Guarda ver_linea.jpg con: la línea (verde), sus puntos numerados, de qué lado
queda cada zona (izquierda / derecha, y cuál es LADO_ENTRADA) y la resolución
real del cuadro. Las coordenadas de LINEA_PUNTOS son en px de ESE cuadro.
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RTSP_URL, LADO_ENTRADA  # noqa: E402
from ml import linea_virtual as lv          # noqa: E402


def tomar_cuadro(fuente):
    img = cv2.imread(fuente) if os.path.isfile(fuente) else None
    if img is not None:
        return img
    cap = cv2.VideoCapture(fuente)
    ok, img = cap.read()
    cap.release()
    if not ok:
        sys.exit(f"No se pudo leer un cuadro de: {fuente}")
    return img


def main():
    fuente = sys.argv[1] if len(sys.argv) > 1 else RTSP_URL
    img = tomar_cuadro(fuente)
    alto, ancho = img.shape[:2]

    # Sombrea de qué lado queda cada píxel (muestreo cada 8 px, rápido)
    capa = img.copy()
    paso = 8
    for y in range(0, alto, paso):
        for x in range(0, ancho, paso):
            lado = lv.lado_actual(x, y)
            color = (255, 120, 0) if lado == LADO_ENTRADA else (0, 0, 255)
            capa[y:y + paso, x:x + paso] = color
    img = cv2.addWeighted(capa, 0.18, img, 0.82, 0)

    lv.dibujar_linea(img, color=(0, 255, 0), grosor=4)
    for i, (x, y) in enumerate(lv.LINEA_PUNTOS):
        cv2.circle(img, (int(x), int(y)), 8, (0, 255, 255), -1)
        cv2.putText(img, str(i + 1), (int(x) + 10, int(y) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)

    texto = [f"Cuadro: {ancho}x{alto}   punto del camion: {lv.LINEA_PUNTO_BUS}",
             f"Azul = {LADO_ENTRADA} (LADO_ENTRADA, adentro)   Rojo = el otro lado"]
    for i, t in enumerate(texto):
        cv2.putText(img, t, (20, 40 + 35 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5)
        cv2.putText(img, t, (20, 40 + 35 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)

    cv2.imwrite("ver_linea.jpg", img)
    print(f"Cuadro {ancho}x{alto} — guardado ver_linea.jpg")
    print(f"LINEA_PUNTOS = {lv.LINEA_PUNTOS}")
    fuera = [p for p in lv.LINEA_PUNTOS if not (0 <= p[0] < ancho and 0 <= p[1] < alto)]
    if fuera:
        print(f"[AVISO] puntos fuera del cuadro: {fuera} — ¿las coordenadas son de otra resolución?")


if __name__ == "__main__":
    main()
