-- 2026_09_grant_areas_employee_monitoring.sql
--
-- Da a svc_workers permiso de INSERTAR en 'area_trabajo'.
--
-- MOTIVO: el clasificador del sync SYS21 (employee_monitoring, que corre como
-- svc_workers) ahora CREA el área estándar (campo/empaque/oficina) cuando la
-- empresa del empleado existe pero no tiene el área de ese tipo (p.ej. empresas
-- 8 y 11-15). Solo INSERT: no actualiza ni borra áreas (eso sigue siendo de tenancy).
--
-- roles_microservicio.sql ya lo incluye para instalaciones nuevas, pero ese archivo
-- SOLO se ejecuta al inicializar un volumen vacío: en una base existente hay que
-- aplicar este GRANT. Idempotente.
GRANT INSERT ON area_trabajo TO svc_workers;
GRANT USAGE, SELECT ON SEQUENCE area_trabajo_id_area_seq TO svc_workers;
