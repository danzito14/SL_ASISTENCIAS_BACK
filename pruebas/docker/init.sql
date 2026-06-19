-- ============================================================
-- EXTENSIONES  (deben ir primero)
-- ============================================================
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- ============================================================
-- Función para auto-actualizar fecha_actualizacion
-- ============================================================
CREATE OR REPLACE FUNCTION set_fecha_actualizacion()
RETURNS TRIGGER AS $$
BEGIN
  NEW.fecha_actualizacion = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- roles
-- ============================================================
CREATE TABLE roles (
    id_rol          SERIAL PRIMARY KEY,
    nombre_rol      VARCHAR(50)  UNIQUE NOT NULL,
    descripcion     TEXT,
    permisos        JSONB,
    estado          VARCHAR(10)  DEFAULT 'activo' CHECK (estado IN ('activo','inactivo')),
    fecha_creacion  TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- usuarios
-- ============================================================
CREATE TABLE usuarios (
    id_usuario          SERIAL PRIMARY KEY,
    nombre_usuario      VARCHAR(50)  UNIQUE NOT NULL,
    contrasena          VARCHAR(255) NOT NULL,
    id_rol              INT          NOT NULL REFERENCES roles(id_rol),
    estado              VARCHAR(10)  DEFAULT 'activo' CHECK (estado IN ('activo','inactivo')),
    fecha_creacion      TIMESTAMPTZ  DEFAULT NOW(),
    fecha_actualizacion TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TRIGGER trg_usuarios_updated
BEFORE UPDATE ON usuarios
FOR EACH ROW EXECUTE FUNCTION set_fecha_actualizacion();

-- ============================================================
-- empresas   (definición única, ya con geography)
-- ============================================================
CREATE TABLE empresas (
    id_empresa     SERIAL PRIMARY KEY,
    nombre_empresa VARCHAR(100)            NOT NULL,
    ubicacion      geography(POLYGON,4326),
    zona_horaria   TEXT                    NOT NULL,
    estado         TEXT                    NOT NULL,
    fecha_creacion TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- area_trabajo   (ya con id_empresa, hora_entrada y geography)
-- ============================================================
CREATE TABLE area_trabajo (
    id_area        SERIAL PRIMARY KEY,
    nombre_area    VARCHAR(100) UNIQUE NOT NULL,
    descripcion    TEXT,
    ubicacion      geography(POLYGON,4326),
    id_empresa     INT          REFERENCES empresas(id_empresa)
                       ON UPDATE CASCADE ON DELETE CASCADE,
    hora_entrada   TIME,
    estado         VARCHAR(10)  DEFAULT 'activo' CHECK (estado IN ('activo','inactivo')),
    fecha_creacion TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- trabajadores
-- ============================================================
CREATE TABLE trabajadores (
    id_trabajador       SERIAL PRIMARY KEY,
    nombre              VARCHAR(100) NOT NULL,
    apellido            VARCHAR(100) NOT NULL,
    id_area             INT          NOT NULL REFERENCES area_trabajo(id_area),
    foto_perfil         BYTEA,
    estado              VARCHAR(15)  DEFAULT 'activo' CHECK (estado IN ('activo','inactivo','suspendido')),
    fecha_creacion      TIMESTAMPTZ  DEFAULT NOW(),
    fecha_actualizacion TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_trabajadores_estado ON trabajadores(estado);

CREATE TRIGGER trg_trabajadores_updated
BEFORE UPDATE ON trabajadores
FOR EACH ROW EXECUTE FUNCTION set_fecha_actualizacion();

-- ============================================================
-- embeddings  (vector pgvector)
-- ============================================================
CREATE TABLE embeddings (
    id_embedding       SERIAL PRIMARY KEY,
    id_trabajador      INT            NOT NULL UNIQUE REFERENCES trabajadores(id_trabajador) ON DELETE CASCADE,
    vector_embedding   VECTOR(512),
    tipo_embedding     VARCHAR(10)    DEFAULT 'facial' CHECK (tipo_embedding IN ('facial','huella','iris')),
    fecha_captura      TIMESTAMPTZ    DEFAULT NOW(),
    calidad_embedding  DECIMAL(3,2)   CHECK (calidad_embedding BETWEEN 0 AND 1),
    modelo_ia          VARCHAR(100),
    estado             VARCHAR(10)    DEFAULT 'activo' CHECK (estado IN ('activo','inactivo'))
);

CREATE INDEX idx_embeddings_hnsw ON embeddings USING hnsw (vector_embedding vector_cosine_ops);

-- ============================================================
-- dispositivos   (ya con geography)
-- ============================================================
CREATE TABLE dispositivos (
    id_dispositivo     SERIAL PRIMARY KEY,
    nombre_dispositivo VARCHAR(100) NOT NULL,
    tipo_dispositivo   VARCHAR(20)  NOT NULL CHECK (tipo_dispositivo IN ('escaner_facial','huella','escaner_qr')),
    ip_dispositivo     VARCHAR(45)  UNIQUE,
    puerto             INT          DEFAULT 8080,
    ubicacion          geography(POINT,4326),
    id_area            INT          REFERENCES area_trabajo(id_area),
    estado             VARCHAR(15)  DEFAULT 'activo' CHECK (estado IN ('activo','inactivo','mantenimiento')),
    ultima_conexion    TIMESTAMPTZ,
    fecha_instalacion  DATE,
    fecha_creacion     TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_dispositivos_estado ON dispositivos(estado);

-- ============================================================
-- puertas_acceso   (ya con id_empresa y geography)
-- ============================================================
CREATE TABLE puertas_acceso (
    id_puerta             SERIAL PRIMARY KEY,
    nombre_puerta         VARCHAR(100) NOT NULL,
    ubicacion             geography(POINT,4326),
    id_area               INT          REFERENCES area_trabajo(id_area),
    id_empresa            INT          REFERENCES empresas(id_empresa)
                              ON UPDATE CASCADE ON DELETE CASCADE,
    id_dispositivo        INT          UNIQUE REFERENCES dispositivos(id_dispositivo),
    tipo_acceso           VARCHAR(15)  DEFAULT 'bidireccional' CHECK (tipo_acceso IN ('entrada','salida','bidireccional')),
    requiere_autorizacion BOOLEAN      DEFAULT FALSE,
    estado                VARCHAR(10)  DEFAULT 'activo' CHECK (estado IN ('activo','inactivo')),
    fecha_creacion        TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- asistencia   (ubicacion ya como geography)
-- ============================================================
CREATE TABLE asistencia (
    id_asistencia        SERIAL PRIMARY KEY,
    id_trabajador        INT          NOT NULL REFERENCES trabajadores(id_trabajador),
    id_puerta            INT          NOT NULL REFERENCES puertas_acceso(id_puerta),
    tipo_registro        VARCHAR(10)  NOT NULL CHECK (tipo_registro IN ('entrada','salida')),
    fecha_hora           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    confianza_biometrica DECIMAL(3,2) CHECK (confianza_biometrica BETWEEN 0 AND 1),
    estado_registro      VARCHAR(10)  DEFAULT 'exitoso' CHECK (estado_registro IN ('exitoso','rechazado','manual')),
    observaciones        TEXT,
    id_dispositivo       INT          REFERENCES dispositivos(id_dispositivo),
    ubicacion            geography(POINT,4326),
    fecha_creacion       TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_asistencia_trabajador  ON asistencia(id_trabajador);
CREATE INDEX idx_asistencia_fecha_hora  ON asistencia(fecha_hora);
CREATE INDEX idx_asistencia_tipo        ON asistencia(tipo_registro);
CREATE INDEX idx_asistencia_estado      ON asistencia(estado_registro);

-- ============================================================
-- escaneos   (definición única, ubicacion como geography)
--   El escáner registra TODO como 'entrada'.
-- ============================================================
CREATE TABLE escaneos (
    id_escaneo           SERIAL PRIMARY KEY,
    id_trabajador        INT          NOT NULL REFERENCES trabajadores(id_trabajador),
    id_puerta            INT          NOT NULL REFERENCES puertas_acceso(id_puerta),
    tipo_registro        VARCHAR(10)  NOT NULL CHECK (tipo_registro IN ('entrada','salida')),
    fecha_hora           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    confianza_biometrica NUMERIC(3,2) CHECK (confianza_biometrica BETWEEN 0 AND 1),
    estado_registro      VARCHAR(10)  DEFAULT 'exitoso' CHECK (estado_registro IN ('exitoso','rechazado','manual')),
    observaciones        TEXT,
    id_dispositivo       INT          REFERENCES dispositivos(id_dispositivo),
    ubicacion            geography(POINT,4326),
    fecha_creacion       TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_escaneo_trabajador ON escaneos(id_trabajador);
CREATE INDEX idx_escaneo_fecha_hora ON escaneos(fecha_hora);
CREATE INDEX idx_escaneos_tipo      ON escaneos(tipo_registro);
CREATE INDEX idx_escaneos_estado    ON escaneos(estado_registro);

-- ============================================================
-- incidencias   (NUEVA: con ruta_foto opcional)
-- ============================================================
CREATE TABLE incidencias (
    id_incidencia   SERIAL PRIMARY KEY,
    id_trabajador   INT          NOT NULL REFERENCES trabajadores(id_trabajador),
    tipo_incidencia VARCHAR(30)  NOT NULL CHECK (tipo_incidencia IN
                        ('salida_sin_registro','entrada_sin_registro','falta','retardo')),
    fecha           DATE         NOT NULL,
    descripcion     TEXT,
    ruta_foto       TEXT,                      -- opcional, multiuso
    id_escaneo_ref  INT          REFERENCES escaneos(id_escaneo),
    estado          VARCHAR(15)  DEFAULT 'pendiente' CHECK (estado IN ('pendiente','revisada','justificada')),
    fecha_creacion  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_incidencias_trabajador ON incidencias(id_trabajador);
CREATE INDEX idx_incidencias_fecha      ON incidencias(fecha);
CREATE INDEX idx_incidencias_tipo       ON incidencias(tipo_incidencia);

-- ============================================================
-- historial_auditoria
-- ============================================================
CREATE TABLE historial_auditoria (
    id_auditoria          SERIAL PRIMARY KEY,
    id_usuario            INT          REFERENCES usuarios(id_usuario),
    tabla_modificada      VARCHAR(100) NOT NULL,
    tipo_operacion        VARCHAR(10)  NOT NULL CHECK (tipo_operacion IN ('INSERT','UPDATE','DELETE','LOGIN','LOGOUT')),
    id_registro_afectado  INT,
    valores_anteriores    JSONB,
    valores_nuevos        JSONB,
    ip_origen             VARCHAR(45),
    user_agent            VARCHAR(255),
    fecha_hora            TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_auditoria_operacion ON historial_auditoria(tipo_operacion);
CREATE INDEX idx_auditoria_fecha     ON historial_auditoria(fecha_hora);
CREATE INDEX idx_auditoria_tabla     ON historial_auditoria(tabla_modificada);

-- ============================================================
-- parametros_sistema
-- ============================================================
CREATE TABLE parametros_sistema (
    id_parametro        SERIAL PRIMARY KEY,
    clave               VARCHAR(100) UNIQUE NOT NULL,
    valor               VARCHAR(500) NOT NULL,
    tipo                VARCHAR(10)  DEFAULT 'texto' CHECK (tipo IN ('numero','texto','booleano','json')),
    descripcion         TEXT,
    editable            BOOLEAN      DEFAULT TRUE,
    fecha_actualizacion TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TRIGGER trg_parametros_updated
BEFORE UPDATE ON parametros_sistema
FOR EACH ROW EXECUTE FUNCTION set_fecha_actualizacion();

-- ============================================================
-- FUNCIÓN: procesar el día
--   Por cada trabajador con escaneos hoy:
--     - 2 o más escaneos  -> el ÚLTIMO se registra como 'salida' en asistencia
--     - 1 solo escaneo     -> incidencia 'entrada_sin_registro'
--   Evita duplicados si el job corre dos veces el mismo día.
-- ============================================================
CREATE OR REPLACE FUNCTION procesar_salidas_dia()
RETURNS TABLE(salidas_registradas INT, incidencias_creadas INT)
LANGUAGE plpgsql
AS $$
DECLARE
    v_salidas     INT := 0;
    v_incidencias INT := 0;
BEGIN
    -- Conteo de escaneos válidos por trabajador en el día
    WITH conteo AS (
        SELECT e.id_trabajador, COUNT(*) AS n
        FROM escaneos e
        WHERE e.fecha_hora >= CURRENT_DATE
          AND e.fecha_hora <  CURRENT_DATE + INTERVAL '1 day'
          AND e.estado_registro IN ('exitoso','manual')
        GROUP BY e.id_trabajador
    ),
    -- El último escaneo del día de cada trabajador
    ultimo AS (
        SELECT DISTINCT ON (e.id_trabajador)
            e.id_escaneo, e.id_trabajador, e.id_puerta, e.fecha_hora,
            e.confianza_biometrica, e.estado_registro, e.observaciones,
            e.id_dispositivo, e.ubicacion
        FROM escaneos e
        WHERE e.fecha_hora >= CURRENT_DATE
          AND e.fecha_hora <  CURRENT_DATE + INTERVAL '1 day'
          AND e.estado_registro IN ('exitoso','manual')
        ORDER BY e.id_trabajador, e.fecha_hora DESC
    ),
    -- INSERT de salidas (trabajadores con 2+ escaneos)
    ins_salidas AS (
        INSERT INTO asistencia (
            id_trabajador, id_puerta, tipo_registro, fecha_hora,
            confianza_biometrica, estado_registro, observaciones,
            id_dispositivo, ubicacion
        )
        SELECT
            u.id_trabajador, u.id_puerta, 'salida', u.fecha_hora,
            u.confianza_biometrica, u.estado_registro, u.observaciones,
            u.id_dispositivo, u.ubicacion
        FROM ultimo u
        JOIN conteo c ON c.id_trabajador = u.id_trabajador
        WHERE c.n >= 2
          AND NOT EXISTS (
              SELECT 1 FROM asistencia a
              WHERE a.id_trabajador = u.id_trabajador
                AND a.tipo_registro = 'salida'
                AND a.fecha_hora >= CURRENT_DATE
                AND a.fecha_hora <  CURRENT_DATE + INTERVAL '1 day'
          )
        RETURNING 1
    ),
    -- INSERT de incidencias (trabajadores con 1 solo escaneo)
    ins_incid AS (
        INSERT INTO incidencias (
            id_trabajador, tipo_incidencia, fecha, descripcion, id_escaneo_ref
        )
        SELECT
            u.id_trabajador, 'entrada_sin_registro', CURRENT_DATE,
            'Solo se registró un escaneo en el día; sin salida detectable.',
            u.id_escaneo
        FROM ultimo u
        JOIN conteo c ON c.id_trabajador = u.id_trabajador
        WHERE c.n = 1
          AND NOT EXISTS (
              SELECT 1 FROM incidencias i
              WHERE i.id_trabajador = u.id_trabajador
                AND i.fecha = CURRENT_DATE
                AND i.tipo_incidencia = 'entrada_sin_registro'
          )
        RETURNING 1
    )
    SELECT
        (SELECT COUNT(*) FROM ins_salidas),
        (SELECT COUNT(*) FROM ins_incid)
    INTO v_salidas, v_incidencias;

    RAISE NOTICE 'Salidas: %, Incidencias: %', v_salidas, v_incidencias;
    salidas_registradas := v_salidas;
    incidencias_creadas := v_incidencias;
    RETURN NEXT;
END;
$$;

-- ============================================================
-- PROGRAMAR EL JOB (diario 11:30 PM)
-- ============================================================
SELECT cron.schedule(
    'procesar-salidas-diarias',
    '30 23 * * *',
    $$ SELECT procesar_salidas_dia(); $$
);