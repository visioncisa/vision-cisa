"""
Lee la información que el sistema guarda en el NOMBRE de cada archivo.

Formatos que produce producción (ml/reconocimiento.py):
  zona del número : <AAAAMMDD>_<HHMMSS>_<mmm>_<numero|unk>_t<track>.jpg
                    (carpeta = delantero / lateral / trasera)
  autobús         : <AAAAMMDD>_<HHMMSS>_<mmm>_t<track>.jpg   (carpeta autobus)
  grabación       : cam1_<AAAAMMDD>_<HHMMSS>.mp4             (scripts/grabar.sh)

Roboflow renombra al exportar: "x.jpg" → "x_jpg.rf.<hash>.jpg". Se limpia.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

ZONAS = {"delantero", "lateral", "trasera", "autobus"}

_NUMERO = re.compile(
    r"^(?P<fecha>\d{8})_(?P<hora>\d{6})_(?P<ms>\d{1,3})_(?P<num>[0-9A-Za-z]+)_t(?P<track>-?\d+)$")
_AUTOBUS = re.compile(
    r"^(?P<fecha>\d{8})_(?P<hora>\d{6})_(?P<ms>\d{1,3})_t(?P<track>-?\d+)$")
_GRABACION = re.compile(r"^(?P<cam>cam\d+)_(?P<fecha>\d{8})_(?P<hora>\d{6})$")
_ROBOFLOW = re.compile(r"(_(jpg|jpeg|png|bmp))?\.rf\.[0-9a-fA-F]+$")


@dataclass(frozen=True)
class InfoRecorte:
    ruta: Path
    momento: Optional[datetime]
    numero_sistema: Optional[str]     # lo que leyó producción (None si 'unk' o no viene)
    track: Optional[int]
    zona: Optional[str]               # carpeta: delantero / lateral / trasera / autobus

    @property
    def timestamp(self) -> Optional[float]:
        return self.momento.timestamp() if self.momento else None

    @property
    def dia(self) -> Optional[str]:
        return self.momento.strftime("%Y%m%d") if self.momento else None

    def clave_pasada(self) -> str:
        """Identifica la pasada sin la ventana de tiempo (zona + día + track)."""
        if self.track is None or self.momento is None:
            return f"suelto:{self.ruta.name}"
        return f"{self.zona or '-'}:{self.dia}:t{self.track}"


def limpiar_stem(nombre: str) -> str:
    stem = Path(nombre).stem
    return _ROBOFLOW.sub("", stem)


def _momento(fecha: str, hora: str, ms: str) -> Optional[datetime]:
    try:
        base = datetime.strptime(fecha + hora, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return base.replace(microsecond=int(ms.ljust(3, "0")[:3]) * 1000)


def leer_recorte(ruta) -> InfoRecorte:
    p = Path(ruta)
    stem = limpiar_stem(p.name)
    zona = p.parent.name.lower() if p.parent.name.lower() in ZONAS else None
    m = _NUMERO.match(stem)
    if m:
        num = m["num"]
        return InfoRecorte(p, _momento(m["fecha"], m["hora"], m["ms"]),
                           None if num.lower() == "unk" else num, int(m["track"]), zona)
    m = _AUTOBUS.match(stem)
    if m:
        return InfoRecorte(p, _momento(m["fecha"], m["hora"], m["ms"]), None,
                           int(m["track"]), zona or "autobus")
    return InfoRecorte(p, None, None, None, zona)


@dataclass(frozen=True)
class InfoGrabacion:
    ruta: Path
    camara: str
    inicio: datetime


def leer_grabacion(ruta) -> Optional[InfoGrabacion]:
    p = Path(ruta)
    m = _GRABACION.match(p.stem)
    if not m:
        return None
    try:
        inicio = datetime.strptime(m["fecha"] + m["hora"], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return InfoGrabacion(p, m["cam"], inicio)
