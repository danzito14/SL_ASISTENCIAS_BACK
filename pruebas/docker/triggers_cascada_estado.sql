-- ============================================================
-- Cascada de ESTADO (activo/inactivo) por jerarquía
-- ============================================================
--   empresa     -> áreas, puertas, usuarios
--   área        -> trabajadores, dispositivos, puertas
--   trabajador  -> embeddings
--
-- Bidireccional con REACTIVACIÓN INTELIGENTE: la columna marca
-- `inactivo_por_cascada` recuerda si la fila la apagó la cascada.
-- Al reactivar el padre, solo se reactivan las filas que apagó la
-- cascada; lo que se desactivó a mano ANTES se queda desactivado.
--
-- La empresa 99 (super-admin, = settings.EMPRESA_ADMIN) NO se puede
-- desactivar ni borrar.
--
-- Idempotente: se puede correr varias veces.
-- ============================================================

-- 1) Columna marca en cada entidad hija ----------------------------------------
ALTER TABLE area_trabajo   ADD COLUMN IF NOT EXISTS inactivo_por_cascada BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE trabajadores   ADD COLUMN IF NOT EXISTS inactivo_por_cascada BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE dispositivos   ADD COLUMN IF NOT EXISTS inactivo_por_cascada BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE puertas_acceso ADD COLUMN IF NOT EXISTS inactivo_por_cascada BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE embeddings     ADD COLUMN IF NOT EXISTS inactivo_por_cascada BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE usuarios       ADD COLUMN IF NOT EXISTS inactivo_por_cascada BOOLEAN NOT NULL DEFAULT FALSE;

-- 2) Proteger empresa 99: no desactivar, no borrar -----------------------------
CREATE OR REPLACE FUNCTION fn_proteger_empresa_admin()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.id_empresa = 99 THEN
            RAISE EXCEPTION 'La empresa 99 (super-admin) no se puede eliminar.';
        END IF;
        RETURN OLD;
    ELSE  -- UPDATE
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

-- 3) Cascada desde EMPRESA -> áreas, puertas, usuarios -------------------------
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

-- 4) Cascada desde ÁREA -> trabajadores, dispositivos, puertas -----------------
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

-- 5) Cascada desde TRABAJADOR -> embeddings ------------------------------------
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
