"""
metricas/storage.py
===================
Capa de persistencia CISA — PostgreSQL (base patio_cca en la Jetson).
Es el ÚNICO módulo que habla con la base de datos.

Conexión: DATABASE_URL del .env, por ejemplo
    DATABASE_URL=postgresql://usuario:contraseña@localhost:5432/patio_cca
(el contenedor usa la red de la Jetson, así que localhost es la Jetson).

Sin datos duplicados:
    * El esquema vive solo en metricas/schema.sql.
    * El padrón se edita en padron.csv (config.UNIDADES_INFO); al
      arrancar, la tabla `unidad` se sincroniza con ese archivo.
    * Eventos y estancias guardan solo id_unidad; número, empresa y
      tipo salen de `unidad` (vistas v_evento y v_estancia).
    * Marca, modelo, año y VIN salen del catálogo `cat`.

El histórico que estaba en SQLite (datos/detecciones.db) se pasa una
sola vez con scripts/migrar_sqlite_a_postgres.py.

Interfaz pública (la misma de siempre):
    inicializar(), cargar(), guardar_evento(ev), leer_eventos(),
    buscar_eventos(), empresas_eventos(), eventos_de_hoy(),
    total_acumulado(), ultima(), dentro_ahora(), historial_estancias(),
    promedio_estancia(), unidades_dentro_count(), estancias_rango(),
    estancias_del_dia(), trayectoria_unidad(), flujo_por_anio(),
    conteo_dentro_por_empresa(), promedio_estancia_por_empresa(),
    no_registrados_hoy()
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
(hora - INTERVAL '3 hours')::date  → ver _dia().
─────────────────────────────────────────────────────────────────
"""

import os
import re
import time
import threading
import logging
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, date, timedelta

import psycopg2
import psycopg2.extras

from config import HORA_CORTE_DIA, UNIDADES_VALIDAS, UNIDADES_INFO, ID_PUERTA, DATABASE_URL

log = logging.getLogger(__name__)

SCHEMA = Path(__file__).resolve().parent / "schema.sql"   # metricas/schema.sql

# ── Conexión por hilo ────────────────────────────────────────
_local     = threading.local()
_init_lock = threading.Lock()
_ready     = False

# Zona: se guarda el código y se muestra la etiqueta (único mapeo del sistema)
ZONAS = {"delantero": "Delantero", "trasera": "Trasero", "lateral": "Lateral"}


def _dsn_sin_clave(dsn: str) -> str:
    """Para los mensajes: la URL sin la contraseña."""
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", dsn)


def _conn():
    c = getattr(_local, "db", None)
    if c is None or c.closed:
        c = psycopg2.connect(
            DATABASE_URL,
            # misma hora que el patio para LOCALTIMESTAMP (v_dentro_ahora, hora_registro)
            options=f"-c timezone={os.getenv('TZ', 'America/Mexico_City')}",
            connect_timeout=5,
            application_name="cisa-vision",
        )
        _local.db = c
    return c


def _cerrar():
    c = getattr(_local, "db", None)
    _local.db = None
    if c is not None:
        try:
            c.close()
        except Exception:
            pass


def _texto(v):
    """Las horas salen como texto ISO ('YYYY-MM-DDTHH:MM:SS'), igual que antes."""
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    return v


def _fila(r) -> dict:
    return {k: _texto(v) for k, v in r.items()}


@contextmanager
def _cursor():
    """Una transacción: confirma al terminar, deshace si algo falla.
    Si se cayó la conexión, la tira para que la siguiente consulta reconecte."""
    c = _conn()
    try:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        c.commit()
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        _cerrar()
        raise
    except Exception:
        try:
            c.rollback()
        except Exception:
            _cerrar()
        raise


def _reintentar(fn):
    """Si PostgreSQL se reinició, la primera consulta falla con la conexión vieja:
    se reconecta y se intenta una vez más."""
    try:
        return fn()
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        log.warning("[DB] Se perdió la conexión con PostgreSQL; reconectando")
        return fn()


def _todas(sql: str, params=()) -> list[dict]:
    def q():
        with _cursor() as cur:
            cur.execute(sql, params)
            return [_fila(r) for r in cur.fetchall()]
    return _reintentar(q)


def _una(sql: str, params=()) -> dict | None:
    def q():
        with _cursor() as cur:
            cur.execute(sql, params)
            r = cur.fetchone()
            return _fila(r) if r else None
    return _reintentar(q)


def _valor(sql: str, params=()):
    r = _una(sql, params)
    return next(iter(r.values())) if r else None


# ════════════════════════════════════════════════════════════
# Día operativo — única implementación (metricas.py la usa)
# ════════════════════════════════════════════════════════════

def dia_operativo(dt: datetime = None) -> date:
    """Fecha operativa de un momento (por defecto, ahora)."""
    return ((dt or datetime.now()) - timedelta(hours=HORA_CORTE_DIA)).date()


def _dia_operativo_hoy() -> str:
    return dia_operativo().isoformat()


def _dia(col: str) -> str:
    """Expresión SQL con el día operativo de una columna de hora."""
    return f"(({col}) - INTERVAL '{int(HORA_CORTE_DIA)} hours')::date"


def _rango_fechas(rango: str) -> tuple[str, str]:
    """'hoy' | 'semana' | 'mes' | 'anio' → (fecha_inicio, fecha_fin) en ISO."""
    hoy = dia_operativo()
    dias = {"semana": 6, "mes": 29, "anio": 364}.get(rango, 0)
    return (hoy - timedelta(days=dias)).isoformat(), hoy.isoformat()


# ════════════════════════════════════════════════════════════
# Esquema y padrón
# ════════════════════════════════════════════════════════════

def _sincronizar_padron(cur):
    """La tabla `unidad` refleja padron.csv."""
    cur.execute("SELECT codigo, id_tipo FROM tipo_unidad")
    tipos = {r["codigo"]: r["id_tipo"] for r in cur.fetchall()}
    for numero, info in UNIDADES_INFO.items():
        if info["tipo"] not in tipos:
            raise ValueError(f"padron.csv: tipo '{info['tipo']}' no existe (unidad {numero})")
        cur.execute("""INSERT INTO unidad (no_economico, empresa, id_tipo, en_padron)
                       VALUES (%s, %s, %s, TRUE)
                       ON CONFLICT (no_economico) DO UPDATE
                       SET empresa = EXCLUDED.empresa, id_tipo = EXCLUDED.id_tipo, en_padron = TRUE""",
                    (numero, info["empresa"], tipos[info["tipo"]]))
    # Las que salieron del padrón se conservan (tienen historial), marcadas como fuera del padrón
    cur.execute("UPDATE unidad SET en_padron = FALSE WHERE en_padron AND NOT (no_economico = ANY(%s))",
                (sorted(UNIDADES_VALIDAS),))


def inicializar(intentos: int = 30, espera: float = 2.0):
    """Crea o actualiza el esquema y sincroniza el padrón. Si PostgreSQL
    todavía no arranca (p. ej. justo después de prender la Jetson), reintenta."""
    global _ready
    with _init_lock:
        if _ready:
            return
        for n in range(1, intentos + 1):
            try:
                _conn()
                break
            except psycopg2.OperationalError as e:
                if n == intentos:
                    log.error("[DB] No pude conectar a %s: %s", _dsn_sin_clave(DATABASE_URL), e)
                    raise
                log.warning("[DB] PostgreSQL no responde (intento %d/%d), reintento en %.0f s",
                            n, intentos, espera)
                time.sleep(espera)
        with _cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(4711)")   # un solo arranque a la vez
            cur.execute(SCHEMA.read_text(encoding="utf-8"))
            _sincronizar_padron(cur)
            cur.execute("SELECT COUNT(*) AS n FROM evento_paso")
            total = cur.fetchone()["n"]
        _ready = True
        log.info("[DB] Base lista: %s (%d eventos, padrón de %d unidades)",
                 _dsn_sin_clave(DATABASE_URL), total, len(UNIDADES_VALIDAS))
        print(f"[DB] PostgreSQL listo: {_dsn_sin_clave(DATABASE_URL)} — "
              f"{total} eventos, padrón de {len(UNIDADES_VALIDAS)} unidades")


# ════════════════════════════════════════════════════════════
# Traducción entre filas y el formato que usa metricas.py
# ════════════════════════════════════════════════════════════

def _fila_a_ev(row) -> dict:
    """Fila de v_evento → dict que espera metricas.py."""
    try:
        ts = datetime.fromisoformat(row["hora_paso"]).timestamp()
    except Exception:
        ts = datetime.now().timestamp()
    return {
        "id":         row["id_evento"],
        "hora_paso":  row["hora_paso"],
        "ts":         ts,
        "numero":     row["no_economico"],
        "empresa":    row["empresa"],
        "zona":       ZONAS.get(row["zona"], "Lateral"),
        "conf":       float(row["confianza"]),
        "frame":      row["ruta_captura"],
        "direccion":  row["direccion"],
        "en_padron":  bool(row["en_padron"]),
        "marca":      row.get("marca"),
        "modelo":     row.get("modelo"),
        "anio":       row.get("anio"),
    }


def _id_unidad(cur, numero: str, empresa: str = None) -> int:
    """id de la unidad; si el número no existe, lo da de alta fuera del padrón."""
    cur.execute("SELECT id_unidad, en_padron, empresa FROM unidad WHERE no_economico = %s", (numero,))
    fila = cur.fetchone()
    if fila:
        if empresa and not fila["en_padron"] and fila["empresa"] == "Desconocida":
            cur.execute("UPDATE unidad SET empresa = %s WHERE id_unidad = %s", (empresa, fila["id_unidad"]))
        return fila["id_unidad"]
    cur.execute(
        """INSERT INTO unidad (no_economico, empresa, id_tipo, en_padron)
           VALUES (%s, %s, (SELECT id_tipo FROM tipo_unidad WHERE codigo = 'desconocido'), FALSE)
           RETURNING id_unidad""",
        (numero, empresa or "Desconocida"))
    return cur.fetchone()["id_unidad"]


# ════════════════════════════════════════════════════════════
# Escritura
# ════════════════════════════════════════════════════════════

def _actualizar_estancia(cur, id_unidad: int, direccion: str, hora: str, id_evento: int):
    """
    entrada → abre una estancia.
    salida  → cierra la estancia abierta más reciente de la unidad. Si no
              hay ninguna (el sistema arrancó con el bus adentro), solo se
              registra el aviso: la salida queda en evento_paso.
    """
    if direccion == "entrada":
        cur.execute("INSERT INTO estancia (id_unidad, entrada_id, hora_entrada) VALUES (%s, %s, %s)",
                    (id_unidad, id_evento, hora))
    elif direccion == "salida":
        cur.execute(
            """SELECT id_estancia FROM estancia
               WHERE id_unidad = %s AND hora_salida IS NULL
               ORDER BY hora_entrada DESC LIMIT 1""", (id_unidad,))
        abierta = cur.fetchone()
        if abierta:
            cur.execute("UPDATE estancia SET salida_id = %s, hora_salida = %s WHERE id_estancia = %s",
                        (id_evento, hora, abierta["id_estancia"]))
        else:
            log.warning("[DB] Salida sin entrada previa (unidad id=%s, %s)", id_unidad, hora)


def guardar_evento(ev: dict):
    """
    Recibe el dict de metricas.py (numero, direccion, zona, conf, ts, frame)
    y, opcional, empresa (para un número fuera del padrón); lo guarda en
    evento_paso y actualiza la estancia, todo en una sola transacción.
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
    if not numero:
        raise ValueError("evento sin número económico")

    def escribir():
        with _cursor() as cur:
            id_unidad = _id_unidad(cur, numero, ev.get("empresa"))
            cur.execute(
                """INSERT INTO evento_paso
                       (id_unidad, direccion, id_puerta, zona, confianza, ruta_captura, hora_paso, hora_registro)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id_evento""",
                (id_unidad, dir_, ID_PUERTA, zona, conf, ev.get("frame") or None, hora, hora))
            id_evento = cur.fetchone()["id_evento"]
            _actualizar_estancia(cur, id_unidad, dir_, hora, id_evento)
            return id_evento

    id_evento = _reintentar(escribir)
    log.debug("[DB] evento %d  %s  %s  %s", id_evento, numero, dir_, hora)


# ════════════════════════════════════════════════════════════
# Lectura de eventos
# ════════════════════════════════════════════════════════════

def cargar() -> list[dict]:
    """Compatibilidad: devuelve los eventos recientes (ya no carga todo el histórico)."""
    return leer_eventos()


def leer_eventos(limite: int = 5000) -> list[dict]:
    """Los `limite` eventos más recientes, en orden cronológico."""
    rows = _todas("SELECT * FROM v_evento ORDER BY hora_paso DESC, id_evento DESC LIMIT %s",
                  (int(limite),))
    return [_fila_a_ev(r) for r in reversed(rows)]


def buscar_eventos(q: str = None, empresa: str = None,
                   desde: str = None, hasta: str = None,
                   cursor_hora: str = None, cursor_id: int = None,
                   limite: int = 10) -> tuple[list[dict], int]:
    """
    Eventos filtrados y paginados para el panel de detecciones.

    - q: busca por número económico y empresa (varias palabras = todas deben aparecer).
    - empresa: filtra por empresa exacta (sin distinguir mayúsculas).
    - desde/hasta: rango de días operativos en ISO (YYYY-MM-DD), inclusivo.
    - cursor_hora/cursor_id: paginación por llaves (no se salta filas si entran
      detecciones nuevas mientras se hace scroll).
    - Devuelve (eventos, total) donde `total` es el total del filtro, sin cursor.
    """
    where, params = [], []

    for token in (q or "").split():
        where.append("(strpos(lower(no_economico), lower(%s)) > 0 OR "
                     " strpos(lower(empresa), lower(%s)) > 0)")
        params += [token, token]

    if empresa:
        where.append("lower(empresa) = lower(%s)")
        params.append(empresa)

    if desde:
        where.append(f"{_dia('hora_paso')} >= %s")
        params.append(desde)

    if hasta:
        where.append(f"{_dia('hora_paso')} <= %s")
        params.append(hasta)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total = _valor("SELECT COUNT(*) AS n FROM v_evento" + where_sql, tuple(params))

    where_datos, params_datos = list(where), list(params)
    if cursor_hora and cursor_id is not None:
        where_datos.append("(hora_paso < %s OR (hora_paso = %s AND id_evento < %s))")
        params_datos += [cursor_hora, cursor_hora, int(cursor_id)]

    where_datos_sql = (" WHERE " + " AND ".join(where_datos)) if where_datos else ""
    rows = _todas(
        "SELECT * FROM v_evento" + where_datos_sql +
        " ORDER BY hora_paso DESC, id_evento DESC LIMIT %s",
        tuple(params_datos) + (max(1, int(limite)),))

    return [_fila_a_ev(r) for r in rows], total


def empresas_eventos() -> list[str]:
    """Empresas que aparecen en las detecciones, para el filtro del panel."""
    rows = _todas(
        "SELECT empresa FROM (SELECT DISTINCT empresa FROM v_evento "
        "                     WHERE empresa IS NOT NULL AND empresa <> '') t "
        "ORDER BY lower(empresa)")
    return [r["empresa"] for r in rows]


def eventos_de_hoy() -> list[dict]:
    """Eventos del día operativo actual."""
    rows = _todas(f"SELECT * FROM v_evento WHERE {_dia('hora_paso')} = %s ORDER BY hora_paso ASC",
                  (_dia_operativo_hoy(),))
    return [_fila_a_ev(r) for r in rows]


def total_acumulado() -> int:
    return _valor("SELECT COUNT(*) AS n FROM evento_paso")


def ultima() -> dict | None:
    row = _una("SELECT * FROM v_evento ORDER BY hora_paso DESC, id_evento DESC LIMIT 1")
    return _fila_a_ev(row) if row else None


# ════════════════════════════════════════════════════════════
# Estancias (dashboard)
# ════════════════════════════════════════════════════════════

def dentro_ahora() -> list[dict]:
    """Unidades actualmente dentro del patio con el tiempo transcurrido."""
    return _todas("SELECT * FROM v_dentro_ahora")


def historial_estancias(numero: str = None, limite: int = 100) -> list[dict]:
    """Historial de visitas con duración en minutos."""
    if numero:
        return _todas("SELECT * FROM v_historial_estancias WHERE no_economico = %s LIMIT %s",
                      (numero, int(limite)))
    return _todas("SELECT * FROM v_historial_estancias LIMIT %s", (int(limite),))


def promedio_estancia() -> list[dict]:
    """Tiempo promedio, mínimo y máximo dentro del patio por empresa."""
    return _todas("SELECT * FROM v_promedio_estancia")


def unidades_dentro_count() -> int:
    """Cuántas unidades hay dentro ahora (estancias abiertas del día operativo actual)."""
    return _valor(
        f"SELECT COUNT(*) AS n FROM estancia WHERE hora_salida IS NULL AND {_dia('hora_entrada')} = %s",
        (_dia_operativo_hoy(),))


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
    rows = _todas(
        f"""SELECT u.no_economico, u.empresa, MAX(e.hora_paso) AS hora_salida, COUNT(*) AS n
            FROM evento_paso e
            JOIN unidad u ON u.id_unidad = e.id_unidad
            WHERE e.direccion = 'salida'
              AND {_dia('e.hora_paso')} BETWEEN %s AND %s
              AND NOT EXISTS (SELECT 1 FROM estancia s WHERE s.salida_id = e.id_evento)
            GROUP BY u.id_unidad, u.no_economico, u.empresa""",
        (fecha_inicio, fecha_fin))
    return {r["no_economico"]: r for r in rows}


def estancias_rango(fecha_inicio: str, fecha_fin: str) -> list[dict]:
    """
    Una fila por unidad con sus movimientos en [fecha_inicio, fecha_fin]
    (días operativos). La estancia abierta MÁS RECIENTE de cada unidad se
    incluye siempre, aunque haya empezado antes del rango (un bus que entró
    ayer a las 23:40 y sigue dentro debe aparecer hoy). ROW_NUMBER() evita
    arrastrar estancias abiertas viejas que nunca se cerraron.
    """
    query = f"""
        WITH marcadas AS (
            SELECT no_economico, empresa, hora_entrada, hora_salida, estatus,
                   CASE WHEN hora_salida IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (hora_salida - hora_entrada))::float8 / 60.0
                   END AS minutos_tramo,
                   ROW_NUMBER() OVER (PARTITION BY id_unidad ORDER BY hora_entrada DESC) AS rn
            FROM v_estancia
        )
        SELECT no_economico, empresa, hora_entrada, hora_salida, estatus, minutos_tramo
        FROM marcadas
        WHERE {_dia('hora_entrada')} BETWEEN %s AND %s
           OR {_dia('hora_salida')} BETWEEN %s AND %s      -- entró otro día y salió en el rango
           OR (estatus = 'dentro' AND rn = 1)
        ORDER BY no_economico, hora_entrada ASC
    """
    rows = _todas(query, (fecha_inicio, fecha_fin, fecha_inicio, fecha_fin))
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
    rows = _todas(
        f"""SELECT no_economico, empresa, hora_entrada, hora_salida, estatus
            FROM v_estancia
            WHERE no_economico = %s AND {_dia('hora_entrada')} BETWEEN %s AND %s
            ORDER BY hora_entrada ASC""",
        (no_economico, fecha_inicio, fecha_fin))

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


def flujo_por_dia(fecha_inicio: date, fecha_fin: date) -> dict:
    """
    Entradas/salidas por día operativo entre dos fechas, inclusivo (agregado
    en SQL, sin el límite de leer_eventos()). Solo trae los días con cruces:
    {date(2026, 11, 18): {"entradas": 150, "salidas": 163}, ...}
    """
    rows = _todas(
        f"""SELECT {_dia('hora_paso')} AS dia, direccion, COUNT(*) AS cnt
            FROM evento_paso
            WHERE {_dia('hora_paso')} BETWEEN %s AND %s
            GROUP BY 1, 2""",
        (fecha_inicio.isoformat(), fecha_fin.isoformat()))

    flujo = {}
    for r in rows:
        if r["direccion"] in ("entrada", "salida"):
            d = date.fromisoformat(str(r["dia"]))
            flujo.setdefault(d, {"entradas": 0, "salidas": 0})[r["direccion"] + "s"] = int(r["cnt"])
    return flujo


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

    rows = _todas(
        f"""SELECT EXTRACT(YEAR  FROM {_dia('hora_paso')})::int AS anio,
                   EXTRACT(MONTH FROM {_dia('hora_paso')})::int AS mes,
                   direccion, COUNT(*) AS cnt
            FROM evento_paso
            WHERE {_dia('hora_paso')} >= %s
            GROUP BY 1, 2, 3""",
        (fecha_inicio,))

    flujo = {k: {"entradas": 0, "salidas": 0} for k in meses}
    for r in rows:
        k = (int(r["anio"]), int(r["mes"]))
        if k in flujo and r["direccion"] in ("entrada", "salida"):
            flujo[k][r["direccion"] + "s"] = r["cnt"]
    return [{"anio": y, "mes": m, **flujo[(y, m)]} for (y, m) in meses]


def conteo_dentro_por_empresa() -> dict:
    """{'CISA': N, 'COPATTSA': N, …} — unidades dentro ahora, día operativo actual."""
    rows = _todas(
        f"""SELECT empresa, COUNT(*) AS cnt FROM (
                SELECT empresa, estatus,
                       ROW_NUMBER() OVER (PARTITION BY id_unidad ORDER BY hora_entrada DESC) AS rn
                FROM v_estancia
                WHERE {_dia('hora_entrada')} = %s) t
            WHERE rn = 1 AND estatus = 'dentro'
            GROUP BY empresa""",
        (_dia_operativo_hoy(),))
    return {r["empresa"]: r["cnt"] for r in rows}


def promedio_estancia_por_empresa() -> dict:
    """{'CISA': 102.5, …} — promedio de minutos de las estancias cerradas de hoy."""
    rows = _todas(
        f"""SELECT empresa,
                   AVG(EXTRACT(EPOCH FROM (hora_salida - hora_entrada))::float8 / 60.0) AS prom
            FROM v_estancia
            WHERE {_dia('hora_entrada')} = %s AND hora_salida IS NOT NULL
            GROUP BY empresa""",
        (_dia_operativo_hoy(),))
    return {r["empresa"]: round(r["prom"], 1) for r in rows if r["prom"] is not None}


def no_registrados_hoy() -> int:
    """Números distintos detectados hoy que no están en el padrón."""
    return _valor(
        f"""SELECT COUNT(DISTINCT id_unidad) AS n FROM v_evento
            WHERE NOT en_padron AND {_dia('hora_paso')} = %s""",
        (_dia_operativo_hoy(),))
