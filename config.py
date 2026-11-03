"""
CISA — Configuración del sistema
================================================================
ÚNICO lugar donde se leen las variables del .env. Ningún otro
archivo usa os.getenv: todos importan de aquí.

Los valores que cambian por patio o por equipo van en el .env
(ver .env.example). Los umbrales de los modelos son constantes
de este archivo.
================================================================
"""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


def _bool(nombre, defecto=False):
    v = os.getenv(nombre)
    return defecto if v in (None, "") else v.strip().lower() in ("1", "true", "si", "sí", "yes")


_REQUIRED = [
    "RTSP_URL", "MODEL_PATH", "DIGITS_MODEL_PATH", "AUTOBUS_MODEL_PATH",
    "TG_TOKEN", "TG_CHAT_ID", "TG_VALIDADOR_IDS", "ID_PUERTA",
    "FRAMES_DIR", "FLASK_HOST", "FLASK_PORT",
]
_missing = [k for k in _REQUIRED if not os.getenv(k)]
if _missing:
    raise EnvironmentError(f"Faltan variables en .env: {', '.join(_missing)}")

# ── Cámara ────────────────────────────────────────────────────────────────────
# RTSP_URL es la cámara (rtsp://...) o un video grabado (ruta a .mp4 = modo prueba).
# Para cambiar entre los dos: python3 scripts/fuente.py camara | video
RTSP_URL      = os.getenv("RTSP_URL")
RTSP_URL_CAM2 = os.getenv("RTSP_URL_CAM2") or None      # opcional (botón "Cam 2")
CAM_BACKEND   = (os.getenv("CAM_BACKEND") or "").lower()  # "ffmpeg" = sin decodificación por hardware
# Modo prueba: carpetas o archivos .mp4 separados por coma; se reproducen uno tras otro.
VIDEOS_PRUEBA = [x.strip() for x in (os.getenv("VIDEOS_PRUEBA") or "").split(",") if x.strip()]

# ── Modelos ───────────────────────────────────────────────────────────────────
MODEL_PATH         = PROJECT_ROOT / os.getenv("MODEL_PATH")          # M2 zona del número
DIGITS_MODEL_PATH  = PROJECT_ROOT / os.getenv("DIGITS_MODEL_PATH")   # M3 dígitos
AUTOBUS_MODEL_PATH = PROJECT_ROOT / os.getenv("AUTOBUS_MODEL_PATH")  # M1 autobús

# El .engine pierde los nombres de clase al exportar a TensorRT.
# Nombres reales de modelo_vista: {0: 'delantero', 1: 'lateral', 2: 'trasera'}
CLASE_M2_IDX = {
    0: 'delantero',
    1: 'lateral',
    2: 'trasera',
}

# ── Umbrales de detección ─────────────────────────────────────────────────────
CONF_AUTOBUS      = 0.65
CONF_VISTA        = 0.50
CONF_DIGITO       = 0.45
PAD_RATIO         = 0.08   # margen alrededor de la zona del número
PAD_RATIO_LATERAL = 0.25   # más contexto para números laterales
N_VOTOS           = 2      # lecturas iguales para confirmar un número
# Número que M3 lee una y otra vez igual pero NO está en el padrón (p. ej. 2508):
# con estas lecturas iguales se registra tal cual, como "fuera del padrón", en vez
# de "corregirlo" a uno parecido del padrón (2508 → 508 → 5008).
VOTOS_FUERA_PADRON = int(os.getenv("VOTOS_FUERA_PADRON", "4"))

BBOX_MIN_POR_TIPO = {      # tamaño mínimo (px) de la zona del número
    'delantero': 80,
    'lateral':   20,
    'trasera':   45,
}
BBOX_MIN_AUTOBUS = 30      # tamaño mínimo (px) del autobús

# ── Rendimiento ───────────────────────────────────────────────────────────────
YOLO_FPS_MAX   = float(os.getenv("YOLO_FPS_MAX", "0"))    # M1. 0 = sin límite (solo cuadros nuevos)
M2_FPS_MAX     = float(os.getenv("M2_FPS_MAX", "5"))      # M2+M3 (lectura del número). 0 = sin límite
CROPS_CADA_SEG = float(os.getenv("CROPS_CADA_SEG", "1"))  # crops de zona a disco: 1 cada N seg por camión (0 = todos)
MAX_ZONAS_POR_BUS = 2      # lecturas de M3 por camión en cada cuadro
MAX_LECTURAS_M3   = 4      # lecturas de M3 por cuadro en total, haya los camiones que haya
RELECTURA_SEG     = 2.0    # camión con número ya confirmado que no ha cruzado: se relee cada N seg

# ── Cruce de la línea y registro ──────────────────────────────────────────────
LINEA_P1       = tuple(int(x) for x in os.getenv("LINEA_P1", "455,479").split(","))
LINEA_P2       = tuple(int(x) for x in os.getenv("LINEA_P2", "292,262").split(","))
LADO_ENTRADA   = os.getenv("LADO_ENTRADA", "izquierda")
MANIOBRA_SEG   = int(os.getenv("MANIOBRA_SEG", 20))        # regreso antes de esto = maniobra
DEBOUNCE_SEG   = int(os.getenv("DEBOUNCE_SEG", 60))        # mismo número no se repite antes de esto
ESPERA_FIN_SEG = float(os.getenv("ESPERA_FIN_SEG", "2"))   # seg sin ver al camión = ya pasó
ESPERA_MAX_SEG = float(os.getenv("ESPERA_MAX_SEG", "25"))  # máximo a esperar; debe ser mayor que MANIOBRA_SEG
# Margen alrededor de la línea (px de la imagen original). El camión solo "cambia de
# lado" cuando su centro se aleja más que esto de la línea; así el temblor de la
# detección con el camión parado encima no cuenta como cruces.
MARGEN_LINEA_PX = float(os.getenv("MARGEN_LINEA_PX", "30"))
ID_PUERTA      = int(os.getenv("ID_PUERTA"))

# ── Telegram y validación con Gemini ──────────────────────────────────────────
TG_TOKEN         = os.getenv("TG_TOKEN")
TG_CHAT_ID       = os.getenv("TG_CHAT_ID")
TG_VALIDADOR_IDS = [x.strip() for x in os.getenv("TG_VALIDADOR_IDS").split(",") if x.strip()]
SIN_TELEGRAM     = _bool("SIN_TELEGRAM")       # True = no manda nada a Telegram (pruebas)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or None
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
# Gemini revisa la foto antes de registrar. Por defecto sigue a Telegram
# (apagado con SIN_TELEGRAM=1); VALIDAR_CON_GEMINI=1 lo prende aunque no haya Telegram.
VALIDAR_CON_GEMINI = _bool("VALIDAR_CON_GEMINI", defecto=not SIN_TELEGRAM)
if VALIDAR_CON_GEMINI and not GEMINI_API_KEY:
    print("[CONFIG] VALIDAR_CON_GEMINI está activo pero falta GEMINI_API_KEY en el .env: se apaga.")
    VALIDAR_CON_GEMINI = False

# ── WhatsApp (servicio cisa-whatsapp, carpeta whatsapp/) ──────────────────────
# Número que recibe los mismos avisos del grupo de Telegram, con lada de país:
# México = 52 + 10 dígitos (ej. 525512345678). Vacío = WhatsApp apagado.
WHATSAPP_NUMERO = "".join(c for c in (os.getenv("WHATSAPP_NUMERO") or "") if c.isdigit()) or None
WHATSAPP_URL    = os.getenv("WHATSAPP_URL", "http://127.0.0.1:5002")

# ── Directorios ───────────────────────────────────────────────────────────────
FRAMES_DIR      = Path(os.getenv("FRAMES_DIR"))
CROPS_DIR       = Path(os.getenv("CROPS_DIR", "/media/cisa/JETSON_SD/crops_dataset"))
GRABACIONES_DIR = Path(os.getenv("GRABACIONES_DIR", "/media/cisa/JETSON_SD"))   # <dir>/cam1_grabacion

# ── Web ───────────────────────────────────────────────────────────────────────
FLASK_HOST        = os.getenv("FLASK_HOST")
FLASK_PORT        = int(os.getenv("FLASK_PORT"))
MJPEG_FPS         = float(os.getenv("MJPEG_FPS", "10"))    # video en vivo: cuadros por segundo
MJPEG_ANCHO       = int(os.getenv("MJPEG_ANCHO", "960"))   # video en vivo: ancho en px
MJPEG_CALIDAD     = 70                                     # calidad JPEG (0-100)
LISTA_DETECCIONES = int(os.getenv("LISTA_DETECCIONES", "10"))  # detecciones en la lista en vivo
THUMB_ANCHO       = 320                                    # ancho de las miniaturas de la lista

# ── Validaciones ──────────────────────────────────────────────────────────────
for p in [MODEL_PATH, DIGITS_MODEL_PATH, AUTOBUS_MODEL_PATH]:
    if not p.exists():
        raise FileNotFoundError(f"Modelo no encontrado: {p}")

for d in [FRAMES_DIR, CROPS_DIR,
          CROPS_DIR / "autobus",
          CROPS_DIR / "delantero",
          CROPS_DIR / "lateral",
          CROPS_DIR / "trasera"]:
    d.mkdir(parents=True, exist_ok=True)

# ── Padrón de unidades ────────────────────────────────────────────────────────
# ÚNICA fuente: padron.csv (columnas no_economico, empresa, tipo).
# Para dar de alta o baja una unidad se edita ese archivo y se reinicia;
# al arrancar, storage.py actualiza la tabla `unidad` de la base con él.
PADRON_PATH  = Path(os.getenv("PADRON_PATH", str(PROJECT_ROOT / "padron.csv")))
TIPOS_UNIDAD = {"electrica", "diesel"}


def _cargar_padron(ruta):
    import csv
    if not ruta.exists():
        raise FileNotFoundError(f"No encontré el padrón: {ruta}")
    info = {}
    with open(ruta, encoding="utf-8", newline="") as f:
        for n, fila in enumerate(csv.DictReader(f), start=2):
            numero  = (fila.get("no_economico") or "").strip()
            empresa = (fila.get("empresa") or "").strip()
            tipo    = (fila.get("tipo") or "").strip().lower()
            if not numero:
                continue
            if not numero.isdigit() or not empresa or tipo not in TIPOS_UNIDAD:
                raise ValueError(f"{ruta.name} línea {n}: fila inválida {dict(fila)}")
            if numero in info:
                raise ValueError(f"{ruta.name} línea {n}: la unidad {numero} está repetida")
            info[numero] = {"empresa": empresa, "tipo": tipo}
    if not info:
        raise ValueError(f"{ruta.name} está vacío")
    return info


UNIDADES_INFO    = _cargar_padron(PADRON_PATH)   # {"5038": {"empresa": "CISA", "tipo": "electrica"}, ...}
UNIDADES_VALIDAS = set(UNIDADES_INFO)

# ── Base de datos ─────────────────────────────────────────────────────────────
# En Docker apunta al volumen: DB_PATH=datos/detecciones.db
DB_PATH = Path(os.getenv("DB_PATH", str(PROJECT_ROOT / "detecciones.db")))

HORA_CORTE_DIA = 3   # el día operativo empieza a las 3 a.m.
