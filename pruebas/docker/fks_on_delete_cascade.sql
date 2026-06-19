-- ============================================================
-- Borrado en cascada por jerarquía (ON DELETE)
-- ============================================================
-- Borrar una empresa borra todo lo de abajo: áreas, trabajadores,
-- dispositivos, puertas, usuarios, embeddings, asistencia, escaneos,
-- incidencias e historial de auditoría.
--
-- Los FK OPCIONALES hacia dispositivos / escaneos usan SET NULL para
-- NO borrar registros históricos cuando solo se elimina un dispositivo
-- o un escaneo suelto (la fila se conserva, solo pierde la referencia).
--
-- La empresa 99 está protegida contra DELETE por el trigger de
-- triggers_cascada_estado.sql.
--
-- Idempotente: DROP ... IF EXISTS antes de cada ADD.
-- ============================================================

-- ── CASCADE (borrar la fila hija) ─────────────────────────────────────────────
ALTER TABLE trabajadores DROP CONSTRAINT IF EXISTS trabajadores_id_area_fkey;
ALTER TABLE trabajadores ADD CONSTRAINT trabajadores_id_area_fkey
    FOREIGN KEY (id_area) REFERENCES area_trabajo(id_area) ON DELETE CASCADE;

ALTER TABLE dispositivos DROP CONSTRAINT IF EXISTS dispositivos_id_area_fkey;
ALTER TABLE dispositivos ADD CONSTRAINT dispositivos_id_area_fkey
    FOREIGN KEY (id_area) REFERENCES area_trabajo(id_area) ON DELETE CASCADE;

ALTER TABLE puertas_acceso DROP CONSTRAINT IF EXISTS puertas_acceso_id_area_fkey;
ALTER TABLE puertas_acceso ADD CONSTRAINT puertas_acceso_id_area_fkey
    FOREIGN KEY (id_area) REFERENCES area_trabajo(id_area) ON DELETE CASCADE;

ALTER TABLE asistencia DROP CONSTRAINT IF EXISTS asistencia_id_trabajador_fkey;
ALTER TABLE asistencia ADD CONSTRAINT asistencia_id_trabajador_fkey
    FOREIGN KEY (id_trabajador) REFERENCES trabajadores(id_trabajador) ON DELETE CASCADE;

ALTER TABLE asistencia DROP CONSTRAINT IF EXISTS asistencia_id_puerta_fkey;
ALTER TABLE asistencia ADD CONSTRAINT asistencia_id_puerta_fkey
    FOREIGN KEY (id_puerta) REFERENCES puertas_acceso(id_puerta) ON DELETE CASCADE;

ALTER TABLE escaneos DROP CONSTRAINT IF EXISTS escaneos_id_trabajador_fkey;
ALTER TABLE escaneos ADD CONSTRAINT escaneos_id_trabajador_fkey
    FOREIGN KEY (id_trabajador) REFERENCES trabajadores(id_trabajador) ON DELETE CASCADE;

ALTER TABLE escaneos DROP CONSTRAINT IF EXISTS escaneos_id_puerta_fkey;
ALTER TABLE escaneos ADD CONSTRAINT escaneos_id_puerta_fkey
    FOREIGN KEY (id_puerta) REFERENCES puertas_acceso(id_puerta) ON DELETE CASCADE;

ALTER TABLE incidencias DROP CONSTRAINT IF EXISTS incidencias_id_trabajador_fkey;
ALTER TABLE incidencias ADD CONSTRAINT incidencias_id_trabajador_fkey
    FOREIGN KEY (id_trabajador) REFERENCES trabajadores(id_trabajador) ON DELETE CASCADE;

ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_empresa__fk;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_empresa__fk
    FOREIGN KEY (empresa) REFERENCES empresas(id_empresa) ON DELETE CASCADE;

ALTER TABLE historial_auditoria DROP CONSTRAINT IF EXISTS historial_auditoria_id_usuario_fkey;
ALTER TABLE historial_auditoria ADD CONSTRAINT historial_auditoria_id_usuario_fkey
    FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario) ON DELETE CASCADE;

-- ── SET NULL (conservar el registro; limpiar la referencia opcional) ──────────
ALTER TABLE asistencia DROP CONSTRAINT IF EXISTS asistencia_id_dispositivo_fkey;
ALTER TABLE asistencia ADD CONSTRAINT asistencia_id_dispositivo_fkey
    FOREIGN KEY (id_dispositivo) REFERENCES dispositivos(id_dispositivo) ON DELETE SET NULL;

ALTER TABLE escaneos DROP CONSTRAINT IF EXISTS escaneos_id_dispositivo_fkey;
ALTER TABLE escaneos ADD CONSTRAINT escaneos_id_dispositivo_fkey
    FOREIGN KEY (id_dispositivo) REFERENCES dispositivos(id_dispositivo) ON DELETE SET NULL;

ALTER TABLE incidencias DROP CONSTRAINT IF EXISTS incidencias_id_escaneo_ref_fkey;
ALTER TABLE incidencias ADD CONSTRAINT incidencias_id_escaneo_ref_fkey
    FOREIGN KEY (id_escaneo_ref) REFERENCES escaneos(id_escaneo) ON DELETE SET NULL;

ALTER TABLE puertas_acceso DROP CONSTRAINT IF EXISTS puertas_acceso_id_dispositivo_fkey;
ALTER TABLE puertas_acceso ADD CONSTRAINT puertas_acceso_id_dispositivo_fkey
    FOREIGN KEY (id_dispositivo) REFERENCES dispositivos(id_dispositivo) ON DELETE SET NULL;

-- Nota: empresa->áreas y empresa->puertas YA tenían ON DELETE CASCADE;
-- trabajador->embeddings también. usuarios->roles se deja en RESTRICT
-- (borrar un rol no debe borrar usuarios).
