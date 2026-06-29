-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║  2026_07_offline_sync.sql                                                  ║
-- ║  Migración IDEMPOTENTE para el microservicio offline_sync.                 ║
-- ║                                                                            ║
-- ║  offline_sync NO agrega tablas ni columnas (reutiliza asistencia /         ║
-- ║  intentos_acceso / trabajadores / embeddings, ya offline-first). Esta      ║
-- ║  migración solo crea el ROL svc_offline y le otorga el mínimo privilegio.  ║
-- ║                                                                            ║
-- ║  Aplicar como superusuario / dueño del esquema en la BD existente:         ║
-- ║    psql -U postgres -d SL_ASISTENCIAS -f 2026_07_offline_sync.sql          ║
-- ║                                                                            ║
-- ║  ⚠️  Cambia la contraseña placeholder (o usa ALTER ROLE ... PASSWORD).     ║
-- ╚══════════════════════════════════════════════════════════════════════════╝

-- 1) Rol de servicio (idempotente).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_offline') THEN
        CREATE ROLE svc_offline LOGIN PASSWORD 'CAMBIAR_offline' CONNECTION LIMIT 15;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO svc_offline;

-- 2) Roster (solo lectura) + cruzados a tenancy.
GRANT SELECT ON
    trabajadores, embeddings, area_trabajo, puertas_acceso, empresas
    TO svc_offline;

-- 3) Enrolamiento walk-in: upsert de trabajadores/embeddings.
GRANT INSERT, UPDATE ON trabajadores, embeddings TO svc_offline;
GRANT USAGE, SELECT ON SEQUENCE
    trabajadores_id_trabajador_seq,
    embeddings_id_embedding_seq
    TO svc_offline;

-- 4) Ingesta de eventos (SELECT por el RETURNING que cuenta insertados/duplicados).
GRANT SELECT, INSERT ON asistencia, intentos_acceso TO svc_offline;

-- 5) Por si una fila de ingesta llega sin UUID (normalmente lo genera el dispositivo).
GRANT EXECUTE ON FUNCTION gen_uuid_v7() TO svc_offline;

-- 6) Rol de aplicación 'escaneador' (identity): kiosko + gestión de trabajadores/
--    rostros. El APK con este rol puede ver/crear/editar trabajadores y asignarles
--    rostro (vía workers /trabajadores y offline_sync /off_sync). scanner:use implica
--    off_sync:read/off_sync:write (ver offline_sync/core/scopes.py). Idempotente.
INSERT INTO roles (nombre_rol, descripcion, permisos, estado) VALUES
    ('escaneador', 'Kiosko + gestión de trabajadores y rostros (enrola/edita/elige trabajador y le pone rostro).',
     '{"scopes": ["scanner:use", "trabajadores:read", "trabajadores:write", "embeddings:read", "embeddings:write", "areas:read"]}'::jsonb,
     'activo')
ON CONFLICT (nombre_rol) DO NOTHING;

-- Verificación:
--   SELECT grantee, privilege_type FROM information_schema.role_table_grants
--     WHERE grantee='svc_offline' ORDER BY table_name, privilege_type;
--   SELECT nombre_rol, permisos FROM roles WHERE nombre_rol = 'escaneador';


-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║  7) USUARIO KIOSKO del APK (login) — NO se siembra por defecto.            ║
-- ║                                                                            ║
-- ║  El APK hace login en identity (POST /usuarios/token) con un usuario de    ║
-- ║  rol 'escaneador' (o 'kiosko'). Su token NO expira porque ese rol está en  ║
-- ║  ROLES_TOKEN_SIN_EXPIRACION="kiosko,escaneador" (ver docker-compose).      ║
-- ║                                                                            ║
-- ║  El usuario va ATADO A UNA EMPRESA (define el roster que baja). Un kiosko  ║
-- ║  por empresa/tipo de fichaje. Igual que el resto del sistema, NO se        ║
-- ║  hornean credenciales por defecto en prod: créalo a propósito.             ║
-- ║                                                                            ║
-- ║  FORMA RECOMENDADA — por la API de identity (hashea la contraseña sola):   ║
-- ║    POST /usuarios  { "nombre_usuario":"kiosko_emp1", "contrasena":"...",   ║
-- ║                      "id_rol": <id de 'escaneador'>, "empresa": 1 }        ║
-- ║                                                                            ║
-- ║  FORMA DIRECTA (psql) — la contraseña debe ir YA HASHEADA con el mismo     ║
-- ║  PBKDF2 de identity/core/security.py:                                      ║
-- ║    pbkdf2_sha256$240000$<salt_hex>$<dk_hex>                                ║
-- ║  Genera el hash con:  python -c "from src.core.security import            ║
-- ║    hash_password; print(hash_password('TU_PASS'))"  (dentro de identity).  ║
-- ║                                                                            ║
-- ║  Ejemplo LISTO (password de prueba 'Kiosko-SL-2026', empresa 1) — CÁMBIALO ║
-- ║  antes de cualquier uso real. Descomenta para sembrarlo:                   ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
-- INSERT INTO usuarios (nombre_usuario, contrasena, id_rol, empresa, estado)
-- SELECT 'kiosko_emp1',
--        'pbkdf2_sha256$240000$37fcf9bf5a33ecb334131e2001cef174$f68ddaa873406b38ec4667303db2622289081be4531f03b8a930d3ea5234b00f',
--        r.id_rol, 1, 'activo'
--   FROM roles r WHERE r.nombre_rol = 'escaneador'
-- ON CONFLICT (nombre_usuario) DO NOTHING;
