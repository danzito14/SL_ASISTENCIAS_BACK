-- 2026_07_reid_grupos.sql — CRUD de cámaras de SEGUIMIENTO (reid).
-- grupos_dvr: agrupa cámaras por DVR/grabador; la contraseña vive UNA vez por grupo
-- (cifrada Fernet) → las cámaras del grupo la REUSAN (no repiten password). Cámaras de
-- DVRs distintos = grupos distintos con credenciales distintas.
-- Extiende la tabla camaras (de vigilancia) con: id_grupo_dvr, roi_poligono, params_reid,
-- y agrega el tipo 'seguimiento'. Idempotente.

CREATE TABLE IF NOT EXISTS grupos_dvr (
    id_grupo_dvr       SERIAL PRIMARY KEY,
    nombre             VARCHAR(100)    NOT NULL,
    id_empresa         INT             REFERENCES empresas(id_empresa)
                           ON UPDATE CASCADE ON DELETE CASCADE,
    host               VARCHAR(45),                 -- IP del DVR (opcional)
    usuario            VARCHAR(100),
    credencial_cifrada BYTEA,                        -- password del DVR, cifrado Fernet
    estado             estado_generico NOT NULL DEFAULT 'activo',
    fecha_creacion     TIMESTAMPTZ     DEFAULT NOW(),
    CONSTRAINT uq_grupo_dvr_empresa_nombre UNIQUE (id_empresa, nombre)
);

-- Nuevo tipo de cámara (ADD VALUE va fuera de transacción; no se usa en esta migración).
ALTER TYPE tipo_camara ADD VALUE IF NOT EXISTS 'seguimiento';

-- camaras: enlace al grupo (reusa credenciales) + ROI (polígono del piso) + params tracker.
ALTER TABLE camaras ADD COLUMN IF NOT EXISTS id_grupo_dvr INT
    REFERENCES grupos_dvr(id_grupo_dvr) ON DELETE SET NULL;
ALTER TABLE camaras ADD COLUMN IF NOT EXISTS roi_poligono TEXT;      -- "x1,y1;x2,y2;..."
ALTER TABLE camaras ADD COLUMN IF NOT EXISTS params_reid JSONB;      -- {min_alto,sim_umbral,kp_conf,...}

-- Grants para el rol de vigilancia (que ya maneja camaras) — CRUD de grupos_dvr.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_vigilancia') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON grupos_dvr TO svc_vigilancia;
        GRANT USAGE, SELECT ON SEQUENCE grupos_dvr_id_grupo_dvr_seq TO svc_vigilancia;
    END IF;
END $$;
