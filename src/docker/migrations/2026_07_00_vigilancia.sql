-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║  2026_07_vigilancia.sql                                                    ║
-- ║  Migración IDEMPOTENTE — microservicio `vigilancia` (FASE 1: solo tablas). ║
-- ║                                                                            ║
-- ║  Alcance ACTUAL = SOLO ASISTENCIA por reconocimiento facial desde cámaras/ ║
-- ║  terminales IP (captura por snapshot ISAPI HTTP; ffmpeg/RTSP NO decodifica ║
-- ║  este "HIK Media Server"). El control de PUERTAS (actuadores/comandos)     ║
-- ║  queda POSPUESTO — no se crea aquí.                                        ║
-- ║                                                                            ║
-- ║  Vigilancia es DELGADO: NO corre IA ni registra asistencia. Manda los      ║
-- ║  frames del terminal al scanner del back (POST /scanner/acceso/foto), que  ║
-- ║  reusa recognition + anti-spoof + escribe escaneos + consolida (svc_access);║
-- ║  aquí solo se procesa el ScanResponse y se loguea eventos_camara.          ║
-- ║                                                                            ║
-- ║  Aplicar como superusuario / dueño del esquema en la BD existente:         ║
-- ║    psql -U postgres -d SL_ASISTENCIAS -f 2026_07_vigilancia.sql            ║
-- ║  ⚠️  Cambia la contraseña placeholder (o usa ALTER ROLE ... PASSWORD).     ║
-- ╚══════════════════════════════════════════════════════════════════════════╝

-- ════════════════════════════════════════════════════════════════════════════
-- 1) ENUMs (idempotentes)
-- ════════════════════════════════════════════════════════════════════════════
DO $$
BEGIN
    -- Propósito de la cámara (por función, no por tipo físico). Hoy usamos 'asistencia';
    -- 'control_acceso'/'vigilancia' quedan para fases futuras.
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_camara') THEN
        CREATE TYPE tipo_camara AS ENUM ('asistencia', 'control_acceso', 'vigilancia');
    END IF;
    -- Desenlace de cada evento del motor de captura (bitácora eventos_camara).
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_evento_camara') THEN
        CREATE TYPE tipo_evento_camara AS ENUM (
            'movimiento',        -- el gate de movimiento se disparó
            'rostro_detectado',  -- había cara, aún sin evaluar match
            'baja_calidad',      -- cara detectada pero no pasó el gate (chica/de lado/borrosa)
            'match',             -- reconocido → generó escaneo/asistencia
            'no_match',          -- cara buena pero sin coincidencia en el roster
            'spoof',             -- anti-spoofing la rechazó
            'no_rostro',         -- frame sin rostro
            'error',             -- error de captura/proceso
            'sin_conexion'       -- no se pudo alcanzar la cámara
        );
    END IF;
END $$;

-- ════════════════════════════════════════════════════════════════════════════
-- 2) TABLA camaras — configuración de cada terminal/cámara de captura
-- ────────────────────────────────────────────────────────────────────────────
-- MULTI-TENANT: id_empresa denormalizado (aislamiento sin joins). id_puerta define
-- el PUNTO DE FICHAJE (de ahí salen empresa/área/tipo del escaneo); es NULL solo en
-- cámaras 'vigilancia'. Captura por snapshot ISAPI: se arma la URL con marca+canal
-- (o ruta_snapshot como override). La credencial va CIFRADA (Fernet), nunca en texto.
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS camaras (
    id_camara            SERIAL PRIMARY KEY,
    nombre               VARCHAR(100)   NOT NULL,
    id_empresa           INT            NOT NULL REFERENCES empresas(id_empresa)
                             ON UPDATE CASCADE ON DELETE CASCADE,
    id_area              INT            REFERENCES area_trabajo(id_area)
                             ON DELETE SET NULL,
    -- Punto de fichaje: define puerta/empresa/tipo del escaneo. Requerido para
    -- cámaras de asistencia (el motor lo valida); NULL solo en 'vigilancia'.
    id_puerta            INT            REFERENCES puertas_acceso(id_puerta)
                             ON DELETE SET NULL,
    -- Opcional: para poblar escaneos.id_dispositivo (auditoría de qué equipo fichó).
    id_dispositivo       INT            REFERENCES dispositivos(id_dispositivo)
                             ON DELETE SET NULL,
    -- ── Conexión (captura ISAPI HTTP) ────────────────────────────────────────
    marca                VARCHAR(20)    NOT NULL DEFAULT 'hikvision',  -- hikvision|dahua|generico
    host                 VARCHAR(45)    NOT NULL,                      -- IP del terminal
    puerto               INT            NOT NULL DEFAULT 80,           -- HTTP ISAPI (no 554/RTSP)
    canal                INT            NOT NULL DEFAULT 101,          -- 101 = cam1 main, 102 sub, 201 cam2...
    ruta_snapshot        TEXT,                                         -- override del path ISAPI (marcas raras)
    usuario              VARCHAR(60),
    credencial_cifrada   BYTEA,                                        -- password CIFRADA (Fernet), NUNCA texto plano
    -- ── Comportamiento ───────────────────────────────────────────────────────
    tipo_camara          tipo_camara    NOT NULL DEFAULT 'asistencia',
    tipo_registro        tipo_registro  NOT NULL DEFAULT 'entrada',    -- consolidar igual lo deriva
    habilitada           BOOLEAN        NOT NULL DEFAULT TRUE,
    -- Cómo captura: 'sondeo' (poll snapshot) o 'evento' (el terminal POSTea al webhook).
    modo_captura         VARCHAR(10)    NOT NULL DEFAULT 'sondeo' CHECK (modo_captura IN ('sondeo','evento')),
    gap_muestreo_seg     REAL           NOT NULL DEFAULT 0.7  CHECK (gap_muestreo_seg > 0),  -- entre snapshots
    umbral_movimiento    REAL           NOT NULL DEFAULT 2.5  CHECK (umbral_movimiento >= 0), -- diff medio "hay cambio"
    cooldown_seg         INT            NOT NULL DEFAULT 90   CHECK (cooldown_seg >= 0),      -- debounce/identidad (>=90 = dedupe servidor)
    -- ── Estado / telemetría ──────────────────────────────────────────────────
    estado               estado_dispositivo NOT NULL DEFAULT 'activo',
    ultima_conexion      TIMESTAMPTZ,
    ultimo_frame_ts      TIMESTAMPTZ,
    fecha_creacion       TIMESTAMPTZ    DEFAULT NOW(),
    CONSTRAINT uq_camara_empresa_nombre UNIQUE (id_empresa, nombre),
    CONSTRAINT uq_camara_empresa_host_canal UNIQUE (id_empresa, host, canal)
);
-- Idempotente para BDs que ya tenían la tabla (el CREATE de arriba la salta).
ALTER TABLE camaras
    ADD COLUMN IF NOT EXISTS modo_captura VARCHAR(10) NOT NULL DEFAULT 'sondeo';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_camara_modo_captura') THEN
        ALTER TABLE camaras ADD CONSTRAINT chk_camara_modo_captura
            CHECK (modo_captura IN ('sondeo','evento'));
    END IF;
END $$;

-- ════════════════════════════════════════════════════════════════════════════
-- 3) TABLA eventos_camara — bitácora/evidencia de lo que vio cada cámara
-- ────────────────────────────────────────────────────────────────────────────
-- UUIDv7 (offline-first, generable en el edge). id_escaneo/id_trabajador son
-- enlaces SUAVES (SIN FK): el escaneo/asistencia lo crea el pipeline y puede vivir
-- en otra BD a futuro. face_px = tamaño de cara detectada (auditoría de calidad).
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS eventos_camara (
    id_evento            UUID           PRIMARY KEY DEFAULT gen_uuid_v7(),
    id_camara            INT            NOT NULL REFERENCES camaras(id_camara)
                             ON DELETE CASCADE,
    id_empresa           INT            REFERENCES empresas(id_empresa)
                             ON UPDATE CASCADE ON DELETE CASCADE,
    id_puerta            INT            REFERENCES puertas_acceso(id_puerta)
                             ON DELETE SET NULL,
    tipo_evento          tipo_evento_camara NOT NULL,
    id_escaneo           UUID,          -- enlace SUAVE (sin FK) al escaneo generado
    id_trabajador        INT,           -- enlace SUAVE (sin FK): a quién se reconoció
    confianza            REAL           CHECK (confianza BETWEEN 0 AND 1),
    face_px              INT,           -- ancho aprox de la cara detectada (px)
    mensaje              TEXT,
    ruta_frame           TEXT,          -- dónde se guardó el frame (media), opcional
    fecha_hora           TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    creado_en_cliente    TIMESTAMPTZ,   -- hora del edge (UTC)
    sincronizado_en      TIMESTAMPTZ    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eventos_camara_cam_fecha  ON eventos_camara (id_camara, fecha_hora DESC);
CREATE INDEX IF NOT EXISTS idx_eventos_camara_emp_fecha  ON eventos_camara (id_empresa, fecha_hora DESC);
CREATE INDEX IF NOT EXISTS idx_eventos_camara_tipo       ON eventos_camara (tipo_evento);

-- ════════════════════════════════════════════════════════════════════════════
-- 4) ROL svc_vigilancia + GRANTs de mínimo privilegio
-- ────────────────────────────────────────────────────────────────────────────
-- Dueño de camaras/eventos_camara. Registra asistencia por el MISMO pipeline que
-- offline_sync (escaneos + funciones SECURITY DEFINER); el match lo hace el
-- servicio recognition (que lee embeddings), así que vigilancia NO necesita
-- embeddings ni escritura sobre asistencia/incidencias.
-- ════════════════════════════════════════════════════════════════════════════
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_vigilancia') THEN
        CREATE ROLE svc_vigilancia LOGIN PASSWORD 'CAMBIAR_vigilancia' CONNECTION LIMIT 15;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO svc_vigilancia;

-- Tablas propias (eventos_camara usa UUID → sin secuencia).
GRANT SELECT, INSERT, UPDATE, DELETE ON camaras, eventos_camara TO svc_vigilancia;
GRANT USAGE, SELECT ON SEQUENCE camaras_id_camara_seq TO svc_vigilancia;

-- Cruzados de solo lectura: resolver cámara→puerta/área/empresa/dispositivo y
-- nombre del trabajador reconocido para la bitácora.
GRANT SELECT ON empresas, area_trabajo, puertas_acceso, dispositivos, trabajadores
    TO svc_vigilancia;

-- vigilancia NO registra asistencia directo: manda los frames al scanner del back
-- (POST /scanner/acceso/foto|liveness), que reusa recognition + anti-spoof + escribe
-- escaneos + consolida (como svc_access). Por eso svc_vigilancia NO tiene grants sobre
-- escaneos/asistencia/intentos ni las funciones del pipeline; solo necesita gen_uuid_v7
-- para el PK UUIDv7 de su propia bitácora eventos_camara.
GRANT EXECUTE ON FUNCTION gen_uuid_v7() TO svc_vigilancia;

-- ════════════════════════════════════════════════════════════════════════════
-- 5) ROL DE APLICACIÓN 'vigilancia' (identity) — para el API detrás del gateway
-- ────────────────────────────────────────────────────────────────────────────
-- CRUD de cámaras + consulta de eventos. Idempotente.
-- ════════════════════════════════════════════════════════════════════════════
INSERT INTO roles (nombre_rol, descripcion, permisos, estado) VALUES
    ('vigilancia',
     'Gestión de cámaras/terminales de asistencia por reconocimiento facial + consulta de eventos.',
     '{"scopes": ["vigilancia:read", "vigilancia:write"]}'::jsonb,
     'activo'),
    ('vigilancia_edge',
     'Cuenta de servicio del motor de captura: manda frames al scanner del back (scanner:use).',
     '{"scopes": ["scanner:use"]}'::jsonb,
     'activo')
ON CONFLICT (nombre_rol) DO NOTHING;

-- ── Verificación ─────────────────────────────────────────────────────────────
--   SELECT grantee, privilege_type FROM information_schema.role_table_grants
--     WHERE grantee='svc_vigilancia' ORDER BY table_name, privilege_type;
--   \d camaras     \d eventos_camara
--   SELECT nombre_rol, permisos FROM roles WHERE nombre_rol = 'vigilancia';
