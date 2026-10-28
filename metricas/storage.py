"""
metricas/storage.py
===================
Capa de persistencia CISA — SQLite (Jetson Orin). Es el ÚNICO módulo
que habla con la base de datos.

Sin datos duplicados:
    * El esquema vive solo en schema.sql.
    * El padrón vive solo en padron.csv (config.UNIDADES_INFO); al
      arrancar, la tabla `unidad` se sincroniza con ese archivo.
    * Eventos y estancias guardan solo id_unidad; número, empresa y
      tipo salen de `unidad` (vistas v_evento y v_estancia).

Versiones del esquema (PRAGMA user_version):
    0 → formato anterior (empresa/tipo copiados en cada evento).
    1 → formato normalizado. inicializar() migra solo de 0 a 1 y,
        antes de tocar nada, guarda un respaldo completo de la base.

Interfaz pública (la misma de siempre):
    inicializar(), cargar(), guardar_evento(ev), leer_eventos(),
    eventos_de_hoy(), total_acumulado(), ultima(), dentro_ahora(),
    historial_estancias(), promedio_estancia(), unidades_dentro_count(),
    estancias_rango(), estancias_del_dia(), trayectoria_unidad(),
    flujo_por_anio(), conteo_dentro_por_empresa(),
    promedio_estancia_por_empresa(), no_registrados_hoy()
    + dia_operativo(dt): la única implementación del "día operativo".

── DÍA OPERATIVO ───────────────────────────────────────────────
El patio tiene turno nocturno: entran unidades ~23:00 y siguen
saliendo/entrando hasta la 1-2am. Se usa HORA_CORTE_DIA (config.py,
default 3) como frontera: toda actividad ANTES de esa hora cuenta como
parte del día anterior.
    23:40 del día 21  →  día operativo 21
    01:15 del día 22  →  día operativo 21 (sigue siendo la noche del 21)
    05:30 del día 22  →  día operativo 22
Las horas se guardan en hora local, así que en SQL basta con
DATE(hora, '-3 hours'). (Antes se usaba además 'localtime', que trata
la hora como UTC y la recorría otras 6 h: el corte real quedaba a las 9am.)
─────────────────────────────────────────────────────────────────
"""

import sqlite3
import threading
import logging
from pathlib import Path
from datetime import datetime, date, timedelta

from config import HORA_CORTE_DIA, UNIDADES_VALIDAS, UNIDADES_INFO, ID_PUERTA, DB_PATH

log = logging.getLogger(__name__)

# ── Rutas ────────────────────────────────────────────────────
_BASE   = Path(__file__).resolve().parent.parent
SCHEMA  = _BASE / "schema.sql"
VERSION_ESQUEMA = 1

# ── Conexión por hilo ────────────────────────────────────────
_local     = threading.local()
_init_lock = threading.Lock()
_ready     = False

# Desfase SQL del día operativo, ej. '-3 hours' → DATE(hora, ?)
_OFFSET = f"-{HORA_CORTE_DIA} hours"

# Zona: se guarda el código y se muestra la etiqueta (único mapeo del sistema)
ZONAS = {"delantero": "Delantero", "trasera": "Trasero", "lateral": "Lateral"}


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "db") or _local.db is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode = WAL;")
        c.execute("PRAGMA foreign_keys = ON;")
        _local.db = c
    return _local.db


# ════════════════════════════════════════════════════════════
# Día operativo — única implementación (metricas.py la usa)
# ════════════════════════════════════════════════════════════

def dia_operativo(dt: datetime = None) -> date:
    """Fecha operativa de un momento (por defecto, ahora)."""
    return ((dt or datetime.now()) - timedelta(hours=HORA_CORTE_DIA)).date()


def _dia_operativo_hoy() -> str:
    return dia_operativo().isoformat()


def _rango_fechas(rango: str) -> tuple[str, str]:
    """'hoy' | 'semana' | 'mes' | 'anio' → (fecha_inicio, fecha_fin) en ISO."""
    hoy = dia_operativo()
    dias = {"semana": 6, "mes": 29, "anio": 364}.get(rango, 0)
    return (hoy - timedelta(days=dias)).isoformat(), hoy.isoformat()


# ════════════════════════════════════════════════════════════
# Esquema: aplicar, migrar y sincronizar el padrón
# ════════════════════════════════════════════════════════════

def _sentencias(sql: str) -> list[str]:
    """Divide un script SQL en sentencias completas (sin los PRAGMA)."""
    salida, actual = [], ""
    for linea in sql.splitlines(keepends=True):
        actual += linea
        if sqlite3.complete_statement(actual):
            s = actual.strip()
            if s and not s.upper().startswith("PRAGMA"):
                salida.append(s)
            actual = ""
    return salida


def _columnas(c, tabla: str) -> set:
    return {r["name"] for r in c.execute(f"PRAGMA table_info({tabla})")}


def _es_formato_anterior(c) -> bool:
    return "empresa" in _columnas(c, "evento_paso")


def _respaldar(c) -> Path:
    destino = Path(DB_PATH).with_name(
        f"{Path(DB_PATH).stem}_respaldo_v0_{datetime.now():%Y%m%d_%H%M%S}.db")
    with sqlite3.connect(str(destino)) as copia:
        c.backup(copia)               # copia consistente, incluye lo que esté en el WAL
    return destino


def _migrar_v0_a_v1(c, schema_sql: str):
    """
    Formato anterior → normalizado. Conserva todos los ids, eventos y
    estancias. Los números que aparecen en eventos pero no en `unidad`
    se dan de alta con en_padron = 0. Si algo falla, no cambia nada.
    """
    respaldo = _respaldar(c)
    log.warning("[DB] Migrando la base al esquema v1. Respaldo: %s", respaldo)
    antes = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("evento_paso", "estancia")}

    c.commit()
    nivel = c.isolation_level
    c.isolation_level = None                       # transacción manual
    c.execute("PRAGMA foreign_keys = OFF")
    try:
        c.execute("BEGIN")
        for (v,) in c.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall():
            c.execute(f"DROP VIEW IF EXISTS {v}")
        for (i,) in c.execute("""SELECT name FROM sqlite_master WHERE type='index'
                                 AND sql IS NOT NULL
                                 AND tbl_name IN ('evento_paso','estancia','unidad')""").fetchall():
            c.execute(f"DROP INDEX IF EXISTS {i}")
        for t in ("evento_paso", "estancia", "unidad"):
            c.execute(f"ALTER TABLE {t} RENAME TO {t}_v0")

        for s in _sentencias(schema_sql):
            c.execute(s)

        c.execute("""INSERT INTO unidad (id_unidad, no_economico, empresa, id_tipo, en_padron)
                     SELECT id_unidad, no_economico, empresa, id_tipo, 1 FROM unidad_v0""")
        c.execute("""INSERT INTO unidad (no_economico, empresa, id_tipo, en_padron)
                     SELECT no_economico, MAX(empresa),
                            (SELECT id_tipo FROM tipo_unidad WHERE codigo = 'desconocido'), 0
                     FROM (SELECT no_economico, empresa FROM evento_paso_v0
                           UNION ALL
                           SELECT no_economico, empresa FROM estancia_v0)
                     WHERE no_economico NOT IN (SELECT no_economico FROM unidad)
                     GROUP BY no_economico""")
        c.execute("""INSERT INTO evento_paso (id_evento, id_unidad, direccion, id_puerta, zona,
                                              confianza, ruta_captura, hora_paso, hora_registro)
                     SELECT e.id_evento, u.id_unidad, e.direccion, e.id_puerta,
                            CASE WHEN e.zona IN ('delantero','lateral','trasera')
                                 THEN e.zona ELSE 'lateral' END,
                            e.confianza, e.ruta_captura, e.hora_paso, e.hora_registro
                     FROM evento_paso_v0 e JOIN unidad u ON u.no_economico = e.no_economico""")
        c.execute("""INSERT INTO estancia (id_estancia, id_unidad, entrada_id, salida_id,
                                           hora_entrada, hora_salida)
                     SELECT s.id_estancia, u.id_unidad, s.entrada_id, s.salida_id,
                            s.hora_entrada, s.hora_salida
                     FROM estancia_v0 s JOIN unidad u ON u.no_economico = s.no_economico""")

        despues = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                   for t in ("evento_paso", "estancia")}
        if despues != antes:
            raise RuntimeError(f"los conteos no coinciden: antes {antes}, después {despues}")

        for t in ("estancia_v0", "evento_paso_v0", "unidad_v0"):
            c.execute(f"DROP TABLE {t}")
        c.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        log.error("[DB] La migración falló; la base quedó como estaba. Respaldo: %s", respaldo)
        raise
    finally:
        c.execute("PRAGMA foreign_keys = ON")
        c.isolation_level = nivel

    problemas = c.execute("PRAGMA foreign_key_check").fetchall()
    if problemas:
        log.warning("[DB] Referencias rotas tras migrar: %d (revisar)", len(problemas))
    log.warning("[DB] Migración completa: %d eventos, %d estancias.",
                antes["evento_paso"], antes["estancia"])


def _sincronizar_padron(c):
    """La tabla `unidad` refleja padron.csv (única fuente del padrón)."""
    tipos = {r["codigo"]: r["id_tipo"] for r in c.execute("SELECT codigo, id_tipo FROM tipo_unidad")}
    for numero, info in UNIDADES_INFO.items():
        if info["tipo"] not in tipos:
            raise ValueError(f"padron.csv: tipo '{info['tipo']}' no existe (unidad {numero})")
        c.execute("""INSERT INTO unidad (no_economico, empresa, id_tipo, en_padron)
                     VALUES (?, ?, ?, 1)
                     ON CONFLICT(no_economico) DO UPDATE
                     SET empresa = excluded.empresa, id_tipo = excluded.id_tipo, en_padron = 1""",
                  (numero, info["empresa"], tipos[info["tipo"]]))
    # Las que salieron del padrón se conservan (tienen historial), marcadas como fuera del padrón
    marca = ",".join("?" * len(UNIDADES_VALIDAS))
    c.execute(f"UPDATE unidad SET en_padron = 0 WHERE en_padron = 1 AND no_economico NOT IN ({marca})",
              tuple(UNIDADES_VALIDAS))
    c.commit()


def inicializar():
    global _ready
    with _init_lock:
        if _ready:
            return
        c = _conn()
        schema_sql = SCHEMA.read_text(encoding="utf-8")
        existe = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='evento_paso'").fetchone()
        if existe and _es_formato_anterior(c):
            _migrar_v0_a_v1(c, schema_sql)
        else:
            c.executescript(schema_sql)
            c.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
        _sincronizar_padron(c)
        _ready = True
        total = c.execute("SELECT COUNT(*) FROM evento_paso").fetchone()[0]
        log.info("[DB] Base lista: %s (%d eventos, padrón de %d unidades)",
                 DB_PATH, total, len(UNIDADES_VALIDAS))


# ════════════════════════════════════════════════════════════
# Traducción entre filas y el formato que usa metricas.py
# ════════════════════════════════════════════════════════════

def _fila_a_ev(row) -> dict:
    """Fila de v_evento → dict que espera metricas.py."""
    try:
        ts = datetime.strptime(row["hora_paso"], "%Y-%m-%dT%H:%M:%S").timestamp()
    except Exception:
        ts = datetime.now().timestamp()
    return {
        "ts":        ts,
        "numero":    row["no_economico"],
        "empresa":   row["empresa"],
        "zona":      ZONAS.get(row["zona"], "Lateral"),
        "conf":      float(row["confianza"]),
        "frame":     row["ruta_captura"],
        "direccion": row["direccion"],
    }


def _id_unidad(c, numero: str) -> int:
    """id de la unidad; si el número no existe, lo da de alta fuera del padrón."""
    fila = c.execute("SELECT id_unidad FROM unidad WHERE no_economico = ?", (numero,)).fetchone()
    if fila:
        return fila["id_unidad"]
    return c.execute(
        """INSERT INTO unidad (no_economico, empresa, id_tipo, en_padron)
           VALUES (?, 'Desconocida', (SELECT id_tipo FROM tipo_unidad WHERE codigo = 'desconocido'), 0)""",
        (numero,)).lastrowid


# ════════════════════════════════════════════════════════════
# Escritura
# ════════════════════════════════════════════════════════════

def _actualizar_estancia(c: sqlite3.Connection, id_unidad: int, direccion: str,
                         hora: str, id_evento: int):
    """
    entrada → abre una estancia.
    salida  → cierra la estancia abierta más reciente de la unidad. Si no
              hay ninguna (el sistema arrancó con el bus adentro), solo se
              registra el aviso: la salida queda en evento_paso.
    """
    if direccion == "entrada":
        c.execute("INSERT INTO estancia (id_unidad, entrada_id, hora_entrada) VALUES (?, ?, ?)",
                  (id_unidad, id_evento, hora))
    elif direccion == "salida":
        abierta = c.execute(
            """SELECT id_estancia FROM estancia
               WHERE id_unidad = ? AND hora_salida IS NULL
               ORDER BY hora_entrada DESC LIMIT 1""", (id_unidad,)).fetchone()
        if abierta:
            c.execute("UPDATE estancia SET salida_id = ?, hora_salida = ? WHERE id_estancia = ?",
                      (id_evento, hora, abierta["id_estancia"]))
        else:
            log.warning("[DB] Salida sin entrada previa (unidad id=%s, %s)", id_unidad, hora)


def guardar_evento(ev: dict):
    """
    Recibe el dict de metricas.py (numero, direccion, zona, conf, ts, frame),
    lo guarda en evento_paso y actualiza la estancia.
    """
    try:
        hora = datetime.fromtimestamp(float(ev["ts"])).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        hora = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    numero = str(ev.get("numero") or "")
    zona   = ev.get("zona") if ev.get("zona") in ZONAS else "lateral"
    conf   = max(0.0, min(1.0, float(ev.get("conf") or 0.0)))
    dir_   = ev.get("direccion")
    if dir_ not in ("entrada", "salida"):
        raise ValueError(f"dirección inválida: {dir_!r}")   # no se inventa una entrada

    c = _conn()
    id_unidad = _id_unidad(c, numero)
    id_evento = c.execute(
        """INSERT INTO evento_paso
               (id_unidad, direccion, id_puerta, zona, confianza, ruta_captura, hora_paso, hora_registro)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (id_unidad, dir_, ID_PUERTA, zona, conf, ev.get("frame") or None, hora, hora),
    ).lastrowid
    _actualizar_estancia(c, id_unidad, dir_, hora, id_evento)
    c.commit()
    log.debug("[DB] evento %d  %s  %s  %s", id_evento, numero, dir_, hora)


# ════════════════════════════════════════════════════════════
# Lectura de eventos
# ════════════════════════════════════════════════════════════

def cargar() -> list[dict]:
    """Compatibilidad: devuelve los eventos recientes (ya no carga todo el histórico)."""
    return leer_eventos()


def leer_eventos(limite: int = 5000) -> list[dict]:
    """Los `limite` eventos más recientes, en orden cronológico."""
    rows = _conn().execute(
        "SELECT * FROM v_evento ORDER BY hora_paso DESC LIMIT ?", (limite,)).fetchall()
    return [_fila_a_ev(r) for r in reversed(rows)]


def eventos_de_hoy() -> list[dict]:
    """Eventos del día operativo actual."""
    rows = _conn().execute(
        "SELECT * FROM v_evento WHERE DATE(hora_paso, ?) = ? ORDER BY hora_paso ASC",
        (_OFFSET, _dia_operativo_hoy())).fetchall()
    return [_fila_a_ev(r) for r in rows]


def total_acumulado() -> int:
    return _conn().execute("SELECT COUNT(*) FROM evento_paso").fetchone()[0]


def ultima() -> dict | None:
    row = _conn().execute("SELECT * FROM v_evento ORDER BY hora_paso DESC LIMIT 1").fetchone()
    return _fila_a_ev(row) if row else None


# ════════════════════════════════════════════════════════════
# Estancias (dashboard)
# ════════════════════════════════════════════════════════════

def dentro_ahora() -> list[dict]:
    """Unidades actualmente dentro del patio con el tiempo transcurrido."""
    return [dict(r) for r in _conn().execute("SELECT * FROM v_dentro_ahora")]


def historial_estancias(numero: str = None, limite: int = 100) -> list[dict]:
    """Historial de visitas con duración en minutos."""
    c = _conn()
    if numero:
        rows = c.execute("SELECT * FROM v_historial_estancias WHERE no_economico = ? LIMIT ?",
                         (numero, limite)).fetchall()
    else:
        rows = c.execute("SELECT * FROM v_historial_estancias LIMIT ?", (limite,)).fetchall()
    return [dict(r) for r in rows]


def promedio_estancia() -> list[dict]:
    """Tiempo promedio, mínimo y máximo dentro del patio por empresa."""
    return [dict(r) for r in _conn().execute("SELECT * FROM v_promedio_estancia")]


def unidades_dentro_count() -> int:
    """Cuántas unidades hay dentro ahora (estancias abiertas del día operativo actual)."""
    return _conn().execute(
        "SELECT COUNT(*) FROM estancia WHERE hora_salida IS NULL AND DATE(hora_entrada, ?) = ?",
        (_OFFSET, _dia_operativo_hoy())).fetchone()[0]


def _agrupar_estancias(rows, salidas_sueltas=None) -> list[dict]:
    """
    Recibe filas de v_estancia (ya filtradas por rango, ordenadas por
    no_economico, hora_entrada ASC) y las agrupa en una fila por unidad.
    Completa con las unidades del padrón sin movimiento en el rango.
    """
    from collections import OrderedDict
    ahora    = datetime.now()
    unidades = OrderedDict()

    for r in rows:
        key = (r["no_economico"], r["empresa"])
        if key not in unidades:
            unidades[key] = {
                "no_economico":        r["no_economico"],
                "empresa":             r["empresa"],
                "primer_ingreso":      r["hora_entrada"],
                "ultimo_ingreso":      r["hora_entrada"],
                "ultima_salida":       r["hora_salida"],
                "viajes":              0,
                "min_dentro_cerradas": 0.0,
                "estatus":             r["estatus"],
            }
        u = unidades[key]
        u["viajes"]        += 1
        u["ultimo_ingreso"] = r["hora_entrada"]          # ASC → el último queda aquí
        if r["hora_salida"]:
            u["ultima_salida"] = r["hora_salida"]
            if r["minutos_tramo"]:
                u["min_dentro_cerradas"] += r["minutos_tramo"]
        u["estatus"] = r["estatus"]

    def fmt(iso_str):
        """Hora si es de hoy; fecha y hora si es de otro día."""
        if not iso_str:
            return None
        try:
            t = datetime.fromisoformat(iso_str)
        except Exception:
            return iso_str
        return t.strftime("%H:%M:%S") if t.date() == ahora.date() else t.strftime("%d/%m %H:%M")

    resultado = []
    for u in unidades.values():
        min_tramo_actual = 0.0
        if u["estatus"] == "dentro":
            try:
                t = datetime.fromisoformat(u["ultimo_ingreso"])
                min_tramo_actual = max(0.0, (ahora - t).total_seconds() / 60.0)
            except Exception:
                pass
        min_dentro_total = u["min_dentro_cerradas"] + min_tramo_actual
        min_fuera = None
        try:
            ventana   = (ahora - datetime.fromisoformat(u["primer_ingreso"])).total_seconds() / 60.0
            min_fuera = max(0.0, ventana - min_dentro_total)
        except Exception:
            pass
        resultado.append({
            "no_economico":           u["no_economico"],
            "empresa":                u["empresa"],
            "ultimo_ingreso":         fmt(u["ultimo_ingreso"]),
            "ultima_salida":          fmt(u["ultima_salida"]) if u["estatus"] == "fuera" else None,
            "minutos_dentro":         round(u["min_dentro_cerradas"], 1) if u["estatus"] == "fuera" else None,
            "minutos_dentro_previos": round(u["min_dentro_cerradas"], 1),
            "minutos_fuera":          round(min_fuera, 1) if min_fuera is not None else None,
            "viajes":                 u["viajes"],
            "status":                 u["estatus"],
            "sin_movimiento":         False,
            "ultimo_ingreso_iso":     u["ultimo_ingreso"],
            "ultimo_mov_iso":         (u["ultimo_ingreso"] if u["estatus"] == "dentro"
                                       else (u["ultima_salida"] or u["ultimo_ingreso"])),
        })

    # Salidas sin entrada registrada (la unidad ya estaba adentro): cuentan como 'fuera'
    con_estancia = {u["no_economico"] for u in resultado}
    for no_eco, s in (salidas_sueltas or {}).items():
        if no_eco in con_estancia:
            continue
        resultado.append({
            "no_economico":           no_eco,
            "empresa":                s["empresa"],
            "ultimo_ingreso":         None,
            "ultima_salida":          fmt(s["hora_salida"]),
            "minutos_dentro":         None,
            "minutos_dentro_previos": 0.0,
            "minutos_fuera":          None,
            "viajes":                 s["n"],
            "status":                 "fuera",
            "sin_movimiento":         False,
            "ultimo_ingreso_iso":     None,
            "ultimo_mov_iso":         s["hora_salida"],
        })

    # Unidades del padrón sin ningún movimiento en el rango: se listan como 'fuera'
    detectadas = {u["no_economico"] for u in resultado}
    for no_economico in UNIDADES_VALIDAS:
        if no_economico in detectadas:
            continue
        resultado.append({
            "no_economico":           no_economico,
            "empresa":                UNIDADES_INFO[no_economico]["empresa"],
            "ultimo_ingreso":         None,
            "ultima_salida":          None,
            "minutos_dentro":         None,
            "minutos_dentro_previos": 0.0,
            "minutos_fuera":          None,
            "viajes":                 0,
            "status":                 "fuera",
            "sin_movimiento":         True,
        })

    # Orden: dentro primero, luego fuera con actividad, luego sin movimiento;
    # en cada grupo, por último ingreso más reciente.
    # (con fecha y hora completas; sin movimiento, por número)
    resultado.sort(key=lambda x: (len(x["no_economico"]), x["no_economico"]))
    resultado.sort(key=lambda x: x.get("ultimo_mov_iso") or "", reverse=True)
    resultado.sort(key=lambda x: 0 if x["status"] == "dentro" else (1 if not x["sin_movimiento"] else 2))
    return resultado


def _salidas_sin_entrada(fecha_inicio: str, fecha_fin: str) -> dict:
    """Salidas del rango que no cerraron ninguna estancia (la unidad no se vio entrar)."""
    rows = _conn().execute(
        """SELECT u.no_economico, u.empresa, MAX(e.hora_paso) AS hora_salida, COUNT(*) AS n
           FROM evento_paso e
           JOIN unidad u ON u.id_unidad = e.id_unidad
           WHERE e.direccion = 'salida'
             AND DATE(e.hora_paso, ?) BETWEEN ? AND ?
             AND NOT EXISTS (SELECT 1 FROM estancia s WHERE s.salida_id = e.id_evento)
           GROUP BY e.id_unidad""",
        (_OFFSET, fecha_inicio, fecha_fin)).fetchall()
    return {r["no_economico"]: dict(r) for r in rows}


def estancias_rango(fecha_inicio: str, fecha_fin: str) -> list[dict]:
    """
    Una fila por unidad con sus movimientos en [fecha_inicio, fecha_fin]
    (días operativos). La estancia abierta MÁS RECIENTE de cada unidad se
    incluye siempre, aunque haya empezado antes del rango (un bus que entró
    ayer a las 23:40 y sigue dentro debe aparecer hoy). ROW_NUMBER() evita
    arrastrar estancias abiertas viejas que nunca se cerraron.
    """
    query = """
        WITH marcadas AS (
            SELECT no_economico, empresa, hora_entrada, hora_salida, estatus,
                   CASE WHEN hora_salida IS NOT NULL
                        THEN CAST((julianday(hora_salida) - julianday(hora_entrada)) * 1440 AS REAL)
                   END AS minutos_tramo,
                   ROW_NUMBER() OVER (PARTITION BY id_unidad ORDER BY hora_entrada DESC) AS rn
            FROM v_estancia
        )
        SELECT no_economico, empresa, hora_entrada, hora_salida, estatus, minutos_tramo
        FROM marcadas
        WHERE DATE(hora_entrada, ?) BETWEEN ? AND ?
           OR DATE(hora_salida, ?) BETWEEN ? AND ?      -- entró otro día y salió en el rango
           OR (estatus = 'dentro' AND rn = 1)
        ORDER BY no_economico, hora_entrada ASC
    """
    rows = _conn().execute(query, (_OFFSET, fecha_inicio, fecha_fin,
                                   _OFFSET, fecha_inicio, fecha_fin)).fetchall()
    return _agrupar_estancias(rows, _salidas_sin_entrada(fecha_inicio, fecha_fin))


def estancias_del_dia() -> list[dict]:
    """Compatibilidad: estancias del día operativo actual."""
    hoy = _dia_operativo_hoy()
    return estancias_rango(hoy, hoy)


def trayectoria_unidad(no_economico: str, rango: str = "hoy") -> dict:
    """
    Trayectoria SIN agregar de una unidad: cada tramo entrada → salida,
    para el timeline del frontend. rango: 'hoy' | 'semana' | 'mes' | 'anio'.
    Devuelve {no_economico, empresa, rango, fecha_inicio, fecha_fin, tramos:[
      {hora_entrada, hora_salida, minutos_dentro, minutos_fuera_antes, en_curso}]}
    """
    fecha_inicio, fecha_fin = _rango_fechas(rango)
    rows = _conn().execute(
        """SELECT no_economico, empresa, hora_entrada, hora_salida, estatus
           FROM v_estancia
           WHERE no_economico = ? AND DATE(hora_entrada, ?) BETWEEN ? AND ?
           ORDER BY hora_entrada ASC""",
        (no_economico, _OFFSET, fecha_inicio, fecha_fin)).fetchall()

    ahora   = datetime.now()
    empresa = rows[0]["empresa"] if rows else None
    tramos, salida_anterior = [], None
    for r in rows:
        t_entrada = t_salida = None
        try:
            t_entrada = datetime.fromisoformat(r["hora_entrada"])
        except Exception:
            pass
        if r["hora_salida"]:
            try:
                t_salida = datetime.fromisoformat(r["hora_salida"])
            except Exception:
                pass
        en_curso = r["estatus"] == "dentro"
        minutos_dentro = None
        if t_entrada and t_salida:
            minutos_dentro = round((t_salida - t_entrada).total_seconds() / 60.0, 1)
        elif t_entrada and en_curso:
            minutos_dentro = round((ahora - t_entrada).total_seconds() / 60.0, 1)
        minutos_fuera_antes = None
        if salida_anterior and t_entrada:
            minutos_fuera_antes = round((t_entrada - salida_anterior).total_seconds() / 60.0, 1)
        tramos.append({
            "hora_entrada":        r["hora_entrada"],
            "hora_salida":         r["hora_salida"],
            "minutos_dentro":      minutos_dentro,
            "minutos_fuera_antes": minutos_fuera_antes,
            "en_curso":            en_curso,
        })
        if t_salida:
            salida_anterior = t_salida

    return {"no_economico": no_economico, "empresa": empresa, "rango": rango,
            "fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin, "tramos": tramos}


def flujo_por_anio() -> list[dict]:
    """
    Entradas/salidas por mes de los últimos 12 meses (agregado en SQL, sin
    el límite de leer_eventos()). Lista cronológica con los 12 meses aunque
    tengan 0: [{"anio": 2025, "mes": 8, "entradas": 120, "salidas": 118}, ...]
    """
    hoy = dia_operativo()
    meses, y, m = [], hoy.year, hoy.month
    for _ in range(12):
        meses.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    meses.reverse()
    fecha_inicio = date(meses[0][0], meses[0][1], 1).isoformat()

    rows = _conn().execute(
        """SELECT strftime('%Y', hora_paso, ?) AS anio,
                  strftime('%m', hora_paso, ?) AS mes,
                  direccion, COUNT(*) AS cnt
           FROM evento_paso
           WHERE DATE(hora_paso, ?) >= ?
           GROUP BY anio, mes, direccion""",
        (_OFFSET, _OFFSET, _OFFSET, fecha_inicio)).fetchall()

    flujo = {k: {"entradas": 0, "salidas": 0} for k in meses}
    for r in rows:
        k = (int(r["anio"]), int(r["mes"]))
        if k in flujo and r["direccion"] in ("entrada", "salida"):
            flujo[k][r["direccion"] + "s"] = r["cnt"]
    return [{"anio": y, "mes": m, **flujo[(y, m)]} for (y, m) in meses]


def conteo_dentro_por_empresa() -> dict:
    """{'CISA': N, 'COPATSA': N, …} — unidades dentro ahora, día operativo actual."""
    rows = _conn().execute(
        """SELECT empresa, COUNT(*) AS cnt FROM (
               SELECT empresa, estatus,
                      ROW_NUMBER() OVER (PARTITION BY id_unidad ORDER BY hora_entrada DESC) AS rn
               FROM v_estancia
               WHERE DATE(hora_entrada, ?) = ?)
           WHERE rn = 1 AND estatus = 'dentro'
           GROUP BY empresa""",
        (_OFFSET, _dia_operativo_hoy())).fetchall()
    return {r["empresa"]: r["cnt"] for r in rows}


def promedio_estancia_por_empresa() -> dict:
    """{'CISA': 102.5, …} — promedio de minutos de las estancias cerradas de hoy."""
    rows = _conn().execute(
        """SELECT empresa,
                  AVG(CAST((julianday(hora_salida) - julianday(hora_entrada)) * 1440 AS REAL)) AS prom
           FROM v_estancia
           WHERE DATE(hora_entrada, ?) = ? AND hora_salida IS NOT NULL
           GROUP BY empresa""",
        (_OFFSET, _dia_operativo_hoy())).fetchall()
    return {r["empresa"]: round(r["prom"], 1) for r in rows if r["prom"] is not None}


def no_registrados_hoy() -> int:
    """Números distintos detectados hoy que no están en el padrón."""
    return _conn().execute(
        """SELECT COUNT(DISTINCT id_unidad) FROM v_evento
           WHERE en_padron = 0 AND DATE(hora_paso, ?) = ?""",
        (_OFFSET, _dia_operativo_hoy())).fetchone()[0]
