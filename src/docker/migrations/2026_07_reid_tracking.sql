-- 2026_07_reid_tracking.sql — SEGUIMIENTO CORPORAL cross-cámara (reid), PASO 1.
-- Objetivo: que la MISMA persona conserve un id GLOBAL entre cámaras (persona-N vale
-- igual en la cam 7 que en la cam 11). Hoy la galería del motor es en memoria y por
-- cámara → no hay identidad compartida. Aquí la galería pasa a ser COMPARTIDA en
-- pgvector (VECTOR(512), misma dim que buffalo_l; OSNet-AIN también es 512-D).
--
-- SIN identidad facial todavía: la persona es anónima (persona-N). id_trabajador queda
-- como columna NULL para el paso futuro (cuando la cámara de asistencia la identifique).
-- Retención 15 días (función purgar_reid). Idempotente.
CREATE EXTENSION IF NOT EXISTS vector;

-- ── reid_personas — el "cluster": una persona (anónima) agrupando sus firmas ──────
CREATE TABLE IF NOT EXISTS reid_personas (
    id_persona      SERIAL PRIMARY KEY,
    id_empresa      INT REFERENCES empresas(id_empresa) ON UPDATE CASCADE ON DELETE CASCADE,
    id_trabajador   INT,                       -- enlace SUAVE (sin FK); se llena en el PASO futuro (identidad)
    etiqueta        VARCHAR(60),               -- "persona-N" (o el nombre cuando se identifique)
    n_avistamientos INT             NOT NULL DEFAULT 0,
    primera_vez     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    ultima_vez      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    estado          estado_generico NOT NULL DEFAULT 'activo',
    fecha_creacion  TIMESTAMPTZ     DEFAULT NOW()
);

-- ── reid_firmas — GALERÍA COMPARTIDA de apariencia (vestimenta/cuerpo) ────────────
-- El match cross-cámara busca el vecino más cercano AQUÍ (sin importar la cámara).
-- Varias firmas por persona (distintas vistas/cámaras) enriquecen el re-emparejado.
CREATE TABLE IF NOT EXISTS reid_firmas (
    id_firma        BIGSERIAL PRIMARY KEY,
    id_persona      INT          NOT NULL REFERENCES reid_personas(id_persona) ON DELETE CASCADE,
    id_camara       INT          REFERENCES camaras(id_camara) ON DELETE SET NULL,
    id_empresa      INT,                        -- denormalizado: acota el match por empresa
    embedding       VECTOR(512)  NOT NULL,      -- firma OSNet-AIN L2-norm (apariencia)
    ruta_crop       TEXT,                       -- foto de la vestimenta registrada (opcional)
    fecha           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reid_firmas_hnsw
    ON reid_firmas USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_reid_firmas_persona       ON reid_firmas (id_persona);
CREATE INDEX IF NOT EXISTS idx_reid_firmas_empresa_fecha ON reid_firmas (id_empresa, fecha);

-- ── reid_avistamientos — LOG de dónde/cuándo se vio a cada persona ────────────────
-- UUIDv7 (offline-first, generable en el edge). Enlaces por FK a persona/cámara.
CREATE TABLE IF NOT EXISTS reid_avistamientos (
    id_avistamiento UUID        PRIMARY KEY DEFAULT gen_uuid_v7(),
    id_persona      INT         NOT NULL REFERENCES reid_personas(id_persona) ON DELETE CASCADE,
    id_camara       INT         REFERENCES camaras(id_camara) ON DELETE SET NULL,
    id_empresa      INT,
    fecha_hora      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    similitud       REAL,                       -- coseno contra la firma más cercana
    evento          VARCHAR(20) NOT NULL DEFAULT 'reaparece',  -- 'nueva' | 'reaparece'
    bbox            TEXT                         -- "x1,y1,x2,y2" en el frame
);
CREATE INDEX IF NOT EXISTS idx_reid_avist_persona_fecha ON reid_avistamientos (id_persona, fecha_hora DESC);
CREATE INDEX IF NOT EXISTS idx_reid_avist_empresa_fecha ON reid_avistamientos (id_empresa, fecha_hora DESC);
CREATE INDEX IF NOT EXISTS idx_reid_avist_camara_fecha  ON reid_avistamientos (id_camara, fecha_hora DESC);

-- ── Retención 15 días ────────────────────────────────────────────────────────────
-- Purga avistamientos/firmas viejos y las personas que quedaron sin firmas.
CREATE OR REPLACE FUNCTION purgar_reid(dias INT DEFAULT 15) RETURNS void AS $$
BEGIN
    DELETE FROM reid_avistamientos WHERE fecha_hora < NOW() - make_interval(days => dias);
    DELETE FROM reid_firmas        WHERE fecha       < NOW() - make_interval(days => dias);
    DELETE FROM reid_personas p
     WHERE p.ultima_vez < NOW() - make_interval(days => dias)
       AND NOT EXISTS (SELECT 1 FROM reid_firmas f WHERE f.id_persona = p.id_persona);
END;
$$ LANGUAGE plpgsql;

-- Agenda diaria con pg_cron (si está disponible). No fatal si falla.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule('purga_reid_diaria', '30 3 * * *', 'SELECT purgar_reid(15);');
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_cron: no se pudo agendar purga_reid (%); agéndala a mano.', SQLERRM;
END $$;

-- ── Grants para el rol de vigilancia (dueño del CRUD de cámaras/reid) ─────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_vigilancia') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON reid_personas, reid_firmas, reid_avistamientos TO svc_vigilancia;
        GRANT USAGE, SELECT ON SEQUENCE reid_personas_id_persona_seq TO svc_vigilancia;
        GRANT USAGE, SELECT ON SEQUENCE reid_firmas_id_firma_seq     TO svc_vigilancia;
        GRANT EXECUTE ON FUNCTION purgar_reid(INT) TO svc_vigilancia;
        GRANT EXECUTE ON FUNCTION gen_uuid_v7()    TO svc_vigilancia;
    END IF;
END $$;
