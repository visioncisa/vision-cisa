#!/usr/bin/env python3
"""
scripts/migrar_sqlite_a_postgres.py
===================================
Pasa UNA VEZ el histórico de la base SQLite anterior (datos/detecciones.db)
a PostgreSQL (patio_cca): unidades, eventos y estancias.

Se corre dentro del contenedor, con el sistema detenido:
    docker compose run --rm --no-deps cisa-vision python3 scripts/migrar_sqlite_a_postgres.py

Qué hace:
    1. Crea el esquema en PostgreSQL y sincroniza el padrón (igual que al arrancar).
    2. Copia unidades (las de fuera del padrón también), eventos y estancias,
       respetando qué estancia corresponde a qué evento.
    3. Compara los conteos. Todo va en una sola transacción: si algo falla,
       PostgreSQL queda como estaba. La base SQLite no se modifica.

No corre dos veces: si PostgreSQL ya tiene eventos, se detiene
(se puede forzar con --forzar, pero duplicaría el histórico).
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DB_PATH            # noqa: E402
from metricas import storage          # noqa: E402

ZONAS_OK = {"delantero", "lateral", "trasera"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sqlite", default=str(DB_PATH), help=f"base SQLite (por defecto {DB_PATH})")
    ap.add_argument("--forzar", action="store_true", help="migrar aunque PostgreSQL ya tenga eventos")
    args = ap.parse_args()

    ruta = Path(args.sqlite)
    if not ruta.exists():
        sys.exit(f"No encontré la base SQLite: {ruta}")

    src = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    cols = {r["name"] for r in src.execute("PRAGMA table_info(evento_paso)")}
    if not cols:
        sys.exit(f"{ruta} no tiene la tabla evento_paso: no es una base del sistema.")
    if "empresa" in cols:
        sys.exit("La base SQLite está en el formato anterior (v0). Arranca una vez la versión "
                 "anterior del sistema para que la convierta, y vuelve a correr esto.")

    tipos_src = {r["id_tipo"]: r["codigo"] for r in src.execute("SELECT id_tipo, codigo FROM tipo_unidad")}
    unidades  = src.execute("SELECT * FROM unidad ORDER BY id_unidad").fetchall()
    eventos   = src.execute("SELECT * FROM evento_paso ORDER BY id_evento").fetchall()
    estancias = src.execute("SELECT * FROM estancia ORDER BY id_estancia").fetchall()
    print(f"SQLite {ruta}: {len(unidades)} unidades, {len(eventos)} eventos, {len(estancias)} estancias")

    storage.inicializar()     # esquema + padrón en PostgreSQL

    with storage._cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM evento_paso")
        ya = cur.fetchone()["n"]
        if ya and not args.forzar:
            sys.exit(f"PostgreSQL ya tiene {ya} eventos: la migración ya se hizo. "
                     "No hice nada (usa --forzar solo si sabes lo que haces).")

        cur.execute("SELECT codigo, id_tipo FROM tipo_unidad")
        tipos_pg = {r["codigo"]: r["id_tipo"] for r in cur.fetchall()}

        # Unidades: las del padrón ya están (por número); las demás se agregan fuera del padrón
        id_u = {}
        for u in unidades:
            cur.execute("SELECT id_unidad FROM unidad WHERE no_economico = %s", (u["no_economico"],))
            fila = cur.fetchone()
            if not fila:
                codigo = tipos_src.get(u["id_tipo"], "desconocido")
                cur.execute(
                    """INSERT INTO unidad (no_economico, empresa, id_tipo, en_padron)
                       VALUES (%s, %s, %s, FALSE) RETURNING id_unidad""",
                    (u["no_economico"], u["empresa"] or "Desconocida",
                     tipos_pg.get(codigo, tipos_pg["desconocido"])))
                fila = cur.fetchone()
            id_u[u["id_unidad"]] = fila["id_unidad"]

        # Eventos
        id_e = {}
        for e in eventos:
            cur.execute(
                """INSERT INTO evento_paso (id_unidad, direccion, id_puerta, zona, confianza,
                                            ruta_captura, hora_paso, hora_registro)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id_evento""",
                (id_u[e["id_unidad"]], e["direccion"], e["id_puerta"] or 1,
                 e["zona"] if e["zona"] in ZONAS_OK else "lateral",
                 max(0.0, min(1.0, float(e["confianza"] or 0))),
                 e["ruta_captura"], e["hora_paso"], e["hora_registro"] or e["hora_paso"]))
            id_e[e["id_evento"]] = cur.fetchone()["id_evento"]

        # Estancias
        for s in estancias:
            cur.execute(
                """INSERT INTO estancia (id_unidad, entrada_id, salida_id, hora_entrada, hora_salida)
                   VALUES (%s, %s, %s, %s, %s)""",
                (id_u[s["id_unidad"]], id_e.get(s["entrada_id"]), id_e.get(s["salida_id"]),
                 s["hora_entrada"], s["hora_salida"]))

        cur.execute("SELECT (SELECT COUNT(*) FROM evento_paso) AS ev, (SELECT COUNT(*) FROM estancia) AS es")
        r = cur.fetchone()
        esperado_ev = len(eventos) + (ya if args.forzar else 0)
        if r["ev"] != esperado_ev:
            raise RuntimeError(f"Los eventos no coinciden: SQLite {len(eventos)}, PostgreSQL {r['ev']}")
        print(f"PostgreSQL: {r['ev']} eventos, {r['es']} estancias. Migración completa.")


if __name__ == "__main__":
    main()
