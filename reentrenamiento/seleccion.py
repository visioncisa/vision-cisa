"""
Selección de fotogramas clave: decide por cada recorte si se
CONSERVA, se manda a REVISAR o se DESCARTA, y por qué.

Reglas, en este orden (docs/POLITICA_DATASET.md las explica):

  1. Mala calidad (borrosa, oscura, sobreexpuesta, sin contraste,
     muy chica, ilegible)                         → descartar
  2. Por pasada (mismo track) se calcula el CONSENSO de lecturas.
     Un recorte es DIFÍCIL si cumple alguna de estas:
       sin_digitos       el modelo no vio ningún dígito
       digitos_raros     leyó una cantidad de dígitos que no existe
       desacuerdo        su lectura no coincide con el consenso
       baja_conf         algún dígito con conf < conf_duda
       sistema_distinto  producción registró otro número
       fuera_padron      la lectura no está en el padrón
       sistema_sin_lectura   producción vio la zona pero no leyó nada ('unk')   ┐ sin modelo:
       sistema_minoria   producción leyó en esta pasada otro número       ┘ vienen en el
                         distinto al más repetido (ej. 505 vs 5051)          nombre del archivo
       condicion_nueva   luz poco representada (noche/contraluz)
       calidad_dudosa    nitidez baja (no descartable)
  3. Cada pasada conserva su recorte más nítido como representante.
     Las pasadas sin nada difícil solo entran en un `porc_faciles`
     (muestra de control para no olvidar lo que ya sabe el modelo).
  4. De las pasadas difíciles se agregan hasta `max_por_pasada`
     recortes difíciles que se vean distintos (dHash ≥ hash_distancia_min).
  5. Lo demás                                     → descartar (redundante / cupo).

  - revisar   = alguien en Roboflow tiene que verlo (es un caso difícil)
  - conservar = entra con su pre-etiqueta; basta revisión por muestreo
  - descartar = no se sube

Sin predicciones del modelo (solo calidad + hash) la selección sigue
funcionando: cuenta como difícil solo lo que se detecta sin modelo.
"""
from __future__ import annotations

import hashlib
import random
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence, Set

from .calidad import Calidad, problemas as problemas_calidad, es_dudosa
from .nombres import InfoRecorte
from .predicciones import Prediccion
from .redundancia import agrupar_pasadas, distancia

CONSERVAR, REVISAR, DESCARTAR = "conservar", "revisar", "descartar"


@dataclass
class Decision:
    ruta: str
    pasada: int
    decision: str
    razones: List[str] = field(default_factory=list)
    prioridad: float = 0.0
    lectura_modelo: str = ""
    consenso: str = ""
    numero_sistema: str = ""
    conf_min: float = 0.0
    nitidez: float = 0.0
    luz: str = ""

    def fila(self) -> Dict:
        d = asdict(self)
        d["razones"] = "|".join(self.razones)
        return d


def _sorteo(clave: str, semilla) -> float:
    """Número 0-1 estable para una pasada (misma pasada = mismo resultado siempre)."""
    h = hashlib.md5(f"{semilla}:{clave}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def seleccionar(infos: Sequence[InfoRecorte],
                calidades: Dict[str, Optional[Calidad]],
                hashes: Dict[str, int],
                predicciones: Optional[Dict[str, Prediccion]],
                nombres_clases: Sequence[str],
                cfg_sel: Dict,
                cfg_cal: Dict,
                padron: Optional[Set[str]] = None,
                luz_rara: Sequence[str] = ("noche", "contraluz")) -> List[Decision]:
    predicciones = predicciones or {}
    digitos_validos = set(cfg_sel.get("digitos_validos", [3, 4]))
    conf_duda = float(cfg_sel.get("conf_duda", 0.5))
    dist_min = int(cfg_sel.get("hash_distancia_min", 6))
    max_pp = int(cfg_sel.get("max_por_pasada", 3))
    porc_faciles = float(cfg_sel.get("porc_faciles", 0.2))
    semilla = cfg_sel.get("semilla", 7)
    usa_digitos = list(nombres_clases) == [str(d) for d in range(10)]
    usa_sistema = usa_digitos and bool(cfg_sel.get("usar_lectura_sistema", True))

    decisiones: List[Decision] = []
    for gi, grupo in enumerate(agrupar_pasadas(infos, float(cfg_sel.get("ventana_seg", 6.0)))):
        filas: List[Decision] = []
        lecturas = []
        con_track = {str(i.ruta) for i in grupo if i.track is not None}
        for info in grupo:
            clave = str(info.ruta)
            cal = calidades.get(clave)
            pred = predicciones.get(clave)
            lectura = pred.lectura(nombres_clases) if pred else ""
            d = Decision(ruta=clave, pasada=gi, decision="", lectura_modelo=lectura,
                         numero_sistema=info.numero_sistema or "",
                         conf_min=round(pred.conf_min, 4) if pred else 0.0,
                         nitidez=cal.nitidez if cal else 0.0, luz=cal.luz if cal else "")
            malos = problemas_calidad(cal, cfg_cal)
            if malos:
                d.decision, d.razones = DESCARTAR, [f"mala_calidad:{m}" for m in malos]
            elif usa_digitos and pred and pred.n in digitos_validos:
                lecturas.append(lectura)
            filas.append(d)

        consenso = Counter(lecturas).most_common(1)[0][0] if lecturas else ""
        utiles = [d for d in filas if not d.decision]
        # Señal SIN modelo: lo que producción leyó (viene en el nombre del archivo).
        # Si la misma pasada tiene lecturas distintas, las de la minoría son difíciles.
        leidas_sist = Counter(d.numero_sistema for d in utiles if d.numero_sistema)
        consenso_sist = leidas_sist.most_common(1)[0][0] if leidas_sist else ""
        sist_inconsistente = len(leidas_sist) > 1
        for d in utiles:
            d.consenso = consenso
            pred = predicciones.get(d.ruta)
            cal = calidades.get(d.ruta)
            r = []
            if pred is not None:
                if pred.n == 0:
                    r.append("sin_digitos" if usa_digitos else "sin_detecciones")
                elif usa_digitos and pred.n not in digitos_validos:
                    r.append("digitos_raros")
                if usa_digitos and consenso and d.lectura_modelo != consenso:
                    r.append("desacuerdo")
                if pred.n and pred.conf_min < conf_duda:
                    r.append("baja_conf")
                if usa_digitos and d.numero_sistema and d.lectura_modelo and d.numero_sistema != d.lectura_modelo:
                    r.append("sistema_distinto")
                if usa_digitos and padron and d.lectura_modelo and d.lectura_modelo not in padron:
                    r.append("fuera_padron")
            if usa_sistema and d.ruta in con_track:
                if not d.numero_sistema:
                    r.append("sistema_sin_lectura")
                elif sist_inconsistente and d.numero_sistema != consenso_sist:
                    r.append("sistema_minoria")
            if cal is not None and cal.luz in luz_rara:
                r.append("condicion_nueva")
            if es_dudosa(cal, cfg_cal):
                r.append("calidad_dudosa")
            d.razones = r
            d.prioridad = round(10 * len(r) + 5 * (1 - (pred.conf_min if pred else 1.0)), 3)

        if not utiles:
            decisiones.extend(filas)
            continue

        dificil = any(d.razones for d in utiles) or len(set(lecturas)) > 1
        representante = max(utiles, key=lambda d: d.nitidez)
        if not dificil and _sorteo(grupo[0].clave_pasada(), semilla) > porc_faciles:
            for d in utiles:
                d.decision = DESCARTAR
                d.razones = d.razones + ["pasada_facil_fuera_de_muestra"]
            decisiones.extend(filas)
            continue

        elegidas = [representante]
        representante.decision = REVISAR if representante.razones else CONSERVAR
        if not representante.razones:
            representante.razones = ["representativa"]
        for d in sorted(utiles, key=lambda x: -x.prioridad):
            if d is representante:
                continue
            if len(elegidas) >= max_pp or not d.razones:
                d.decision, d.razones = DESCARTAR, d.razones + ["cupo_pasada"]
                continue
            h = hashes.get(d.ruta)
            parecida = h is not None and any(
                hashes.get(e.ruta) is not None and distancia(h, hashes[e.ruta]) < dist_min for e in elegidas)
            if parecida:
                d.decision, d.razones = DESCARTAR, d.razones + ["redundante"]
            else:
                d.decision = REVISAR
                elegidas.append(d)
        decisiones.extend(filas)

    tope = int(cfg_sel.get("max_total", 0) or 0)
    if tope:
        vivos = sorted([d for d in decisiones if d.decision != DESCARTAR], key=lambda d: -d.prioridad)
        for d in vivos[tope:]:
            d.decision, d.razones = DESCARTAR, d.razones + ["tope_total"]
    return decisiones


def resumen(decisiones: Sequence[Decision]) -> Dict:
    por_decision = Counter(d.decision for d in decisiones)
    razones = Counter(r for d in decisiones for r in d.razones)
    total = len(decisiones)
    elegidas = por_decision[CONSERVAR] + por_decision[REVISAR]
    return {
        "total": total,
        "pasadas": len({d.pasada for d in decisiones}),
        "conservar": por_decision[CONSERVAR],
        "revisar": por_decision[REVISAR],
        "descartar": por_decision[DESCARTAR],
        "porc_a_etiquetar": round(100 * elegidas / total, 1) if total else 0.0,
        "razones": dict(razones.most_common()),
    }
