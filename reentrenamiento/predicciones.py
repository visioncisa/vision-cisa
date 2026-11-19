"""
Predicciones de un modelo YOLO y lectura del número a partir de las cajas.

`lectura_desde_cajas` reproduce la regla de producción
(ml/reconocimiento.py: leer_digitos + quitar_encimados): si dos cajas
se enciman más de la mitad del ancho de la más angosta, se queda la de
mayor confianza; luego se leen de izquierda a derecha. Se copia aquí
porque ml/reconocimiento.py carga los modelos en la GPU al importarse.
Si cambia allá, hay que cambiarla aquí (lo cubre tests/test_predicciones.py).

Formato de una caja: (clase, cx, cy, w, h, conf), coordenadas normalizadas 0-1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Caja = Tuple[int, float, float, float, float, float]


@dataclass
class Prediccion:
    cajas: List[Caja] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.cajas)

    @property
    def conf_min(self) -> float:
        return min((c[5] for c in self.cajas), default=0.0)

    def lectura(self, nombres: Sequence[str], max_traslape: float = 0.5) -> str:
        return lectura_desde_cajas(self.cajas, nombres, max_traslape)


def quitar_encimadas(cajas: Iterable[Caja], max_traslape: float = 0.5) -> List[Caja]:
    quedan: List[Caja] = []
    for c in sorted(cajas, key=lambda c: -c[5]):
        x1, x2 = c[1] - c[3] / 2, c[1] + c[3] / 2
        encimada = False
        for q in quedan:
            qx1, qx2 = q[1] - q[3] / 2, q[1] + q[3] / 2
            traslape = min(x2, qx2) - max(x1, qx1)
            angosta = max(1e-9, min(x2 - x1, qx2 - qx1))
            if traslape / angosta > max_traslape:
                encimada = True
                break
        if not encimada:
            quedan.append(c)
    return sorted(quedan, key=lambda c: c[1])


def lectura_desde_cajas(cajas: Iterable[Caja], nombres: Sequence[str], max_traslape: float = 0.5) -> str:
    return "".join(str(nombres[int(c[0])]) for c in quitar_encimadas(cajas, max_traslape))


# ── Archivos de etiquetas YOLO ────────────────────────────────────────────────
def leer_yolo(ruta: Path, con_conf: bool = False) -> List[Caja]:
    """Lee un .txt YOLO. Las etiquetas humanas no traen conf: se pone 1.0."""
    cajas: List[Caja] = []
    ruta = Path(ruta)
    if not ruta.exists():
        return cajas
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        partes = linea.split()
        if len(partes) < 5:
            continue
        conf = float(partes[5]) if con_conf and len(partes) >= 6 else 1.0
        cajas.append((int(float(partes[0])), float(partes[1]), float(partes[2]),
                      float(partes[3]), float(partes[4]), conf))
    return cajas


def escribir_yolo(ruta: Path, cajas: Iterable[Caja], con_conf: bool = False) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    lineas = []
    for c in cajas:
        base = f"{int(c[0])} {c[1]:.6f} {c[2]:.6f} {c[3]:.6f} {c[4]:.6f}"
        lineas.append(base + (f" {c[5]:.4f}" if con_conf else ""))
    ruta.write_text("\n".join(lineas) + ("\n" if lineas else ""), encoding="utf-8")


# ── Modelo real (opcional: solo si está instalado ultralytics) ────────────────
class PredictorUltralytics:
    """Envuelve un .pt/.engine de Ultralytics. Se importa solo al usarlo."""

    def __init__(self, modelo: Path, imgsz: int = 640, conf: float = 0.25,
                 half: bool = True, lote: int = 64, clases_esperadas: Optional[List[str]] = None):
        try:
            from ultralytics import YOLO
        except ImportError as e:   # pragma: no cover - depende del entorno
            raise RuntimeError("Falta ultralytics. En Colab: pip install ultralytics==8.4.171") from e
        self.modelo = YOLO(str(modelo), task="detect")
        self.nombres = [self.modelo.names[i] for i in sorted(self.modelo.names)]
        if clases_esperadas is not None:
            from .clases import comparar_clases
            problemas = comparar_clases(clases_esperadas, self.nombres)
            if problemas:
                raise ValueError("Las clases del modelo no coinciden:\n  " + "\n  ".join(problemas))
        self.imgsz, self.conf, self.half, self.lote = imgsz, conf, half, lote

    def predecir(self, rutas: Sequence[Path]) -> Dict[str, Prediccion]:  # pragma: no cover
        salida: Dict[str, Prediccion] = {}
        rutas = [str(r) for r in rutas]
        for i in range(0, len(rutas), self.lote):
            trozo = rutas[i:i + self.lote]
            resultados = self.modelo.predict(trozo, imgsz=self.imgsz, conf=self.conf,
                                             half=self.half, verbose=False)
            for ruta, r in zip(trozo, resultados):
                b = r.boxes
                cls = b.cls.cpu().numpy().astype(int).tolist()
                xywhn = b.xywhn.cpu().numpy().tolist()
                conf = b.conf.cpu().numpy().tolist()
                salida[ruta] = Prediccion([(c, *map(float, xywhn[k]), float(conf[k]))
                                           for k, c in enumerate(cls)])
        return salida
