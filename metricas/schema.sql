-- ============================================================
-- CISA — Esquema PostgreSQL (base patio_cca)
-- Archivo: metricas/schema.sql. ÚNICO esquema del sistema.
-- Lo aplica storage.inicializar() en cada arranque; todo es
-- "IF NOT EXISTS" / "OR REPLACE", así que se puede correr siempre.
--
-- Reglas para no duplicar datos:
--   * El padrón se edita en padron.csv; al arrancar, storage.py
--     sincroniza la tabla `unidad` con ese archivo.
--   * Los eventos y las estancias solo guardan id_unidad; número,
--     empresa y tipo se leen de `unidad` al consultar.
--   * Los números detectados que no están en el padrón también tienen
--     su fila en `unidad`, con en_padron = FALSE.
--   * `cat` es el catálogo de unidades (VIN, marca, modelo, año, motor).
--     Se carga con scripts/cargar_cat.py; aquí solo se crea si no existe.
-- Las horas se guardan en hora local del patio (TIMESTAMP sin zona).
-- ============================================================

-- ── Catálogo de unidades (VIN, marca, modelo, año) ───────────
CREATE TABLE IF NOT EXISTS cat (
    eco        INTEGER     PRIMARY KEY,          -- número económico
    vin        VARCHAR(50) NOT NULL UNIQUE,
    destino    VARCHAR(15) NOT NULL,             -- empresa
    marca      VARCHAR(20) NOT NULL,
    modelo     VARCHAR(20) NOT NULL,
    anio       INTEGER,
    motor      VARCHAR(30),
    seriemotor VARCHAR(30)
);

-- ── Tipo de unidad ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tipo_unidad (
    id_tipo     SERIAL PRIMARY KEY,
    codigo      TEXT   NOT NULL UNIQUE,
    descripcion TEXT
);
INSERT INTO tipo_unidad (codigo, descripcion) VALUES
    ('electrica',   'Unidad eléctrica — batería'),
    ('diesel',      'Unidad diesel — combustión interna'),
    ('gasolina',    'Unidad de gasolina'),
    ('desconocido', 'Número detectado fuera del padrón')
ON CONFLICT (codigo) DO NOTHING;

-- ── Puertas del patio ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS puerta (
    id_puerta SERIAL PRIMARY KEY,
    nombre    TEXT   NOT NULL UNIQUE
);
INSERT INTO puerta (id_puerta, nombre) VALUES (1, 'uno'), (2, 'dos')
ON CONFLICT DO NOTHING;
SELECT setval(pg_get_serial_sequence('puerta', 'id_puerta'),
              GREATEST((SELECT MAX(id_puerta) FROM puerta), 1));

-- ── Unidades (se llena desde padron.csv) ─────────────────────
CREATE TABLE IF NOT EXISTS unidad (
    id_unidad    SERIAL  PRIMARY KEY,
    no_economico TEXT    NOT NULL UNIQUE,
    empresa      TEXT    NOT NULL DEFAULT 'Desconocida',
    id_tipo      INTEGER NOT NULL REFERENCES tipo_unidad(id_tipo),
    en_padron    BOOLEAN NOT NULL DEFAULT TRUE
);

-- ── Cada vez que una unidad cruza la línea ───────────────────
CREATE TABLE IF NOT EXISTS evento_paso (
    id_evento     SERIAL    PRIMARY KEY,
    id_unidad     INTEGER   NOT NULL REFERENCES unidad(id_unidad),
    direccion     TEXT      NOT NULL CHECK (direccion IN ('entrada','salida')),
    id_puerta     INTEGER   NOT NULL DEFAULT 1 REFERENCES puerta(id_puerta),
    zona          TEXT      NOT NULL DEFAULT 'lateral'
                  CHECK (zona IN ('delantero','lateral','trasera')),
    confianza     REAL      NOT NULL DEFAULT 0 CHECK (confianza BETWEEN 0 AND 1),
    ruta_captura  TEXT,
    hora_paso     TIMESTAMP(0) NOT NULL,
    hora_registro TIMESTAMP(0) NOT NULL DEFAULT LOCALTIMESTAMP(0)
);
CREATE INDEX IF NOT EXISTS idx_ep_hora   ON evento_paso (hora_paso DESC);
CREATE INDEX IF NOT EXISTS idx_ep_unidad ON evento_paso (id_unidad, hora_paso);

-- ── Una fila por visita: se abre al entrar y se cierra al salir ──
-- Resumen derivado de evento_paso (entrada_id / salida_id);
-- duración y estatus se calculan solos, no se escriben.
CREATE TABLE IF NOT EXISTS estancia (
    id_estancia  SERIAL  PRIMARY KEY,
    id_unidad    INTEGER NOT NULL REFERENCES unidad(id_unidad),
    entrada_id   INTEGER REFERENCES evento_paso(id_evento),
    salida_id    INTEGER REFERENCES evento_paso(id_evento),
    hora_entrada TIMESTAMP(0) NOT NULL,
    hora_salida  TIMESTAMP(0),                 -- NULL mientras sigue adentro
    minutos      DOUBLE PRECISION GENERATED ALWAYS AS (
        CASE WHEN hora_salida IS NOT NULL
        THEN ROUND((EXTRACT(EPOCH FROM (hora_salida - hora_entrada)) / 60.0)::numeric, 1)::float8
        END
    ) STORED,
    estatus      TEXT GENERATED ALWAYS AS (
        CASE WHEN hora_salida IS NULL THEN 'dentro' ELSE 'fuera' END
    ) STORED
);
CREATE INDEX IF NOT EXISTS idx_est_unidad  ON estancia (id_unidad, hora_entrada);
CREATE INDEX IF NOT EXISTS idx_est_abierta ON estancia (id_unidad) WHERE hora_salida IS NULL;
CREATE INDEX IF NOT EXISTS idx_est_entrada ON estancia (hora_entrada DESC);

-- ── Vistas que usa el código ─────────────────────────────────
-- Se borran y se vuelven a crear en cada arranque para que siempre
-- coincidan con este archivo.
DROP VIEW IF EXISTS v_no_registrados, v_promedio_estancia, v_historial_estancias,
                    v_dentro_ahora, v_evento, v_estancia;

-- Estancias con los datos de su unidad (base de todas las consultas)
CREATE VIEW v_estancia AS
SELECT s.id_estancia, s.id_unidad, u.no_economico, u.empresa,
       s.hora_entrada, s.hora_salida, s.minutos, s.estatus
FROM estancia s
JOIN unidad u ON u.id_unidad = s.id_unidad;

-- Eventos con los datos de su unidad y del catálogo
CREATE VIEW v_evento AS
SELECT e.id_evento, e.id_unidad, u.no_economico, u.empresa,
       t.codigo AS tipo_unidad, u.en_padron,
       e.direccion, e.id_puerta, e.zona, e.confianza,
       e.ruta_captura, e.hora_paso, e.hora_registro,
       TRIM(c.marca) AS marca, TRIM(c.modelo) AS modelo, c.anio, c.vin
FROM evento_paso e
JOIN unidad u      ON u.id_unidad = e.id_unidad
JOIN tipo_unidad t ON t.id_tipo   = u.id_tipo
LEFT JOIN cat c    ON c.eco::text = u.no_economico;

-- Unidades que están dentro del patio AHORA
CREATE VIEW v_dentro_ahora AS
SELECT no_economico, empresa, hora_entrada,
       ROUND((EXTRACT(EPOCH FROM (LOCALTIMESTAMP - hora_entrada)) / 60.0)::numeric, 1)::float8
           AS minutos_dentro
FROM v_estancia
WHERE estatus = 'dentro'
ORDER BY hora_entrada;

-- Historial de estancias (con duración)
CREATE VIEW v_historial_estancias AS
SELECT no_economico, empresa, hora_entrada, hora_salida, minutos, estatus
FROM v_estancia
ORDER BY hora_entrada DESC;

-- Promedio de tiempo dentro por empresa (histórico)
CREATE VIEW v_promedio_estancia AS
SELECT empresa,
       COUNT(*)                                   AS total_visitas,
       ROUND(AVG(minutos)::numeric, 1)::float8    AS promedio_minutos,
       ROUND(MIN(minutos)::numeric, 1)::float8    AS minimo_minutos,
       ROUND(MAX(minutos)::numeric, 1)::float8    AS maximo_minutos
FROM v_estancia
WHERE estatus = 'fuera'
GROUP BY empresa
ORDER BY empresa;

-- Números detectados que no están en el padrón
CREATE VIEW v_no_registrados AS
SELECT no_economico, empresa,
       COUNT(*)       AS veces,
       MAX(hora_paso) AS ultima_vez
FROM v_evento
WHERE NOT en_padron
GROUP BY no_economico, empresa
ORDER BY veces DESC;
