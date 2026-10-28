"""
Cambia de dónde toma la imagen el sistema: el video grabado o la cámara real.
Se corre desde la carpeta del proyecto:

  python3 scripts/fuente.py           muestra cuál está activa (sin contraseña)
  python3 scripts/fuente.py camara    usa la cámara real
  python3 scripts/fuente.py video     regresa al video grabado

La dirección de la cámara se toma de RTSP_URL_CAMARA en el .env; si no existe,
se copia la RTSP_URL del .env del proyecto original (~/Documents/ProyectoIA/.env).
Después de cambiar:  docker compose up -d --force-recreate
Guarda el .env anterior como .env.antes_fuente.
"""
import os, re, shutil, sys

ENV  = ".env"
ORIG = os.path.expanduser("~/Documents/ProyectoIA/.env")

def leer(p):
    with open(p, encoding="utf-8") as f:
        return f.read().splitlines()

def valor(lineas, clave):
    for l in lineas:
        if l.startswith(clave + "="):
            return l.split("=", 1)[1].strip()
    return None

def poner(lineas, clave, v):
    for i, l in enumerate(lineas):
        if l.startswith(clave + "="):
            lineas[i] = f"{clave}={v}"
            return
    lineas.append(f"{clave}={v}")

def oculto(url):
    return re.sub(r"(//[^:/@]+:)[^@]*@", r"\1****@", url or "(vacío)")

if not os.path.exists(ENV):
    sys.exit("Corre esto dentro de la carpeta del proyecto (donde está el .env).")
env = leer(ENV)
actual = valor(env, "RTSP_URL") or ""
modo = "video" if actual.startswith("/") else "camara"

if len(sys.argv) < 2:
    print(f"Fuente activa: {modo}  →  {oculto(actual)}")
    sys.exit(0)

pedido = sys.argv[1].lower()
if pedido not in ("camara", "video"):
    sys.exit("Usa: python3 scripts/fuente.py camara   o   python3 scripts/fuente.py video")

if modo == "video":
    poner(env, "RTSP_URL_VIDEO", actual)            # se guarda para poder regresar
else:
    poner(env, "RTSP_URL_CAMARA", actual)

if pedido == "camara":
    url = valor(env, "RTSP_URL_CAMARA")
    if not url and os.path.exists(ORIG):
        url = valor(leer(ORIG), "RTSP_URL")
        if url:
            poner(env, "RTSP_URL_CAMARA", url)
    if not url or not url.startswith("rtsp://"):
        sys.exit("No encontré la dirección de la cámara. Agrega al .env una línea "
                 "RTSP_URL_CAMARA=rtsp://... y vuelve a correr esto.")
else:
    url = valor(env, "RTSP_URL_VIDEO")
    if not url or not os.path.isfile(url):
        sys.exit(f"No encontré el video ({url}). Revisa RTSP_URL_VIDEO en el .env.")

poner(env, "RTSP_URL", url)
shutil.copy(ENV, ".env.antes_fuente")
with open(ENV, "w", encoding="utf-8") as f:
    f.write("\n".join(env) + "\n")
print(f"LISTO: fuente = {pedido}  →  {oculto(url)}")
print("Ahora:  docker compose up -d --force-recreate")
