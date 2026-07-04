-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║  2026_07_offline_derivacion.sql                                            ║
-- ║  Migración IDEMPOTENTE: el flujo OFFLINE deja de escribir 'asistencia'     ║
-- ║  directo y pasa a alimentar el MISMO pipeline que el online:               ║
-- ║      escaneos → validar_escaneos_lote() → consolidar_asistencia_dia()      ║
-- ║                                                                            ║
-- ║  Contenido:                                                                ║
-- ║   1) validar_escaneos_lote: GPS nulo NO penaliza (no marca fuera_de_area;  ║
-- ║      conserva el dentro_de_area del cliente).                              ║
-- ║   2) consolidar_asistencia_dia: + ventana de dedupe (doble-scan) y         ║
-- ║      RECONCILIACIÓN de lotes tardíos/desordenados (retracta               ║
-- ║      entrada_sin_registro y re-ajusta entrada/salida auto-derivadas).      ║
-- ║   3) Ambas funciones pasan a SECURITY DEFINER (corren como su dueño) para  ║
-- ║      que svc_offline solo necesite EXECUTE, sin escritura directa sobre    ║
-- ║      asistencia/incidencias (mínimo privilegio).                          ║
-- ║   4) Grants nuevos a svc_offline: SELECT/INSERT en escaneos + EXECUTE.     ║
-- ║                                                                            ║
-- ║  Aplicar como superusuario / dueño del esquema:                           ║
-- ║    psql -U postgres -d SL_ASISTENCIAS -f 2026_07_offline_derivacion.sql    ║
-- ╚══════════════════════════════════════════════════════════════════════════╝

-- ════════════════════════════════════════════════════════════════════════════
-- 1) VALIDACIÓN DE ESCANEOS  (3 capas). Cambio: política de GPS nulo.
--    Si no hay punto (offline sin fix) o el área no tiene polígono, la geo es
--    INDETERMINADA → NO se marca fuera_de_area y se CONSERVA el dentro_de_area
--    que trajo el cliente (el APK lo precalcula). Antes se asumía FALSE (fuera).
-- ════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION validar_escaneos_lote(
    p_desde TIMESTAMPTZ DEFAULT NULL   -- si se pasa, solo valida sincronizados >= p_desde
)
RETURNS TABLE(
    validados        INT,
    area_incorrecta  INT,
    otra_empresa     INT,
    fuera_de_area    INT
)
LANGUAGE plpgsql
AS $$
DECLARE
    r                 RECORD;
    v_tipo_puerta     tipo_puerta;
    v_permiso         permiso_escaneo;
    v_emp_trab        INT;
    v_emp_puerta      INT;
    v_poligono        geography(POLYGON,4326);
    v_dentro          BOOLEAN;
    v_geo_indet       BOOLEAN;
    v_nuevo_estado    estado_registro;
    v_tipo_inc        tipo_incidencia;
    v_desc            TEXT;
    c_validados       INT := 0;
    c_area_inc        INT := 0;
    c_otra_emp        INT := 0;
    c_fuera           INT := 0;
BEGIN
    FOR r IN
        SELECT e.id_escaneo, e.id_trabajador, e.id_puerta, e.id_empresa,
               e.ubicacion, e.fecha_hora, e.creado_en_cliente
        FROM escaneos e
        WHERE e.estado_registro = 'exitoso'
          AND (p_desde IS NULL OR e.sincronizado_en >= p_desde)
    LOOP
        SELECT t.permiso_escaneo, t.id_empresa
          INTO v_permiso, v_emp_trab
          FROM trabajadores t WHERE t.id_trabajador = r.id_trabajador;

        SELECT p.tipo_puerta, p.id_empresa
          INTO v_tipo_puerta, v_emp_puerta
          FROM puertas_acceso p WHERE p.id_puerta = r.id_puerta;

        v_nuevo_estado := NULL;
        v_tipo_inc     := NULL;
        v_geo_indet    := FALSE;

        -- ── Capa 1: tipo de puerta compatible con el permiso ──────────────
        IF v_tipo_puerta = 'campo' AND v_permiso = 'administrativo' THEN
            v_nuevo_estado := 'rechazado'; v_tipo_inc := 'area_incorrecta';
            v_desc := 'Trabajador administrativo en puerta de campo.';
        ELSIF v_tipo_puerta = 'administrativa' AND v_permiso = 'campo' THEN
            v_nuevo_estado := 'rechazado'; v_tipo_inc := 'area_incorrecta';
            v_desc := 'Trabajador de campo en puerta administrativa.';
        END IF;

        -- ── Capa 2: empresa correcta (salvo 'super') ──────────────────────
        IF v_nuevo_estado IS NULL
           AND v_permiso <> 'super'
           AND v_emp_trab IS DISTINCT FROM v_emp_puerta THEN
            v_nuevo_estado := 'rechazado'; v_tipo_inc := 'acceso_otra_empresa';
            v_desc := 'Escaneo en puerta de otra empresa sin permiso super.';
        END IF;

        -- ── Capa 3: geolocalización (solo si pasó 1 y 2) ──────────────────
        IF v_nuevo_estado IS NULL AND v_permiso = 'super' THEN
            -- 'super' ficha en cualquier lado → exento de la geocerca.
            v_geo_indet := TRUE;
        ELSIF v_nuevo_estado IS NULL THEN
            -- Geocerca: puerta de campo + trabajador de campo = su ÁREA asignada
            -- (verifica al jornalero en su campo). En cualquier otro caso
            -- (general/administrativo, o campo en puerta administrativa) = polígono
            -- de la EMPRESA (roaming dentro de la empresa).
            IF v_tipo_puerta = 'campo' AND v_permiso = 'campo' THEN
                SELECT a.ubicacion INTO v_poligono
                  FROM trabajadores t
                  JOIN area_trabajo a ON a.id_area = t.id_area
                 WHERE t.id_trabajador = r.id_trabajador;
            ELSE
                SELECT em.ubicacion INTO v_poligono
                  FROM empresas em WHERE em.id_empresa = v_emp_puerta;
            END IF;

            IF v_poligono IS NULL OR r.ubicacion IS NULL THEN
                -- Sin datos para juzgar (offline sin GPS o sin geocerca): NO penalizar.
                v_geo_indet := TRUE;
            ELSE
                v_dentro := ST_Covers(v_poligono, r.ubicacion);
                IF NOT v_dentro THEN
                    v_nuevo_estado := 'fuera_de_area'; v_tipo_inc := 'fuera_de_area';
                    v_desc := 'Ubicación fuera del área permitida.';
                END IF;
            END IF;
        END IF;

        -- ── Aplicar resultado ─────────────────────────────────────────────
        IF v_nuevo_estado IS NULL THEN
            -- Pasó las 3 capas. Solo tocamos dentro_de_area si SÍ pudimos juzgar
            -- la geo; si fue indeterminada, se conserva el valor del cliente.
            IF NOT v_geo_indet THEN
                UPDATE escaneos SET dentro_de_area = TRUE WHERE id_escaneo = r.id_escaneo;
            END IF;
            c_validados := c_validados + 1;
        ELSE
            UPDATE escaneos
               SET estado_registro = v_nuevo_estado,
                   dentro_de_area  = (v_nuevo_estado <> 'fuera_de_area')
             WHERE id_escaneo = r.id_escaneo;

            INSERT INTO incidencias (
                id_trabajador, id_empresa, tipo_incidencia, fecha,
                descripcion, id_escaneo_ref, creado_en_cliente
            )
            VALUES (
                r.id_trabajador, v_emp_trab, v_tipo_inc,
                COALESCE(r.creado_en_cliente, r.fecha_hora)::date,
                v_desc, r.id_escaneo, r.creado_en_cliente
            );

            IF    v_tipo_inc = 'area_incorrecta'      THEN c_area_inc := c_area_inc + 1;
            ELSIF v_tipo_inc = 'acceso_otra_empresa'  THEN c_otra_emp := c_otra_emp + 1;
            ELSIF v_tipo_inc = 'fuera_de_area'        THEN c_fuera    := c_fuera    + 1;
            END IF;
        END IF;
    END LOOP;

    validados       := c_validados;
    area_incorrecta := c_area_inc;
    otra_empresa    := c_otra_emp;
    fuera_de_area   := c_fuera;
    RETURN NEXT;
END;
$$;


-- ════════════════════════════════════════════════════════════════════════════
-- 2) CONSOLIDACIÓN DIARIA  (entrada + salida, derivada de escaneos).
--    Cambios sobre la versión previa:
--     · DEDUPE doble-scan: escaneos del mismo trabajador dentro de una ventana
--       corta cuentan como UN solo evento (no generan salida espuria).
--     · RECONCILIACIÓN de lotes tardíos/desordenados: la entrada/salida
--       auto-derivadas se RE-AJUSTAN al primer/último scan actual (no quedan
--       congeladas por el primer INSERT), y al aparecer la 2ª marca se RETRACTA
--       la incidencia 'entrada_sin_registro' pendiente. Las filas MANUALES
--       (justificaciones) NO se tocan.
--    tipo_registro se DERIVA aquí; lo que traiga el cliente es irrelevante.
-- ════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION consolidar_asistencia_dia(
    p_dias_atras     INT     DEFAULT 1,
    p_id_trabajador  INT     DEFAULT NULL,
    p_incluir_salida BOOLEAN DEFAULT TRUE
)
RETURNS TABLE(entradas_creadas INT, salidas_creadas INT, incidencias_creadas INT)
LANGUAGE plpgsql
AS $$
DECLARE
    c_dedupe_seg CONSTANT INT := 90;   -- ventana de dedupe doble-scan (segundos)
    v_entradas    INT := 0;
    v_salidas     INT := 0;
    v_incidencias INT := 0;
BEGIN
    -- 0) Derivación por (trabajador, día) a una tabla temporal (idempotente
    --    entre llamadas dentro de la misma transacción vía DROP IF EXISTS).
    DROP TABLE IF EXISTS _deriv_asis;
    CREATE TEMP TABLE _deriv_asis AS
    WITH params AS (
        SELECT em.id_empresa,
               em.zona_horaria,
               ((date_trunc('day', timezone(em.zona_horaria, now()))
                    - make_interval(days => p_dias_atras)) AT TIME ZONE em.zona_horaria)                  AS ini_utc,
               ((date_trunc('day', timezone(em.zona_horaria, now()))
                    - make_interval(days => p_dias_atras)) AT TIME ZONE em.zona_horaria + INTERVAL '1 day') AS fin_utc
        FROM empresas em
        WHERE em.estado = 'activo'
    ),
    ev AS (
        SELECT e.*,
               COALESCE(e.creado_en_cliente, e.fecha_hora) AS momento,
               p.id_empresa AS emp,
               p.ini_utc, p.fin_utc,
               (timezone(p.zona_horaria, COALESCE(e.creado_en_cliente, e.fecha_hora)))::date AS fecha_local
        FROM escaneos e
        JOIN params p ON p.id_empresa = e.id_empresa
        WHERE COALESCE(e.creado_en_cliente, e.fecha_hora) >= p.ini_utc
          AND COALESCE(e.creado_en_cliente, e.fecha_hora) <  p.fin_utc
          AND e.estado_registro IN ('exitoso','manual')
          AND (p_id_trabajador IS NULL OR e.id_trabajador = p_id_trabajador)
    ),
    ev_evt AS (
        SELECT ev.*,
               (lag(momento) OVER w IS NULL
                OR momento - lag(momento) OVER w >= make_interval(secs => c_dedupe_seg)) AS es_evento
        FROM ev
        WINDOW w AS (PARTITION BY id_trabajador ORDER BY momento)
    ),
    conteo AS (   -- nº de EVENTOS distintos (tras dedupe), no de filas
        SELECT id_trabajador, COUNT(*) FILTER (WHERE es_evento) AS n
        FROM ev_evt GROUP BY id_trabajador
    ),
    primero AS (  -- primer escaneo del día = ENTRADA
        SELECT DISTINCT ON (id_trabajador)
            id_trabajador, id_puerta, emp, ini_utc, fin_utc, momento,
            confianza_biometrica, estado_registro, dentro_de_area, id_dispositivo, id_dispositivo_origen, ubicacion
        FROM ev ORDER BY id_trabajador, momento ASC
    ),
    ultimo AS (   -- último escaneo del día = SALIDA (si hay 2+ eventos)
        SELECT DISTINCT ON (id_trabajador)
            id_escaneo, id_trabajador, id_puerta, emp, momento, fecha_local,
            confianza_biometrica, estado_registro, dentro_de_area, id_dispositivo, id_dispositivo_origen, ubicacion
        FROM ev ORDER BY id_trabajador, momento DESC
    )
    SELECT pr.id_trabajador, pr.emp, u.fecha_local, c.n, pr.ini_utc, pr.fin_utc,
           pr.id_puerta AS e_puerta, pr.momento AS e_momento, pr.confianza_biometrica AS e_conf,
           pr.estado_registro AS e_estado, pr.dentro_de_area AS e_dentro,
           pr.id_dispositivo AS e_disp, pr.id_dispositivo_origen AS e_disp_orig, pr.ubicacion AS e_ubic,
           u.id_escaneo AS u_escaneo, u.id_puerta AS s_puerta, u.momento AS s_momento,
           u.confianza_biometrica AS s_conf, u.estado_registro AS s_estado,
           u.dentro_de_area AS s_dentro, u.id_dispositivo AS s_disp,
           u.id_dispositivo_origen AS s_disp_orig, u.ubicacion AS s_ubic
    FROM primero pr
    JOIN conteo c ON c.id_trabajador = pr.id_trabajador
    JOIN ultimo u ON u.id_trabajador = pr.id_trabajador;

    -- 1) ENTRADA — re-ajustar la auto-derivada al primer scan actual (reconciliación).
    UPDATE asistencia a
       SET fecha_hora = d.e_momento, creado_en_cliente = d.e_momento,
           id_puerta = d.e_puerta, confianza_biometrica = d.e_conf,
           estado_registro = d.e_estado, dentro_de_area = d.e_dentro,
           id_dispositivo = d.e_disp, id_dispositivo_origen = d.e_disp_orig, ubicacion = d.e_ubic
      FROM _deriv_asis d
     WHERE a.id_trabajador = d.id_trabajador
       AND a.tipo_registro = 'entrada'
       AND a.fecha_hora >= d.ini_utc AND a.fecha_hora < d.fin_utc
       AND a.observaciones LIKE 'Entrada (primer escaneo%'   -- solo las auto-derivadas
       AND a.fecha_hora <> d.e_momento;

    -- ...y crearla si aún no existe (auto o manual) ese día.
    WITH ins AS (
        INSERT INTO asistencia (
            id_trabajador, id_puerta, id_empresa, tipo_registro, fecha_hora,
            confianza_biometrica, estado_registro, dentro_de_area, observaciones,
            id_dispositivo, id_dispositivo_origen, ubicacion, creado_en_cliente
        )
        SELECT d.id_trabajador, d.e_puerta, d.emp, 'entrada', d.e_momento,
               d.e_conf, d.e_estado, d.e_dentro, 'Entrada (primer escaneo del día).',
               d.e_disp, d.e_disp_orig, d.e_ubic, d.e_momento
        FROM _deriv_asis d
        WHERE NOT EXISTS (
            SELECT 1 FROM asistencia a
            WHERE a.id_trabajador = d.id_trabajador AND a.tipo_registro = 'entrada'
              AND a.fecha_hora >= d.ini_utc AND a.fecha_hora < d.fin_utc
        )
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_entradas FROM ins;

    IF p_incluir_salida THEN
        -- 2) SALIDA (solo con 2+ eventos) — re-ajustar la auto al último scan actual.
        UPDATE asistencia a
           SET fecha_hora = d.s_momento, creado_en_cliente = d.s_momento,
               id_puerta = d.s_puerta, confianza_biometrica = d.s_conf,
               estado_registro = d.s_estado, dentro_de_area = d.s_dentro,
               id_dispositivo = d.s_disp, id_dispositivo_origen = d.s_disp_orig, ubicacion = d.s_ubic
          FROM _deriv_asis d
         WHERE d.n >= 2 AND a.id_trabajador = d.id_trabajador
           AND a.tipo_registro = 'salida'
           AND a.fecha_hora >= d.ini_utc AND a.fecha_hora < d.fin_utc
           AND a.observaciones LIKE 'Salida inferida%'
           AND a.fecha_hora <> d.s_momento;

        -- ...y crearla si no existe.
        WITH ins AS (
            INSERT INTO asistencia (
                id_trabajador, id_puerta, id_empresa, tipo_registro, fecha_hora,
                confianza_biometrica, estado_registro, dentro_de_area, observaciones,
                id_dispositivo, id_dispositivo_origen, ubicacion, creado_en_cliente
            )
            SELECT d.id_trabajador, d.s_puerta, d.emp, 'salida', d.s_momento,
                   d.s_conf, d.s_estado, d.s_dentro, 'Salida inferida (último escaneo del día).',
                   d.s_disp, d.s_disp_orig, d.s_ubic, d.s_momento
            FROM _deriv_asis d
            WHERE d.n >= 2
              AND NOT EXISTS (
                  SELECT 1 FROM asistencia a
                  WHERE a.id_trabajador = d.id_trabajador AND a.tipo_registro = 'salida'
                    AND a.fecha_hora >= d.ini_utc AND a.fecha_hora < d.fin_utc
              )
            RETURNING 1
        )
        SELECT COUNT(*) INTO v_salidas FROM ins;

        -- 3) RECONCILIAR: ya hay salida (2+ eventos) → retractar la incidencia
        --    'entrada_sin_registro' PENDIENTE (falso positivo del lote anterior).
        --    Las revisadas/justificadas NO se tocan (ya generaron su salida manual).
        DELETE FROM incidencias i
         USING _deriv_asis d
         WHERE d.n >= 2 AND i.id_trabajador = d.id_trabajador
           AND i.fecha = d.fecha_local
           AND i.tipo_incidencia = 'entrada_sin_registro'
           AND i.estado = 'pendiente';

        -- 4) INCIDENCIA 'entrada_sin_registro' (un solo evento) si no existe.
        WITH ins AS (
            INSERT INTO incidencias (
                id_trabajador, id_empresa, tipo_incidencia, fecha, descripcion, id_escaneo_ref
            )
            SELECT d.id_trabajador, d.emp, 'entrada_sin_registro', d.fecha_local,
                   'Solo un escaneo en el día; sin salida detectable.', d.u_escaneo
            FROM _deriv_asis d
            WHERE d.n = 1
              AND NOT EXISTS (
                  SELECT 1 FROM incidencias i
                  WHERE i.id_trabajador = d.id_trabajador AND i.fecha = d.fecha_local
                    AND i.tipo_incidencia = 'entrada_sin_registro'
              )
            RETURNING 1
        )
        SELECT COUNT(*) INTO v_incidencias FROM ins;
    END IF;

    DROP TABLE IF EXISTS _deriv_asis;

    RAISE NOTICE 'Entradas: %, Salidas: %, Incidencias: %', v_entradas, v_salidas, v_incidencias;
    entradas_creadas    := v_entradas;
    salidas_creadas     := v_salidas;
    incidencias_creadas := v_incidencias;
    RETURN NEXT;
END;
$$;


-- ════════════════════════════════════════════════════════════════════════════
-- 3) SECURITY DEFINER  — que las funciones corran como su DUEÑO (superusuario
--    del esquema) para que los callers (svc_offline, svc_access, app_cron) solo
--    necesiten EXECUTE, sin escritura directa sobre asistencia/incidencias.
--    search_path fijado por seguridad (igual patrón que las cascadas de estado).
-- ════════════════════════════════════════════════════════════════════════════
ALTER FUNCTION validar_escaneos_lote(timestamptz)
    SECURITY DEFINER SET search_path = public, pg_temp;
ALTER FUNCTION consolidar_asistencia_dia(integer, integer, boolean)
    SECURITY DEFINER SET search_path = public, pg_temp;


-- ════════════════════════════════════════════════════════════════════════════
-- 4) GRANTS a svc_offline: ahora alimenta 'escaneos' y corre el pipeline.
--    (SELECT en escaneos por el RETURNING que cuenta insertados/duplicados y por
--     la consulta de días del lote.) Con SECURITY DEFINER NO necesita INSERT en
--     asistencia/incidencias; el INSERT en asistencia previo queda inocuo.
-- ════════════════════════════════════════════════════════════════════════════
GRANT SELECT, INSERT ON escaneos TO svc_offline;
GRANT EXECUTE ON FUNCTION
    validar_escaneos_lote(timestamptz),
    consolidar_asistencia_dia(integer, integer, boolean)
    TO svc_offline;

-- Verificación:
--   SELECT proname, prosecdef FROM pg_proc
--     WHERE proname IN ('validar_escaneos_lote','consolidar_asistencia_dia');
--   SELECT grantee, privilege_type FROM information_schema.role_table_grants
--     WHERE table_name='escaneos' AND grantee='svc_offline';
