-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║  2026_07_fix_schema_drift.sql                                              ║
-- ║  Columnas que se agregaron a init.sql DESPUÉS del primer deploy y que      ║
-- ║  init.sql NO puede aplicar a una BD existente:                             ║
-- ║    · `CREATE TABLE IF NOT EXISTS` SALTA la tabla (ya existe) → columnas    ║
-- ║      nuevas del CREATE nunca se agregan.                                   ║
-- ║    · Los `ALTER ... ADD COLUMN` inline de init.sql tampoco corren, porque  ║
-- ║      init.sql SOLO se ejecuta en una BD nueva (initdb), no en cada deploy. ║
-- ║  deploy_prod.sh corre migrations/*.sql → los ALTER idempotentes van AQUÍ.  ║
-- ║                                                                            ║
-- ║  Síntoma que arregla: 500 en /scanner/acceso/* y /incidencias/combinado    ║
-- ║    → psycopg2 UndefinedColumn: column "estado" of relation                 ║
-- ║      "intentos_acceso" does not exist.                                     ║
-- ╚══════════════════════════════════════════════════════════════════════════╝

-- intentos_acceso.estado (estado de revisión; 'justificada' dispara asistencia manual).
ALTER TABLE intentos_acceso
    ADD COLUMN IF NOT EXISTS estado estado_incidencia NOT NULL DEFAULT 'pendiente';

-- trabajadores.foto_perfil (aparece en el ORM Trabajador y en /incidencias/combinado).
ALTER TABLE trabajadores
    ADD COLUMN IF NOT EXISTS foto_perfil BYTEA;

-- Verificación:
--   SELECT column_name FROM information_schema.columns
--     WHERE table_name='intentos_acceso' AND column_name='estado';
--   SELECT column_name FROM information_schema.columns
--     WHERE table_name='trabajadores' AND column_name='foto_perfil';
