-- Consulta 1: entradas registradas — id de SYS21, trabajador, fecha y hora.
-- La hora se convierte a America/Mazatlan (la BD guarda TIMESTAMPTZ en UTC).
-- Para acotar a una empresa, descomenta la linea del WHERE.
COPY (
    SELECT
        t.id_emp                                                        AS id_sys21,
        t.origen_nomina,
        t.id_trabajador,
        t.nombre || ' ' || t.apellido                                   AS trabajador,
        a.id_empresa                                                    AS id_empresa_ficha,
        em.nombre_empresa                                               AS empresa_ficha,
        t.id_empresa                                                    AS id_empresa_trabajador,
        (a.fecha_hora AT TIME ZONE 'America/Mazatlan')::date            AS fecha,
        to_char(a.fecha_hora AT TIME ZONE 'America/Mazatlan', 'HH24:MI:SS') AS hora,
        p.nombre_puerta                                                 AS puerta,
        a.estado_registro,
        a.dentro_de_area,
        round(a.confianza_biometrica::numeric, 4)                       AS confianza
    FROM asistencia a
    JOIN trabajadores   t  ON t.id_trabajador = a.id_trabajador
    LEFT JOIN empresas  em ON em.id_empresa   = a.id_empresa
    LEFT JOIN puertas_acceso p ON p.id_puerta = a.id_puerta
    WHERE a.tipo_registro = 'entrada'
      -- AND a.id_empresa = 7
      -- AND (a.fecha_hora AT TIME ZONE 'America/Mazatlan')::date >= '2026-09-01'
    ORDER BY a.fecha_hora DESC
) TO STDOUT WITH (FORMAT csv, HEADER true);
