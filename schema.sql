-- ============================================================
-- CISA — Esquema SQLite (versión 1, normalizado)
-- Archivo: schema.sql (raíz del proyecto). ÚNICO esquema del sistema.
-- Lo aplica storage.inicializar() en cada arranque; si encuentra una
-- base del formato anterior, primero la migra (ver storage.py).
--
-- Reglas para no duplicar datos:
--   * El padrón NO vive aquí: su única fuente es padron.csv.
--     Al arrancar, storage.py sincroniza la tabla `unidad` con ese archivo.
--   * Los eventos y las estancias solo guardan id_unidad; la empresa y el
--     tipo se leen de `unidad` al consultar.
--   * Los números detectados que no están en el padrón también tienen su
--     fila en `unidad`, con en_padron = 0 y empresa 'Desconocida'.
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── Catálogo: tipo de unidad ─────────────────────────────────
CREATE TABLE IF NOT EXISTS tipo_unidad (
    id_tipo     INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo      TEXT    NOT NULL UNIQUE,
    descripcion TEXT
);
INSERT OR IGNORE INTO tipo_unidad (codigo, descripcion) VALUES
    ('electrica',   'Unidad eléctrica — batería'),
    ('diesel',      'Unidad diesel — combustión interna'),
    ('desconocido', 'Número detectado fuera del padrón');

-- ── Catálogo: puertas del patio ──────────────────────────────
CREATE TABLE IF NOT EXISTS puerta (
    id_puerta INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT    NOT NULL UNIQUE
);
INSERT OR IGNORE INTO puerta (id_puerta, nombre) VALUES (1, 'uno'), (2, 'dos');

-- ── Unidades (se llena desde padron.csv) ─────────────────────
CREATE TABLE IF NOT EXISTS unidad (
    id_unidad    INTEGER PRIMARY KEY AUTOINCREMENT,
    no_economico TEXT    NOT NULL UNIQUE,
    empresa      TEXT    NOT NULL DEFAULT 'Desconocida',
    id_tipo      INTEGER NOT NULL REFERENCES tipo_unidad(id_tipo),
    en_padron    INTEGER NOT NULL DEFAULT 1 CHECK (en_padron IN (0, 1))
);

-- ── Cada vez que una unidad cruza la línea ───────────────────
CREATE TABLE IF NOT EXISTS evento_paso (
    id_evento     INTEGER PRIMARY KEY AUTOINCREMENT,
    id_unidad     INTEGER NOT NULL REFERENCES unidad(id_unidad),
    direccion     TEXT    NOT NULL CHECK (direccion IN ('entrada','salida')),
    id_puerta     INTEGER NOT NULL DEFAULT 1 REFERENCES puerta(id_puerta),
    zona          TEXT    NOT NULL DEFAULT 'lateral'
                  CHECK (zona IN ('delantero','lateral','trasera')),
    confianza     REAL    NOT NULL DEFAULT 0.0 CHECK (confianza BETWEEN 0 AND 1),
    ruta_captura  TEXT,
    hora_paso     TEXT    NOT NULL,        -- 'YYYY-MM-DDTHH:MM:SS', hora local del patio
    hora_registro TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_ep_hora   ON evento_paso(hora_paso DESC);
CREATE INDEX IF NOT EXISTS idx_ep_unidad ON evento_paso(id_unidad, hora_paso);

-- ── Una fila por visita: se abre al entrar y se cierra al salir ──
-- Es un resumen derivado de evento_paso (entrada_id / salida_id);
-- duración y estatus se calculan solos, no se escriben.
CREATE TABLE IF NOT EXISTS estancia (
    id_estancia  INTEGER PRIMARY KEY AUTOINCREMENT,
    id_unidad    INTEGER NOT NULL REFERENCES unidad(id_unidad),
    entrada_id   INTEGER REFERENCES evento_paso(id_evento),
    salida_id    INTEGER REFERENCES evento_paso(id_evento),
    hora_entrada TEXT    NOT NULL,
    hora_salida  TEXT,                     -- NULL mientras sigue adentro
    minutos      REAL GENERATED ALWAYS AS (
        CASE WHEN hora_salida IS NOT NULL
        THEN ROUND((julianday(hora_salida) - julianday(hora_entrada)) * 1440.0, 1)
        END
    ) STORED,
    estatus      TEXT GENERATED ALWAYS AS (
        CASE WHEN hora_salida IS NULL THEN 'dentro' ELSE 'fuera' END
    ) VIRTUAL
);
CREATE INDEX IF NOT EXISTS idx_est_unidad  ON estancia(id_unidad, hora_entrada);
CREATE INDEX IF NOT EXISTS idx_est_abierta ON estancia(id_unidad) WHERE hora_salida IS NULL;
CREATE INDEX IF NOT EXISTS idx_est_entrada ON estancia(hora_entrada DESC);

-- ── Vistas que usa el código ─────────────────────────────────
-- Estancias con los datos de su unidad (base de todas las consultas)
CREATE VIEW IF NOT EXISTS v_estancia AS
SELECT s.id_estancia, s.id_unidad, u.no_economico, u.empresa,
       s.hora_entrada, s.hora_salida, s.minutos, s.estatus
FROM estancia s
JOIN unidad u ON u.id_unidad = s.id_unidad;

-- Eventos con los datos de su unidad
CREATE VIEW IF NOT EXISTS v_evento AS
SELECT e.id_evento, e.id_unidad, u.no_economico, u.empresa,
       t.codigo AS tipo_unidad, u.en_padron,
       e.direccion, e.id_puerta, e.zona, e.confianza,
       e.ruta_captura, e.hora_paso, e.hora_registro
FROM evento_paso e
JOIN unidad u      ON u.id_unidad = e.id_unidad
JOIN tipo_unidad t ON t.id_tipo   = u.id_tipo;

-- Unidades que están dentro del patio AHORA
CREATE VIEW IF NOT EXISTS v_dentro_ahora AS
SELECT no_economico, empresa, hora_entrada,
       ROUND((julianday('now','localtime') - julianday(hora_entrada)) * 1440.0, 1) AS minutos_dentro
FROM v_estancia
WHERE estatus = 'dentro'
ORDER BY hora_entrada;

-- Historial de estancias (con duración)
CREATE VIEW IF NOT EXISTS v_historial_estancias AS
SELECT no_economico, empresa, hora_entrada, hora_salida, minutos, estatus
FROM v_estancia
ORDER BY hora_entrada DESC;

-- Promedio de tiempo dentro por empresa (histórico)
CREATE VIEW IF NOT EXISTS v_promedio_estancia AS
SELECT empresa,
       COUNT(*)               AS total_visitas,
       ROUND(AVG(minutos), 1) AS promedio_minutos,
       ROUND(MIN(minutos), 1) AS minimo_minutos,
       ROUND(MAX(minutos), 1) AS maximo_minutos
FROM v_estancia
WHERE estatus = 'fuera'
GROUP BY empresa
ORDER BY empresa;

-- Números detectados que no están en el padrón
CREATE VIEW IF NOT EXISTS v_no_registrados AS
SELECT no_economico, empresa,
       COUNT(*)       AS veces,
       MAX(hora_paso) AS ultima_vez
FROM v_evento
WHERE en_padron = 0
GROUP BY no_economico
ORDER BY veces DESC;
