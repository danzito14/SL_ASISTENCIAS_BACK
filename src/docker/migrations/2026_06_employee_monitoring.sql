-- ════════════════════════════════════════════════════════════════════════════
-- Migración: employee_monitoring (sincronización SYS21 → trabajadores/embeddings)
-- ────────────────────────────────────────────────────────────────────────────
-- init.sql solo corre cuando el volumen de Postgres está VACÍO. Para una BD ya
-- inicializada, aplica este script MANUALMENTE (idempotente, repetible sin error):
--
--   psql "$DATABASE_URL" -f src/docker/migrations/2026_06_employee_monitoring.sql
--
-- Cambios:
--   1) Columnas de identidad externa en trabajadores (id_emp, origen_nomina)
--   2) Tablas de estado del sync: sync_estado, fotos_pendientes
--   3) Índices
--   4) GRANTs a svc_workers (el rol con el que corre employee_monitoring)
-- ════════════════════════════════════════════════════════════════════════════

-- 1) Identidad EXTERNA de la nómina SYS21 en trabajadores --------------------
ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS id_emp        VARCHAR(50);
ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS origen_nomina VARCHAR(30);

-- Clasificación del área (oficina | empaque | campo) para el sync.
ALTER TABLE area_trabajo ADD COLUMN IF NOT EXISTS tipo_area VARCHAR(20);

-- Clave de conflicto del upsert del sync: única por (id_emp, origen_nomina),
-- parcial para permitir múltiples trabajadores manuales con id_emp NULL.
CREATE UNIQUE INDEX IF NOT EXISTS idx_trabajadores_id_emp
    ON trabajadores(id_emp, origen_nomina) WHERE id_emp IS NOT NULL;

-- 2) Estado operativo del sync ------------------------------------------------
CREATE TABLE IF NOT EXISTS sync_estado (
    id_sync                 SERIAL PRIMARY KEY,
    id_emp                  VARCHAR(50)  NOT NULL,
    origen_nomina           VARCHAR(30)  NOT NULL,
    id_empresa              INT,
    hash_datos              VARCHAR(64),
    hash_foto               VARCHAR(64),
    foto_mtime              BIGINT,
    foto_size               BIGINT,
    estado_foto             VARCHAR(20),
    visto_en_ultima_corrida BOOLEAN      NOT NULL DEFAULT FALSE,
    ultima_sync             TIMESTAMPTZ,
    ultima_sync_ok          TIMESTAMPTZ,
    UNIQUE (id_emp, origen_nomina)
);

CREATE TABLE IF NOT EXISTS fotos_pendientes (
    id_pendiente   SERIAL PRIMARY KEY,
    id_emp         VARCHAR(50)  NOT NULL,
    origen_nomina  VARCHAR(30)  NOT NULL,
    id_trabajador  INT          REFERENCES trabajadores(id_trabajador) ON DELETE CASCADE,
    id_empresa     INT,
    motivo         VARCHAR(40)  NOT NULL,
    detalle        TEXT,
    fecha          TIMESTAMPTZ  DEFAULT NOW(),
    estado         VARCHAR(15)  NOT NULL DEFAULT 'pendiente'
);

-- 3) Índices ------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_sync_estado_empresa
    ON sync_estado(id_empresa);
CREATE INDEX IF NOT EXISTS idx_fotos_pend_empresa_estado
    ON fotos_pendientes(id_empresa, estado);
CREATE INDEX IF NOT EXISTS idx_fotos_pend_emp
    ON fotos_pendientes(id_emp, origen_nomina);

-- 4) Permisos (svc_workers = rol de employee_monitoring) ----------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON
    sync_estado, fotos_pendientes
    TO svc_workers;
GRANT USAGE, SELECT ON SEQUENCE
    sync_estado_id_sync_seq,
    fotos_pendientes_id_pendiente_seq
    TO svc_workers;
