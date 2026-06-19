-- ============================================================
-- Migración: encapsulación por empresa + intentos de acceso
-- (2026-06-18). Idempotente: se puede correr varias veces.
--
-- Aplicar sobre una BD YA EXISTENTE (init.sql/seed_roles solo corren con
-- volumen vacío). En el VPS:
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < migracion_empresa_intentos.sql
-- ============================================================

-- 1) Columna usuarios.empresa (+ FK a empresas) ------------------------------
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS empresa INTEGER DEFAULT 1;

DO $$ BEGIN
    ALTER TABLE usuarios
        ADD CONSTRAINT usuarios_empresa__fk
        FOREIGN KEY (empresa) REFERENCES empresas(id_empresa);
EXCEPTION WHEN duplicate_object THEN NULL;  -- ya existe
END $$;

-- 2) Empresa 99 = super-admin (ve TODAS). El FK la exige. ubicacion (POLYGON),
--    zona_horaria y estado son NOT NULL → se ponen valores centinela.
INSERT INTO empresas (id_empresa, nombre_empresa, ubicacion, zona_horaria, estado)
VALUES (99, 'ADMIN GLOBAL',
        ST_GeogFromText('SRID=4326;POLYGON((0 0,0 1,1 1,1 0,0 0))'),
        'America/Mazatlan', 'activo')
ON CONFLICT (id_empresa) DO NOTHING;

-- 3) Nuevo tipo de incidencia 'acceso_otra_empresa' --------------------------
ALTER TABLE incidencias DROP CONSTRAINT IF EXISTS incidencias_tipo_incidencia_check;
ALTER TABLE incidencias
    ADD CONSTRAINT incidencias_tipo_incidencia_check
    CHECK (tipo_incidencia IN (
        'salida_sin_registro', 'entrada_sin_registro', 'falta',
        'retardo', 'fuera_de_area', 'acceso_otra_empresa'
    ));

-- 4) Tabla de intentos de acceso rechazados ----------------------------------
CREATE TABLE IF NOT EXISTS intentos_acceso (
    id_intento    SERIAL PRIMARY KEY,
    id_puerta     INTEGER REFERENCES puertas_acceso(id_puerta),
    id_empresa    INTEGER REFERENCES empresas(id_empresa),
    tipo          VARCHAR(20) NOT NULL,
    id_trabajador INTEGER REFERENCES trabajadores(id_trabajador),
    similitud     NUMERIC(4,3),
    ruta_foto     TEXT,
    ubicacion     GEOGRAPHY(POINT,4326),
    fecha         TIMESTAMPTZ DEFAULT now()
);

-- 5) Renombrar roles a nombres más entendibles (no-op si ya están nuevos) -----
UPDATE roles SET nombre_rol='consultor'     WHERE nombre_rol='lectura';
UPDATE roles SET nombre_rol='operador'      WHERE nombre_rol='escritura';
UPDATE roles SET nombre_rol='administrador' WHERE nombre_rol='total';
UPDATE roles SET nombre_rol='kiosko'        WHERE nombre_rol='scanner';

-- 6) (Opcional) dar permiso para ver los intentos a roles que lo necesiten.
--    Ejemplo: agregar 'intentos:read' al scope de 'supervisor'.
--    El rol 'administrador' (scope '*') ya los ve.
-- UPDATE roles
-- SET permisos = jsonb_set(permisos, '{scopes}',
--     (permisos->'scopes') || '["intentos:read"]'::jsonb)
-- WHERE nombre_rol = 'supervisor'
--   AND NOT (permisos->'scopes' ? 'intentos:read');
