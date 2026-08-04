-- 2026_08_geocerca_centros_trabajo.sql
--
-- Exige que quien puede fichar en CUALQUIER escáner (permiso 'administrativo' o
-- 'general') esté dentro de ALGÚN polígono REGISTRADO de su empresa: el de la EMPRESA
-- o el de CUALQUIER área (campo, empaque, oficina). Antes solo se comparaba contra el
-- polígono de la empresa; si ese polígono es amplio, un fichaje desde casa entraba como
-- válido y quien revisa la asistencia no tenía forma de detectarlo.
--
-- El jornalero en puerta de campo NO cambia: se le sigue exigiendo SU área asignada.
--
-- ALCANCE REAL: mídelo antes de aplicar. En esta base son ~5 300 trabajadores 'general'
-- los que pasan a validarse con esta regla (no hay ninguno 'administrativo').
--
-- SEGURIDAD: si la empresa no tiene NINGÚN polígono (ni propio ni de áreas), la
-- validación queda indeterminada y no penaliza. Revisa antes qué falta por cargar:
--     SELECT e.nombre_empresa,
--            count(*) FILTER (WHERE a.ubicacion IS NULL) AS areas_sin_geocerca,
--            bool_or(e.ubicacion IS NOT NULL)            AS empresa_con_poligono
--       FROM empresas e LEFT JOIN area_trabajo a
--         ON a.id_empresa = e.id_empresa AND a.estado='activo'
--      WHERE e.estado='activo' GROUP BY e.nombre_empresa;
--
-- Aplicar:  psql "$DATABASE_URL" -f src/docker/migrations/2026_08_geocerca_centros_trabajo.sql
-- Idempotente: CREATE OR REPLACE con la misma firma.

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
    r                RECORD;
    v_tipo_puerta    tipo_puerta;
    v_permiso        permiso_escaneo;
    v_emp_trab       INT;
    v_emp_puerta     INT;
    v_poligono       geography(POLYGON,4326);
    v_dentro         BOOLEAN;
    v_geo_indet      BOOLEAN;
    v_hay_geocercas  BOOLEAN;
    v_nuevo_estado   estado_registro;
    v_tipo_inc       tipo_incidencia;
    v_desc           TEXT;
    c_validados      INT := 0;
    c_area_inc       INT := 0;
    c_otra_emp       INT := 0;
    c_fuera          INT := 0;
BEGIN
    FOR r IN
        SELECT e.id_escaneo, e.id_trabajador, e.id_puerta, e.id_empresa,
               e.ubicacion, e.fecha_hora, e.creado_en_cliente
        FROM escaneos e
        WHERE e.estado_registro = 'exitoso'
          AND (p_desde IS NULL OR e.sincronizado_en >= p_desde)
    LOOP
        -- Datos de contexto
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
        -- 'mixta' acepta a todos. 'campo'/'administrativa' restringen.
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
        ELSIF v_tipo_puerta = 'campo' AND v_permiso = 'campo' THEN
            -- Jornalero en puerta de campo: se exige su ÁREA ASIGNADA (lo verifica en
            -- SU campo, no en cualquiera).
            SELECT a.ubicacion INTO v_poligono
              FROM trabajadores t
              JOIN area_trabajo a ON a.id_area = t.id_area
             WHERE t.id_trabajador = r.id_trabajador;

            IF v_poligono IS NULL OR r.ubicacion IS NULL THEN
                v_geo_indet := TRUE;   -- sin GPS o sin geocerca: NO penalizar
            ELSIF NOT ST_Covers(v_poligono, r.ubicacion) THEN
                v_nuevo_estado := 'fuera_de_area'; v_tipo_inc := 'fuera_de_area';
                v_desc := 'Ubicación fuera del área asignada al trabajador.';
            END IF;

        ELSIF v_nuevo_estado IS NULL THEN
            -- Quien puede fichar en cualquier escáner (administrativo/general, y campo en
            -- puerta administrativa) debe estar dentro de ALGÚN polígono REGISTRADO de su
            -- empresa: el de la EMPRESA o el de CUALQUIER área (campo, empaque, oficina).
            -- Da igual cuál: lo que se garantiza es que el fichaje ocurrió en un lugar
            -- dado de alta en el sistema, y no en su casa o en la playa. Un área
            -- administrativa que hereda las coordenadas de la empresa también vale.
            SELECT EXISTS (
                SELECT 1 FROM empresas em
                 WHERE em.id_empresa = v_emp_puerta AND em.ubicacion IS NOT NULL
                UNION ALL
                SELECT 1 FROM area_trabajo a
                 WHERE a.id_empresa = v_emp_puerta
                   AND a.estado = 'activo' AND a.ubicacion IS NOT NULL
            ) INTO v_hay_geocercas;

            IF NOT v_hay_geocercas OR r.ubicacion IS NULL THEN
                -- Sin GPS, o empresa sin NINGÚN polígono cargado: indeterminado. Es
                -- deliberado: si no hay contra qué comparar, marcar a todos fuera de área
                -- sería un falso positivo masivo.
                v_geo_indet := TRUE;
            ELSE
                SELECT EXISTS (
                    SELECT 1 FROM empresas em
                     WHERE em.id_empresa = v_emp_puerta
                       AND em.ubicacion IS NOT NULL
                       AND ST_Covers(em.ubicacion, r.ubicacion)
                    UNION ALL
                    SELECT 1 FROM area_trabajo a
                     WHERE a.id_empresa = v_emp_puerta
                       AND a.estado = 'activo'
                       AND a.ubicacion IS NOT NULL
                       AND ST_Covers(a.ubicacion, r.ubicacion)
                ) INTO v_dentro;

                IF NOT v_dentro THEN
                    v_nuevo_estado := 'fuera_de_area'; v_tipo_inc := 'fuera_de_area';
                    v_desc := 'Ubicación fuera de todo polígono registrado (empresa y áreas).';
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
