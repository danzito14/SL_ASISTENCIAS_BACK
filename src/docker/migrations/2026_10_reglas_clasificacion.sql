-- 2026_10_reglas_clasificacion.sql
--
-- Reglas de clasificación del sync SYS21 en la BASE (antes vivían fijas en
-- employee_monitoring/src/sync/clasificador_areas.py). Cada regla dice a qué grupo
-- (oficina/empaque/campo) va un PUESTO (agrícola) o DEPARTAMENTO (comercial), y
-- opcionalmente reemplaza el permiso_escaneo / nivel_acceso_interno por defecto del
-- grupo. Se administran por API (/emp_sync/reglas, solo super-admin) y el
-- clasificador las relee en cada corrida del sync.
--
-- Incluye las 96 reglas que había en el código. Idempotente.

CREATE TABLE IF NOT EXISTS reglas_clasificacion (
    id_regla             SERIAL PRIMARY KEY,
    origen_nomina        VARCHAR(30)  NOT NULL
                         CHECK (origen_nomina IN ('agricola', 'agricola_com')),
    -- Puesto/departamento NORMALIZADO (minúsculas, sin acentos, espacios colapsados):
    -- es con lo que el clasificador empata la nómina.
    clave                VARCHAR(150) NOT NULL,
    -- Texto tal como se capturó (para mostrar).
    nombre               VARCHAR(150) NOT NULL,
    grupo                VARCHAR(20)  NOT NULL
                         CHECK (grupo IN ('oficina', 'empaque', 'campo')),
    -- Reemplazos opcionales del default del grupo. NULL = usar el del grupo.
    permiso_escaneo      permiso_escaneo,
    nivel_acceso_interno nivel_acceso_interno,
    actualizado_por      VARCHAR(100),
    fecha_creacion       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    fecha_actualizacion  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_regla_origen_clave UNIQUE (origen_nomina, clave)
);

INSERT INTO reglas_clasificacion (origen_nomina, clave, nombre, grupo, permiso_escaneo, nivel_acceso_interno) VALUES
    ('agricola_com', 'administracion', 'ADMINISTRACION', 'oficina', NULL, NULL),
    ('agricola_com', 'compras', 'COMPRAS', 'oficina', NULL, NULL),
    ('agricola_com', 'rrhh y nominas', 'RRHH Y NOMINAS', 'oficina', NULL, NULL),
    ('agricola_com', 'sistemas', 'SISTEMAS', 'oficina', NULL, NULL),
    ('agricola_com', 'administracion sl', 'ADMINISTRACION SL', 'oficina', NULL, NULL),
    ('agricola_com', 'servicios administrativos sl', 'SERVICIOS ADMINISTRATIVOS SL', 'oficina', NULL, NULL),
    ('agricola_com', 'ventas', 'VENTAS', 'oficina', NULL, NULL),
    ('agricola_com', 'gasolina fija', 'GASOLINA FIJA', 'oficina', NULL, NULL),
    ('agricola_com', 'practicantes', 'PRACTICANTES', 'oficina', NULL, NULL),
    ('agricola_com', 'gasolina', 'GASOLINA', 'oficina', NULL, NULL),
    ('agricola_com', 'administracion alpine', 'ADMINISTRACION ALPINE', 'oficina', NULL, NULL),
    ('agricola_com', 'logistica', 'LOGISTICA', 'oficina', NULL, NULL),
    ('agricola_com', 'inocuidad', 'INOCUIDAD', 'oficina', NULL, NULL),
    ('agricola_com', 'seguridad e intendencia', 'SEGURIDAD E INTENDENCIA', 'oficina', NULL, NULL),
    ('agricola_com', 'mantenimiento y equipo de transporte', 'MANTENIMIENTO Y EQUIPO DE TRANSPORTE', 'oficina', NULL, NULL),
    ('agricola_com', 'campo abierto', 'CAMPO ABIERTO', 'campo', NULL, NULL),
    ('agricola_com', 'campo protegido', 'CAMPO PROTEGIDO', 'campo', NULL, NULL),
    ('agricola_com', 'campo', 'CAMPO', 'campo', NULL, NULL),
    ('agricola_com', 'fijos caco sinaloa', 'FIJOS CACO SINALOA', 'campo', NULL, NULL),
    ('agricola_com', 'fijos caco jalisco', 'FIJOS CACO JALISCO', 'campo', NULL, NULL),
    ('agricola_com', 'fijos produce', 'FIJOS PRODUCE', 'campo', NULL, NULL),
    ('agricola_com', 'huerta de mango', 'HUERTA DE MANGO', 'campo', NULL, NULL),
    ('agricola_com', 'todos santos', 'TODOS SANTOS', 'campo', NULL, NULL),
    ('agricola_com', 'almacen', 'ALMACEN', 'empaque', NULL, NULL),
    ('agricola_com', 'empaque ejote', 'EMPAQUE EJOTE', 'empaque', NULL, NULL),
    ('agricola_com', 'albergues', 'ALBERGUES', 'empaque', NULL, NULL),
    ('agricola_com', 'empaque chile', 'EMPAQUE CHILE', 'empaque', NULL, NULL),
    ('agricola_com', 'empaque', 'EMPAQUE', 'empaque', NULL, NULL),
    ('agricola_com', 'fijos no fijos planta sl', 'FIJOS NO FIJOS PLANTA SL', 'empaque', NULL, 'mixto'),
    ('agricola_com', 'fijo empacadora', 'FIJO EMPACADORA', 'empaque', NULL, NULL),
    ('agricola_com', 'emapque', 'EMAPQUE', 'empaque', NULL, NULL),
    ('agricola_com', 'mango', 'MANGO', 'campo', NULL, NULL),
    ('agricola_com', 'todo santos fijos', 'TODO SANTOS FIJOS', 'campo', NULL, NULL),
    ('agricola_com', 'gasolina fija caco', 'GASOLINA FIJA CACO', 'oficina', NULL, NULL),
    ('agricola_com', 'cat malacon', 'CAT MALACON', 'oficina', NULL, NULL),
    ('agricola', 'administrativo', 'ADMINISTRATIVO', 'oficina', NULL, NULL),
    ('agricola', 'auxiliar administrativo', 'AUXILIAR ADMINISTRATIVO', 'oficina', NULL, NULL),
    ('agricola', 'administracion', 'ADMINISTRACION', 'oficina', NULL, NULL),
    ('agricola', 'auxiliar-sistemas', 'AUXILIAR-SISTEMAS', 'oficina', NULL, NULL),
    ('agricola', 'auxiliar nominas', 'AUXILIAR NOMINAS', 'oficina', NULL, NULL),
    ('agricola', 'aux. de nomina', 'AUX. DE NOMINA', 'oficina', NULL, NULL),
    ('agricola', 'aux contable', 'AUX CONTABLE', 'oficina', NULL, NULL),
    ('agricola', 'auxiliar imss (prefiliar)', 'AUXILIAR IMSS (PREFILIAR)', 'oficina', NULL, NULL),
    ('agricola', 'seguridad y salud', 'SEGURIDAD Y SALUD', 'oficina', NULL, NULL),
    ('agricola', 'trabajadora social', 'TRABAJADORA SOCIAL', 'oficina', NULL, NULL),
    ('agricola', 'trabajador social aux', 'TRABAJADOR SOCIAL AUX', 'oficina', NULL, NULL),
    ('agricola', 'mensajero', 'MENSAJERO', 'oficina', NULL, NULL),
    ('agricola', 'asesora educativa', 'ASESORA EDUCATIVA', 'oficina', NULL, NULL),
    ('agricola', 'practicante', 'PRACTICANTE', 'oficina', NULL, NULL),
    ('agricola', 'monitoreo', 'MONITOREO', 'oficina', NULL, NULL),
    ('agricola', 'aux inocuidad', 'AUX INOCUIDAD', 'oficina', NULL, NULL),
    ('agricola', 'auxiliar compras', 'AUXILIAR COMPRAS', 'oficina', NULL, NULL),
    ('agricola', 'empaque', 'EMPAQUE', 'empaque', NULL, NULL),
    ('agricola', 'almacen empaque', 'ALMACEN EMPAQUE', 'empaque', NULL, NULL),
    ('agricola', 'montacarguista almacen', 'MONTACARGUISTA ALMACEN', 'empaque', NULL, NULL),
    ('agricola', 'guardia empaque', 'GUARDIA EMPAQUE', 'empaque', NULL, NULL),
    ('agricola', 'escaneador', 'ESCANEADOR', 'empaque', NULL, NULL),
    ('agricola', 'revisador caco campo', 'REVISADOR CACO CAMPO', 'empaque', NULL, NULL),
    ('agricola', 'vaciadores', 'VACIADORES', 'empaque', NULL, NULL),
    ('agricola', 'jornalero', 'JORNALERO', 'campo', NULL, NULL),
    ('agricola', 'cuadrillero', 'CUADRILLERO', 'campo', NULL, NULL),
    ('agricola', 'chofer', 'CHOFER', 'campo', NULL, NULL),
    ('agricola', 'mantenimiento', 'MANTENIMIENTO', 'campo', NULL, NULL),
    ('agricola', 'produccion', 'PRODUCCION', 'campo', NULL, NULL),
    ('agricola', 'operador', 'OPERADOR', 'campo', NULL, NULL),
    ('agricola', 'mayordomo', 'MAYORDOMO', 'campo', NULL, NULL),
    ('agricola', 'apuntador', 'APUNTADOR', 'campo', NULL, NULL),
    ('agricola', 'campero', 'CAMPERO', 'campo', NULL, NULL),
    ('agricola', 'malleros', 'MALLEROS', 'campo', NULL, NULL),
    ('agricola', 'ninera', 'NINERA', 'campo', NULL, NULL),
    ('agricola', 'cocinera', 'COCINERA', 'campo', NULL, NULL),
    ('agricola', 'portero', 'PORTERO', 'campo', NULL, NULL),
    ('agricola', 'campo', 'CAMPO', 'campo', NULL, NULL),
    ('agricola', 'auxiliar de corte', 'AUXILIAR DE CORTE', 'campo', NULL, NULL),
    ('agricola', 'supervisor corte-chile', 'SUPERVISOR CORTE-CHILE', 'campo', NULL, NULL),
    ('agricola', 'jardinero', 'JARDINERO', 'campo', NULL, NULL),
    ('agricola', 'mantenimiento albergue', 'MANTENIMIENTO ALBERGUE', 'campo', NULL, NULL),
    ('agricola', 'mantenimiento electrico', 'MANTENIMIENTO ELECTRICO', 'campo', NULL, NULL),
    ('agricola', 'supervisor campo natoches', 'SUPERVISOR CAMPO NATOCHES', 'campo', NULL, NULL),
    ('agricola', 'guardia', 'GUARDIA', 'campo', NULL, NULL),
    ('agricola', 'aux. mantenimiento', 'AUX. MANTENIMIENTO', 'campo', NULL, NULL),
    ('agricola', 'enc de motor de riego carcamo', 'ENC DE MOTOR DE RIEGO CARCAMO', 'campo', NULL, NULL),
    ('agricola', 'carcamo riego', 'CARCAMO RIEGO', 'campo', NULL, NULL),
    ('agricola', 'caco-velador', 'CACO-VELADOR', 'campo', NULL, NULL),
    ('agricola', 'fuguero caco campo', 'FUGUERO CACO CAMPO', 'campo', NULL, NULL),
    ('agricola', 'canalero', 'CANALERO', 'campo', NULL, NULL),
    ('agricola', 'enc. de sistemas de riego', 'ENC. DE SISTEMAS DE RIEGO', 'campo', NULL, NULL),
    ('agricola', 'aplicador de herbicida', 'APLICADOR DE HERBICIDA', 'campo', NULL, NULL),
    ('agricola', 'aux. de riego', 'AUX. DE RIEGO', 'campo', NULL, NULL),
    ('agricola', 'monitoreo caco campo', 'MONITOREO CACO CAMPO', 'campo', NULL, NULL),
    ('agricola', 'aplicador de fungicida', 'APLICADOR DE FUNGICIDA', 'campo', NULL, NULL),
    ('agricola', 'sanquero', 'SANQUERO', 'campo', NULL, NULL),
    ('agricola', 'supervisor campo viva organica', 'SUPERVISOR CAMPO VIVA ORGANICA', 'campo', NULL, NULL),
    ('agricola', 'spervisor corte-chile', 'SPERVISOR CORTE-CHILE', 'campo', NULL, NULL),
    ('agricola', 'caco- velador', 'CACO- VELADOR', 'campo', NULL, NULL),
    ('agricola', 'fuguero agropotato', 'FUGUERO AGROPOTATO', 'campo', NULL, NULL)
ON CONFLICT (origen_nomina, clave) DO NOTHING;

-- employee_monitoring corre como svc_workers: lee las reglas en cada sync y las
-- administra por API.
GRANT SELECT, INSERT, UPDATE, DELETE ON reglas_clasificacion TO svc_workers;
GRANT USAGE, SELECT ON SEQUENCE reglas_clasificacion_id_regla_seq TO svc_workers;
