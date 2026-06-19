--
-- PostgreSQL database dump
--

\restrict 5jOR4XjuUIGwoB9cdUfKPYl3An1Eyuu6YCuNAGgIJwkS8gm1V7vZleYzlzumlSG

-- Dumped from database version 17.10 (Debian 17.10-1.pgdg12+1)
-- Dumped by pg_dump version 17.10 (Debian 17.10-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_cron; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_cron WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION pg_cron; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_cron IS 'Job scheduler for PostgreSQL';


--
-- Name: postgis; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;


--
-- Name: EXTENSION postgis; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis IS 'PostGIS geometry and geography spatial types and functions';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: fn_cascada_estado_area(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_cascada_estado_area() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: fn_cascada_estado_empresa(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_cascada_estado_empresa() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: fn_cascada_estado_trabajador(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_cascada_estado_trabajador() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: fn_proteger_empresa_admin(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_proteger_empresa_admin() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: fn_validar_asistencia_escaneo(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_validar_asistencia_escaneo() RETURNS trigger
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


--
-- Name: procesar_salidas_dia(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.procesar_salidas_dia() RETURNS TABLE(salidas_registradas integer, incidencias_creadas integer)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_salidas     INT := 0;
    v_incidencias INT := 0;
BEGIN
    -- Conteo de escaneos válidos por trabajador en el día
    WITH conteo AS (
        SELECT e.id_trabajador, COUNT(*) AS n
        FROM escaneos e
        WHERE e.fecha_hora >= CURRENT_DATE
          AND e.fecha_hora <  CURRENT_DATE + INTERVAL '1 day'
          AND e.estado_registro IN ('exitoso','manual')
        GROUP BY e.id_trabajador
    ),
    -- El último escaneo del día de cada trabajador
    ultimo AS (
        SELECT DISTINCT ON (e.id_trabajador)
            e.id_escaneo, e.id_trabajador, e.id_puerta, e.fecha_hora,
            e.confianza_biometrica, e.estado_registro, e.observaciones,
            e.id_dispositivo, e.ubicacion
        FROM escaneos e
        WHERE e.fecha_hora >= CURRENT_DATE
          AND e.fecha_hora <  CURRENT_DATE + INTERVAL '1 day'
          AND e.estado_registro IN ('exitoso','manual')
        ORDER BY e.id_trabajador, e.fecha_hora DESC
    ),
    -- INSERT de salidas (trabajadores con 2+ escaneos)
    ins_salidas AS (
        INSERT INTO asistencia (
            id_trabajador, id_puerta, tipo_registro, fecha_hora,
            confianza_biometrica, estado_registro, observaciones,
            id_dispositivo, ubicacion
        )
        SELECT
            u.id_trabajador, u.id_puerta, 'salida', u.fecha_hora,
            u.confianza_biometrica, u.estado_registro, u.observaciones,
            u.id_dispositivo, u.ubicacion
        FROM ultimo u
        JOIN conteo c ON c.id_trabajador = u.id_trabajador
        WHERE c.n >= 2
          AND NOT EXISTS (
              SELECT 1 FROM asistencia a
              WHERE a.id_trabajador = u.id_trabajador
                AND a.tipo_registro = 'salida'
                AND a.fecha_hora >= CURRENT_DATE
                AND a.fecha_hora <  CURRENT_DATE + INTERVAL '1 day'
          )
        RETURNING 1
    ),
    -- INSERT de incidencias (trabajadores con 1 solo escaneo)
    ins_incid AS (
        INSERT INTO incidencias (
            id_trabajador, tipo_incidencia, fecha, descripcion, id_escaneo_ref
        )
        SELECT
            u.id_trabajador, 'entrada_sin_registro', CURRENT_DATE,
            'Solo se registró un escaneo en el día; sin salida detectable.',
            u.id_escaneo
        FROM ultimo u
        JOIN conteo c ON c.id_trabajador = u.id_trabajador
        WHERE c.n = 1
          AND NOT EXISTS (
              SELECT 1 FROM incidencias i
              WHERE i.id_trabajador = u.id_trabajador
                AND i.fecha = CURRENT_DATE
                AND i.tipo_incidencia = 'entrada_sin_registro'
          )
        RETURNING 1
    )
    SELECT
        (SELECT COUNT(*) FROM ins_salidas),
        (SELECT COUNT(*) FROM ins_incid)
    INTO v_salidas, v_incidencias;

    RAISE NOTICE 'Salidas: %, Incidencias: %', v_salidas, v_incidencias;
    salidas_registradas := v_salidas;
    incidencias_creadas := v_incidencias;
    RETURN NEXT;
END;
$$;


--
-- Name: set_fecha_actualizacion(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_fecha_actualizacion() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.fecha_actualizacion = NOW();
  RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: area_trabajo; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.area_trabajo (
    id_area integer NOT NULL,
    nombre_area character varying(100) NOT NULL,
    descripcion text,
    ubicacion public.geography(Polygon,4326),
    id_empresa integer,
    hora_entrada time without time zone,
    estado character varying(10) DEFAULT 'activo'::character varying,
    fecha_creacion timestamp with time zone DEFAULT now(),
    inactivo_por_cascada boolean DEFAULT false NOT NULL,
    CONSTRAINT area_trabajo_estado_check CHECK (((estado)::text = ANY ((ARRAY['activo'::character varying, 'inactivo'::character varying])::text[])))
);


--
-- Name: area_trabajo_id_area_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.area_trabajo_id_area_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: area_trabajo_id_area_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.area_trabajo_id_area_seq OWNED BY public.area_trabajo.id_area;


--
-- Name: asistencia; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.asistencia (
    id_asistencia integer NOT NULL,
    id_trabajador integer NOT NULL,
    id_puerta integer NOT NULL,
    tipo_registro character varying(50) NOT NULL,
    fecha_hora timestamp with time zone DEFAULT now() NOT NULL,
    confianza_biometrica numeric(3,2),
    estado_registro character varying(50) DEFAULT 'exitoso'::character varying,
    observaciones text,
    id_dispositivo integer,
    ubicacion public.geography(Point,4326),
    fecha_creacion timestamp with time zone DEFAULT now(),
    CONSTRAINT asistencia_confianza_biometrica_check CHECK (((confianza_biometrica >= (0)::numeric) AND (confianza_biometrica <= (1)::numeric))),
    CONSTRAINT asistencia_estado_registro_check CHECK (((estado_registro)::text = ANY (ARRAY[('exitoso'::character varying)::text, ('rechazado'::character varying)::text, ('manual'::character varying)::text, ('fuera_de_area'::character varying)::text, ('cancelado'::character varying)::text]))),
    CONSTRAINT asistencia_tipo_registro_check CHECK (((tipo_registro)::text = ANY (ARRAY[('entrada'::character varying)::text, ('salida'::character varying)::text])))
);


--
-- Name: asistencia_id_asistencia_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.asistencia_id_asistencia_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: asistencia_id_asistencia_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.asistencia_id_asistencia_seq OWNED BY public.asistencia.id_asistencia;


--
-- Name: dispositivos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dispositivos (
    id_dispositivo integer NOT NULL,
    nombre_dispositivo character varying(100) NOT NULL,
    tipo_dispositivo character varying(20) NOT NULL,
    ip_dispositivo character varying(45),
    puerto integer DEFAULT 8080,
    ubicacion public.geography(Point,4326),
    id_area integer,
    estado character varying(15) DEFAULT 'activo'::character varying,
    ultima_conexion timestamp with time zone,
    fecha_instalacion date,
    fecha_creacion timestamp with time zone DEFAULT now(),
    inactivo_por_cascada boolean DEFAULT false NOT NULL,
    CONSTRAINT dispositivos_estado_check CHECK (((estado)::text = ANY ((ARRAY['activo'::character varying, 'inactivo'::character varying, 'mantenimiento'::character varying])::text[]))),
    CONSTRAINT dispositivos_tipo_dispositivo_check CHECK (((tipo_dispositivo)::text = ANY ((ARRAY['escaner_facial'::character varying, 'huella'::character varying, 'escaner_qr'::character varying])::text[])))
);


--
-- Name: dispositivos_id_dispositivo_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dispositivos_id_dispositivo_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dispositivos_id_dispositivo_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dispositivos_id_dispositivo_seq OWNED BY public.dispositivos.id_dispositivo;


--
-- Name: embeddings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.embeddings (
    id_embedding integer NOT NULL,
    id_trabajador integer NOT NULL,
    vector_embedding public.vector(512),
    tipo_embedding character varying(10) DEFAULT 'facial'::character varying,
    fecha_captura timestamp with time zone DEFAULT now(),
    calidad_embedding numeric(3,2),
    modelo_ia character varying(100),
    estado character varying(10) DEFAULT 'activo'::character varying,
    inactivo_por_cascada boolean DEFAULT false NOT NULL,
    CONSTRAINT embeddings_calidad_embedding_check CHECK (((calidad_embedding >= (0)::numeric) AND (calidad_embedding <= (1)::numeric))),
    CONSTRAINT embeddings_estado_check CHECK (((estado)::text = ANY ((ARRAY['activo'::character varying, 'inactivo'::character varying])::text[]))),
    CONSTRAINT embeddings_tipo_embedding_check CHECK (((tipo_embedding)::text = ANY ((ARRAY['facial'::character varying, 'huella'::character varying, 'iris'::character varying])::text[])))
);


--
-- Name: embeddings_id_embedding_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.embeddings_id_embedding_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: embeddings_id_embedding_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.embeddings_id_embedding_seq OWNED BY public.embeddings.id_embedding;


--
-- Name: empresas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.empresas (
    id_empresa integer NOT NULL,
    nombre_empresa character varying(100) NOT NULL,
    ubicacion public.geography(Polygon,4326),
    zona_horaria text NOT NULL,
    estado text NOT NULL,
    fecha_creacion timestamp with time zone DEFAULT now()
);


--
-- Name: empresas_id_empresa_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.empresas_id_empresa_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: empresas_id_empresa_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.empresas_id_empresa_seq OWNED BY public.empresas.id_empresa;


--
-- Name: escaneos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.escaneos (
    id_escaneo integer NOT NULL,
    id_trabajador integer NOT NULL,
    id_puerta integer NOT NULL,
    tipo_registro character varying(50) NOT NULL,
    fecha_hora timestamp with time zone DEFAULT now() NOT NULL,
    confianza_biometrica numeric(3,2),
    estado_registro character varying(50) DEFAULT 'exitoso'::character varying,
    observaciones text,
    id_dispositivo integer,
    ubicacion public.geography(Point,4326),
    fecha_creacion timestamp with time zone DEFAULT now(),
    CONSTRAINT escaneos_confianza_biometrica_check CHECK (((confianza_biometrica >= (0)::numeric) AND (confianza_biometrica <= (1)::numeric))),
    CONSTRAINT escaneos_estado_registro_check CHECK (((estado_registro)::text = ANY (ARRAY[('exitoso'::character varying)::text, ('rechazado'::character varying)::text, ('manual'::character varying)::text, ('fuera_de_area'::character varying)::text, ('cancelado'::character varying)::text]))),
    CONSTRAINT escaneos_tipo_registro_check CHECK (((tipo_registro)::text = ANY (ARRAY[('entrada'::character varying)::text, ('salida'::character varying)::text])))
);


--
-- Name: escaneos_id_escaneo_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.escaneos_id_escaneo_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: escaneos_id_escaneo_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.escaneos_id_escaneo_seq OWNED BY public.escaneos.id_escaneo;


--
-- Name: historial_auditoria; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.historial_auditoria (
    id_auditoria integer NOT NULL,
    id_usuario integer,
    tabla_modificada character varying(100) NOT NULL,
    tipo_operacion character varying(10) NOT NULL,
    id_registro_afectado integer,
    valores_anteriores jsonb,
    valores_nuevos jsonb,
    ip_origen character varying(45),
    user_agent character varying(255),
    fecha_hora timestamp with time zone DEFAULT now(),
    CONSTRAINT historial_auditoria_tipo_operacion_check CHECK (((tipo_operacion)::text = ANY ((ARRAY['INSERT'::character varying, 'UPDATE'::character varying, 'DELETE'::character varying, 'LOGIN'::character varying, 'LOGOUT'::character varying])::text[])))
);


--
-- Name: historial_auditoria_id_auditoria_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.historial_auditoria_id_auditoria_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: historial_auditoria_id_auditoria_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.historial_auditoria_id_auditoria_seq OWNED BY public.historial_auditoria.id_auditoria;


--
-- Name: incidencias; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incidencias (
    id_incidencia integer NOT NULL,
    id_trabajador integer NOT NULL,
    tipo_incidencia character varying(30) NOT NULL,
    fecha date NOT NULL,
    descripcion text,
    ruta_foto text,
    id_escaneo_ref integer,
    estado character varying(15) DEFAULT 'pendiente'::character varying,
    fecha_creacion timestamp with time zone DEFAULT now(),
    CONSTRAINT incidencias_estado_check CHECK (((estado)::text = ANY ((ARRAY['pendiente'::character varying, 'revisada'::character varying, 'justificada'::character varying])::text[]))),
    CONSTRAINT incidencias_tipo_incidencia_check CHECK (((tipo_incidencia)::text = ANY ((ARRAY['salida_sin_registro'::character varying, 'entrada_sin_registro'::character varying, 'falta'::character varying, 'retardo'::character varying, 'fuera_de_area'::character varying, 'acceso_otra_empresa'::character varying])::text[])))
);


--
-- Name: incidencias_id_incidencia_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.incidencias_id_incidencia_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: incidencias_id_incidencia_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.incidencias_id_incidencia_seq OWNED BY public.incidencias.id_incidencia;


--
-- Name: parametros_sistema; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parametros_sistema (
    id_parametro integer NOT NULL,
    clave character varying(100) NOT NULL,
    valor character varying(500) NOT NULL,
    tipo character varying(10) DEFAULT 'texto'::character varying,
    descripcion text,
    editable boolean DEFAULT true,
    fecha_actualizacion timestamp with time zone DEFAULT now(),
    CONSTRAINT parametros_sistema_tipo_check CHECK (((tipo)::text = ANY ((ARRAY['numero'::character varying, 'texto'::character varying, 'booleano'::character varying, 'json'::character varying])::text[])))
);


--
-- Name: parametros_sistema_id_parametro_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.parametros_sistema_id_parametro_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: parametros_sistema_id_parametro_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.parametros_sistema_id_parametro_seq OWNED BY public.parametros_sistema.id_parametro;


--
-- Name: puertas_acceso; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.puertas_acceso (
    id_puerta integer NOT NULL,
    nombre_puerta character varying(100) NOT NULL,
    ubicacion public.geography(Point,4326),
    id_area integer,
    id_empresa integer,
    id_dispositivo integer,
    tipo_acceso character varying(15) DEFAULT 'bidireccional'::character varying,
    requiere_autorizacion boolean DEFAULT false,
    estado character varying(10) DEFAULT 'activo'::character varying,
    fecha_creacion timestamp with time zone DEFAULT now(),
    inactivo_por_cascada boolean DEFAULT false NOT NULL,
    CONSTRAINT puertas_acceso_estado_check CHECK (((estado)::text = ANY ((ARRAY['activo'::character varying, 'inactivo'::character varying])::text[]))),
    CONSTRAINT puertas_acceso_tipo_acceso_check CHECK (((tipo_acceso)::text = ANY ((ARRAY['entrada'::character varying, 'salida'::character varying, 'bidireccional'::character varying])::text[])))
);


--
-- Name: puertas_acceso_id_puerta_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.puertas_acceso_id_puerta_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: puertas_acceso_id_puerta_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.puertas_acceso_id_puerta_seq OWNED BY public.puertas_acceso.id_puerta;


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id_rol integer NOT NULL,
    nombre_rol character varying(50) NOT NULL,
    descripcion text,
    permisos jsonb,
    estado character varying(10) DEFAULT 'activo'::character varying,
    fecha_creacion timestamp with time zone DEFAULT now(),
    CONSTRAINT roles_estado_check CHECK (((estado)::text = ANY ((ARRAY['activo'::character varying, 'inactivo'::character varying])::text[])))
);


--
-- Name: roles_id_rol_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.roles_id_rol_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: roles_id_rol_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.roles_id_rol_seq OWNED BY public.roles.id_rol;


--
-- Name: trabajadores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trabajadores (
    id_trabajador integer NOT NULL,
    nombre character varying(100) NOT NULL,
    apellido character varying(100) NOT NULL,
    id_area integer NOT NULL,
    foto_perfil bytea,
    estado character varying(15) DEFAULT 'activo'::character varying,
    fecha_creacion timestamp with time zone DEFAULT now(),
    fecha_actualizacion timestamp with time zone DEFAULT now(),
    inactivo_por_cascada boolean DEFAULT false NOT NULL,
    CONSTRAINT trabajadores_estado_check CHECK (((estado)::text = ANY ((ARRAY['activo'::character varying, 'inactivo'::character varying, 'suspendido'::character varying])::text[])))
);


--
-- Name: trabajadores_id_trabajador_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.trabajadores_id_trabajador_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: trabajadores_id_trabajador_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.trabajadores_id_trabajador_seq OWNED BY public.trabajadores.id_trabajador;


--
-- Name: usuarios; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usuarios (
    id_usuario integer NOT NULL,
    nombre_usuario character varying(50) NOT NULL,
    contrasena character varying(255) NOT NULL,
    id_rol integer NOT NULL,
    estado character varying(10) DEFAULT 'activo'::character varying,
    fecha_creacion timestamp with time zone DEFAULT now(),
    fecha_actualizacion timestamp with time zone DEFAULT now(),
    empresa integer DEFAULT 1,
    inactivo_por_cascada boolean DEFAULT false NOT NULL,
    CONSTRAINT usuarios_estado_check CHECK (((estado)::text = ANY ((ARRAY['activo'::character varying, 'inactivo'::character varying])::text[])))
);


--
-- Name: usuarios_id_usuario_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.usuarios_id_usuario_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: usuarios_id_usuario_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.usuarios_id_usuario_seq OWNED BY public.usuarios.id_usuario;


--
-- Name: area_trabajo id_area; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.area_trabajo ALTER COLUMN id_area SET DEFAULT nextval('public.area_trabajo_id_area_seq'::regclass);


--
-- Name: asistencia id_asistencia; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asistencia ALTER COLUMN id_asistencia SET DEFAULT nextval('public.asistencia_id_asistencia_seq'::regclass);


--
-- Name: dispositivos id_dispositivo; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dispositivos ALTER COLUMN id_dispositivo SET DEFAULT nextval('public.dispositivos_id_dispositivo_seq'::regclass);


--
-- Name: embeddings id_embedding; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embeddings ALTER COLUMN id_embedding SET DEFAULT nextval('public.embeddings_id_embedding_seq'::regclass);


--
-- Name: empresas id_empresa; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.empresas ALTER COLUMN id_empresa SET DEFAULT nextval('public.empresas_id_empresa_seq'::regclass);


--
-- Name: escaneos id_escaneo; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escaneos ALTER COLUMN id_escaneo SET DEFAULT nextval('public.escaneos_id_escaneo_seq'::regclass);


--
-- Name: historial_auditoria id_auditoria; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.historial_auditoria ALTER COLUMN id_auditoria SET DEFAULT nextval('public.historial_auditoria_id_auditoria_seq'::regclass);


--
-- Name: incidencias id_incidencia; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incidencias ALTER COLUMN id_incidencia SET DEFAULT nextval('public.incidencias_id_incidencia_seq'::regclass);


--
-- Name: parametros_sistema id_parametro; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parametros_sistema ALTER COLUMN id_parametro SET DEFAULT nextval('public.parametros_sistema_id_parametro_seq'::regclass);


--
-- Name: puertas_acceso id_puerta; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.puertas_acceso ALTER COLUMN id_puerta SET DEFAULT nextval('public.puertas_acceso_id_puerta_seq'::regclass);


--
-- Name: roles id_rol; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles ALTER COLUMN id_rol SET DEFAULT nextval('public.roles_id_rol_seq'::regclass);


--
-- Name: trabajadores id_trabajador; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trabajadores ALTER COLUMN id_trabajador SET DEFAULT nextval('public.trabajadores_id_trabajador_seq'::regclass);


--
-- Name: usuarios id_usuario; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuarios ALTER COLUMN id_usuario SET DEFAULT nextval('public.usuarios_id_usuario_seq'::regclass);


--
-- Name: area_trabajo area_trabajo_nombre_area_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.area_trabajo
    ADD CONSTRAINT area_trabajo_nombre_area_key UNIQUE (nombre_area);


--
-- Name: area_trabajo area_trabajo_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.area_trabajo
    ADD CONSTRAINT area_trabajo_pkey PRIMARY KEY (id_area);


--
-- Name: asistencia asistencia_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asistencia
    ADD CONSTRAINT asistencia_pkey PRIMARY KEY (id_asistencia);


--
-- Name: dispositivos dispositivos_ip_dispositivo_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dispositivos
    ADD CONSTRAINT dispositivos_ip_dispositivo_key UNIQUE (ip_dispositivo);


--
-- Name: dispositivos dispositivos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dispositivos
    ADD CONSTRAINT dispositivos_pkey PRIMARY KEY (id_dispositivo);


--
-- Name: embeddings embeddings_id_trabajador_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embeddings
    ADD CONSTRAINT embeddings_id_trabajador_key UNIQUE (id_trabajador);


--
-- Name: embeddings embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embeddings
    ADD CONSTRAINT embeddings_pkey PRIMARY KEY (id_embedding);


--
-- Name: empresas empresas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.empresas
    ADD CONSTRAINT empresas_pkey PRIMARY KEY (id_empresa);


--
-- Name: escaneos escaneos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escaneos
    ADD CONSTRAINT escaneos_pkey PRIMARY KEY (id_escaneo);


--
-- Name: historial_auditoria historial_auditoria_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.historial_auditoria
    ADD CONSTRAINT historial_auditoria_pkey PRIMARY KEY (id_auditoria);


--
-- Name: incidencias incidencias_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incidencias
    ADD CONSTRAINT incidencias_pkey PRIMARY KEY (id_incidencia);


--
-- Name: parametros_sistema parametros_sistema_clave_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parametros_sistema
    ADD CONSTRAINT parametros_sistema_clave_key UNIQUE (clave);


--
-- Name: parametros_sistema parametros_sistema_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parametros_sistema
    ADD CONSTRAINT parametros_sistema_pkey PRIMARY KEY (id_parametro);


--
-- Name: puertas_acceso puertas_acceso_id_dispositivo_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.puertas_acceso
    ADD CONSTRAINT puertas_acceso_id_dispositivo_key UNIQUE (id_dispositivo);


--
-- Name: puertas_acceso puertas_acceso_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.puertas_acceso
    ADD CONSTRAINT puertas_acceso_pkey PRIMARY KEY (id_puerta);


--
-- Name: roles roles_nombre_rol_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_nombre_rol_key UNIQUE (nombre_rol);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id_rol);


--
-- Name: trabajadores trabajadores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trabajadores
    ADD CONSTRAINT trabajadores_pkey PRIMARY KEY (id_trabajador);


--
-- Name: usuarios usuarios_nombre_usuario_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuarios
    ADD CONSTRAINT usuarios_nombre_usuario_key UNIQUE (nombre_usuario);


--
-- Name: usuarios usuarios_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuarios
    ADD CONSTRAINT usuarios_pkey PRIMARY KEY (id_usuario);


--
-- Name: idx_asistencia_estado; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_asistencia_estado ON public.asistencia USING btree (estado_registro);


--
-- Name: idx_asistencia_fecha_hora; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_asistencia_fecha_hora ON public.asistencia USING btree (fecha_hora);


--
-- Name: idx_asistencia_tipo; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_asistencia_tipo ON public.asistencia USING btree (tipo_registro);


--
-- Name: idx_asistencia_trabajador; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_asistencia_trabajador ON public.asistencia USING btree (id_trabajador);


--
-- Name: idx_auditoria_fecha; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_auditoria_fecha ON public.historial_auditoria USING btree (fecha_hora);


--
-- Name: idx_auditoria_operacion; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_auditoria_operacion ON public.historial_auditoria USING btree (tipo_operacion);


--
-- Name: idx_auditoria_tabla; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_auditoria_tabla ON public.historial_auditoria USING btree (tabla_modificada);


--
-- Name: idx_dispositivos_estado; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dispositivos_estado ON public.dispositivos USING btree (estado);


--
-- Name: idx_embeddings_hnsw; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_embeddings_hnsw ON public.embeddings USING hnsw (vector_embedding public.vector_cosine_ops);


--
-- Name: idx_escaneo_fecha_hora; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_escaneo_fecha_hora ON public.escaneos USING btree (fecha_hora);


--
-- Name: idx_escaneo_trabajador; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_escaneo_trabajador ON public.escaneos USING btree (id_trabajador);


--
-- Name: idx_escaneos_estado; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_escaneos_estado ON public.escaneos USING btree (estado_registro);


--
-- Name: idx_escaneos_tipo; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_escaneos_tipo ON public.escaneos USING btree (tipo_registro);


--
-- Name: idx_incidencias_fecha; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_incidencias_fecha ON public.incidencias USING btree (fecha);


--
-- Name: idx_incidencias_tipo; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_incidencias_tipo ON public.incidencias USING btree (tipo_incidencia);


--
-- Name: idx_incidencias_trabajador; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_incidencias_trabajador ON public.incidencias USING btree (id_trabajador);


--
-- Name: idx_trabajadores_estado; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trabajadores_estado ON public.trabajadores USING btree (estado);


--
-- Name: area_trabajo trg_cascada_estado_area; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cascada_estado_area AFTER UPDATE OF estado ON public.area_trabajo FOR EACH ROW WHEN (((old.estado)::text IS DISTINCT FROM (new.estado)::text)) EXECUTE FUNCTION public.fn_cascada_estado_area();


--
-- Name: empresas trg_cascada_estado_empresa; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cascada_estado_empresa AFTER UPDATE OF estado ON public.empresas FOR EACH ROW WHEN ((old.estado IS DISTINCT FROM new.estado)) EXECUTE FUNCTION public.fn_cascada_estado_empresa();


--
-- Name: trabajadores trg_cascada_estado_trabajador; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cascada_estado_trabajador AFTER UPDATE OF estado ON public.trabajadores FOR EACH ROW WHEN (((old.estado)::text IS DISTINCT FROM (new.estado)::text)) EXECUTE FUNCTION public.fn_cascada_estado_trabajador();


--
-- Name: parametros_sistema trg_parametros_updated; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_parametros_updated BEFORE UPDATE ON public.parametros_sistema FOR EACH ROW EXECUTE FUNCTION public.set_fecha_actualizacion();


--
-- Name: empresas trg_proteger_empresa_admin_del; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_proteger_empresa_admin_del BEFORE DELETE ON public.empresas FOR EACH ROW EXECUTE FUNCTION public.fn_proteger_empresa_admin();


--
-- Name: empresas trg_proteger_empresa_admin_upd; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_proteger_empresa_admin_upd BEFORE UPDATE OF estado ON public.empresas FOR EACH ROW EXECUTE FUNCTION public.fn_proteger_empresa_admin();


--
-- Name: trabajadores trg_trabajadores_updated; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_trabajadores_updated BEFORE UPDATE ON public.trabajadores FOR EACH ROW EXECUTE FUNCTION public.set_fecha_actualizacion();


--
-- Name: usuarios trg_usuarios_updated; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_usuarios_updated BEFORE UPDATE ON public.usuarios FOR EACH ROW EXECUTE FUNCTION public.set_fecha_actualizacion();


--
-- Name: escaneos trg_validar_asistencia; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_validar_asistencia AFTER INSERT ON public.escaneos FOR EACH ROW EXECUTE FUNCTION public.fn_validar_asistencia_escaneo();


--
-- Name: area_trabajo area_trabajo_id_empresa_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.area_trabajo
    ADD CONSTRAINT area_trabajo_id_empresa_fkey FOREIGN KEY (id_empresa) REFERENCES public.empresas(id_empresa) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: asistencia asistencia_id_dispositivo_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asistencia
    ADD CONSTRAINT asistencia_id_dispositivo_fkey FOREIGN KEY (id_dispositivo) REFERENCES public.dispositivos(id_dispositivo) ON DELETE SET NULL;


--
-- Name: asistencia asistencia_id_puerta_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asistencia
    ADD CONSTRAINT asistencia_id_puerta_fkey FOREIGN KEY (id_puerta) REFERENCES public.puertas_acceso(id_puerta) ON DELETE CASCADE;


--
-- Name: asistencia asistencia_id_trabajador_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asistencia
    ADD CONSTRAINT asistencia_id_trabajador_fkey FOREIGN KEY (id_trabajador) REFERENCES public.trabajadores(id_trabajador) ON DELETE CASCADE;


--
-- Name: dispositivos dispositivos_id_area_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dispositivos
    ADD CONSTRAINT dispositivos_id_area_fkey FOREIGN KEY (id_area) REFERENCES public.area_trabajo(id_area) ON DELETE CASCADE;


--
-- Name: embeddings embeddings_id_trabajador_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embeddings
    ADD CONSTRAINT embeddings_id_trabajador_fkey FOREIGN KEY (id_trabajador) REFERENCES public.trabajadores(id_trabajador) ON DELETE CASCADE;


--
-- Name: escaneos escaneos_id_dispositivo_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escaneos
    ADD CONSTRAINT escaneos_id_dispositivo_fkey FOREIGN KEY (id_dispositivo) REFERENCES public.dispositivos(id_dispositivo) ON DELETE SET NULL;


--
-- Name: escaneos escaneos_id_puerta_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escaneos
    ADD CONSTRAINT escaneos_id_puerta_fkey FOREIGN KEY (id_puerta) REFERENCES public.puertas_acceso(id_puerta) ON DELETE CASCADE;


--
-- Name: escaneos escaneos_id_trabajador_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escaneos
    ADD CONSTRAINT escaneos_id_trabajador_fkey FOREIGN KEY (id_trabajador) REFERENCES public.trabajadores(id_trabajador) ON DELETE CASCADE;


--
-- Name: historial_auditoria historial_auditoria_id_usuario_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.historial_auditoria
    ADD CONSTRAINT historial_auditoria_id_usuario_fkey FOREIGN KEY (id_usuario) REFERENCES public.usuarios(id_usuario) ON DELETE CASCADE;


--
-- Name: incidencias incidencias_id_escaneo_ref_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incidencias
    ADD CONSTRAINT incidencias_id_escaneo_ref_fkey FOREIGN KEY (id_escaneo_ref) REFERENCES public.escaneos(id_escaneo) ON DELETE SET NULL;


--
-- Name: incidencias incidencias_id_trabajador_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incidencias
    ADD CONSTRAINT incidencias_id_trabajador_fkey FOREIGN KEY (id_trabajador) REFERENCES public.trabajadores(id_trabajador) ON DELETE CASCADE;


--
-- Name: puertas_acceso puertas_acceso_id_area_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.puertas_acceso
    ADD CONSTRAINT puertas_acceso_id_area_fkey FOREIGN KEY (id_area) REFERENCES public.area_trabajo(id_area) ON DELETE CASCADE;


--
-- Name: puertas_acceso puertas_acceso_id_dispositivo_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.puertas_acceso
    ADD CONSTRAINT puertas_acceso_id_dispositivo_fkey FOREIGN KEY (id_dispositivo) REFERENCES public.dispositivos(id_dispositivo) ON DELETE SET NULL;


--
-- Name: puertas_acceso puertas_acceso_id_empresa_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.puertas_acceso
    ADD CONSTRAINT puertas_acceso_id_empresa_fkey FOREIGN KEY (id_empresa) REFERENCES public.empresas(id_empresa) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: trabajadores trabajadores_id_area_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trabajadores
    ADD CONSTRAINT trabajadores_id_area_fkey FOREIGN KEY (id_area) REFERENCES public.area_trabajo(id_area) ON DELETE CASCADE;


--
-- Name: usuarios usuarios_empresa__fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuarios
    ADD CONSTRAINT usuarios_empresa__fk FOREIGN KEY (empresa) REFERENCES public.empresas(id_empresa) ON DELETE CASCADE;


--
-- Name: usuarios usuarios_id_rol_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuarios
    ADD CONSTRAINT usuarios_id_rol_fkey FOREIGN KEY (id_rol) REFERENCES public.roles(id_rol);


--
-- PostgreSQL database dump complete
--

\unrestrict 5jOR4XjuUIGwoB9cdUfKPYl3An1Eyuu6YCuNAGgIJwkS8gm1V7vZleYzlzumlSG

