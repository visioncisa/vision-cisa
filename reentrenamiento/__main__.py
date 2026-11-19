"""
Línea de comandos:  python -m reentrenamiento <paso> [opciones]

  extraer      cuadros de las grabaciones, por eventos o periódicos
  seleccionar  fotogramas clave por calidad + repetición (sin modelo)
  preanotar    igual que seleccionar, pero usa el modelo actual para
               medir incertidumbre y dejar las cajas ya dibujadas
  validar      revisa un dataset YOLO antes de entrenar
  dividir      train/valid/test por pasada, con test congelado
  entrenar     fine-tuning desde un YAML de experimento, con registro
  evaluar      compara candidato vs actual y decide ACEPTAR/RECHAZAR

Códigos de salida: 0 bien · 1 error de uso/datos · 3 modelo RECHAZADO
Guía completa: docs/PIPELINE_REENTRENAMIENTO.md
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Optional, Set

from . import configuracion
from .clases import clases_de

EXT_IMG = (".jpg", ".jpeg", ".png", ".bmp")


def _padron(ruta: Optional[str]) -> Optional[Set[str]]:
    if not ruta:
        return None
    with open(ruta, encoding="utf-8", newline="") as fh:
        filas = list(csv.DictReader(fh))
    if not filas:
        return set()
    col = "no_economico" if "no_economico" in filas[0] else next(iter(filas[0]))
    return {(f.get(col) or "").strip() for f in filas if (f.get(col) or "").strip()}


def _imagenes(carpeta: str):
    return sorted(p for p in Path(carpeta).rglob("*") if p.suffix.lower() in EXT_IMG)


def cmd_extraer(a, cfg) -> int:
    from . import extraer_video as ev
    if a.modo == "eventos":
        if not (a.eventos and a.grabaciones):
            print("Faltan --eventos y --grabaciones"); return 1
        r = ev.por_eventos(ev.cargar_eventos(Path(a.eventos)), Path(a.grabaciones), Path(a.salida),
                           a.antes, a.despues, a.paso, a.camara)
    else:
        if not a.video:
            print("Falta --video"); return 1
        r = {"cuadros": ev.periodico(Path(a.video), Path(a.salida), a.cada)}
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0


def _lote(a, cfg, con_modelo: bool) -> int:
    from .calidad import medir_archivo
    from .nombres import leer_recorte
    from .preanotacion import escribir_lote
    from .redundancia import hash_archivo
    from .seleccion import seleccionar

    clases = clases_de(a.modelo)
    rutas = _imagenes(a.entrada)
    if not rutas:
        print(f"No hay imágenes en {a.entrada}"); return 1
    print(f"Imágenes: {len(rutas)}")
    infos = [leer_recorte(r) for r in rutas]
    calidades, hashes = {}, {}
    for r in rutas:
        calidades[str(r)] = medir_archivo(r, cfg["calidad"])
        try:
            hashes[str(r)] = hash_archivo(r)
        except ValueError:
            pass
    predicciones = None
    info_extra = {"entrada": str(a.entrada), "modelo": a.modelo}
    if con_modelo:
        from .predicciones import PredictorUltralytics
        p = cfg["preanotacion"]
        pred = PredictorUltralytics(Path(a.pesos), imgsz=int(a.imgsz or p["imgsz"]), conf=float(p["conf"]),
                                    half=bool(p["half"]), lote=int(p["lote_gpu"]), clases_esperadas=clases)
        validas = [r for r in rutas if calidades.get(str(r)) is not None]
        predicciones = pred.predecir(validas)
        info_extra.update({"pesos": str(a.pesos), "conf_preetiqueta": p["conf"]})
    decisiones = seleccionar(infos, calidades, hashes, predicciones, clases,
                             cfg["seleccion"], cfg["calidad"], padron=_padron(a.padron))
    man = escribir_lote(decisiones, predicciones, Path(a.salida), clases, info_extra)
    print(json.dumps(man["resumen"], indent=2, ensure_ascii=False))
    print(f"Lote listo en {a.salida} (subir la carpeta completa a Roboflow)")
    return 0


def cmd_seleccionar(a, cfg) -> int:
    return _lote(a, cfg, con_modelo=False)


def cmd_preanotar(a, cfg) -> int:
    if not a.pesos:
        print("preanotar necesita --pesos (p. ej. modelo_digitos_v3.pt)"); return 1
    return _lote(a, cfg, con_modelo=True)


def cmd_validar(a, cfg) -> int:
    from .validar_etiquetas import validar
    rep = validar(Path(a.dataset), clases_de(a.modelo), min_por_clase=a.min_por_clase,
                  revisar_fuga=not a.sin_fuga)
    print(rep.texto())
    return 0 if rep.ok else 1


def cmd_dividir(a, cfg) -> int:
    from .dividir import dividir
    d = cfg["division"]
    r = dividir(Path(a.origen), Path(a.destino), d["proporciones"], str(d["semilla"]),
                Path(a.congelado) if a.congelado else None, clases_de(a.modelo))
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0


def cmd_entrenar(a, cfg) -> int:
    from .entrenar import entrenar
    fila = entrenar(Path(a.experimento), Path(a.registro), Path(a.proyecto), simular=a.simular)
    print(json.dumps(fila, indent=2, ensure_ascii=False))
    return 0


def cmd_evaluar(a, cfg) -> int:
    from . import evaluar as ev
    clases = clases_de(a.modelo)
    verdad = Path(a.verdad)
    salida = Path(a.salida)
    pred_actual, pred_cand = a.pred_actual, a.pred_candidato
    imgsz = int(a.imgsz or cfg["preanotacion"]["imgsz"])
    if a.pesos_actual:
        pred_actual = str(salida / "pred_actual")
        ev.predecir_a_carpeta(Path(a.pesos_actual), verdad / "images", Path(pred_actual), imgsz, clases=clases)
    if a.pesos_candidato:
        pred_cand = str(salida / "pred_candidato")
        ev.predecir_a_carpeta(Path(a.pesos_candidato), verdad / "images", Path(pred_cand), imgsz, clases=clases)
    if not (pred_actual and pred_cand):
        print("Faltan predicciones: usa --pred-actual/--pred-candidato o --pesos-actual/--pesos-candidato")
        return 1
    iou = float(cfg["evaluacion"]["iou"])
    base = ev.metricas(verdad, Path(pred_actual), clases, iou)
    cand = ev.metricas(verdad, Path(pred_cand), clases, iou)
    if a.data_yaml and a.pesos_actual and a.pesos_candidato:
        base.update(ev.metricas_ultralytics(Path(a.pesos_actual), Path(a.data_yaml), imgsz))
        cand.update(ev.metricas_ultralytics(Path(a.pesos_candidato), Path(a.data_yaml), imgsz))
    veredicto = ev.comparar(base, cand, cfg["evaluacion"]["criterios"])
    ev.guardar(salida, base, cand, veredicto, a.titulo)
    print(f"Decisión: {veredicto['decision']}")
    for m in veredicto["motivos_rechazo"]:
        print(f"  ✗ {m}")
    for m in veredicto["mejoras"]:
        print(f"  ✓ {m}")
    print(f"Reporte: {salida / 'evaluacion.md'}")
    return 0 if veredicto["decision"] == "ACEPTAR" else 3


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m reentrenamiento", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="YAML de configuración (por defecto reentrenamiento/config_reentrenamiento.yaml)")
    sub = p.add_subparsers(dest="paso", required=True)

    s = sub.add_parser("extraer", help="cuadros de las grabaciones")
    s.add_argument("--modo", choices=["eventos", "periodico"], default="eventos")
    s.add_argument("--eventos", help="JSON de /api/detecciones o CSV con columna ts")
    s.add_argument("--grabaciones", help="carpeta con cam1_AAAAMMDD_HHMMSS.mp4")
    s.add_argument("--video", help="video para el modo periódico")
    s.add_argument("--salida", required=True)
    s.add_argument("--antes", type=float, default=3.0)
    s.add_argument("--despues", type=float, default=3.0)
    s.add_argument("--paso", type=float, default=1.0)
    s.add_argument("--cada", type=float, default=30.0)
    s.add_argument("--camara", default="cam1")
    s.set_defaults(fn=cmd_extraer)

    for nombre, fn, ayuda in (("seleccionar", cmd_seleccionar, "fotogramas clave sin modelo"),
                              ("preanotar", cmd_preanotar, "fotogramas clave + pre-etiquetas del modelo")):
        s = sub.add_parser(nombre, help=ayuda)
        s.add_argument("--entrada", required=True, help="carpeta con recortes (se busca en subcarpetas)")
        s.add_argument("--modelo", required=True, choices=["m1", "m2", "m3"])
        s.add_argument("--salida", required=True, help="carpeta del lote a crear")
        s.add_argument("--pesos", help=".pt del modelo actual (obligatorio en preanotar)")
        s.add_argument("--padron", help="padron.csv (columna no_economico)")
        s.add_argument("--imgsz", type=int)
        s.set_defaults(fn=fn)

    s = sub.add_parser("validar", help="revisa un dataset YOLO")
    s.add_argument("--dataset", required=True)
    s.add_argument("--modelo", required=True, choices=["m1", "m2", "m3"])
    s.add_argument("--min-por-clase", type=int, default=20)
    s.add_argument("--sin-fuga", action="store_true", help="no buscar fuga entre splits (más rápido)")
    s.set_defaults(fn=cmd_validar)

    s = sub.add_parser("dividir", help="train/valid/test por pasada")
    s.add_argument("--origen", required=True, help="carpeta con images/ y labels/")
    s.add_argument("--destino", required=True)
    s.add_argument("--modelo", required=True, choices=["m1", "m2", "m3"])
    s.add_argument("--congelado", help="lista de pasadas del test congelado (se crea si no existe)")
    s.set_defaults(fn=cmd_dividir)

    s = sub.add_parser("entrenar", help="fine-tuning con registro")
    s.add_argument("--experimento", required=True)
    s.add_argument("--registro", default="experimentos/registro.jsonl")
    s.add_argument("--proyecto", default="experimentos/corridas")
    s.add_argument("--simular", action="store_true", help="solo valida y registra, no entrena")
    s.set_defaults(fn=cmd_entrenar)

    s = sub.add_parser("evaluar", help="candidato vs actual → ACEPTAR/RECHAZAR")
    s.add_argument("--verdad", required=True, help="split de prueba con images/ y labels/ (test congelado)")
    s.add_argument("--modelo", required=True, choices=["m1", "m2", "m3"])
    s.add_argument("--salida", required=True)
    s.add_argument("--pred-actual", help="carpeta de .txt (con conf) del modelo actual")
    s.add_argument("--pred-candidato", help="carpeta de .txt (con conf) del candidato")
    s.add_argument("--pesos-actual", help="o bien: .pt actual (genera las predicciones)")
    s.add_argument("--pesos-candidato", help="o bien: .pt candidato")
    s.add_argument("--data-yaml", help="data.yaml para calcular mAP con Ultralytics")
    s.add_argument("--imgsz", type=int)
    s.add_argument("--titulo", default="Evaluación de modelo candidato")
    s.set_defaults(fn=cmd_evaluar)
    return p


def main(argv=None) -> int:
    a = construir_parser().parse_args(argv)
    cfg = configuracion.cargar(Path(a.config) if a.config else None)
    try:
        return a.fn(a, cfg)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
