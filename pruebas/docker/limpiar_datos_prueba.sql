-- ============================================================
-- Limpieza de DATOS DE PRUEBA para arrancar producción en limpio.
-- Deja la ESTRUCTURA, los ROLES, el usuario admin y la empresa 99 listos
-- para cargar datos reales desde la app.
--
-- ⚠️  DESTRUCTIVO E IRREVERSIBLE. Haz backup ANTES:
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backup_pre_limpieza.sql
--
-- ⚠️  Ajusta 'admin' al nombre REAL de tu usuario administrador. Si te
--     equivocas, borras a todos los usuarios y te quedas sin poder entrar.
-- ============================================================
BEGIN;

-- 1) Borrar registros y entidades de prueba (CASCADE limpia dependientes y
--    RESTART IDENTITY reinicia los IDs para que lo real empiece en 1).
TRUNCATE
    intentos_acceso,
    incidencias,
    asistencia,
    escaneos,
    embeddings,
    trabajadores,
    puertas_acceso,
    dispositivos,
    area_trabajo,
    historial_auditoria
    RESTART IDENTITY CASCADE;

-- 2) Conservar SOLO el usuario admin (ajusta el nombre); déjalo en la empresa 99.
DELETE FROM usuarios WHERE nombre_usuario <> 'admin';
UPDATE usuarios SET empresa = 99 WHERE nombre_usuario = 'admin';

-- 3) Conservar SOLO la empresa comodín 99 (super-admin).
DELETE FROM empresas WHERE id_empresa <> 99;

COMMIT;
