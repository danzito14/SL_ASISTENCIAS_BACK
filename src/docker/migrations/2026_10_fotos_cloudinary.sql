-- 2026_10_fotos_cloudinary.sql
--
-- Copia en Cloudinary (carpeta SL-Asistencias) de la foto ACEPTADA de cada trabajador,
-- para consultarla después. Dos orígenes de la foto, mismo destino:
--   · el sync SYS21 (employee_monitoring): SL-Asistencias/<origen>/<id_emp>
--   · el panel (workers, registrar/actualizar rostro): igual si el trabajador es de
--     nómina; SL-Asistencias/manual/<id_trabajador> si es alta manual.
--
-- trabajadores.foto_url = la ÚLTIMA foto aceptada (la que consulta el sistema).
-- sync_estado.foto_url  = control del sync: NULL = falta copiarla (se reintenta).
-- svc_workers ya tiene UPDATE sobre ambas tablas. Idempotente.
ALTER TABLE sync_estado
    ADD COLUMN IF NOT EXISTS foto_url       TEXT,
    ADD COLUMN IF NOT EXISTS foto_subida_en TIMESTAMPTZ;

ALTER TABLE trabajadores
    ADD COLUMN IF NOT EXISTS foto_url       TEXT,
    ADD COLUMN IF NOT EXISTS foto_subida_en TIMESTAMPTZ;
