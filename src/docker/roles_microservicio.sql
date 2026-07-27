-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║  roles_microservicio.sql                                                   ║
-- ║  Roles (usuarios de PostgreSQL) por MICROSERVICIO + GRANTs de mínimo        ║
-- ║  privilegio, derivados del esquema de init.sql.                            ║
-- ║                                                                            ║
-- ║  Modelo: 1 BD compartida (fase strangler-fig) + 1 rol LOGIN por servicio.  ║
-- ║  Cada servicio solo puede tocar SUS tablas; los SELECT cruzados son        ║
-- ║  explícitos (= la "deuda" que se paga al separar BDs por dominio).         ║
-- ║                                                                            ║
-- ║  Cómo aplicarlo (como superusuario / dueño del esquema):                   ║
-- ║    psql -U postgres -d <db> -f roles_microservicio.sql                     ║
-- ║                                                                            ║
-- ║  ⚠️  CONTRASEÑAS: las de abajo son PLACEHOLDERS. Cámbialas antes de usar    ║
-- ║      (o mejor: ALTER ROLE ... PASSWORD desde un gestor de secretos).       ║
-- ║  Idempotente: se puede correr varias veces (CREATE ROLE va en bloque DO;   ║
-- ║  los GRANT son repetibles sin error).                                      ║
-- ╚══════════════════════════════════════════════════════════════════════════╝


-- ════════════════════════════════════════════════════════════════════════════
-- 0) ENDURECER EL ESQUEMA public
-- ────────────────────────────────────────────────────────────────────────────
-- Evita que los roles de servicio CREEN objetos en public (solo el dueño/DDL).
-- No revocamos EXECUTE de funciones a PUBLIC: rompería PostGIS/pgvector (cientos
-- de funciones se otorgan a PUBLIC por defecto). El control real es no dar DML
-- de más a cada rol (abajo).
-- ════════════════════════════════════════════════════════════════════════════
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;   -- red de seguridad


-- ════════════════════════════════════════════════════════════════════════════
-- 1) CREACIÓN DE ROLES (idempotente)
-- ────────────────────────────────────────────────────────────────────────────
-- CONNECTION LIMIT orientativo; ajústalo a tu pool/pgbouncer real.
-- ════════════════════════════════════════════════════════════════════════════
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_identity') THEN
        CREATE ROLE svc_identity    LOGIN PASSWORD 'CAMBIAR_identity'    CONNECTION LIMIT 15;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_tenancy') THEN
        CREATE ROLE svc_tenancy     LOGIN PASSWORD 'CAMBIAR_tenancy'     CONNECTION LIMIT 15;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_workers') THEN
        CREATE ROLE svc_workers     LOGIN PASSWORD 'CAMBIAR_workers'     CONNECTION LIMIT 20;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_recognition') THEN
        CREATE ROLE svc_recognition LOGIN PASSWORD 'CAMBIAR_recognition' CONNECTION LIMIT 25;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_access') THEN
        CREATE ROLE svc_access      LOGIN PASSWORD 'CAMBIAR_access'      CONNECTION LIMIT 25;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_reports') THEN
        CREATE ROLE svc_reports     LOGIN PASSWORD 'CAMBIAR_reports'     CONNECTION LIMIT 10;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_offline') THEN
        CREATE ROLE svc_offline     LOGIN PASSWORD 'CAMBIAR_offline'     CONNECTION LIMIT 15;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_vigilancia') THEN
        CREATE ROLE svc_vigilancia  LOGIN PASSWORD 'CAMBIAR_vigilancia'  CONNECTION LIMIT 15;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_cron') THEN
        CREATE ROLE app_cron        LOGIN PASSWORD 'CAMBIAR_cron'        CONNECTION LIMIT 5;
    END IF;
END $$;

-- USAGE del esquema para todos los roles de servicio.
GRANT USAGE ON SCHEMA public TO
    svc_identity, svc_tenancy, svc_workers, svc_recognition,
    svc_access, svc_reports, svc_offline, svc_vigilancia, app_cron;


-- ════════════════════════════════════════════════════════════════════════════
-- 2) IDENTITY  — usuarios, roles, auditoría, parámetros (config)
-- ────────────────────────────────────────────────────────────────────────────
-- Dueño de la autenticación. parametros_sistema es config compartida: aquí tiene
-- escritura; los demás solo la leen (ver §8).
-- ════════════════════════════════════════════════════════════════════════════
GRANT SELECT, INSERT, UPDATE, DELETE ON
    usuarios, roles, historial_auditoria, parametros_sistema
    TO svc_identity;
GRANT USAGE, SELECT ON SEQUENCE
    usuarios_id_usuario_seq,
    roles_id_rol_seq,
    historial_auditoria_id_auditoria_seq,
    parametros_sistema_id_parametro_seq
    TO svc_identity;


-- ════════════════════════════════════════════════════════════════════════════
-- 3) TENANCY  — empresas, áreas, puertas, dispositivos (estructura física)
-- ════════════════════════════════════════════════════════════════════════════
GRANT SELECT, INSERT, UPDATE, DELETE ON
    empresas, area_trabajo, puertas_acceso, dispositivos
    TO svc_tenancy;
GRANT USAGE, SELECT ON SEQUENCE
    empresas_id_empresa_seq,
    area_trabajo_id_area_seq,
    puertas_acceso_id_puerta_seq,
    dispositivos_id_dispositivo_seq
    TO svc_tenancy;
-- La cascada de estado de empresa toca usuarios (identity); de área toca
-- trabajadores (workers). Se resuelve con SECURITY DEFINER en §9 (no se otorga
-- a tenancy escritura sobre tablas de otros dominios).


-- ════════════════════════════════════════════════════════════════════════════
-- 4) WORKERS (RRHH)  — trabajadores + biometría (pgvector)
-- ────────────────────────────────────────────────────────────────────────────
-- Al dar de alta un trabajador valida el área y deriva id_empresa → necesita
-- SELECT sobre tenancy (área/empresa).
-- ════════════════════════════════════════════════════════════════════════════
GRANT SELECT, INSERT, UPDATE, DELETE ON
    trabajadores, embeddings
    TO svc_workers;
GRANT USAGE, SELECT ON SEQUENCE
    trabajadores_id_trabajador_seq,
    embeddings_id_embedding_seq
    TO svc_workers;
-- SELECT cruzado a tenancy (validar área / derivar empresa):
GRANT SELECT ON area_trabajo, empresas TO svc_workers;

-- employee_monitoring corre como svc_workers (sincroniza nómina SYS21 → trabajadores
-- /embeddings) y es dueño de sus tablas de estado de sync. El DML sobre trabajadores
-- /embeddings ya está concedido arriba; aquí se añaden las tablas propias del sync.
GRANT SELECT, INSERT, UPDATE, DELETE ON
    sync_estado, fotos_pendientes
    TO svc_workers;
GRANT USAGE, SELECT ON SEQUENCE
    sync_estado_id_sync_seq,
    fotos_pendientes_id_pendiente_seq
    TO svc_workers;


-- ════════════════════════════════════════════════════════════════════════════
-- 4b) OFFLINE_SYNC  — roster para el APK (lectura) + ingesta de eventos offline +
--     enrolamiento walk-in (alta de rostros que NO están en SYS21)
-- ────────────────────────────────────────────────────────────────────────────
-- Sirve al APK kiosko. Baja el roster (trabajadores+embeddings+áreas+puertas),
-- recibe asistencias/intentos por lotes (INSERT idempotente ON CONFLICT) y enrola
-- walk-in (upsert de trabajadores/embeddings con id_emp=UUID, origen 'apk').
-- ════════════════════════════════════════════════════════════════════════════
-- Roster (solo lectura) + cruzados a tenancy:
GRANT SELECT ON
    trabajadores, embeddings, area_trabajo, puertas_acceso, empresas
    TO svc_offline;
-- Enrolamiento walk-in: upsert de trabajadores/embeddings.
GRANT INSERT, UPDATE ON trabajadores, embeddings TO svc_offline;
GRANT USAGE, SELECT ON SEQUENCE
    trabajadores_id_trabajador_seq,
    embeddings_id_embedding_seq
    TO svc_offline;
-- Ingesta de eventos. Las ASISTENCIAS ya NO se escriben directo: el lote offline
-- alimenta 'escaneos' y corre el MISMO pipeline que el online (validar +
-- consolidar), que DERIVA entrada/salida e incidencias. Los INTENTOS sí van
-- directos a intentos_acceso (no requieren derivación).
--   · escaneos: SELECT (RETURNING de conteo + consulta de días del lote) + INSERT.
--   · las funciones son SECURITY DEFINER (§9c) → svc_offline solo necesita EXECUTE,
--     NO escritura sobre asistencia/incidencias. El INSERT en asistencia de abajo
--     queda como no-op histórico (inocuo).
GRANT SELECT, INSERT ON escaneos TO svc_offline;
GRANT SELECT, INSERT ON asistencia, intentos_acceso TO svc_offline;
-- UPDATE en intentos_acceso: al subir la FOTO de evidencia offline (POST
-- /off_sync/intentos/foto), offline_sync pone la ruta con UPDATE ... SET ruta_foto.
GRANT UPDATE ON intentos_acceso TO svc_offline;
GRANT EXECUTE ON FUNCTION
    validar_escaneos_lote(timestamptz),
    consolidar_asistencia_dia(integer, integer, boolean)
    TO svc_offline;
-- Por si una fila llega sin UUID (normalmente lo genera el dispositivo).
GRANT EXECUTE ON FUNCTION gen_uuid_v7() TO svc_offline;


-- ════════════════════════════════════════════════════════════════════════════
-- 4c) VIGILANCIA  — cámaras/terminales de asistencia por reconocimiento facial
-- ────────────────────────────────────────────────────────────────────────────
-- Dueño de camaras/eventos_camara. Es DELGADO: NO corre IA ni registra asistencia;
-- manda los frames al scanner del back (POST /scanner/acceso/foto|liveness), que reusa
-- recognition + anti-spoof + escribe escaneos + consolida (como svc_access). Por eso
-- solo necesita SUS 2 tablas + lectura de tenancy. Alcance ACTUAL = solo asistencia.
-- ════════════════════════════════════════════════════════════════════════════
GRANT SELECT, INSERT, UPDATE, DELETE ON camaras, eventos_camara TO svc_vigilancia;
GRANT USAGE, SELECT ON SEQUENCE camaras_id_camara_seq TO svc_vigilancia;
-- Cruzados de solo lectura (resolver cámara→puerta/área/empresa/dispositivo + nombre del match):
GRANT SELECT ON empresas, area_trabajo, puertas_acceso, dispositivos, trabajadores
    TO svc_vigilancia;
-- Solo gen_uuid_v7 para el PK UUIDv7 de eventos_camara (no toca escaneos/asistencia:
-- eso lo hace el scanner del back como svc_access).
GRANT EXECUTE ON FUNCTION gen_uuid_v7() TO svc_vigilancia;


-- ════════════════════════════════════════════════════════════════════════════
-- 5) RECOGNITION  — motor facial, SIN ESTADO (solo lee para hacer match)
-- ────────────────────────────────────────────────────────────────────────────
-- Lee embeddings + trabajadores (workers) y puerta/empresa para acotar la
-- búsqueda (tenancy). NO escribe en BD: publica el resultado y 'access' registra.
-- (Transición: si por ahora el propio servicio del scanner escribe escaneos /
--  intentos, dale temporalmente los grants de §6 — ver NOTA al final.)
-- ════════════════════════════════════════════════════════════════════════════
GRANT SELECT ON
    embeddings, trabajadores,
    puertas_acceso, area_trabajo, empresas
    TO svc_recognition;


-- ════════════════════════════════════════════════════════════════════════════
-- 6) ACCESS / ATTENDANCE  — escaneos, asistencia, incidencias, intentos, accesos
-- ────────────────────────────────────────────────────────────────────────────
-- Dueño de los eventos. Sus PKs son UUID (gen_uuid_v7) → no necesita secuencias,
-- pero sí EXECUTE de gen_uuid_v7 y de las funciones de validación.
-- ════════════════════════════════════════════════════════════════════════════
GRANT SELECT, INSERT, UPDATE, DELETE ON
    escaneos, asistencia, incidencias, intentos_acceso, accesos_internos
    TO svc_access;
-- SELECT cruzado: validar_escaneos_lote / evaluar_acceso_interno leen workers y
-- tenancy (permiso del trabajador, tipo/empresa/geocerca de la puerta).
GRANT SELECT ON trabajadores, puertas_acceso, area_trabajo, empresas TO svc_access;
-- Funciones que invoca (corren como INVOKER → usan los grants de svc_access).
-- consolidar_asistencia_dia: el scanner la llama en vivo tras cada escaneo
-- (materializa la ENTRADA del día en asistencia).
GRANT EXECUTE ON FUNCTION
    gen_uuid_v7(),
    validar_escaneos_lote(timestamptz),
    evaluar_acceso_interno(integer, integer, geography, real, integer),
    consolidar_asistencia_dia(integer, integer, boolean)
    TO svc_access;


-- ════════════════════════════════════════════════════════════════════════════
-- 7) REPORTS  — SOLO LECTURA de todo (idealmente contra una réplica)
-- ════════════════════════════════════════════════════════════════════════════
GRANT SELECT ON ALL TABLES IN SCHEMA public TO svc_reports;
-- Que las tablas FUTURAS también queden legibles para reports sin re-otorgar:
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO svc_reports;


-- ════════════════════════════════════════════════════════════════════════════
-- 8) PARÁMETROS DE SISTEMA  — config compartida de SOLO LECTURA para los demás
-- ════════════════════════════════════════════════════════════════════════════
GRANT SELECT ON parametros_sistema TO
    svc_tenancy, svc_workers, svc_recognition, svc_access;


-- ════════════════════════════════════════════════════════════════════════════
-- 9) CRON + CASCADAS DE ESTADO (cruzan dominios)
-- ────────────────────────────────────────────────────────────────────────────
-- 9a) Cierre diario (3 AM): lo corre app_cron. consolidar_asistencia_dia() inserta
--     asistencia e incidencias y lee escaneos/empresas → grants de access + lectura.
GRANT SELECT, INSERT, UPDATE ON asistencia, incidencias TO app_cron;
GRANT SELECT ON escaneos, empresas TO app_cron;
GRANT EXECUTE ON FUNCTION consolidar_asistencia_dia(integer, integer, boolean) TO app_cron;
-- NOTA pg_cron: el job se AGENDA con privilegios sobre el esquema 'cron' (tarea
-- de admin). Para que el job corra como app_cron, reprográmalo con su username:
--   UPDATE cron.job SET username = 'app_cron' WHERE jobname = 'consolidar-asistencia-diaria';
-- (o agéndalo ya bajo ese rol). Verifica con: SELECT jobname, username FROM cron.job;

-- 9b) Cascada de estado: cuando tenancy desactiva una empresa/área, el trigger
--     escribe en usuarios (identity) y trabajadores (workers). Para NO otorgarle
--     a tenancy escritura sobre esos dominios, las funciones de cascada pasan a
--     SECURITY DEFINER (corren como su DUEÑO, que sí puede tocar esas tablas) y
--     fijan search_path por seguridad. El dueño debe poder escribir las tablas
--     cascadeadas (lo cumple el superusuario que creó el esquema).
ALTER FUNCTION fn_cascada_estado_empresa()    SECURITY DEFINER SET search_path = public, pg_temp;
ALTER FUNCTION fn_cascada_estado_area()       SECURITY DEFINER SET search_path = public, pg_temp;
ALTER FUNCTION fn_cascada_estado_trabajador() SECURITY DEFINER SET search_path = public, pg_temp;
-- fn_proteger_empresa_admin solo lanza excepción: no requiere DEFINER.

-- 9c) Pipeline de asistencia (escaneos → validar → consolidar). Pasan a SECURITY
--     DEFINER (corren como su DUEÑO) para que los callers (svc_access, app_cron y
--     ahora svc_offline con la ingesta offline) solo necesiten EXECUTE, sin
--     escritura directa sobre asistencia/incidencias/escaneos. search_path fijo.
ALTER FUNCTION validar_escaneos_lote(timestamptz)                SECURITY DEFINER SET search_path = public, pg_temp;
ALTER FUNCTION consolidar_asistencia_dia(integer, integer, boolean) SECURITY DEFINER SET search_path = public, pg_temp;


-- ════════════════════════════════════════════════════════════════════════════
-- 10) VERIFICACIÓN RÁPIDA
-- ────────────────────────────────────────────────────────────────────────────
--   SELECT rolname, rolconnlimit FROM pg_roles WHERE rolname LIKE 'svc\_%' OR rolname='app_cron';
--   -- ¿qué puede hacer un rol sobre una tabla?
--   SELECT grantee, privilege_type FROM information_schema.role_table_grants
--     WHERE table_name='escaneos' ORDER BY grantee;
-- ════════════════════════════════════════════════════════════════════════════

-- ── NOTA de transición (strangler-fig) ───────────────────────────────────────
-- Mientras el monolito siga escribiendo escaneos/intentos desde el flujo del
-- scanner (hoy en scanner_service), ese proceso debe conectarse con svc_access
-- (que ya tiene esos permisos), NO con svc_recognition. Cuando 'recognition' se
-- extraiga como servicio sin estado, quitará toda escritura y solo conservará los
-- SELECT de §5. Revisa y recorta los GRANT cruzados (§4,5,6) a medida que cada
-- dominio pase a hablar por API/eventos en vez de por SQL directo.
