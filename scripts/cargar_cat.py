#!/usr/bin/env python3
"""
scripts/cargar_cat.py
=====================
Carga o actualiza el catálogo de unidades (tabla `cat` de PostgreSQL) desde
un CSV con columnas VIN, DESTINO, ECO, MARCA, MODELO, YEAR, MOTOR, SERIEMOTOR
(separado por ';' o ',', se detecta solo).

Se puede correr las veces que se quiera: si la unidad ya existe (mismo ECO),
se actualizan sus datos en lugar de fallar.

Uso, desde la carpeta del proyecto en la Jetson:
    python3 scripts/cargar_cat.py ~/catalogo.csv

La conexión sale de DATABASE_URL en el .env del proyecto (no se escribe aquí).
"""
import csv
import os
import sys
from pathlib import Path

import psycopg2

RAIZ = Path(__file__).resolve().parent.parent
EMPRESAS_VALIDAS = {"CCA", "CISA", "CORENSA", "SKYBUS", "VYCSA", "COPATTSA"}
OBLIGATORIAS = ("VIN", "DESTINO", "ECO", "MARCA", "MODELO", "YEAR")


def _database_url() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env = RAIZ / ".env"
    if env.exists():
        for linea in env.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea.startswith("DATABASE_URL="):
                return linea.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("Falta DATABASE_URL en el .env del proyecto.")


def _leer(ruta: Path) -> list[dict]:
    texto = ruta.read_text(encoding="utf-8-sig")
    sep = ";" if texto.splitlines()[0].count(";") >= texto.splitlines()[0].count(",") else ","
    filas = []
    for fila in csv.DictReader(texto.splitlines(), delimiter=sep):
        filas.append({(k or "").strip().upper(): " ".join((v or "").split()) for k, v in fila.items()})
    return filas


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    ruta = Path(sys.argv[1]).expanduser()
    if not ruta.exists():
        sys.exit(f"No encontré {ruta}")

    filas = _leer(ruta)
    print(f"Leí {len(filas)} filas de {ruta.name}")

    validas, omitidas = [], []
    for n, f in enumerate(filas, start=2):
        if any(not f.get(c) for c in OBLIGATORIAS):
            omitidas.append((n, "faltan datos"))
            continue
        if f["DESTINO"].upper() not in EMPRESAS_VALIDAS:
            omitidas.append((n, f"empresa {f['DESTINO']} no válida"))
            continue
        try:
            eco, anio = int(f["ECO"]), int(float(f["YEAR"]))
        except ValueError:
            omitidas.append((n, f"ECO o año inválido ({f['ECO']}, {f['YEAR']})"))
            continue
        validas.append((eco, f["VIN"].upper(), f["DESTINO"].upper(), f["MARCA"].upper(),
                        f["MODELO"].upper(), anio, f.get("MOTOR") or None, f.get("SERIEMOTOR") or None))

    for n, motivo in omitidas:
        print(f"  línea {n}: se omite ({motivo})")

    con = psycopg2.connect(_database_url(), connect_timeout=5)
    try:
        with con, con.cursor() as cur:
            for v in validas:
                cur.execute(
                    """INSERT INTO cat (eco, vin, destino, marca, modelo, anio, motor, seriemotor)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (eco) DO UPDATE SET
                           vin = EXCLUDED.vin, destino = EXCLUDED.destino,
                           marca = EXCLUDED.marca, modelo = EXCLUDED.modelo,
                           anio = EXCLUDED.anio, motor = EXCLUDED.motor,
                           seriemotor = EXCLUDED.seriemotor""", v)
            # limpia espacios que hayan quedado de cargas anteriores
            cur.execute("UPDATE cat SET marca = TRIM(marca), modelo = TRIM(modelo) "
                        "WHERE marca <> TRIM(marca) OR modelo <> TRIM(modelo)")
            cur.execute("SELECT COUNT(*) FROM cat")
            total = cur.fetchone()[0]
    finally:
        con.close()
    print(f"Listo: {len(validas)} unidades cargadas o actualizadas, {len(omitidas)} omitidas. "
          f"El catálogo tiene {total} unidades.")


if __name__ == "__main__":
    main()
