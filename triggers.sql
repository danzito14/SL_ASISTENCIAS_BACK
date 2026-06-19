-- ============================================================
-- TRIGGER: validar y registrar asistencia al primer escaneo del día
-- ============================================================
--
-- Lógica:
--   Al INSERTAR un escaneo, si es el PRIMERO del día de ese trabajador:
--     - id_puerta = 8080 (CAMPO)           -> área ASIGNADA del trabajador (trabajadores.id_area)
--     - id_puerta <> 8080 (ADMINISTRATIVO) -> área de la EMPRESA (puertas_acceso.id_empresa)
--   Si el punto cae DENTRO del polígono -> asistencia 'exitoso'
--   Si cae FUERA -> asistencia 'fuera_de_area' + incidencia 'fuera_de_area'
--                   + el escaneo original se marca 'fuera_de_area'
--   Si NO es el primer escaneo del día -> no hace nada
-- ============================================================

-- ------------------------------------------------------------
-- 0) Agregar el nuevo tipo de incidencia 'fuera_de_area'
-- ------------------------------------------------------------
ALTER TABLE incidencias
    DROP CONSTRAINT IF EXISTS incidencias_tipo_incidencia_check;

ALTER TABLE incidencias
    ADD CONSTRAINT incidencias_tipo_incidencia_check
    CHECK (tipo_incidencia IN (
        'salida_sin_registro',
        'entrada_sin_registro',
        'falta',
        'retardo',
        'fuera_de_area',
        'acceso_otra_empresa'
    ));

-- ------------------------------------------------------------
-- 1) Función del trigger
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_validar_asistencia_escaneo()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_es_primero    BOOLEAN;
    v_area_poligono geography(POLYGON,4326);
    v_dentro        BOOLEAN;
    v_id_area       INT;
    v_id_empresa    INT;
BEGIN
    -- 1) ¿Es el primer escaneo del día de este trabajador?
    SELECT NOT EXISTS (
        SELECT 1
        FROM escaneos e
        WHERE e.id_trabajador = NEW.id_trabajador
          AND e.fecha_hora >= date_trunc('day', NEW.fecha_hora)
          AND e.fecha_hora <  date_trunc('day', NEW.fecha_hora) + INTERVAL '1 day'
          AND e.id_escaneo <> NEW.id_escaneo
    )
    INTO v_es_primero;

    IF NOT v_es_primero THEN
        RETURN NEW;
    END IF;

    -- 2) Determinar el polígono del área según tipo (campo vs administrativo)
    IF NEW.id_puerta = 8080 THEN
        -- CAMPO: área ASIGNADA del trabajador
        SELECT t.id_area INTO v_id_area
        FROM trabajadores t
        WHERE t.id_trabajador = NEW.id_trabajador;

        SELECT a.ubicacion INTO v_area_poligono
        FROM area_trabajo a
        WHERE a.id_area = v_id_area;
    ELSE
        -- ADMINISTRATIVO: área de la EMPRESA, vía la puerta
        SELECT p.id_empresa INTO v_id_empresa
        FROM puertas_acceso p
        WHERE p.id_puerta = NEW.id_puerta;

        SELECT em.ubicacion INTO v_area_poligono
        FROM empresas em
        WHERE em.id_empresa = v_id_empresa;
    END IF;

    -- 3) Comparar coordenada: ¿el punto cae dentro del polígono?
    --    ST_Covers incluye los puntos en el borde.
    --    Sin polígono o sin punto -> se trata como fuera (false).
    IF v_area_poligono IS NULL OR NEW.ubicacion IS NULL THEN
        v_dentro := FALSE;
    ELSE
        v_dentro := ST_Covers(v_area_poligono, NEW.ubicacion);
    END IF;

    -- 4) Registrar asistencia según el resultado
    IF v_dentro THEN
        INSERT INTO asistencia (
            id_trabajador, id_puerta, tipo_registro, fecha_hora,
            confianza_biometrica, estado_registro, observaciones,
            id_dispositivo, ubicacion
        )
        VALUES (
            NEW.id_trabajador, NEW.id_puerta, 'entrada', NEW.fecha_hora,
            NEW.confianza_biometrica, 'exitoso',
            'Entrada validada por geolocalización.',
            NEW.id_dispositivo, NEW.ubicacion
        );
    ELSE
        INSERT INTO asistencia (
            id_trabajador, id_puerta, tipo_registro, fecha_hora,
            confianza_biometrica, estado_registro, observaciones,
            id_dispositivo, ubicacion
        )
        VALUES (
            NEW.id_trabajador, NEW.id_puerta, 'entrada', NEW.fecha_hora,
            NEW.confianza_biometrica, 'fuera_de_area',
            'Ubicación fuera del área permitida.',
            NEW.id_dispositivo, NEW.ubicacion
        );

        INSERT INTO incidencias (
            id_trabajador, tipo_incidencia, fecha, descripcion, id_escaneo_ref
        )
        VALUES (
            NEW.id_trabajador, 'fuera_de_area', NEW.fecha_hora::date,
            'Escaneo fuera del área permitida; entrada marcada como fuera_de_area.',
            NEW.id_escaneo
        );

        -- Marcar el escaneo original también como fuera_de_area
        UPDATE escaneos
        SET estado_registro = 'fuera_de_area'
        WHERE id_escaneo = NEW.id_escaneo;
    END IF;

    RETURN NEW;
END;
$$;

-- ------------------------------------------------------------
-- 2) El trigger: AFTER INSERT (necesitamos NEW.id_escaneo ya generado)
-- ------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_validar_asistencia ON escaneos;

CREATE TRIGGER trg_validar_asistencia
AFTER INSERT ON escaneos
FOR EACH ROW
EXECUTE FUNCTION fn_validar_asistencia_escaneo();