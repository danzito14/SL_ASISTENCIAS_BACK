-- 2026_08_retencion_fotos.sql
--
-- Retención de un mes para las fotos de evidencia (incidencias e intentos de acceso).
-- Son dato biométrico y su valor probatorio es de corto plazo: conservarlas para
-- siempre solo aumenta el daño de un robo del equipo y llena el disco, que crece con
-- cada rostro no reconocido.
--
-- SE BORRA la imagen; NO el registro. La incidencia y el intento quedan para auditoría.
-- NO afecta a trabajadores.foto_perfil (foto de enrolamiento, vive en la BD y debe
-- conservarse mientras el trabajador esté activo).
--
-- ESTA MITAD limpia la columna 'ruta_foto' para que la interfaz no muestre imágenes
-- rotas. Los ARCHIVOS los borra el microservicio 'media' por su cuenta, por antigüedad
-- del archivo (MEDIA_RETENCION_DIAS, por defecto 30). media no tiene BD a propósito, y
-- esa independencia es lo que permite mover el almacenamiento sin tocar al resto; el
-- precio es que las dos mitades van por separado, con la misma ventana de días.
--
-- Aplicar:  psql "$DATABASE_URL" -f src/docker/migrations/2026_08_retencion_fotos.sql
-- Idempotente: CREATE OR REPLACE + reprogramación del job.
--
-- Para cambiar la ventana hay que tocar LOS DOS lados:
--   · aquí:  SELECT cron.schedule('purgar-fotos-vencidas', '30 3 * * *',
--                                 $cron$ SELECT purgar_fotos_vencidas(60); $cron$);
--   · media: MEDIA_RETENCION_DIAS=60 en el compose.

CREATE OR REPLACE FUNCTION purgar_fotos_vencidas(p_dias INT DEFAULT 30)
RETURNS TABLE(incidencias_limpiadas INT, intentos_limpiados INT)
LANGUAGE plpgsql
AS $$
DECLARE
    v_corte TIMESTAMPTZ := now() - make_interval(days => p_dias);
    v_inc   INT := 0;
    v_int   INT := 0;
BEGIN
    WITH u AS (
        UPDATE incidencias SET ruta_foto = NULL
         WHERE ruta_foto IS NOT NULL AND fecha_creacion < v_corte
        RETURNING 1
    ) SELECT COUNT(*) INTO v_inc FROM u;

    WITH u AS (
        UPDATE intentos_acceso SET ruta_foto = NULL
         WHERE ruta_foto IS NOT NULL AND fecha < v_corte
        RETURNING 1
    ) SELECT COUNT(*) INTO v_int FROM u;

    incidencias_limpiadas := v_inc;
    intentos_limpiados    := v_int;
    RETURN NEXT;
END;
$$;

DO $$
BEGIN
    PERFORM cron.unschedule('purgar-fotos-vencidas') FROM cron.job
     WHERE jobname = 'purgar-fotos-vencidas';
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;

-- A las 3:30, después de la consolidación diaria de asistencia (3:00).
SELECT cron.schedule(
    'purgar-fotos-vencidas',
    '30 3 * * *',
    $cron$ SELECT purgar_fotos_vencidas(30); $cron$
);

-- Arrastre inicial: al aplicar la migración, limpia lo que ya está vencido en vez de
-- esperar al primer cron. El barrido de archivos de media hará lo propio al arrancar.
SELECT * FROM purgar_fotos_vencidas(30);
