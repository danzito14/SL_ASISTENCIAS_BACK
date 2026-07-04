-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║  init.sql — Esquema consolidado SL_ASISTENCIAS                              ║
-- ║  Control de asistencia biométrico · multi-tenant · offline-first           ║
-- ║                                                                            ║
-- ║  Diseñado para: +20k trabajadores · múltiples empresas en una sola BD ·    ║
-- ║  sincronización desde APK offline (SQLite) vía microservicio.              ║
-- ║                                                                            ║
-- ║  Idempotente: se puede correr varias veces sin error.                      ║
-- ║  Requiere: PostgreSQL 17 + pgvector + PostGIS + pg_cron.                    ║
-- ╚══════════════════════════════════════════════════════════════════════════╝


-- ════════════════════════════════════════════════════════════════════════════
-- 0) EXTENSIONES  (deben ir primero)
-- ════════════════════════════════════════════════════════════════════════════
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_cron;


-- ════════════════════════════════════════════════════════════════════════════
-- 1) TIPOS ENUM NATIVOS
-- ────────────────────────────────────────────────────────────────────────────
-- Reemplazan los CHECK manuales del diseño viejo. Ventajas a escala:
--   · más compactos y rápidos en comparaciones masivas
--   · agregar un valor nuevo es ALTER TYPE ... ADD VALUE (no recrear constraint)
-- Idempotencia: cada tipo se crea solo si no existe (bloque DO).
-- ════════════════════════════════════════════════════════════════════════════

DO $$ BEGIN
    -- Estado genérico activo/inactivo (empresas, áreas, puertas, dispositivos…)
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_generico') THEN
        CREATE TYPE estado_generico AS ENUM ('activo', 'inactivo');
    END IF;

    -- Estado de trabajador (incluye 'suspendido')
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_trabajador') THEN
        CREATE TYPE estado_trabajador AS ENUM ('activo', 'inactivo', 'suspendido');
    END IF;

    -- Estado de dispositivo (incluye 'mantenimiento')
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_dispositivo') THEN
        CREATE TYPE estado_dispositivo AS ENUM ('activo', 'inactivo', 'mantenimiento');
    END IF;

    -- Tipo de registro de entrada/salida
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_registro') THEN
        CREATE TYPE tipo_registro AS ENUM ('entrada', 'salida');
    END IF;

    -- Estado de un registro de asistencia/escaneo
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_registro') THEN
        CREATE TYPE estado_registro AS ENUM (
            'exitoso', 'rechazado', 'manual', 'fuera_de_area', 'cancelado'
        );
    END IF;

    -- Tipo de incidencia. 'area_incorrecta' = permiso de escaneo incompatible
    -- con el tipo de puerta; 'acceso_otra_empresa' = tenant equivocado.
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_incidencia') THEN
        CREATE TYPE tipo_incidencia AS ENUM (
            'salida_sin_registro', 'entrada_sin_registro', 'falta', 'retardo',
            'fuera_de_area', 'acceso_otra_empresa', 'area_incorrecta'
        );
    END IF;

    -- Estado de revisión de una incidencia
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_incidencia') THEN
        CREATE TYPE estado_incidencia AS ENUM ('pendiente', 'revisada', 'justificada');
    END IF;

    -- Tipo de dispositivo físico
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_dispositivo') THEN
        CREATE TYPE tipo_dispositivo AS ENUM ('escaner_facial', 'huella', 'escaner_qr');
    END IF;

    -- Tipo de acceso de una puerta (dirección)
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_acceso') THEN
        CREATE TYPE tipo_acceso AS ENUM ('entrada', 'salida', 'bidireccional');
    END IF;

    -- ── NUEVO ── Tipo físico de puerta (reemplaza el número mágico 8080).
    -- 'mixta' = zonas como el empaque (pegado a oficinas pero entra gente de campo).
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_puerta') THEN
        CREATE TYPE tipo_puerta AS ENUM ('campo', 'administrativa', 'mixta');
    END IF;

    -- ── NUEVO ── Permiso/rango de escaneo del trabajador.
    --   campo          -> solo puertas 'campo' (y 'mixta')
    --   administrativo -> solo puertas 'administrativa' (y 'mixta')
    --   general        -> cualquier tipo de puerta, su propia empresa
    --   super          -> cualquier tipo de puerta, CUALQUIER empresa
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'permiso_escaneo') THEN
        CREATE TYPE permiso_escaneo AS ENUM ('campo', 'administrativo', 'general', 'super');
    END IF;

    -- ── NUEVO ── Función de la puerta: fichar asistencia vs. control de acceso.
    --   asistencia     -> registra entrada/salida (puertas actuales)
    --   control_acceso -> puerta INTERNA: valida permiso y da paso a una zona,
    --                     NO ficha asistencia (registra en accesos_internos)
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'funcion_puerta') THEN
        CREATE TYPE funcion_puerta AS ENUM ('asistencia', 'control_acceso');
    END IF;

    -- ── NUEVO ── Categoría de zona para control de acceso interno (genérico).
    --   La puerta interna da acceso a una de estas categorías.
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'categoria_zona') THEN
        CREATE TYPE categoria_zona AS ENUM ('oficina', 'empaque', 'mixto');
    END IF;

    -- ── NUEVO ── Nivel de acceso interno del trabajador.
    --   oficina -> entra a zonas 'oficina' (y 'mixto')
    --   empaque -> entra a zonas 'empaque' (y 'mixto')
    --   mixto   -> entra a ambas (oficina <-> empaque)
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'nivel_acceso_interno') THEN
        CREATE TYPE nivel_acceso_interno AS ENUM ('oficina', 'empaque', 'mixto');
    END IF;

    -- ── NUEVO ── Resultado de un intento de acceso por puerta interna.
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'resultado_acceso') THEN
        CREATE TYPE resultado_acceso AS ENUM ('permitido', 'negado');
    END IF;

    -- Tipo de embedding biométrico
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_embedding') THEN
        CREATE TYPE tipo_embedding AS ENUM ('facial', 'huella', 'iris');
    END IF;

    -- Tipo de operación en auditoría
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_operacion') THEN
        CREATE TYPE tipo_operacion AS ENUM ('INSERT','UPDATE','DELETE','LOGIN','LOGOUT');
    END IF;

    -- Tipo de parámetro de sistema
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_parametro') THEN
        CREATE TYPE tipo_parametro AS ENUM ('numero','texto','booleano','json');
    END IF;

    -- Tipo de intento de acceso RECHAZADO en una puerta de asistencia.
    --   spoofing     -> el anti-spoof lo rechazó (foto/pantalla/papel)
    --   desconocido  -> rostro detectado claro pero no enrolado en esa empresa
    --   otra_empresa -> match con un trabajador de OTRA empresa
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_intento') THEN
        CREATE TYPE tipo_intento AS ENUM ('spoofing', 'desconocido', 'otra_empresa');
    END IF;
END $$;


-- ════════════════════════════════════════════════════════════════════════════
-- 2) FUNCIÓN gen_uuid_v7()  —  UUIDv7 generado en el servidor
-- ────────────────────────────────────────────────────────────────────────────
-- PG17 no trae uuidv7() nativo (llega en PG18). Esta función produce UUIDv7
-- válidos (timestamp Unix ms en los primeros 48 bits => k-sortable, ideal para
-- índices B-tree y como cursor de sincronización).
--
-- El APK genera sus propios UUIDv7 offline; esta función cubre las filas que
-- nacen en el servidor (job nocturno, inserts administrativos, etc.).
-- ════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION gen_uuid_v7()
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
AS $$
DECLARE
    unix_ts_ms  BIGINT;
    uuid_bytes  BYTEA;
BEGIN
    unix_ts_ms := (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT;

    -- 16 bytes aleatorios derivados de gen_random_uuid() (núcleo PG13+,
    -- no requiere pgcrypto). Los primeros 6 se sobreescriben con el timestamp.
    uuid_bytes := uuid_send(gen_random_uuid());

    -- Primeros 6 bytes = timestamp en ms (48 bits) -> k-sortable
    uuid_bytes := set_byte(uuid_bytes, 0, ((unix_ts_ms >> 40) & 255)::int);
    uuid_bytes := set_byte(uuid_bytes, 1, ((unix_ts_ms >> 32) & 255)::int);
    uuid_bytes := set_byte(uuid_bytes, 2, ((unix_ts_ms >> 24) & 255)::int);
    uuid_bytes := set_byte(uuid_bytes, 3, ((unix_ts_ms >> 16) & 255)::int);
    uuid_bytes := set_byte(uuid_bytes, 4, ((unix_ts_ms >>  8) & 255)::int);
    uuid_bytes := set_byte(uuid_bytes, 5, ( unix_ts_ms        & 255)::int);

    -- Version 7: nibble alto del byte 6 = 0111
    uuid_bytes := set_byte(uuid_bytes, 6,
                  ((get_byte(uuid_bytes, 6) & 15) | 112)::int);
    -- Variant RFC 4122: dos bits altos del byte 8 = 10
    uuid_bytes := set_byte(uuid_bytes, 8,
                  ((get_byte(uuid_bytes, 8) & 63) | 128)::int);

    RETURN encode(uuid_bytes, 'hex')::uuid;
END;
$$;


-- ════════════════════════════════════════════════════════════════════════════
-- 3) FUNCIÓN set_fecha_actualizacion()  —  auto-touch de updated_at
-- ════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION set_fecha_actualizacion()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.fecha_actualizacion = NOW();
    RETURN NEW;
END;
$$;


-- ════════════════════════════════════════════════════════════════════════════
-- 4) TABLAS
-- ════════════════════════════════════════════════════════════════════════════

-- ── roles ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS roles (
    id_rol          SERIAL PRIMARY KEY,
    nombre_rol      VARCHAR(50)      UNIQUE NOT NULL,
    descripcion     TEXT,
    permisos        JSONB,
    estado          estado_generico  NOT NULL DEFAULT 'activo',
    fecha_creacion  TIMESTAMPTZ      DEFAULT NOW()
);

-- ── empresas ─────────────────────────────────────────────────────────────────
-- La empresa 99 (super-admin) está protegida por trigger (no borrar/desactivar).
CREATE TABLE IF NOT EXISTS empresas (
    id_empresa     SERIAL PRIMARY KEY,
    nombre_empresa VARCHAR(100)            NOT NULL,
    ubicacion      geography(POLYGON,4326),
    zona_horaria   TEXT                    NOT NULL,
    estado         estado_generico         NOT NULL DEFAULT 'activo',
    fecha_creacion TIMESTAMPTZ DEFAULT NOW()
);

-- ── usuarios ─────────────────────────────────────────────────────────────────
-- 'empresa' asocia al usuario con su tenant. FK e índices más abajo.
CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario           SERIAL PRIMARY KEY,
    nombre_usuario       VARCHAR(50)      UNIQUE NOT NULL,
    contrasena           VARCHAR(255)     NOT NULL,
    id_rol               INT              NOT NULL REFERENCES roles(id_rol),
    empresa              INT              NOT NULL DEFAULT 1,
    estado               estado_generico  NOT NULL DEFAULT 'activo',
    inactivo_por_cascada BOOLEAN          NOT NULL DEFAULT FALSE,
    fecha_creacion       TIMESTAMPTZ      DEFAULT NOW(),
    fecha_actualizacion  TIMESTAMPTZ      DEFAULT NOW()
);

-- ── area_trabajo ─────────────────────────────────────────────────────────────
-- MULTI-TENANT: nombre_area ya NO es único global, sino por empresa.
CREATE TABLE IF NOT EXISTS area_trabajo (
    id_area              SERIAL PRIMARY KEY,
    nombre_area          VARCHAR(100) NOT NULL,
    descripcion          TEXT,
    -- Clasificación operativa para el sync (employee_monitoring): grupo del área
    -- 'oficina' | 'empaque' | 'campo'. De aquí salen permiso_escaneo y
    -- nivel_acceso_interno por defecto del trabajador. NULL = sin clasificar.
    tipo_area            VARCHAR(20),
    ubicacion            geography(POLYGON,4326),
    id_empresa           INT          REFERENCES empresas(id_empresa)
                             ON UPDATE CASCADE ON DELETE CASCADE,
    hora_entrada         TIME,
    estado               estado_generico NOT NULL DEFAULT 'activo',
    inactivo_por_cascada BOOLEAN         NOT NULL DEFAULT FALSE,
    fecha_creacion       TIMESTAMPTZ     DEFAULT NOW(),
    CONSTRAINT uq_area_empresa_nombre UNIQUE (id_empresa, nombre_area)
);

-- ── dispositivos ─────────────────────────────────────────────────────────────
-- MULTI-TENANT: la IP es única POR EMPRESA (redes separadas pueden repetir IPs).
-- Para enlazar el dispositivo a su empresa lo hacemos vía su área; además
-- guardamos id_empresa denormalizado para el UNIQUE compuesto y consultas.
CREATE TABLE IF NOT EXISTS dispositivos (
    id_dispositivo       SERIAL PRIMARY KEY,
    nombre_dispositivo   VARCHAR(100)      NOT NULL,
    tipo_dispositivo     tipo_dispositivo  NOT NULL,
    ip_dispositivo       VARCHAR(45),
    puerto               INT               DEFAULT 8080,
    ubicacion            geography(POINT,4326),
    id_area              INT               REFERENCES area_trabajo(id_area)
                             ON DELETE CASCADE,
    id_empresa           INT               REFERENCES empresas(id_empresa)
                             ON UPDATE CASCADE ON DELETE CASCADE,
    estado               estado_dispositivo NOT NULL DEFAULT 'activo',
    inactivo_por_cascada BOOLEAN            NOT NULL DEFAULT FALSE,
    ultima_conexion      TIMESTAMPTZ,
    fecha_instalacion    DATE,
    fecha_creacion       TIMESTAMPTZ        DEFAULT NOW(),
    CONSTRAINT uq_disp_empresa_ip UNIQUE (id_empresa, ip_dispositivo)
);

-- ── puertas_acceso ───────────────────────────────────────────────────────────
-- NUEVO: tipo_puerta (campo/administrativa/mixta) reemplaza el número mágico 8080.
CREATE TABLE IF NOT EXISTS puertas_acceso (
    id_puerta             SERIAL PRIMARY KEY,
    nombre_puerta         VARCHAR(100) NOT NULL,
    ubicacion             geography(POINT,4326),
    id_area               INT          REFERENCES area_trabajo(id_area)
                              ON DELETE CASCADE,
    id_empresa            INT          REFERENCES empresas(id_empresa)
                              ON UPDATE CASCADE ON DELETE CASCADE,
    id_dispositivo        INT          UNIQUE REFERENCES dispositivos(id_dispositivo)
                              ON DELETE SET NULL,
    tipo_puerta           tipo_puerta  NOT NULL DEFAULT 'campo',
    funcion_puerta        funcion_puerta NOT NULL DEFAULT 'asistencia',
    -- Solo aplica si funcion_puerta='control_acceso': a qué categoría de zona
    -- da paso esta puerta interna. NULL para puertas de asistencia.
    categoria_zona_destino categoria_zona,
    tipo_acceso           tipo_acceso  NOT NULL DEFAULT 'bidireccional',
    requiere_autorizacion BOOLEAN      DEFAULT FALSE,
    estado                estado_generico NOT NULL DEFAULT 'activo',
    inactivo_por_cascada  BOOLEAN         NOT NULL DEFAULT FALSE,
    fecha_creacion        TIMESTAMPTZ     DEFAULT NOW()
);

-- ── trabajadores ─────────────────────────────────────────────────────────────
-- NUEVO: permiso_escaneo (campo/administrativo/general/super) default 'campo'.
-- id_empresa denormalizado para aislamiento multi-tenant sin joins.
CREATE TABLE IF NOT EXISTS trabajadores (
    id_trabajador        SERIAL PRIMARY KEY,
    -- Identidad EXTERNA en la nómina SYS21 (la sincroniza employee_monitoring).
    -- NULL en trabajadores creados manualmente vía workers. El par
    -- (id_emp, origen_nomina) es ÚNICO (idx_trabajadores_id_emp, parcial) y es la
    -- clave de conflicto del upsert del sync. VARCHAR para soportar id numérico o
    -- alfanumérico; origen_nomina distingue ASL_Nomina vs ASL_Nomina_COM.
    id_emp               VARCHAR(50),
    origen_nomina        VARCHAR(30),
    nombre               VARCHAR(100)      NOT NULL,
    apellido             VARCHAR(100)      NOT NULL,
    id_area              INT               NOT NULL REFERENCES area_trabajo(id_area)
                             ON DELETE CASCADE,
    id_empresa           INT               REFERENCES empresas(id_empresa)
                             ON UPDATE CASCADE ON DELETE CASCADE,
    permiso_escaneo      permiso_escaneo   NOT NULL DEFAULT 'campo',
    -- Nivel de acceso a zonas internas (puertas de control_acceso). Independiente
    -- de permiso_escaneo (que es para fichar). NULL = SIN acceso interno (lo típico
    -- de los de campo): evaluar_acceso_interno niega SIEMPRE a un nivel NULL, incluso
    -- en zonas 'mixto'. Solo administrativos/empaque llevan oficina/empaque/mixto.
    nivel_acceso_interno nivel_acceso_interno,
    foto_perfil          BYTEA,
    estado               estado_trabajador NOT NULL DEFAULT 'activo',
    inactivo_por_cascada BOOLEAN           NOT NULL DEFAULT FALSE,
    fecha_creacion       TIMESTAMPTZ       DEFAULT NOW(),
    fecha_actualizacion  TIMESTAMPTZ       DEFAULT NOW()
);

-- ── embeddings ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS embeddings (
    id_embedding         SERIAL PRIMARY KEY,
    id_trabajador        INT             NOT NULL UNIQUE REFERENCES trabajadores(id_trabajador)
                             ON DELETE CASCADE,
    vector_embedding     VECTOR(512),
    tipo_embedding       tipo_embedding  NOT NULL DEFAULT 'facial',
    fecha_captura        TIMESTAMPTZ     DEFAULT NOW(),
    calidad_embedding    REAL            CHECK (calidad_embedding BETWEEN 0 AND 1),
    modelo_ia            VARCHAR(100),
    estado               estado_generico NOT NULL DEFAULT 'activo',
    inactivo_por_cascada BOOLEAN         NOT NULL DEFAULT FALSE
);

-- ── sync_estado (employee_monitoring) ─────────────────────────────────────────
-- Estado OPERATIVO de la sincronización con la nómina SYS21. Una fila por
-- (id_emp, origen_nomina): guarda los hashes para detectar cambios de DATOS y de
-- FOTO (full-scan idempotente) y banderas de control de corrida. NO mapea a
-- id_trabajador: ese vínculo ya vive en trabajadores.id_emp.
CREATE TABLE IF NOT EXISTS sync_estado (
    id_sync                 SERIAL PRIMARY KEY,
    id_emp                  VARCHAR(50)  NOT NULL,
    origen_nomina           VARCHAR(30)  NOT NULL,
    id_empresa              INT,
    hash_datos              VARCHAR(64),
    hash_foto               VARCHAR(64),
    foto_mtime              BIGINT,        -- mtime remoto (SFTP) para detectar foto nueva sin descargar
    foto_size               BIGINT,        -- tamaño remoto (SFTP), idem
    estado_foto             VARCHAR(20),   -- 'ok' | 'pendiente' | 'sin_foto'
    visto_en_ultima_corrida BOOLEAN      NOT NULL DEFAULT FALSE,
    ultima_sync             TIMESTAMPTZ,
    ultima_sync_ok          TIMESTAMPTZ,
    UNIQUE (id_emp, origen_nomina)
);

-- ── fotos_pendientes (employee_monitoring) ────────────────────────────────────
-- Empleados cuya foto NO pasó las reglas de validación: hay que volver a tomarla.
-- La llena el sync con el motivo del rechazo; un admin la consulta por endpoint.
CREATE TABLE IF NOT EXISTS fotos_pendientes (
    id_pendiente   SERIAL PRIMARY KEY,
    id_emp         VARCHAR(50)  NOT NULL,
    origen_nomina  VARCHAR(30)  NOT NULL,
    id_trabajador  INT          REFERENCES trabajadores(id_trabajador) ON DELETE CASCADE,
    id_empresa     INT,
    -- formato_invalido | resolucion_baja | archivo_corrupto | archivo_grande |
    -- sin_foto | no_rostro | spoofing | recognition_no_disponible | duplicado | area_invalida
    motivo         VARCHAR(40)  NOT NULL,
    detalle        TEXT,
    fecha          TIMESTAMPTZ  DEFAULT NOW(),
    estado         VARCHAR(15)  NOT NULL DEFAULT 'pendiente'  -- 'pendiente' | 'resuelto' | 'ignorado'
);

-- ── escaneos ─────────────────────────────────────────────────────────────────
-- OFFLINE-FIRST: PK = UUIDv7 (generado en cliente o servidor).
--   · creado_en_cliente   = hora REAL del evento en el dispositivo
--   · sincronizado_en     = cuándo llegó al servidor (puede ser horas después)
--   · id_dispositivo_origen = qué kiosko/celular lo generó (auditoría de sync)
--   · dentro_de_area       = flag que el APK pre-calcula (point-in-polygon local);
--                            el servidor lo re-audita con PostGIS.
--   · id_empresa denormalizado para aislamiento multi-tenant.
-- Ingesta idempotente: INSERT ... ON CONFLICT (id_escaneo) DO NOTHING.
CREATE TABLE IF NOT EXISTS escaneos (
    id_escaneo            UUID          PRIMARY KEY DEFAULT gen_uuid_v7(),
    id_trabajador         INT           NOT NULL REFERENCES trabajadores(id_trabajador)
                              ON DELETE CASCADE,
    id_puerta             INT           NOT NULL REFERENCES puertas_acceso(id_puerta)
                              ON DELETE CASCADE,
    id_empresa            INT           REFERENCES empresas(id_empresa)
                              ON UPDATE CASCADE ON DELETE CASCADE,
    tipo_registro         tipo_registro NOT NULL,
    fecha_hora            TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    confianza_biometrica  REAL          CHECK (confianza_biometrica BETWEEN 0 AND 1),
    estado_registro       estado_registro NOT NULL DEFAULT 'exitoso',
    dentro_de_area        BOOLEAN,
    observaciones         TEXT,
    id_dispositivo        INT           REFERENCES dispositivos(id_dispositivo)
                              ON DELETE SET NULL,
    id_dispositivo_origen INT,
    ubicacion             geography(POINT,4326),
    creado_en_cliente     TIMESTAMPTZ,
    sincronizado_en       TIMESTAMPTZ   DEFAULT NOW(),
    fecha_creacion        TIMESTAMPTZ   DEFAULT NOW()
);

-- ── asistencia ───────────────────────────────────────────────────────────────
-- Misma estrategia offline-first / UUIDv7 que escaneos.
CREATE TABLE IF NOT EXISTS asistencia (
    id_asistencia         UUID          PRIMARY KEY DEFAULT gen_uuid_v7(),
    id_trabajador         INT           NOT NULL REFERENCES trabajadores(id_trabajador)
                              ON DELETE CASCADE,
    id_puerta             INT           NOT NULL REFERENCES puertas_acceso(id_puerta)
                              ON DELETE CASCADE,
    id_empresa            INT           REFERENCES empresas(id_empresa)
                              ON UPDATE CASCADE ON DELETE CASCADE,
    tipo_registro         tipo_registro NOT NULL,
    fecha_hora            TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    confianza_biometrica  REAL          CHECK (confianza_biometrica BETWEEN 0 AND 1),
    estado_registro       estado_registro NOT NULL DEFAULT 'exitoso',
    dentro_de_area        BOOLEAN,
    observaciones         TEXT,
    id_dispositivo        INT           REFERENCES dispositivos(id_dispositivo)
                              ON DELETE SET NULL,
    id_dispositivo_origen INT,
    ubicacion             geography(POINT,4326),
    creado_en_cliente     TIMESTAMPTZ,
    sincronizado_en       TIMESTAMPTZ   DEFAULT NOW(),
    fecha_creacion        TIMESTAMPTZ   DEFAULT NOW()
);

-- ── incidencias ──────────────────────────────────────────────────────────────
-- UUIDv7. id_escaneo_ref ahora es UUID (apunta a escaneos.id_escaneo).
CREATE TABLE IF NOT EXISTS incidencias (
    id_incidencia         UUID            PRIMARY KEY DEFAULT gen_uuid_v7(),
    id_trabajador         INT             NOT NULL REFERENCES trabajadores(id_trabajador)
                              ON DELETE CASCADE,
    id_empresa            INT             REFERENCES empresas(id_empresa)
                              ON UPDATE CASCADE ON DELETE CASCADE,
    tipo_incidencia       tipo_incidencia NOT NULL,
    fecha                 DATE            NOT NULL,
    descripcion           TEXT,
    ruta_foto             TEXT,
    id_escaneo_ref        UUID            REFERENCES escaneos(id_escaneo)
                              ON DELETE SET NULL,
    estado                estado_incidencia NOT NULL DEFAULT 'pendiente',
    creado_en_cliente     TIMESTAMPTZ,
    sincronizado_en       TIMESTAMPTZ     DEFAULT NOW(),
    fecha_creacion        TIMESTAMPTZ     DEFAULT NOW()
);

-- ── accesos_internos ─────────────────────────────────────────────────────────
-- Registro de paso por puertas INTERNAS (funcion_puerta='control_acceso').
-- NO es asistencia: es un log de "quién intentó entrar a qué zona y si se le
-- permitió". Separado de 'asistencia' para no ensuciar los reportes de fichaje.
-- UUIDv7 + columnas de sync por consistencia y futuro offline.
CREATE TABLE IF NOT EXISTS accesos_internos (
    id_acceso             UUID             PRIMARY KEY DEFAULT gen_uuid_v7(),
    id_trabajador         INT              NOT NULL REFERENCES trabajadores(id_trabajador)
                              ON DELETE CASCADE,
    id_puerta             INT              NOT NULL REFERENCES puertas_acceso(id_puerta)
                              ON DELETE CASCADE,
    id_empresa            INT              REFERENCES empresas(id_empresa)
                              ON UPDATE CASCADE ON DELETE CASCADE,
    -- A qué área concreta se accedía (el "otro lado" de la puerta), opcional.
    id_area_destino       INT              REFERENCES area_trabajo(id_area)
                              ON DELETE SET NULL,
    -- Categoría de zona solicitada (heredada de la puerta) — para el log/tablero.
    categoria_zona        categoria_zona,
    resultado             resultado_acceso NOT NULL,
    motivo_negacion       TEXT,
    fecha_hora            TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    confianza_biometrica  REAL             CHECK (confianza_biometrica BETWEEN 0 AND 1),
    ubicacion             geography(POINT,4326),
    id_dispositivo        INT              REFERENCES dispositivos(id_dispositivo)
                              ON DELETE SET NULL,
    id_dispositivo_origen INT,
    creado_en_cliente     TIMESTAMPTZ,
    sincronizado_en       TIMESTAMPTZ      DEFAULT NOW(),
    fecha_creacion        TIMESTAMPTZ      DEFAULT NOW()
);
-- NOTA cámaras (módulo en evaluación): cuando se defina el soporte de cámaras
-- de apoyo a estas puertas, la relación cámara<->acceso se modelará aquí
-- (p.ej. id_camara o una tabla evidencias_acceso con clips/frames). No se
-- modela aún para no fijar un diseño prematuro.

-- ── intentos_acceso ──────────────────────────────────────────────────────────
-- Intentos de acceso RECHAZADOS en una puerta de ASISTENCIA (spoofing, rostro
-- desconocido, o trabajador de otra empresa). A diferencia de 'incidencias' NO
-- requieren trabajador (un spoofing/desconocido no tiene id_trabajador): son
-- eventos de la PUERTA, scopeados por la empresa de la puerta (id_empresa). Los
-- crea el scanner cuando rechaza un acceso. Alimentan la vista /incidencias/combinado.
-- UUIDv7 + columnas de sync por consistencia con el resto del modelo offline-first.
CREATE TABLE IF NOT EXISTS intentos_acceso (
    id_intento            UUID          PRIMARY KEY DEFAULT gen_uuid_v7(),
    id_puerta             INT           REFERENCES puertas_acceso(id_puerta)
                              ON DELETE CASCADE,
    id_empresa            INT           REFERENCES empresas(id_empresa)
                              ON UPDATE CASCADE ON DELETE CASCADE,
    tipo                  tipo_intento  NOT NULL,
    -- Solo en 'otra_empresa': el trabajador (de otra empresa) que se reconoció.
    id_trabajador         INT           REFERENCES trabajadores(id_trabajador)
                              ON DELETE SET NULL,
    similitud             REAL          CHECK (similitud BETWEEN 0 AND 1),
    ruta_foto             TEXT,
    ubicacion             geography(POINT,4326),
    id_dispositivo        INT           REFERENCES dispositivos(id_dispositivo)
                              ON DELETE SET NULL,
    id_dispositivo_origen INT,
    -- Estado de revisión (igual que las incidencias). 'justificada' en un intento
    -- 'otra_empresa' dispara la creación de una asistencia manual (ver backend).
    estado                estado_incidencia NOT NULL DEFAULT 'pendiente',
    creado_en_cliente     TIMESTAMPTZ,
    sincronizado_en       TIMESTAMPTZ   DEFAULT NOW(),
    fecha                 TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Migración idempotente para BDs ya creadas (la tabla usa CREATE ... IF NOT EXISTS,
-- así que en una BD existente el ALTER es lo que realmente agrega la columna).
ALTER TABLE intentos_acceso
    ADD COLUMN IF NOT EXISTS estado estado_incidencia NOT NULL DEFAULT 'pendiente';

-- ── historial_auditoria ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS historial_auditoria (
    id_auditoria          SERIAL PRIMARY KEY,
    id_usuario            INT            REFERENCES usuarios(id_usuario) ON DELETE CASCADE,
    tabla_modificada      VARCHAR(100)   NOT NULL,
    tipo_operacion        tipo_operacion NOT NULL,
    id_registro_afectado  TEXT,
    valores_anteriores    JSONB,
    valores_nuevos        JSONB,
    ip_origen             VARCHAR(45),
    user_agent            VARCHAR(255),
    fecha_hora            TIMESTAMPTZ    DEFAULT NOW()
);

-- ── parametros_sistema ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parametros_sistema (
    id_parametro        SERIAL PRIMARY KEY,
    clave               VARCHAR(100)   UNIQUE NOT NULL,
    valor               VARCHAR(500)   NOT NULL,
    tipo                tipo_parametro NOT NULL DEFAULT 'texto',
    descripcion         TEXT,
    editable            BOOLEAN        DEFAULT TRUE,
    fecha_actualizacion TIMESTAMPTZ    DEFAULT NOW()
);


-- ════════════════════════════════════════════════════════════════════════════
-- 5) ÍNDICES  (afinados para +20k trabajadores, multi-tenant, offline-sync)
-- ════════════════════════════════════════════════════════════════════════════

-- ── trabajadores ──
CREATE INDEX IF NOT EXISTS idx_trabajadores_estado    ON trabajadores(estado);
CREATE INDEX IF NOT EXISTS idx_trabajadores_empresa   ON trabajadores(id_empresa);
CREATE INDEX IF NOT EXISTS idx_trabajadores_area      ON trabajadores(id_area);
-- Identidad externa SYS21: ÚNICA por (id_emp, origen_nomina); parcial para permitir
-- múltiples manuales (id_emp NULL). Es la clave de conflicto del upsert del sync.
CREATE UNIQUE INDEX IF NOT EXISTS idx_trabajadores_id_emp
    ON trabajadores(id_emp, origen_nomina) WHERE id_emp IS NOT NULL;

-- ── sync_estado / fotos_pendientes (employee_monitoring) ──
CREATE INDEX IF NOT EXISTS idx_sync_estado_empresa
    ON sync_estado(id_empresa);
CREATE INDEX IF NOT EXISTS idx_fotos_pend_empresa_estado
    ON fotos_pendientes(id_empresa, estado);
CREATE INDEX IF NOT EXISTS idx_fotos_pend_emp
    ON fotos_pendientes(id_emp, origen_nomina);

-- ── embeddings (HNSW afinado) ──
-- m / ef_construction más altos = mejor recall a costa de tiempo de build.
-- maintenance_work_mem alto (ver docker-compose) acelera mucho esta construcción.
CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
    ON embeddings USING hnsw (vector_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ── escaneos ──
-- Compuesto trabajador+tiempo: lo usan el job nocturno y casi toda consulta.
CREATE INDEX IF NOT EXISTS idx_escaneos_trab_fecha
    ON escaneos(id_trabajador, fecha_hora DESC);
-- Reportes por empresa.
CREATE INDEX IF NOT EXISTS idx_escaneos_empresa_fecha
    ON escaneos(id_empresa, fecha_hora DESC);
-- BRIN sobre el tiempo: tabla append-only ordenada por fecha => índice de KB.
CREATE INDEX IF NOT EXISTS idx_escaneos_fecha_brin
    ON escaneos USING brin(fecha_hora);
-- Tablero de incidencias: solo los fuera de área (índice parcial = pequeño).
CREATE INDEX IF NOT EXISTS idx_escaneos_fuera_area
    ON escaneos(id_empresa, fecha_hora)
    WHERE estado_registro = 'fuera_de_area';
-- Sincronización incremental: qué falta procesar.
CREATE INDEX IF NOT EXISTS idx_escaneos_sync
    ON escaneos(sincronizado_en);

-- ── asistencia ──
CREATE INDEX IF NOT EXISTS idx_asistencia_trab_fecha
    ON asistencia(id_trabajador, fecha_hora DESC);
CREATE INDEX IF NOT EXISTS idx_asistencia_empresa_fecha
    ON asistencia(id_empresa, fecha_hora DESC);
CREATE INDEX IF NOT EXISTS idx_asistencia_fecha_brin
    ON asistencia USING brin(fecha_hora);
CREATE INDEX IF NOT EXISTS idx_asistencia_tipo
    ON asistencia(tipo_registro);

-- ── incidencias ──
CREATE INDEX IF NOT EXISTS idx_incidencias_trabajador ON incidencias(id_trabajador);
CREATE INDEX IF NOT EXISTS idx_incidencias_empresa_fecha ON incidencias(id_empresa, fecha);
CREATE INDEX IF NOT EXISTS idx_incidencias_tipo       ON incidencias(tipo_incidencia);
CREATE INDEX IF NOT EXISTS idx_incidencias_estado     ON incidencias(estado);

-- ── accesos_internos ──
CREATE INDEX IF NOT EXISTS idx_accesos_trab_fecha
    ON accesos_internos(id_trabajador, fecha_hora DESC);
CREATE INDEX IF NOT EXISTS idx_accesos_empresa_fecha
    ON accesos_internos(id_empresa, fecha_hora DESC);
CREATE INDEX IF NOT EXISTS idx_accesos_fecha_brin
    ON accesos_internos USING brin(fecha_hora);
-- Tablero de seguridad: accesos negados (índice parcial = pequeño).
CREATE INDEX IF NOT EXISTS idx_accesos_negados
    ON accesos_internos(id_empresa, fecha_hora)
    WHERE resultado = 'negado';

-- ── intentos_acceso ──
CREATE INDEX IF NOT EXISTS idx_intentos_empresa_fecha
    ON intentos_acceso(id_empresa, fecha DESC);
CREATE INDEX IF NOT EXISTS idx_intentos_tipo   ON intentos_acceso(tipo);
CREATE INDEX IF NOT EXISTS idx_intentos_puerta ON intentos_acceso(id_puerta);

-- ── dispositivos ──
CREATE INDEX IF NOT EXISTS idx_dispositivos_estado  ON dispositivos(estado);
CREATE INDEX IF NOT EXISTS idx_dispositivos_empresa ON dispositivos(id_empresa);

-- ── puertas ──
CREATE INDEX IF NOT EXISTS idx_puertas_empresa ON puertas_acceso(id_empresa);
CREATE INDEX IF NOT EXISTS idx_puertas_tipo    ON puertas_acceso(tipo_puerta);

-- ── usuarios ──
CREATE INDEX IF NOT EXISTS idx_usuarios_empresa ON usuarios(empresa);
CREATE INDEX IF NOT EXISTS idx_usuarios_rol     ON usuarios(id_rol);

-- ── auditoría ──
CREATE INDEX IF NOT EXISTS idx_auditoria_operacion ON historial_auditoria(tipo_operacion);
CREATE INDEX IF NOT EXISTS idx_auditoria_fecha     ON historial_auditoria(fecha_hora);
CREATE INDEX IF NOT EXISTS idx_auditoria_tabla     ON historial_auditoria(tabla_modificada);


-- ════════════════════════════════════════════════════════════════════════════
-- 6) TRIGGERS: auto-fecha_actualizacion
-- ════════════════════════════════════════════════════════════════════════════
DROP TRIGGER IF EXISTS trg_usuarios_updated ON usuarios;
CREATE TRIGGER trg_usuarios_updated
    BEFORE UPDATE ON usuarios
    FOR EACH ROW EXECUTE FUNCTION set_fecha_actualizacion();

DROP TRIGGER IF EXISTS trg_trabajadores_updated ON trabajadores;
CREATE TRIGGER trg_trabajadores_updated
    BEFORE UPDATE ON trabajadores
    FOR EACH ROW EXECUTE FUNCTION set_fecha_actualizacion();

DROP TRIGGER IF EXISTS trg_parametros_updated ON parametros_sistema;
CREATE TRIGGER trg_parametros_updated
    BEFORE UPDATE ON parametros_sistema
    FOR EACH ROW EXECUTE FUNCTION set_fecha_actualizacion();


-- ════════════════════════════════════════════════════════════════════════════
-- 7) CASCADA DE ESTADO (activo/inactivo) POR JERARQUÍA
-- ────────────────────────────────────────────────────────────────────────────
--   empresa     -> áreas, puertas, usuarios
--   área        -> trabajadores, dispositivos, puertas
--   trabajador  -> embeddings
-- Reactivación inteligente: inactivo_por_cascada recuerda quién apagó la fila;
-- al reactivar el padre, solo revive lo que la cascada apagó (lo desactivado a
-- mano se queda apagado). La empresa 99 (super-admin) no se desactiva ni borra.
-- ════════════════════════════════════════════════════════════════════════════

-- Empresa 99: protección contra DELETE y desactivación ------------------------
CREATE OR REPLACE FUNCTION fn_proteger_empresa_admin()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.id_empresa = 99 THEN
            RAISE EXCEPTION 'La empresa 99 (super-admin) no se puede eliminar.';
        END IF;
        RETURN OLD;
    ELSE
        IF OLD.id_empresa = 99 AND NEW.estado = 'inactivo' THEN
            RAISE EXCEPTION 'La empresa 99 (super-admin) no se puede desactivar.';
        END IF;
        RETURN NEW;
    END IF;
END;
$$;

DROP TRIGGER IF EXISTS trg_proteger_empresa_admin_del ON empresas;
CREATE TRIGGER trg_proteger_empresa_admin_del
    BEFORE DELETE ON empresas
    FOR EACH ROW EXECUTE FUNCTION fn_proteger_empresa_admin();

DROP TRIGGER IF EXISTS trg_proteger_empresa_admin_upd ON empresas;
CREATE TRIGGER trg_proteger_empresa_admin_upd
    BEFORE UPDATE OF estado ON empresas
    FOR EACH ROW EXECUTE FUNCTION fn_proteger_empresa_admin();

-- Cascada EMPRESA -> áreas, puertas, usuarios ---------------------------------
CREATE OR REPLACE FUNCTION fn_cascada_estado_empresa()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.estado = 'inactivo' THEN
        UPDATE area_trabajo   SET estado='inactivo', inactivo_por_cascada=TRUE
            WHERE id_empresa = NEW.id_empresa AND estado='activo';
        UPDATE puertas_acceso SET estado='inactivo', inactivo_por_cascada=TRUE
            WHERE id_empresa = NEW.id_empresa AND estado='activo';
        UPDATE usuarios       SET estado='inactivo', inactivo_por_cascada=TRUE
            WHERE empresa = NEW.id_empresa AND estado='activo' AND empresa <> 99;
    ELSIF NEW.estado = 'activo' THEN
        UPDATE area_trabajo   SET estado='activo', inactivo_por_cascada=FALSE
            WHERE id_empresa = NEW.id_empresa AND estado='inactivo' AND inactivo_por_cascada=TRUE;
        UPDATE puertas_acceso SET estado='activo', inactivo_por_cascada=FALSE
            WHERE id_empresa = NEW.id_empresa AND estado='inactivo' AND inactivo_por_cascada=TRUE;
        UPDATE usuarios       SET estado='activo', inactivo_por_cascada=FALSE
            WHERE empresa = NEW.id_empresa AND estado='inactivo' AND inactivo_por_cascada=TRUE;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_cascada_estado_empresa ON empresas;
CREATE TRIGGER trg_cascada_estado_empresa
    AFTER UPDATE OF estado ON empresas
    FOR EACH ROW WHEN (OLD.estado IS DISTINCT FROM NEW.estado)
    EXECUTE FUNCTION fn_cascada_estado_empresa();

-- Cascada ÁREA -> trabajadores, dispositivos, puertas -------------------------
CREATE OR REPLACE FUNCTION fn_cascada_estado_area()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.estado = 'inactivo' THEN
        UPDATE trabajadores   SET estado='inactivo', inactivo_por_cascada=TRUE
            WHERE id_area = NEW.id_area AND estado='activo';
        UPDATE dispositivos   SET estado='inactivo', inactivo_por_cascada=TRUE
            WHERE id_area = NEW.id_area AND estado='activo';
        UPDATE puertas_acceso SET estado='inactivo', inactivo_por_cascada=TRUE
            WHERE id_area = NEW.id_area AND estado='activo';
    ELSIF NEW.estado = 'activo' THEN
        UPDATE trabajadores   SET estado='activo', inactivo_por_cascada=FALSE
            WHERE id_area = NEW.id_area AND estado='inactivo' AND inactivo_por_cascada=TRUE;
        UPDATE dispositivos   SET estado='activo', inactivo_por_cascada=FALSE
            WHERE id_area = NEW.id_area AND estado='inactivo' AND inactivo_por_cascada=TRUE;
        UPDATE puertas_acceso SET estado='activo', inactivo_por_cascada=FALSE
            WHERE id_area = NEW.id_area AND estado='inactivo' AND inactivo_por_cascada=TRUE;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_cascada_estado_area ON area_trabajo;
CREATE TRIGGER trg_cascada_estado_area
    AFTER UPDATE OF estado ON area_trabajo
    FOR EACH ROW WHEN (OLD.estado IS DISTINCT FROM NEW.estado)
    EXECUTE FUNCTION fn_cascada_estado_area();

-- Cascada TRABAJADOR -> embeddings --------------------------------------------
CREATE OR REPLACE FUNCTION fn_cascada_estado_trabajador()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.estado = 'inactivo' THEN
        UPDATE embeddings SET estado='inactivo', inactivo_por_cascada=TRUE
            WHERE id_trabajador = NEW.id_trabajador AND estado='activo';
    ELSIF NEW.estado = 'activo' THEN
        UPDATE embeddings SET estado='activo', inactivo_por_cascada=FALSE
            WHERE id_trabajador = NEW.id_trabajador AND estado='inactivo' AND inactivo_por_cascada=TRUE;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_cascada_estado_trabajador ON trabajadores;
CREATE TRIGGER trg_cascada_estado_trabajador
    AFTER UPDATE OF estado ON trabajadores
    FOR EACH ROW WHEN (OLD.estado IS DISTINCT FROM NEW.estado)
    EXECUTE FUNCTION fn_cascada_estado_trabajador();


-- ════════════════════════════════════════════════════════════════════════════
-- 8) VALIDACIÓN DE ESCANEOS EN LOTE  (reemplaza el trigger AFTER INSERT viejo)
-- ────────────────────────────────────────────────────────────────────────────
-- POR QUÉ EN LOTE Y NO EN TRIGGER: con sincronización offline, los escaneos
-- llegan en bloques tras horas sin conexión y en desorden. La lógica vieja de
-- "¿es el primer escaneo del día?" (trigger fila-por-fila) se rompe ahí. Esta
-- función la llama el microservicio DESPUÉS de ingerir cada lote (o un job).
--
-- Evalúa 3 capas, de la más barata a la más cara:
--   1. tipo_puerta vs permiso_escaneo  -> incidencia 'area_incorrecta'
--   2. empresa del trabajador vs puerta -> incidencia 'acceso_otra_empresa'
--      (excepto permiso 'super', que entra a cualquier empresa)
--   3. geolocalización ST_Covers        -> incidencia 'fuera_de_area'
--
-- Procesa solo escaneos aún en estado 'exitoso' (recién ingeridos) para ser
-- idempotente: re-correrla no re-evalúa lo ya marcado.
-- Devuelve cuántos escaneos marcó en cada categoría.
-- ════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION validar_escaneos_lote(
    p_desde TIMESTAMPTZ DEFAULT NULL   -- si se pasa, solo valida sincronizados >= p_desde
)
RETURNS TABLE(
    validados        INT,
    area_incorrecta  INT,
    otra_empresa     INT,
    fuera_de_area    INT
)
LANGUAGE plpgsql
AS $$
DECLARE
    r                RECORD;
    v_tipo_puerta    tipo_puerta;
    v_permiso        permiso_escaneo;
    v_emp_trab       INT;
    v_emp_puerta     INT;
    v_poligono       geography(POLYGON,4326);
    v_dentro         BOOLEAN;
    v_geo_indet      BOOLEAN;
    v_nuevo_estado   estado_registro;
    v_tipo_inc       tipo_incidencia;
    v_desc           TEXT;
    c_validados      INT := 0;
    c_area_inc       INT := 0;
    c_otra_emp       INT := 0;
    c_fuera          INT := 0;
BEGIN
    FOR r IN
        SELECT e.id_escaneo, e.id_trabajador, e.id_puerta, e.id_empresa,
               e.ubicacion, e.fecha_hora, e.creado_en_cliente
        FROM escaneos e
        WHERE e.estado_registro = 'exitoso'
          AND (p_desde IS NULL OR e.sincronizado_en >= p_desde)
    LOOP
        -- Datos de contexto
        SELECT t.permiso_escaneo, t.id_empresa
          INTO v_permiso, v_emp_trab
          FROM trabajadores t WHERE t.id_trabajador = r.id_trabajador;

        SELECT p.tipo_puerta, p.id_empresa
          INTO v_tipo_puerta, v_emp_puerta
          FROM puertas_acceso p WHERE p.id_puerta = r.id_puerta;

        v_nuevo_estado := NULL;
        v_tipo_inc     := NULL;
        v_geo_indet    := FALSE;

        -- ── Capa 1: tipo de puerta compatible con el permiso ──────────────
        -- 'mixta' acepta a todos. 'campo'/'administrativa' restringen.
        IF v_tipo_puerta = 'campo' AND v_permiso = 'administrativo' THEN
            v_nuevo_estado := 'rechazado'; v_tipo_inc := 'area_incorrecta';
            v_desc := 'Trabajador administrativo en puerta de campo.';
        ELSIF v_tipo_puerta = 'administrativa' AND v_permiso = 'campo' THEN
            v_nuevo_estado := 'rechazado'; v_tipo_inc := 'area_incorrecta';
            v_desc := 'Trabajador de campo en puerta administrativa.';
        END IF;

        -- ── Capa 2: empresa correcta (salvo 'super') ──────────────────────
        IF v_nuevo_estado IS NULL
           AND v_permiso <> 'super'
           AND v_emp_trab IS DISTINCT FROM v_emp_puerta THEN
            v_nuevo_estado := 'rechazado'; v_tipo_inc := 'acceso_otra_empresa';
            v_desc := 'Escaneo en puerta de otra empresa sin permiso super.';
        END IF;

        -- ── Capa 3: geolocalización (solo si pasó 1 y 2) ──────────────────
        IF v_nuevo_estado IS NULL AND v_permiso = 'super' THEN
            -- 'super' ficha en cualquier lado → exento de la geocerca.
            v_geo_indet := TRUE;
        ELSIF v_nuevo_estado IS NULL THEN
            -- Geocerca: puerta de campo + trabajador de campo = su ÁREA asignada
            -- (verifica al jornalero en su campo). En cualquier otro caso
            -- (general/administrativo, o campo en puerta administrativa) = polígono
            -- de la EMPRESA (roaming dentro de la empresa).
            IF v_tipo_puerta = 'campo' AND v_permiso = 'campo' THEN
                SELECT a.ubicacion INTO v_poligono
                  FROM trabajadores t
                  JOIN area_trabajo a ON a.id_area = t.id_area
                 WHERE t.id_trabajador = r.id_trabajador;
            ELSE
                SELECT em.ubicacion INTO v_poligono
                  FROM empresas em WHERE em.id_empresa = v_emp_puerta;
            END IF;

            IF v_poligono IS NULL OR r.ubicacion IS NULL THEN
                -- Sin datos para juzgar (offline sin GPS o sin geocerca): NO penalizar.
                v_geo_indet := TRUE;
            ELSE
                v_dentro := ST_Covers(v_poligono, r.ubicacion);
                IF NOT v_dentro THEN
                    v_nuevo_estado := 'fuera_de_area'; v_tipo_inc := 'fuera_de_area';
                    v_desc := 'Ubicación fuera del área permitida.';
                END IF;
            END IF;
        END IF;

        -- ── Aplicar resultado ─────────────────────────────────────────────
        IF v_nuevo_estado IS NULL THEN
            -- Pasó las 3 capas. Solo tocamos dentro_de_area si SÍ pudimos juzgar
            -- la geo; si fue indeterminada, se conserva el valor del cliente.
            IF NOT v_geo_indet THEN
                UPDATE escaneos SET dentro_de_area = TRUE WHERE id_escaneo = r.id_escaneo;
            END IF;
            c_validados := c_validados + 1;
        ELSE
            UPDATE escaneos
               SET estado_registro = v_nuevo_estado,
                   dentro_de_area  = (v_nuevo_estado <> 'fuera_de_area')
             WHERE id_escaneo = r.id_escaneo;

            INSERT INTO incidencias (
                id_trabajador, id_empresa, tipo_incidencia, fecha,
                descripcion, id_escaneo_ref, creado_en_cliente
            )
            VALUES (
                r.id_trabajador, v_emp_trab, v_tipo_inc,
                COALESCE(r.creado_en_cliente, r.fecha_hora)::date,
                v_desc, r.id_escaneo, r.creado_en_cliente
            );

            IF    v_tipo_inc = 'area_incorrecta'      THEN c_area_inc := c_area_inc + 1;
            ELSIF v_tipo_inc = 'acceso_otra_empresa'  THEN c_otra_emp := c_otra_emp + 1;
            ELSIF v_tipo_inc = 'fuera_de_area'        THEN c_fuera    := c_fuera    + 1;
            END IF;
        END IF;
    END LOOP;

    validados       := c_validados;
    area_incorrecta := c_area_inc;
    otra_empresa    := c_otra_emp;
    fuera_de_area   := c_fuera;
    RETURN NEXT;
END;
$$;


-- ════════════════════════════════════════════════════════════════════════════
-- 8b) CONTROL DE ACCESO INTERNO  (puertas funcion_puerta='control_acceso')
-- ────────────────────────────────────────────────────────────────────────────
-- Decide si un trabajador puede pasar por una puerta interna y REGISTRA el
-- intento en accesos_internos. Pensada para llamarse en TIEMPO REAL (el control
-- de acceso físico ocurre en sitio con conexión), pero también sirve en lote.
--
-- Regla de zona (genérica): el nivel_acceso_interno del trabajador debe cubrir
-- la categoria_zona_destino de la puerta. 'mixto' (en cualquiera de los dos
-- lados) abre el paso oficina<->empaque. Además se respeta el aislamiento por
-- empresa salvo permiso_escaneo='super'.
--
-- Devuelve el resultado ('permitido'/'negado') y el id del registro creado.
-- ════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION evaluar_acceso_interno(
    p_id_trabajador  INT,
    p_id_puerta      INT,
    p_ubicacion      geography DEFAULT NULL,
    p_confianza      REAL      DEFAULT NULL,
    p_id_dispositivo INT       DEFAULT NULL
)
RETURNS TABLE(resultado resultado_acceso, id_acceso UUID, motivo TEXT)
LANGUAGE plpgsql
AS $$
DECLARE
    v_func        funcion_puerta;
    v_zona_dest   categoria_zona;
    v_emp_puerta  INT;
    v_id_area     INT;
    v_nivel       nivel_acceso_interno;
    v_permiso     permiso_escaneo;
    v_emp_trab    INT;
    v_res         resultado_acceso;
    v_motivo      TEXT := NULL;
    v_id          UUID;
BEGIN
    -- Datos de la puerta
    SELECT funcion_puerta, categoria_zona_destino, id_empresa, id_area
      INTO v_func, v_zona_dest, v_emp_puerta, v_id_area
      FROM puertas_acceso WHERE id_puerta = p_id_puerta;

    IF v_func IS DISTINCT FROM 'control_acceso' THEN
        RAISE EXCEPTION 'La puerta % no es de control de acceso interno.', p_id_puerta;
    END IF;

    -- Datos del trabajador
    SELECT nivel_acceso_interno, permiso_escaneo, id_empresa
      INTO v_nivel, v_permiso, v_emp_trab
      FROM trabajadores WHERE id_trabajador = p_id_trabajador;

    -- ── Capa empresa (salvo super) ──
    IF v_permiso <> 'super' AND v_emp_trab IS DISTINCT FROM v_emp_puerta THEN
        v_res := 'negado';
        v_motivo := 'Acceso a zona de otra empresa sin permiso super.';
    -- ── Capa "sin acceso interno" ──
    --   nivel NULL (típico de los de campo) = NUNCA pasa por una puerta interna,
    --   ni siquiera a zonas 'mixto'. Va ANTES del chequeo de zona a propósito.
    ELSIF v_nivel IS NULL THEN
        v_res := 'negado';
        v_motivo := 'El trabajador no tiene acceso a zonas internas (solo fichaje de campo).';
    -- ── Capa zona ──
    --   permitido si: la zona destino es 'mixto', o el nivel del trabajador es
    --   'mixto', o nivel coincide con la zona destino.
    ELSIF v_zona_dest IS NULL THEN
        v_res := 'negado';
        v_motivo := 'La puerta interna no tiene categoría de zona configurada.';
    ELSIF v_zona_dest = 'mixto'
          OR v_nivel = 'mixto'
          OR v_nivel::text = v_zona_dest::text THEN
        v_res := 'permitido';
    ELSE
        v_res := 'negado';
        v_motivo := format('Nivel de acceso "%s" no cubre la zona "%s".',
                           v_nivel, v_zona_dest);
    END IF;

    -- Registrar el intento
    INSERT INTO accesos_internos (
        id_trabajador, id_puerta, id_empresa, id_area_destino, categoria_zona,
        resultado, motivo_negacion, ubicacion, confianza_biometrica, id_dispositivo
    )
    VALUES (
        p_id_trabajador, p_id_puerta, v_emp_trab, v_id_area, v_zona_dest,
        v_res, v_motivo, p_ubicacion, p_confianza, p_id_dispositivo
    )
    RETURNING accesos_internos.id_acceso INTO v_id;

    resultado := v_res;
    id_acceso := v_id;
    motivo    := v_motivo;
    RETURN NEXT;
END;
$$;


-- ════════════════════════════════════════════════════════════════════════════
-- 9) CONSOLIDACIÓN DIARIA DE ASISTENCIA  (entrada + salida, derivada de escaneos)
-- ────────────────────────────────────────────────────────────────────────────
-- Materializa 'asistencia' a partir de 'escaneos' (la fuente de verdad). Por cada
-- trabajador con escaneos válidos del día (en SU zona horaria de empresa):
--   · ENTRADA = primer escaneo del día        -> fila 'entrada' en asistencia
--   · SALIDA  = último escaneo (si hay 2+)     -> fila 'salida'  en asistencia
--   · 1 solo escaneo                            -> incidencia 'entrada_sin_registro'
--
-- Se DERIVA (no se inserta a mano): da igual el orden de llegada (offline) y se
-- puede correr N veces sin duplicar (NOT EXISTS). Se llama en 3 momentos, SIEMPRE
-- con esta misma función:
--   · Online, tras cada escaneo   -> consolidar_asistencia_dia(0, <trab>, FALSE)
--                                    (ENTRADA en vivo; la salida aún no es definitiva)
--   · Tras cada lote offline      -> consolidar_asistencia_dia(<días>, NULL, TRUE)
--   · Cierre nocturno (cron 3 AM) -> consolidar_asistencia_dia()  [= ayer, con salida]
--
-- Parámetros:
--   p_dias_atras     0 = día en curso; 1 = ayer (default, cierre nocturno).
--   p_id_trabajador  NULL = todos; si se pasa, solo ese trabajador (uso en vivo).
--   p_incluir_salida FALSE durante el día (salida/incidencia se difieren al cierre).
-- Multi-tenant TZ: "el día" se calcula con empresas.zona_horaria; usa creado_en_cliente.
-- ════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION consolidar_asistencia_dia(
    p_dias_atras     INT     DEFAULT 1,
    p_id_trabajador  INT     DEFAULT NULL,
    p_incluir_salida BOOLEAN DEFAULT TRUE
)
RETURNS TABLE(entradas_creadas INT, salidas_creadas INT, incidencias_creadas INT)
LANGUAGE plpgsql
AS $$
DECLARE
    c_dedupe_seg CONSTANT INT := 90;   -- ventana de dedupe doble-scan (segundos)
    v_entradas    INT := 0;
    v_salidas     INT := 0;
    v_incidencias INT := 0;
BEGIN
    -- 0) Derivación por (trabajador, día) a una tabla temporal (idempotente
    --    entre llamadas dentro de la misma transacción vía DROP IF EXISTS).
    DROP TABLE IF EXISTS _deriv_asis;
    CREATE TEMP TABLE _deriv_asis AS
    WITH params AS (
        -- Ventana del día objetivo (hoy - p_dias_atras) por empresa, en UTC.
        SELECT em.id_empresa,
               em.zona_horaria,
               ((date_trunc('day', timezone(em.zona_horaria, now()))
                    - make_interval(days => p_dias_atras)) AT TIME ZONE em.zona_horaria)                  AS ini_utc,
               ((date_trunc('day', timezone(em.zona_horaria, now()))
                    - make_interval(days => p_dias_atras)) AT TIME ZONE em.zona_horaria + INTERVAL '1 day') AS fin_utc
        FROM empresas em
        WHERE em.estado = 'activo'
    ),
    -- Momento del evento: hora real (creado_en_cliente) o, si falta, fecha_hora.
    ev AS (
        SELECT e.*,
               COALESCE(e.creado_en_cliente, e.fecha_hora) AS momento,
               p.id_empresa AS emp,
               p.ini_utc, p.fin_utc,
               (timezone(p.zona_horaria, COALESCE(e.creado_en_cliente, e.fecha_hora)))::date AS fecha_local
        FROM escaneos e
        JOIN params p ON p.id_empresa = e.id_empresa
        WHERE COALESCE(e.creado_en_cliente, e.fecha_hora) >= p.ini_utc
          AND COALESCE(e.creado_en_cliente, e.fecha_hora) <  p.fin_utc
          AND e.estado_registro IN ('exitoso','manual')
          AND (p_id_trabajador IS NULL OR e.id_trabajador = p_id_trabajador)
    ),
    -- Dedupe: un scan a < c_dedupe_seg del anterior del mismo trabajador NO es
    -- un evento nuevo (evita salida espuria por doble-scan).
    ev_evt AS (
        SELECT ev.*,
               (lag(momento) OVER w IS NULL
                OR momento - lag(momento) OVER w >= make_interval(secs => c_dedupe_seg)) AS es_evento
        FROM ev
        WINDOW w AS (PARTITION BY id_trabajador ORDER BY momento)
    ),
    conteo AS (   -- nº de EVENTOS distintos (tras dedupe), no de filas
        SELECT id_trabajador, COUNT(*) FILTER (WHERE es_evento) AS n
        FROM ev_evt GROUP BY id_trabajador
    ),
    primero AS (   -- primer escaneo del día = ENTRADA
        SELECT DISTINCT ON (id_trabajador)
            id_trabajador, id_puerta, emp, ini_utc, fin_utc, momento,
            confianza_biometrica, estado_registro, dentro_de_area,
            id_dispositivo, id_dispositivo_origen, ubicacion
        FROM ev
        ORDER BY id_trabajador, momento ASC
    ),
    ultimo AS (    -- último escaneo del día = SALIDA (si hay 2+ eventos)
        SELECT DISTINCT ON (id_trabajador)
            id_escaneo, id_trabajador, id_puerta, emp, momento, fecha_local,
            confianza_biometrica, estado_registro, dentro_de_area,
            id_dispositivo, id_dispositivo_origen, ubicacion
        FROM ev
        ORDER BY id_trabajador, momento DESC
    )
    SELECT pr.id_trabajador, pr.emp, u.fecha_local, c.n, pr.ini_utc, pr.fin_utc,
           pr.id_puerta AS e_puerta, pr.momento AS e_momento, pr.confianza_biometrica AS e_conf,
           pr.estado_registro AS e_estado, pr.dentro_de_area AS e_dentro,
           pr.id_dispositivo AS e_disp, pr.id_dispositivo_origen AS e_disp_orig, pr.ubicacion AS e_ubic,
           u.id_escaneo AS u_escaneo, u.id_puerta AS s_puerta, u.momento AS s_momento,
           u.confianza_biometrica AS s_conf, u.estado_registro AS s_estado,
           u.dentro_de_area AS s_dentro, u.id_dispositivo AS s_disp,
           u.id_dispositivo_origen AS s_disp_orig, u.ubicacion AS s_ubic
    FROM primero pr
    JOIN conteo c ON c.id_trabajador = pr.id_trabajador
    JOIN ultimo u ON u.id_trabajador = pr.id_trabajador;

    -- 1) ENTRADA — re-ajustar la auto-derivada al primer scan actual (reconciliación).
    UPDATE asistencia a
       SET fecha_hora = d.e_momento, creado_en_cliente = d.e_momento,
           id_puerta = d.e_puerta, confianza_biometrica = d.e_conf,
           estado_registro = d.e_estado, dentro_de_area = d.e_dentro,
           id_dispositivo = d.e_disp, id_dispositivo_origen = d.e_disp_orig, ubicacion = d.e_ubic
      FROM _deriv_asis d
     WHERE a.id_trabajador = d.id_trabajador
       AND a.tipo_registro = 'entrada'
       AND a.fecha_hora >= d.ini_utc AND a.fecha_hora < d.fin_utc
       AND a.observaciones LIKE 'Entrada (primer escaneo%'   -- solo las auto-derivadas
       AND a.fecha_hora <> d.e_momento;

    -- ...y crearla si aún no existe (auto o manual) ese día.
    WITH ins AS (
        INSERT INTO asistencia (
            id_trabajador, id_puerta, id_empresa, tipo_registro, fecha_hora,
            confianza_biometrica, estado_registro, dentro_de_area, observaciones,
            id_dispositivo, id_dispositivo_origen, ubicacion, creado_en_cliente
        )
        SELECT d.id_trabajador, d.e_puerta, d.emp, 'entrada', d.e_momento,
               d.e_conf, d.e_estado, d.e_dentro, 'Entrada (primer escaneo del día).',
               d.e_disp, d.e_disp_orig, d.e_ubic, d.e_momento
        FROM _deriv_asis d
        WHERE NOT EXISTS (
            SELECT 1 FROM asistencia a
            WHERE a.id_trabajador = d.id_trabajador AND a.tipo_registro = 'entrada'
              AND a.fecha_hora >= d.ini_utc AND a.fecha_hora < d.fin_utc
        )
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_entradas FROM ins;

    IF p_incluir_salida THEN
        -- 2) SALIDA (solo con 2+ eventos) — re-ajustar la auto al último scan actual.
        UPDATE asistencia a
           SET fecha_hora = d.s_momento, creado_en_cliente = d.s_momento,
               id_puerta = d.s_puerta, confianza_biometrica = d.s_conf,
               estado_registro = d.s_estado, dentro_de_area = d.s_dentro,
               id_dispositivo = d.s_disp, id_dispositivo_origen = d.s_disp_orig, ubicacion = d.s_ubic
          FROM _deriv_asis d
         WHERE d.n >= 2 AND a.id_trabajador = d.id_trabajador
           AND a.tipo_registro = 'salida'
           AND a.fecha_hora >= d.ini_utc AND a.fecha_hora < d.fin_utc
           AND a.observaciones LIKE 'Salida inferida%'
           AND a.fecha_hora <> d.s_momento;

        -- ...y crearla si no existe.
        WITH ins AS (
            INSERT INTO asistencia (
                id_trabajador, id_puerta, id_empresa, tipo_registro, fecha_hora,
                confianza_biometrica, estado_registro, dentro_de_area, observaciones,
                id_dispositivo, id_dispositivo_origen, ubicacion, creado_en_cliente
            )
            SELECT d.id_trabajador, d.s_puerta, d.emp, 'salida', d.s_momento,
                   d.s_conf, d.s_estado, d.s_dentro, 'Salida inferida (último escaneo del día).',
                   d.s_disp, d.s_disp_orig, d.s_ubic, d.s_momento
            FROM _deriv_asis d
            WHERE d.n >= 2
              AND NOT EXISTS (
                  SELECT 1 FROM asistencia a
                  WHERE a.id_trabajador = d.id_trabajador AND a.tipo_registro = 'salida'
                    AND a.fecha_hora >= d.ini_utc AND a.fecha_hora < d.fin_utc
              )
            RETURNING 1
        )
        SELECT COUNT(*) INTO v_salidas FROM ins;

        -- 3) RECONCILIAR: ya hay salida (2+ eventos) → retractar la incidencia
        --    'entrada_sin_registro' PENDIENTE (falso positivo del lote anterior).
        --    Las revisadas/justificadas NO se tocan (ya generaron su salida manual).
        DELETE FROM incidencias i
         USING _deriv_asis d
         WHERE d.n >= 2 AND i.id_trabajador = d.id_trabajador
           AND i.fecha = d.fecha_local
           AND i.tipo_incidencia = 'entrada_sin_registro'
           AND i.estado = 'pendiente';

        -- 4) INCIDENCIA 'entrada_sin_registro' (un solo evento) si no existe.
        WITH ins AS (
            INSERT INTO incidencias (
                id_trabajador, id_empresa, tipo_incidencia, fecha, descripcion, id_escaneo_ref
            )
            SELECT d.id_trabajador, d.emp, 'entrada_sin_registro', d.fecha_local,
                   'Solo un escaneo en el día; sin salida detectable.', d.u_escaneo
            FROM _deriv_asis d
            WHERE d.n = 1
              AND NOT EXISTS (
                  SELECT 1 FROM incidencias i
                  WHERE i.id_trabajador = d.id_trabajador AND i.fecha = d.fecha_local
                    AND i.tipo_incidencia = 'entrada_sin_registro'
              )
            RETURNING 1
        )
        SELECT COUNT(*) INTO v_incidencias FROM ins;
    END IF;

    DROP TABLE IF EXISTS _deriv_asis;

    RAISE NOTICE 'Entradas: %, Salidas: %, Incidencias: %', v_entradas, v_salidas, v_incidencias;
    entradas_creadas    := v_entradas;
    salidas_creadas     := v_salidas;
    incidencias_creadas := v_incidencias;
    RETURN NEXT;
END;
$$;

-- Programar el cierre diario a las 3:00 AM (zona del cron = America/Mazatlan, ver
-- docker-compose). A esa hora ya no queda nadie marcando (los que salen pasadas
-- las 23:30 ya cerraron) y no hay turnos de madrugada, así que el día PREVIO está
-- completo: por eso se consolida AYER (consolidar_asistencia_dia() usa p_dias_atras=1).
-- Idempotente: si ya existe el job (nombre viejo o nuevo), se reprograma.
DO $$
BEGIN
    PERFORM cron.unschedule(jobname)
    FROM cron.job
    WHERE jobname IN ('procesar-salidas-diarias', 'consolidar-asistencia-diaria');
EXCEPTION WHEN OTHERS THEN
    NULL;  -- si pg_cron no está listo aún, se ignora
END $$;

SELECT cron.schedule(
    'consolidar-asistencia-diaria',
    '0 3 * * *',
    $cron$ SELECT consolidar_asistencia_dia(); $cron$
);


-- ════════════════════════════════════════════════════════════════════════════
-- 10) SEED: roles base
-- ────────────────────────────────────────────────────────────────────────────
-- Permisos = JSONB {"scopes": [...]}. Un scope puede ser:
--   "*"  ·  "recurso:*"  ·  "*:accion"  ·  "recurso:accion"
-- Acciones: GET=read · POST/PUT/PATCH=write · DELETE=delete.
-- El scanner usa el scope especial "scanner:use".
--
-- NOTA SOBRE SCOPES DE UI (no de router): 'reportes:read' e 'intentos:read'
-- NO corresponden a un router REST literal — son banderas que el FRONT lee
-- para mostrar/ocultar las secciones "Reportes" e "Intentos" (esta última va
-- de la mano con incidencias). Se conservan a propósito; no buscar /reportes
-- ni /intentos en el backend.
--
-- Idempotente: ON CONFLICT (nombre_rol) DO NOTHING.
-- ════════════════════════════════════════════════════════════════════════════
INSERT INTO roles (nombre_rol, descripcion, permisos, estado) VALUES
    ('consultor',     'Solo lectura de todos los recursos.',
        '{"scopes": ["*:read"]}'::jsonb, 'activo'),
    ('operador',      'Lee y crea/edita todo, usa el scanner. No borra.',
        '{"scopes": ["*:read", "*:write", "scanner:use"]}'::jsonb, 'activo'),
    ('administrador', 'Acceso total (lectura, escritura, borrado y scanner).',
        '{"scopes": ["*"]}'::jsonb, 'activo'),
    ('kiosko',        'Dispositivo/kiosko: solo scanner:use.',
        '{"scopes": ["scanner:use"]}'::jsonb, 'activo'),
    ('escaneador',    'Kiosko + gestión de trabajadores y rostros (enrola/edita/elige trabajador y le pone rostro).',
        '{"scopes": ["scanner:use", "trabajadores:read", "trabajadores:write", "embeddings:read", "embeddings:write", "areas:read"]}'::jsonb, 'activo'),
    ('usuarios_consulta', 'Ver usuarios.',
        '{"scopes": ["usuarios:read"]}'::jsonb, 'activo'),
    ('usuarios_gestion',  'Ver + crear/editar usuarios.',
        '{"scopes": ["usuarios:read", "usuarios:write"]}'::jsonb, 'activo'),
    ('usuarios_admin',    'Ver + crear/editar + borrar usuarios.',
        '{"scopes": ["usuarios:read", "usuarios:write", "usuarios:delete"]}'::jsonb, 'activo'),
    ('roles_consulta', 'Ver roles.',
        '{"scopes": ["roles:read"]}'::jsonb, 'activo'),
    ('roles_gestion',  'Ver + crear/editar roles.',
        '{"scopes": ["roles:read", "roles:write"]}'::jsonb, 'activo'),
    ('roles_admin',    'Ver + crear/editar + borrar roles.',
        '{"scopes": ["roles:read", "roles:write", "roles:delete"]}'::jsonb, 'activo'),
    ('rrhh',          'RRHH: gestiona trabajadores y rostros. Ve reportes e intentos. No borra.',
        '{"scopes": ["trabajadores:read", "trabajadores:write", "embeddings:read", "embeddings:write", "areas:read", "reportes:read", "intentos:read"]}'::jsonb, 'activo'),
    ('supervisor',    'Consulta asistencias y revisa/justifica incidencias.',
        '{"scopes": ["asistencias:read", "incidencias:read", "incidencias:write", "trabajadores:read", "intentos:read"]}'::jsonb, 'activo'),
    ('configuracion', 'Gestiona empresas, áreas, puertas y dispositivos. No borra.',
        '{"scopes": ["empresas:read", "empresas:write", "areas:read", "areas:write", "puertas:read", "puertas:write", "dispositivos:read", "dispositivos:write"]}'::jsonb, 'activo'),
    ('reportes',      'Tableros/exportes: reportes, asistencias, incidencias, intentos, escaneos, trabajadores.',
        '{"scopes": ["reportes:read", "asistencias:read", "incidencias:read", "intentos:read", "escaneos:read", "trabajadores:read"]}'::jsonb, 'activo')
ON CONFLICT (nombre_rol) DO NOTHING;


-- ════════════════════════════════════════════════════════════════════════════
-- 11) SEED: empresa 99 (super-admin) + parámetros base
-- ────────────────────────────────────────────────────────────────────────────
-- La empresa 99 es el tenant super-admin protegido por trigger. Se siembra con
-- un id fijo (99) para que coincida con settings.EMPRESA_ADMIN del backend.
-- Idempotente.
-- ════════════════════════════════════════════════════════════════════════════
INSERT INTO empresas (id_empresa, nombre_empresa, zona_horaria, estado)
VALUES (99, 'SUPER-ADMIN', 'America/Mazatlan', 'activo')
ON CONFLICT (id_empresa) DO NOTHING;

-- Asegurar que la secuencia no choque con el id 99 sembrado a mano.
SELECT setval('empresas_id_empresa_seq',
              GREATEST((SELECT MAX(id_empresa) FROM empresas), 1), true);

INSERT INTO parametros_sistema (clave, valor, tipo, descripcion) VALUES
    ('empresa_admin_id', '99', 'numero', 'ID de la empresa super-admin protegida.'),
    ('umbral_confianza_facial', '0.85', 'numero', 'Confianza mínima para aceptar un match facial.'),
    ('hora_corte_dia', '23:30', 'texto', 'Hora del job nocturno de cierre.')
ON CONFLICT (clave) DO NOTHING;


-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║  FIN init.sql                                                              ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
