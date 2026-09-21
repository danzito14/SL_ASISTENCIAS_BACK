-- Consulta 2: trabajadores de la EMPRESA 7 que SI tienen rostro (embedding) en el sistema.
-- NO exporta el vector (512 floats no caben en un CSV util); solo el metadato.
-- Cambia el 7 si quieres otra empresa.
COPY (
    SELECT
        t.id_emp                                                          AS id_sys21,
        t.origen_nomina,
        t.id_trabajador,
        t.nombre || ' ' || t.apellido                                     AS trabajador,
        t.id_empresa,
        em.nombre_empresa                                                 AS empresa,
        ar.nombre_area                                                    AS area,
        ar.tipo_area,
        t.permiso_escaneo,
        t.nivel_acceso_interno,
        t.estado                                                          AS estado_trabajador,
        e.id_embedding,
        e.tipo_embedding,
        e.modelo_ia,
        round(e.calidad_embedding::numeric, 4)                            AS calidad,
        e.estado                                                          AS estado_embedding,
        to_char(e.fecha_captura AT TIME ZONE 'America/Mazatlan', 'YYYY-MM-DD HH24:MI:SS') AS fecha_captura
    FROM trabajadores t
    JOIN embeddings   e  ON e.id_trabajador = t.id_trabajador
    LEFT JOIN empresas    em ON em.id_empresa = t.id_empresa
    LEFT JOIN area_trabajo ar ON ar.id_area   = t.id_area
    WHERE t.id_empresa = 7
    ORDER BY t.nombre, t.apellido
) TO STDOUT WITH (FORMAT csv, HEADER true);
