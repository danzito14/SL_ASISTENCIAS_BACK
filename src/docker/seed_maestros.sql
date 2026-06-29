-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║  seed_maestros.sql — Datos maestros para sembrar un prod NUEVO (vacío).    ║
-- ║  Exportado de la BD local (esquema nuevo) el 2026-06-27. Incluye:          ║
-- ║    empresas, area_trabajo (con tipo_area + ubicacion PostGIS), puertas,    ║
-- ║    dispositivos y usuarios. NO incluye trabajadores/embeddings (vienen del ║
-- ║    sync SYS21). Idempotente (ON CONFLICT DO NOTHING). --column-inserts:     ║
-- ║    nombra las columnas, inmune a diferencias de orden vs init.sql.          ║
-- ║                                                                            ║
-- ║  Aplicar DESPUÉS de deploy_prod.sh (init.sql ya creó el esquema+roles):    ║
-- ║    docker compose -f docker-compose.prod.yml exec -T postgres \            ║
-- ║      sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \║
-- ║      < seed_maestros.sql                                                    ║
-- ║                                                                            ║
-- ║  OJO: usuarios kiosko_test/kiosko_emp7 traen contraseñas de PRUEBA         ║
-- ║  (Kiosko-SL-2026 / Kiosko-Emp7-2026). Cámbialas en prod.                   ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
BEGIN;
--
-- PostgreSQL database dump
--

\restrict HI9p4TY2QevsNmzEQlcE42LY5kTwqD6GnReGrmjeTyqRdmTg8CbPmnPgWdI76Gg

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
-- Data for Name: empresas; Type: TABLE DATA; Schema: public; Owner: root
--

INSERT INTO public.empresas (id_empresa, nombre_empresa, ubicacion, zona_horaria, estado, fecha_creacion) VALUES (7, 'Empacadora de Mango del Noroeste (Fresh Pack)', '0103000020E61000000100000005000000F2F18EEC183A5BC0B78949D686DC3940EA8BD342EB395BC0C2127F1FEADB394094BED1FF2D3A5BC094A83E61C2DA3940A74DC3D3513A5BC06DAFFE1904DB3940F2F18EEC183A5BC0B78949D686DC3940', 'America/Mazatlan', 'activo', '2026-06-22 16:37:57.348882-07') ON CONFLICT DO NOTHING;
INSERT INTO public.empresas (id_empresa, nombre_empresa, ubicacion, zona_horaria, estado, fecha_creacion) VALUES (1, 'SL Agricola SA de CV', '0103000020E610000001000000050000007F426AD7562E5BC06C17548C70B63940A8403308272E5BC0899A34528EB73940D73BCFBE002E5BC08A27556642B739400085D42A302E5BC0F2E2F7B820B639407F426AD7562E5BC06C17548C70B63940', 'America/Mazatlan', 'activo', '2026-06-22 16:36:44.628788-07') ON CONFLICT DO NOTHING;
INSERT INTO public.empresas (id_empresa, nombre_empresa, ubicacion, zona_horaria, estado, fecha_creacion) VALUES (2, 'AGRICOLA VANTA', '0103000020E610000001000000050000007F426AD7562E5BC06C17548C70B63940A8403308272E5BC0899A34528EB73940D73BCFBE002E5BC08A27556642B739400085D42A302E5BC0F2E2F7B820B639407F426AD7562E5BC06C17548C70B63940', 'America/Mazatlan', 'activo', '2026-06-22 16:36:44.628788-07') ON CONFLICT DO NOTHING;
INSERT INTO public.empresas (id_empresa, nombre_empresa, ubicacion, zona_horaria, estado, fecha_creacion) VALUES (5, 'AGRICOLA POTATO', '0103000020E610000001000000050000007F426AD7562E5BC06C17548C70B63940A8403308272E5BC0899A34528EB73940D73BCFBE002E5BC08A27556642B739400085D42A302E5BC0F2E2F7B820B639407F426AD7562E5BC06C17548C70B63940', 'America/Mazatlan', 'activo', '2026-06-22 16:36:44.628788-07') ON CONFLICT DO NOTHING;
INSERT INTO public.empresas (id_empresa, nombre_empresa, ubicacion, zona_horaria, estado, fecha_creacion) VALUES (9, 'MARIO ALBERTO LOPEZ BRAVO', '0103000020E610000001000000050000007F426AD7562E5BC06C17548C70B63940A8403308272E5BC0899A34528EB73940D73BCFBE002E5BC08A27556642B739400085D42A302E5BC0F2E2F7B820B639407F426AD7562E5BC06C17548C70B63940', 'America/Mazatlan', 'activo', '2026-06-22 16:36:44.628788-07') ON CONFLICT DO NOTHING;
INSERT INTO public.empresas (id_empresa, nombre_empresa, ubicacion, zona_horaria, estado, fecha_creacion) VALUES (10, 'AZARES PRODUCE', '0103000020E610000001000000050000007F426AD7562E5BC06C17548C70B63940A8403308272E5BC0899A34528EB73940D73BCFBE002E5BC08A27556642B739400085D42A302E5BC0F2E2F7B820B639407F426AD7562E5BC06C17548C70B63940', 'America/Mazatlan', 'activo', '2026-06-22 16:36:44.628788-07') ON CONFLICT DO NOTHING;
INSERT INTO public.empresas (id_empresa, nombre_empresa, ubicacion, zona_horaria, estado, fecha_creacion) VALUES (6, 'COMERCIALIZADORA DE LEGUMBRES DE LOS MOCHIS CAT', '0103000020E61000000100000007000000978DCEF9294A5BC089B663EAAEF039409B5AB6D6174A5BC0F2B391EBA6F0394055302AA9134A5BC0CA198A3BDEF03940892650C4224A5BC0E6CAA0DAE0F03940A034D428244A5BC08A75AA7CCFF039400FF27A30294A5BC0062FFA0AD2F03940978DCEF9294A5BC089B663EAAEF03940', 'America/Mazatlan', 'activo', '2026-06-22 16:36:44.628788-07') ON CONFLICT DO NOTHING;
INSERT INTO public.empresas (id_empresa, nombre_empresa, ubicacion, zona_horaria, estado, fecha_creacion) VALUES (4, 'COMERCIALIZADORA DE LEGUMBRES CACO', '0103000020E610000001000000050000006FD39FFD482E5BC0A2EF6E6589B6394015A8C5E0612E5BC02DEC6987BFB63940FE5F75E4482E5BC04089CF9D60B7394082380F27302E5BC064CE33F625B739406FD39FFD482E5BC0A2EF6E6589B63940', 'America/Mazatlan', 'activo', '2026-06-22 16:36:44.628788-07') ON CONFLICT DO NOTHING;


--
-- Data for Name: area_trabajo; Type: TABLE DATA; Schema: public; Owner: root
--

INSERT INTO public.area_trabajo (id_area, nombre_area, descripcion, ubicacion, id_empresa, hora_entrada, estado, inactivo_por_cascada, fecha_creacion, tipo_area) VALUES (2, 'Oficinas Administrativas de SL Agricola', 'Oficinas administivas de SL Agricola', '0103000020E610000001000000050000007F426AD7562E5BC06C17548C70B63940A8403308272E5BC0899A34528EB73940D73BCFBE002E5BC08A27556642B739400085D42A302E5BC0F2E2F7B820B639407F426AD7562E5BC06C17548C70B63940', 1, '08:30:00', 'activo', false, '2026-06-22 16:39:01.106663-07', 'oficina') ON CONFLICT DO NOTHING;
INSERT INTO public.area_trabajo (id_area, nombre_area, descripcion, ubicacion, id_empresa, hora_entrada, estado, inactivo_por_cascada, fecha_creacion, tipo_area) VALUES (3, 'Empaque SL Agricola', 'Empaque de verduras del SL Agricola', '0103000020E61000000100000005000000EB1DFD55532E5BC010FF89B497B63940A8403308272E5BC0899A34528EB73940D73BCFBE002E5BC08A27556642B7394066E53B24292E5BC09798EB2B44B63940EB1DFD55532E5BC010FF89B497B63940', 1, '08:30:00', 'activo', false, '2026-06-22 16:41:52.503007-07', 'empaque') ON CONFLICT DO NOTHING;
INSERT INTO public.area_trabajo (id_area, nombre_area, descripcion, ubicacion, id_empresa, hora_entrada, estado, inactivo_por_cascada, fecha_creacion, tipo_area) VALUES (5, 'Empaque de Mango Fresh Pack', 'Empaque de Mango Fresh Pack', '0103000020E61000000100000005000000F2F18EEC183A5BC0B78949D686DC3940EA8BD342EB395BC0C2127F1FEADB394094BED1FF2D3A5BC094A83E61C2DA3940A74DC3D3513A5BC06DAFFE1904DB3940F2F18EEC183A5BC0B78949D686DC3940', 7, '08:30:00', 'activo', false, '2026-06-22 16:43:46.100862-07', 'empaque') ON CONFLICT DO NOTHING;
INSERT INTO public.area_trabajo (id_area, nombre_area, descripcion, ubicacion, id_empresa, hora_entrada, estado, inactivo_por_cascada, fecha_creacion, tipo_area) VALUES (4, 'Oficinas Administrativas de Mango Fresh Pack', 'Oficinas Administrativas de Mango Fresh Pack', '0103000020E61000000100000005000000F2F18EEC183A5BC0B78949D686DC3940EA8BD342EB395BC0C2127F1FEADB394094BED1FF2D3A5BC094A83E61C2DA3940A74DC3D3513A5BC06DAFFE1904DB3940F2F18EEC183A5BC0B78949D686DC3940', 7, '08:30:00', 'activo', false, '2026-06-22 16:42:54.435804-07', 'oficina') ON CONFLICT DO NOTHING;
INSERT INTO public.area_trabajo (id_area, nombre_area, descripcion, ubicacion, id_empresa, hora_entrada, estado, inactivo_por_cascada, fecha_creacion, tipo_area) VALUES (39, 'Campo SL Agricola', NULL, NULL, 1, NULL, 'activo', false, '2026-06-23 18:15:11.570712-07', 'campo') ON CONFLICT DO NOTHING;


--
-- Data for Name: dispositivos; Type: TABLE DATA; Schema: public; Owner: root
--

INSERT INTO public.dispositivos (id_dispositivo, nombre_dispositivo, tipo_dispositivo, ip_dispositivo, puerto, ubicacion, id_area, id_empresa, estado, inactivo_por_cascada, ultima_conexion, fecha_instalacion, fecha_creacion) VALUES (1, 'Scanner FreshPack', 'escaner_facial', NULL, 8080, '0101000020E6100000A75CE15D2E3A5BC0B7D5AC33BEDB3940', 5, 7, 'activo', false, NULL, NULL, '2026-06-22 16:50:13.182485-07') ON CONFLICT DO NOTHING;
INSERT INTO public.dispositivos (id_dispositivo, nombre_dispositivo, tipo_dispositivo, ip_dispositivo, puerto, ubicacion, id_area, id_empresa, estado, inactivo_por_cascada, ultima_conexion, fecha_instalacion, fecha_creacion) VALUES (2, 'Scanner Oficinas SL Agricola', 'escaner_facial', NULL, 8080, '0101000020E610000033198EE7332E5BC0D847A7AE7CB63940', 2, 1, 'activo', false, NULL, NULL, '2026-06-22 16:51:14.777325-07') ON CONFLICT DO NOTHING;
INSERT INTO public.dispositivos (id_dispositivo, nombre_dispositivo, tipo_dispositivo, ip_dispositivo, puerto, ubicacion, id_area, id_empresa, estado, inactivo_por_cascada, ultima_conexion, fecha_instalacion, fecha_creacion) VALUES (3, 'Scanner Empaque SL Agricola', 'escaner_facial', NULL, 8080, '0101000020E61000000A86730D332E5BC05586713788B63940', 3, 1, 'activo', false, NULL, NULL, '2026-06-22 16:54:15.932883-07') ON CONFLICT DO NOTHING;


--
-- Data for Name: puertas_acceso; Type: TABLE DATA; Schema: public; Owner: root
--

INSERT INTO public.puertas_acceso (id_puerta, nombre_puerta, ubicacion, id_area, id_empresa, id_dispositivo, tipo_puerta, funcion_puerta, categoria_zona_destino, tipo_acceso, requiere_autorizacion, estado, inactivo_por_cascada, fecha_creacion) VALUES (5, 'Puerta Oficinas SL Agricola', '0101000020E610000033198EE7332E5BC0D847A7AE7CB63940', 2, 1, 2, 'administrativa', 'asistencia', NULL, 'bidireccional', false, 'activo', false, '2026-06-22 17:44:42.689183-07') ON CONFLICT DO NOTHING;
INSERT INTO public.puertas_acceso (id_puerta, nombre_puerta, ubicacion, id_area, id_empresa, id_dispositivo, tipo_puerta, funcion_puerta, categoria_zona_destino, tipo_acceso, requiere_autorizacion, estado, inactivo_por_cascada, fecha_creacion) VALUES (6, 'Puerta Empaque SL Agricola', '0101000020E61000000A86730D332E5BC05586713788B63940', 3, 1, 3, 'administrativa', 'asistencia', NULL, 'bidireccional', false, 'activo', false, '2026-06-22 17:45:50.00592-07') ON CONFLICT DO NOTHING;
INSERT INTO public.puertas_acceso (id_puerta, nombre_puerta, ubicacion, id_area, id_empresa, id_dispositivo, tipo_puerta, funcion_puerta, categoria_zona_destino, tipo_acceso, requiere_autorizacion, estado, inactivo_por_cascada, fecha_creacion) VALUES (7, 'Puerta General Mango Fresh Pack', '0101000020E61000004A601AB7273A5BC0ED7B7E7D95DB3940', 5, 7, 1, 'mixta', 'asistencia', NULL, 'bidireccional', false, 'activo', false, '2026-06-23 10:19:25.9882-07') ON CONFLICT DO NOTHING;


--
-- Name: area_trabajo_id_area_seq; Type: SEQUENCE SET; Schema: public; Owner: root
--

SELECT pg_catalog.setval('public.area_trabajo_id_area_seq', 39, true);


--
-- Name: dispositivos_id_dispositivo_seq; Type: SEQUENCE SET; Schema: public; Owner: root
--

SELECT pg_catalog.setval('public.dispositivos_id_dispositivo_seq', 3, true);


--
-- Name: empresas_id_empresa_seq; Type: SEQUENCE SET; Schema: public; Owner: root
--

SELECT pg_catalog.setval('public.empresas_id_empresa_seq', 106, true);


--
-- Name: puertas_acceso_id_puerta_seq; Type: SEQUENCE SET; Schema: public; Owner: root
--

SELECT pg_catalog.setval('public.puertas_acceso_id_puerta_seq', 7, true);


--
-- PostgreSQL database dump complete
--

\unrestrict HI9p4TY2QevsNmzEQlcE42LY5kTwqD6GnReGrmjeTyqRdmTg8CbPmnPgWdI76Gg


-- Usuarios (id_rol resuelto por nombre de rol; id_usuario lo asigna la secuencia).
INSERT INTO public.usuarios (nombre_usuario,contrasena,empresa,estado,id_rol) SELECT 'admin_test','pbkdf2_sha256$240000$4c789381c27ab524dc53094d6ad5eb01$e2e3d8baa27383198ec310d708d2166056b45f6458c5d21d7b6a6f73dfb1ac54',99,'activo',r.id_rol FROM public.roles r WHERE r.nombre_rol='administrador' ON CONFLICT (nombre_usuario) DO NOTHING;
INSERT INTO public.usuarios (nombre_usuario,contrasena,empresa,estado,id_rol) SELECT 'admin','pbkdf2_sha256$240000$3ee9d6bcdf6f05f846998a5c5dd4eafc$a689da89977218490c4b61461f1ccc103e769894b037b43b81899f80a4fcc859',99,'activo',r.id_rol FROM public.roles r WHERE r.nombre_rol='administrador' ON CONFLICT (nombre_usuario) DO NOTHING;
INSERT INTO public.usuarios (nombre_usuario,contrasena,empresa,estado,id_rol) SELECT 'kiosko_test','pbkdf2_sha256$240000$37fcf9bf5a33ecb334131e2001cef174$f68ddaa873406b38ec4667303db2622289081be4531f03b8a930d3ea5234b00f',1,'activo',r.id_rol FROM public.roles r WHERE r.nombre_rol='escaneador' ON CONFLICT (nombre_usuario) DO NOTHING;
INSERT INTO public.usuarios (nombre_usuario,contrasena,empresa,estado,id_rol) SELECT 'kiosko_emp7','pbkdf2_sha256$240000$f584c0e3f58bd25bf8f2649f1203b3ba$607a74be42063c9fb3c3f627bbf3a4f8519315cd81387604f73da9dc02265e59',7,'activo',r.id_rol FROM public.roles r WHERE r.nombre_rol='escaneador' ON CONFLICT (nombre_usuario) DO NOTHING;

COMMIT;
