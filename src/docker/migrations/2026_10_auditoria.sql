-- 2026_10_auditoria.sql
--
-- Historial de cambios en la BASE: triggers que escriben en historial_auditoria
-- cada INSERT / UPDATE / DELETE de las tablas de configuración y personal.
--
-- Diseño:
--   · Una sola función genérica fn_auditar(pk, columnas_a_ignorar...).
--   · UPDATE: guarda SOLO los campos que cambiaron (anterior → nuevo); si no cambió
--     nada real, no registra. INSERT/DELETE: la fila completa.
--   · Nunca guarda contraseñas (se marca '***' si cambió) ni binarios (foto_perfil).
--   · Quién: la variable de sesión app.id_usuario / app.usuario / app.ip (la ponen
--     los servicios por petición; si no viene, queda NULL) + el rol de BD que hizo
--     el cambio (svc_workers, svc_tenancy…, o el usuario de consola).
--   · Si la auditoría falla, la operación de negocio NO se cae (solo un WARNING).
--   · Retención: pg_cron borra lo de más de 180 días (03:45 diario).
--
-- Idempotente.

-- ── 1) Ajustes a historial_auditoria ─────────────────────────────────────────
ALTER TABLE historial_auditoria
    ADD COLUMN IF NOT EXISTS usuario_app        VARCHAR(150),   -- nombre del usuario del panel
    ADD COLUMN IF NOT EXISTS rol_bd             VARCHAR(63),    -- rol de BD que hizo el cambio
    ADD COLUMN IF NOT EXISTS campos_modificados TEXT[];         -- solo en UPDATE

-- Borrar un usuario NO debe borrar el historial de lo que hizo.
ALTER TABLE historial_auditoria DROP CONSTRAINT IF EXISTS historial_auditoria_id_usuario_fkey;
ALTER TABLE historial_auditoria
    ADD CONSTRAINT historial_auditoria_id_usuario_fkey
    FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_auditoria_registro
    ON historial_auditoria (tabla_modificada, id_registro_afectado);
CREATE INDEX IF NOT EXISTS idx_auditoria_usuario
    ON historial_auditoria (id_usuario);

-- ── 2) Función genérica ──────────────────────────────────────────────────────
-- Argumentos del trigger: TG_ARGV[0] = columna PK; TG_ARGV[1..] = columnas a ignorar.
-- SECURITY DEFINER: los roles de servicio no necesitan permiso sobre la tabla.
CREATE OR REPLACE FUNCTION fn_auditar()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_pk       TEXT   := TG_ARGV[0];
    v_ignorar  TEXT[] := CASE WHEN TG_NARGS > 1 THEN TG_ARGV[1:TG_NARGS - 1] ELSE '{}'::TEXT[] END;
    v_ocultar  TEXT[] := ARRAY['contrasena'];
    v_viejo    JSONB;
    v_nuevo    JSONB;
    v_campos   TEXT[];
    v_ant      JSONB;
    v_nue      JSONB;
    v_uid_txt  TEXT;
    v_uid      INT;
    k          TEXT;
BEGIN
    IF TG_OP <> 'INSERT' THEN v_viejo := to_jsonb(OLD) - v_ignorar; END IF;
    IF TG_OP <> 'DELETE' THEN v_nuevo := to_jsonb(NEW) - v_ignorar; END IF;

    IF TG_OP = 'UPDATE' THEN
        SELECT array_agg(n.key ORDER BY n.key) INTO v_campos
        FROM jsonb_each(v_nuevo) n
        WHERE n.value IS DISTINCT FROM v_viejo -> n.key;
        IF v_campos IS NULL THEN
            RETURN NULL;                      -- nada cambió de verdad: no se registra
        END IF;
        SELECT jsonb_object_agg(c, v_viejo -> c), jsonb_object_agg(c, v_nuevo -> c)
          INTO v_ant, v_nue
        FROM unnest(v_campos) c;
    ELSE
        v_ant := v_viejo;
        v_nue := v_nuevo;
    END IF;

    -- Nunca guardar el valor de columnas sensibles: solo que existen/cambiaron.
    FOREACH k IN ARRAY v_ocultar LOOP
        IF v_ant ? k THEN v_ant := jsonb_set(v_ant, ARRAY[k], '"***"'); END IF;
        IF v_nue ? k THEN v_nue := jsonb_set(v_nue, ARRAY[k], '"***"'); END IF;
    END LOOP;

    BEGIN
        v_uid_txt := NULLIF(current_setting('app.id_usuario', true), '');
        IF v_uid_txt ~ '^\d+$' THEN
            v_uid := v_uid_txt::INT;
            IF NOT EXISTS (SELECT 1 FROM usuarios WHERE id_usuario = v_uid) THEN
                v_uid := NULL;                -- id que no existe (p.ej. dev): no romper la FK
            END IF;
        END IF;

        INSERT INTO historial_auditoria (
            id_usuario, usuario_app, rol_bd, tabla_modificada, tipo_operacion,
            id_registro_afectado, campos_modificados, valores_anteriores, valores_nuevos,
            ip_origen
        ) VALUES (
            v_uid,
            LEFT(NULLIF(current_setting('app.usuario', true), ''), 150),
            session_user,
            TG_TABLE_NAME,
            TG_OP::tipo_operacion,
            COALESCE(v_nuevo, v_viejo) ->> v_pk,
            v_campos,
            v_ant,
            v_nue,
            LEFT(NULLIF(current_setting('app.ip', true), ''), 45)
        );
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'auditoría: no se pudo registrar % en % (%)', TG_OP, TG_TABLE_NAME, SQLERRM;
    END;
    RETURN NULL;
END;
$$;

-- ── 3) Triggers (tabla, PK, columnas que no se auditan) ───────────────────────
DO $$
DECLARE
    t RECORD;
BEGIN
    FOR t IN
        SELECT * FROM (VALUES
            ('trabajadores',         'id_trabajador', ARRAY['foto_perfil', 'fecha_actualizacion']),
            ('area_trabajo',         'id_area',       ARRAY[]::TEXT[]),
            ('empresas',             'id_empresa',    ARRAY[]::TEXT[]),
            ('usuarios',             'id_usuario',    ARRAY['fecha_actualizacion']),
            ('roles',                'id_rol',        ARRAY[]::TEXT[]),
            ('reglas_clasificacion', 'id_regla',      ARRAY['fecha_actualizacion']),
            ('puertas_acceso',       'id_puerta',     ARRAY[]::TEXT[]),
            ('dispositivos',         'id_dispositivo', ARRAY['ultima_conexion']),
            ('parametros_sistema',   'id_parametro',  ARRAY['fecha_actualizacion'])
        ) AS v(tabla, pk, ignorar)
    LOOP
        IF to_regclass('public.' || t.tabla) IS NULL THEN
            RAISE NOTICE 'auditoría: la tabla % no existe, se omite.', t.tabla;
            CONTINUE;
        END IF;
        EXECUTE format('DROP TRIGGER IF EXISTS trg_auditar_%1$s ON %1$I', t.tabla);
        EXECUTE format(
            'CREATE TRIGGER trg_auditar_%1$s AFTER INSERT OR UPDATE OR DELETE ON %1$I '
            'FOR EACH ROW EXECUTE FUNCTION fn_auditar(%2$L%3$s)',
            t.tabla, t.pk,
            (SELECT COALESCE(string_agg(', ' || quote_literal(c), ''), '') FROM unnest(t.ignorar) c)
        );
    END LOOP;
END $$;

-- ── 4) Retención: borra lo de más de N días ──────────────────────────────────
CREATE OR REPLACE FUNCTION purgar_auditoria(p_dias INT DEFAULT 180)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
    v_borrados INT;
BEGIN
    DELETE FROM historial_auditoria WHERE fecha_hora < now() - make_interval(days => p_dias);
    GET DIAGNOSTICS v_borrados = ROW_COUNT;
    RETURN v_borrados;
END;
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        -- 03:45, después de la consolidación (3:00) y las purgas de fotos/reid (3:30).
        PERFORM cron.schedule('purgar-auditoria', '45 3 * * *', 'SELECT purgar_auditoria(180);');
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_cron: no se pudo agendar purgar-auditoria (%); agéndala a mano.', SQLERRM;
END $$;
