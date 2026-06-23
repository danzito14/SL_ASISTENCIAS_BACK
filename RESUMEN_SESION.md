# Resumen de sesión — handoff

> Qué se hizo y dónde retomar. El monolito se alineó al esquema nuevo, se "pre-cortó"
> por dominios y luego se **extrajeron de verdad los 6 dominios a microservicios
> independientes** (BD compartida + un rol por servicio). Hoy hay **8 servicios** en
> `docker-compose.prod.yml` y el "backend" quedó como puro **access**.

---

## 1. Lo que se hizo

### A) Alineación del backend con el `init.sql` nuevo (multi-tenant / offline-first)
- **`intentos_acceso` re-agregada** al `init.sql` con estilo nuevo (PK UUIDv7, `id_empresa`, enum `tipo_intento`, índices). El rediseño la había omitido.
- **Modelos**: PK `int → UUID` en `escaneos`/`asistencia`/`incidencias`/`intentos_acceso`; `id_empresa` denormalizado; campos nuevos (`tipo_puerta`/`funcion_puerta`/`categoria_zona_destino` en puertas; `permiso_escaneo`/`nivel_acceso_interno` en trabajadores; columnas de sync; `inactivo_por_cascada`); `Empresa.ubicacion` nullable.
- **Schemas**: ids `int → UUID`, enums a `Literal`, campos nuevos.
- **Routers**: path params `int → UUID`.
- **Services**: scoping por `id_empresa` denormalizado; se deriva `id_empresa` en cada alta; fix `UUID → str` en export XLSX.
- **scanner**: setea `id_empresa`; como el trigger viejo ya no existe, llama `validar_escaneos_lote()` online tras cada escaneo.

### B) Gap de asistencia "entrada" (resuelto)
- `procesar_salidas_dia()` → **`consolidar_asistencia_dia(p_dias_atras, p_id_trabajador, p_incluir_salida)`**: deriva **entrada + salida** desde `escaneos`, idempotente. Se llama **en vivo** (scanner, entrada del día), tras lote **offline**, y en el **cron**.
- Cron movido a **3:00 AM** (consolida **ayer**: captura salidas posteriores a las 23:30; no hay turnos de madrugada).

### C) Roles de BD + Docker
- **`src/docker/roles_microservicio.sql`**: un rol de PostgreSQL por microservicio + GRANTs de mínimo privilegio (dueño DDL separado del runtime, `reports` solo lectura, cascadas en `SECURITY DEFINER`). Cableado en ambos compose (corre tras `init.sql`).
- **BD renombrada a `SL_ASISTENCIAS`** (compose + `.env` + `cron.database_name` + `DB_NAME`). Nombre de proyecto compose `sl_asistencias` → volumen aislado de la v1.
- **Fixes**: `docker-compose.prod.yml` backend `context: ../app/back`; `.gitignore` → `app/back/media/`.

### D) Prep de microservicios (#1–#6, costuras dentro del monolito)
Cada dominio se aisló primero dentro del monolito (JWT self-contained, facades de
lectura, services-puro-motor) sin cambiar comportamiento — base para el corte real.

### E) Extracción REAL — los 6 dominios ya son servicios independientes ✅
Patrón por servicio: app FastAPI propia en `src/app/<svc>/`, se conecta con su rol
**`svc_*`** de mínimo privilegio, valida el JWT de identity **stateless**, modelos
**recortados** (sin relaciones cross-domain → mappers limpios), su Dockerfile/requirements
a la medida, ruteo en Nginx y servicio en compose. Verificado en cada uno:
`compileall` + `configure_mappers()` + import de `main` + prueba en vivo del rol `svc_*`.

| Servicio    | Puerto host | Rol DB          | Sirve / hace                                               | Imagen |
|-------------|-------------|-----------------|-----------------------------------------------------------|--------|
| identity    | 8001        | svc_identity    | `/usuarios` `/roles` + login/JWT (único con read-guard)   | liviana |
| tenancy     | 8002        | svc_tenancy     | `/empresas` `/areas` `/puertas` `/dispositivos`           | + geo |
| workers     | 8003        | svc_workers     | `/trabajadores` `/embeddings`; llama a recognition p/enrolar | + pgvector |
| reports     | 8004        | svc_reports     | `/reportes/*` (CSV/XLSX, **solo lectura**)                | + openpyxl |
| media       | interno     | — (sin BD)      | guarda/sirve fotos (API interna con token)                | mínima |
| recognition | interno     | svc_recognition | motor facial coarse (API interna con token)               | pesada (IA) |
| **backend** | 8000        | (falta svc_access)| `/asistencias` `/escaneos` `/incidencias` `/intentos` `/scanner` | liviana (sin visión) |

El backend pasó a **cliente HTTP** de media + recognition y **soltó todo el stack de
visión**. Mantiene EN PROCESO los facades de lectura (`Tenancy_Service`) y los modelos
necesarios para enriquecer Asistencia — esas costuras se vuelven cliente HTTP al separar
la BD por servicio.

**Archivos nuevos:** `src/app/{identity,media,recognition,tenancy,workers,reports}/`
(servicios completos), `PLAN_MICROSERVICIOS.md`, `src/docker/roles_microservicio.sql`.

### F) API Gateway — Traefik ✅
Se reemplazó el Nginx del host por **Traefik** (servicio `traefik` en compose) como
**único punto de entrada** (80/443). Elegido por escalabilidad: van a sumarse 2–5
servicios más, y con Traefik agregar uno **no requiere editar un archivo central** —
se enruta solo con labels.
- **Descubrimiento por labels** (`providers.docker`, `exposedByDefault=false`): cada
  servicio declara su `rule=PathPrefix(...)`. backend es el **catch-all** (`/`),
  los demás capturan sus prefijos; `media`/`recognition` con `enable=false` (internos).
- **Middlewares centralizados** (`traefik/dynamic.yml`): `rate-limit` + `secure-headers`
  en todos los routers públicos, y **`jwt-auth` (ForwardAuth) ACTIVO** en backend/
  tenancy/workers/reports (ver §1.G).
- **Los microservicios ya NO publican puertos al host**: Traefik los alcanza por la red
  interna de Docker. Solo Traefik expone 80/443; el **dashboard** queda en `127.0.0.1:8080`.
- **TLS Let's Encrypt** preconfigurado (comentado) en `traefik/traefik.yml`: al tener
  dominio, descomentar el `certresolver` + usar `Host(...)` en las reglas.
- `nginx/fe-scanner.conf` queda como **referencia histórica** (marcado obsoleto; no
  instalar junto a Traefik, pelearían por el :80).
- **`dockerproxy` (nginx) — obligatorio con Docker Engine 29+:** el Engine 29 exige API
  ≥ 1.40 y rechaza con `400 Bad Request` la versión vieja que pide el SDK embebido de
  Traefik (y Traefik **ignora** `DOCKER_API_VERSION`). Se interpone un mini-proxy nginx
  (`traefik/dockerproxy.conf`) que **reescribe `/vX.YZ/` → `/v1.44/`**; Traefik apunta su
  provider a `tcp://dockerproxy:2375` y **ya no monta el socket** (bonus de seguridad: el
  socket lo tiene solo el proxy). Traefik se subió a **v3.5**.

### ✅ PROBADO EN VIVO (`docker compose up`, 10 contenedores)
- Routing por labels OK: Traefik descubre backend/identity/tenancy/workers/reports.
- `/health` (público) → 200 · `/trabajadores`,`/empresas`,`/reportes`,`/usuarios` SIN token → 401.
- Con **JWT válido** (firmado con el `JWT_SECRET` real) → **200** en las 4 rutas protegidas.
- Token con **firma alterada** → **401** (identity `/validate` lo rechaza en el borde).
- `GET /usuarios/login` → 422 (identity lo atiende sin token: login público).
- → La cadena completa **gateway → ForwardAuth/JWT centralizado → scope → servicio** funciona.

### H) Control de acceso por puerta — 2 fixes ✅
La lógica de permisos vive en funciones PL/pgSQL; faltaba **conectarla** y **reflejarla**.
- **Sistema A (fichaje, `funcion_puerta='asistencia'`):** `validar_escaneos_lote` compara
  `tipo_puerta` (campo/administrativa/mixta) ↔ `permiso_escaneo`. Ya marcaba el escaneo
  `rechazado` + incidencia `area_incorrecta`, pero el scanner respondía **siempre "Acceso
  concedido"**. **Fix A:** `_registrar_match` ahora lee `estado_registro` tras validar y
  responde `acceso=False` + el motivo de la incidencia (campo↔administrativa, otra empresa,
  fuera de área).
- **Sistema B (acceso interno, `funcion_puerta='control_acceso'`):** `evaluar_acceso_interno`
  compara `nivel_acceso_interno` (oficina/empaque/mixto) ↔ `categoria_zona_destino`. **No lo
  llamaba nadie.** **Fix B:** el scanner ramifica por `funcion_puerta` (`_procesar_match` →
  `_evaluar_acceso_interno`); las puertas internas deciden con esa función (registra en
  `accesos_internos`, no genera asistencia).
- **Regla del NULL (clave):** `nivel_acceso_interno` pasó a **NULLABLE**; el servicio de
  workers **fuerza NULL cuando `permiso_escaneo='campo'`** (antes el default `'oficina'` daba
  acceso a oficinas por error). `evaluar_acceso_interno` **niega SIEMPRE** un nivel NULL,
  incluso en zonas `'mixto'` (el check de NULL va antes que el de zona).
- **Probado en vivo** (transacción revertida): campo(NULL)→oficina **negado**, empaque→oficina
  **negado**, oficina→oficina **permitido**, mixto→oficina **permitido**, campo(NULL)→mixto
  **negado**. Backend+workers reconstruidos; `/trabajadores` y `/asistencias` → 200.

**Archivos nuevos:** `src/docker/traefik/{traefik.yml,dynamic.yml}`.

### G) Validación de JWT CENTRALIZADA (ForwardAuth) ✅
Se quitó la duplicación de validar el token en cada servicio. Ahora la **autenticación**
ocurre UNA vez en el borde y cada servicio solo hace **autorización** por scope.
- **`GET/POST… /validate` en identity**: decodifica/verifica el JWT (firma + expiración)
  y responde **204 + headers `X-*`** (`X-User-Id`, `X-Empresa`, `X-Scopes`, `X-Rol`,
  `X-Id-Rol`, `X-Nombre-Usuario`) o **401**. Es público en el guard de identity y
  respeta rutas públicas (lee `X-Forwarded-Uri`: health/docs pasan sin token).
  **Importante (CORS):** deja pasar los **preflight `OPTIONS`** (lee `X-Forwarded-Method`)
  → si no, el ForwardAuth respondería 401 al preflight y el navegador bloquearía TODAS las
  llamadas con auth del front (el OPTIONS nunca trae token; la petición real sí se valida).
- **Alias de dev `:8000`**: Traefik publica también `127.0.0.1:8000:80` para que el front
  antiguo (apuntaba al monolito en `:8000`) enrute por el gateway sin cambios. Lo correcto a
  futuro: apuntar el front al `:80`/dominio (`environment.ts` → `apiUrl`) y quitar el alias.
- **Traefik** llama a `/validate` por **ForwardAuth** (`jwt-auth@file`) antes de enrutar
  a backend/tenancy/workers/reports; si es 401, el servicio nunca se toca. identity NO
  usa `jwt-auth` (valida su propio token y su `/usuarios/login` debe ser público).
- **Los 4 servicios** cambiaron su `auth.py`: `Principal` se construye desde los headers
  `X-*` (no decodifican JWT). `guard_scopes` sigue aplicando el scope (lee `X-Scopes`).
  **Fail-closed**: ruta protegida sin identidad del gateway → 401.
- **El `JWT_SECRET` quedó SOLO en identity**: se hizo opcional en los 4 configs, se quitó
  de su `environment` en compose, y se borró el `security.py` muerto de cada uno. Se
  añadió `.dockerignore` (excluye `.env`) a todos los servicios que no lo tenían.

**Token de gateway (anti-bypass) ✅:** para que un contenedor comprometido NO pueda
pegarle directo a un servicio con headers `X-*` falsificados (saltándose Traefik), Traefik
inyecta `X-Gateway-Token` (middleware `gateway-token`, `customRequestHeaders`) en cada
request que reenvía, y los 4 servicios lo verifican en `guard_scopes` (`_verificar_gateway`):
si no coincide → 401. El secreto sale de **una sola** variable de `.env`
(`GATEWAY_INTERNAL_TOKEN`): la leen a la vez el middleware (label del backend, compose la
interpola) y el env de los 4 servicios → sin desincronía. Si la variable se deja vacía, el
chequeo no se exige (retrocompatible). Como un cliente no puede falsificar el header
(Traefik lo sobreescribe), y el secreto no viaja al cliente, el bypass queda cerrado.

**Verificado (en seco):** `/validate` emite/rechaza bien (válido→204+headers, público→204,
inválido/sin token→401); los 4 servicios **arrancan sin `JWT_SECRET`**, autorizan por scope,
son fail-closed, y **rechazan (401) un request sin/ con mal token de gateway** (y pasan con
el correcto; retrocompatibles si no se configura); identity conserva el secreto JWT y
`/validate`; el middleware `gateway-token` se define e interpola desde `.env`; compose
válido (9 servicios).

---

## 2. Estado verificado
- ✅ Python: `compileall` + `configure_mappers()` + import de modelos/schemas/services/routers/`main` en cada paso.
- ✅ **Validado contra Postgres real** (`SL_ASISTENCIAS`, contenedor `postgres_pgvector`):
  `init.sql` + `roles_microservicio.sql` cargan limpio → 16 tablas, 19 enums, funciones
  `gen_uuid_v7`/`validar_escaneos_lote`/`consolidar_asistencia_dia`/`evaluar_acceso_interno`
  ejecutan OK; cron `consolidar-asistencia-diaria` a las 3 AM; 7 roles `svc_*`/`app_cron`
  con grants de mínimo privilegio; cascadas en `SECURITY DEFINER`.
- ✅ **Round-trip ORM**: inserción empresa→área→trabajador→puerta→escaneo; `id_escaneo`
  llega como `UUID` v7 (server_default), defaults de trabajador OK, enums como `str` OK.

---

## 3. Cosas a recordar (gotchas)
- `init.sql` (+ `roles_microservicio.sql`) **solo corren con volumen vacío**. Reaplicar en dev: `docker compose down -v && up`.
- `roles_microservicio.sql` trae **contraseñas placeholder** (`CAMBIAR_*`) — cambiarlas antes de prod.
- Reasignar el job pg_cron a `app_cron` (`UPDATE cron.job SET username='app_cron' WHERE jobname='consolidar-asistencia-diaria';`).
- El backend alineado **solo funciona contra el `init.sql` NUEVO** (volumen fresco), **no** contra la BD vieja de producción.

---

## 4. Pendiente
- [x] Validar `init.sql` + roles end-to-end contra Postgres real — **hecho** (ver §2).
- [x] **Extracción real de los 6 dominios** a servicios independientes — **hecho** (ver §1.E).

**Lo que sigue:**
1. ~~Prueba en caliente del stack + gateway + auth~~ — **HECHO** (10 contenedores arriba; ver §1.F
   "PROBADO EN VIVO"). Falta solo **smoke del flujo FACIAL** end-to-end: enrolar un rostro
   (`POST /trabajadores` con foto → workers → recognition) y un escaneo de acceso
   (`/scanner` → recognition + media), con un `.env` real y el modelo ya cargado en recognition.
2. **Crear/asignar `svc_access`** al backend (hoy corre con rol amplio); está en `roles_microservicio.sql`.
3. **Operativos antes de prod**: cambiar contraseñas `CAMBIAR_*` (incluido `GATEWAY_INTERNAL_TOKEN`,
   que es UNA variable en `.env` para Traefik + los 4 servicios); reasignar el job pg_cron a `app_cron`;
   generar `JWT_SECRET` (ya **solo en identity**) y los `*_INTERNAL_TOKEN`;
   **gateway**: al tener dominio, activar TLS Let's Encrypt en `traefik/traefik.yml` (+ `Host(...)` en las reglas).
4. **DB-per-service** (fase final): convertir los facades EN PROCESO en clientes HTTP
   (`Tenancy_Service` en backend y workers → API de tenancy; recognition → API de embeddings de workers),
   separar esquemas/BD por dominio y definir el bus de eventos (recognition→access, cascadas).
5. **Migración de datos** producción → esquema nuevo (`serial → UUID`, `id_empresa`, enums) — documento aparte;
   conservar `db_pruebas.sql` como referencia. (Datos actuales son ficticios → no urge.)

> Detalle completo en `PLAN_MICROSERVICIOS.md` (§4 fases, §6 contratos, §7 retos, §9 orden, §10 checklist con el estado de cada extracción).
