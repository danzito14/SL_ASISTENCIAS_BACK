CREATE OR REPLACE FUNCTION registrar_salidas_dia()
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    filas_insertadas integer;
BEGIN
    WITH ultimos_escaneos AS (
        SELECT DISTINCT ON (e.id_trabajador)
            e.id_trabajador,
            e.id_puerta,
            e.fecha_hora,
            e.confianza_biometrica,
            e.estado_registro,
            e.observaciones,
            e.id_dispositivo,
            e.ubicacion
        FROM escaneos e
        WHERE e.fecha_hora >= CURRENT_DATE
          AND e.fecha_hora <  CURRENT_DATE + INTERVAL '1 day'
          AND e.estado_registro IN ('exitoso', 'manual')   -- ignora rechazados
        ORDER BY e.id_trabajador, e.fecha_hora DESC          -- el último de cada trabajador
    )
    INSERT INTO asistencia (
        id_trabajador, id_puerta, tipo_registro, fecha_hora,
        confianza_biometrica, estado_registro, observaciones,
        id_dispositivo, ubicacion
    )
    SELECT
        u.id_trabajador,
        u.id_puerta,
        'salida',                                            -- se registra como salida
        u.fecha_hora,
        u.confianza_biometrica,
        u.estado_registro,
        u.observaciones,
        u.id_dispositivo,
        CASE
            WHEN u.ubicacion IS NULL OR btrim(u.ubicacion) = '' THEN NULL
            ELSE ST_GeographyFromText('SRID=4326;POINT(' || u.ubicacion || ')')
        END
    FROM ultimos_escaneos u
    WHERE NOT EXISTS (                                       -- evita duplicados del día
        SELECT 1
        FROM asistencia a
        WHERE a.id_trabajador = u.id_trabajador
          AND a.tipo_registro = 'salida'
          AND a.fecha_hora >= CURRENT_DATE
          AND a.fecha_hora <  CURRENT_DATE + INTERVAL '1 day'
    );

    GET DIAGNOSTICS filas_insertadas = ROW_COUNT;
    RAISE NOTICE 'Salidas registradas: %', filas_insertadas;
    RETURN filas_insertadas;
END;
$$;