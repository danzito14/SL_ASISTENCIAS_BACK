# FB_ESCANER — Contexto del proyecto

> Documento de handoff. Resume arquitectura, modelo de datos, lógica de dominio,
> endpoints, despliegue y decisiones clave del backend monolítico actual, además de
> una **propuesta de descomposición en microservicios**. Pensado como base para esa
> migración.

---

## 1. ¿Qué es?

Sistema de **control de acceso y asistencia por reconocimiento facial**, multi-empresa
(multi-tenant). Un dispositivo/kiosko escanea el rostro en una puerta, el backend lo
reconoce contra los embeddings de esa empresa, valida que sea una persona viva (liveness)
y no un ataque (anti-spoofing), y registra el acceso. La asistencia se valida por
**geolocalización** (que el escaneo caiga dentro del polígono del área/empresa).

- **Frontend:** Angular (repo aparte). Consume la API bajo `/api` vía Nginx.
- **Backend:** FastAPI (este repo, `pruebas/app/back_py`).
- **Idioma del dominio:** español (nombres de tablas, campos, roles).
- **Zona horaria del sistema:** `America/Mazatlan` (importante, ver §10).

---

## 2. Stack técnico

| Capa | Tecnología |
|------|-----------|
| API | FastAPI 0.115 + Uvicorn/Gunicorn |
| ORM | SQLAlchemy 2.0 |
| BD | PostgreSQL 17 + **pgvector** (embeddings) + **PostGIS** (geografía) + **pg_cron** |
| Reconocimiento facial | InsightFace `buffalo_l` (ArcFace, embeddings 512-dim, CPU) |
| Anti-spoofing | Silent-Face / MiniFASNet vía ONNX Runtime |
| Imágenes | OpenCV (`opencv-python`) |
| Auth | JWT (PyJWT) + scopes por rol |
| Reportes | `openpyxl` (XLSX) + `csv` nativo |
| Contenedores | Docker + docker-compose; Nginx (host) como reverse proxy + HTTPS |

---

## 3. Estructura del repo

```
pruebas/
  app/
    back_py/                 # BACKEND (FastAPI)
      main.py                # app, CORS, montaje de routers, /health
      requirements.txt
      Dockerfile             # imagen del backend
      .dockerignore
      models/antispoof/      # modelo ONNX anti-spoof (versionado)
      src/
        core/
          config.py          # Settings (pydantic-settings) — todas las env vars
          pgdb.py            # engine, Base, get_db
          auth.py            # guard_scopes, resolver_empresa_scope, exigir_empresa...
          security.py        # hash/verify password, create/decode JWT
          scopes.py          # lógica de comodines de scopes
        models/              # SQLAlchemy (uno por agregado)
        schemas/             # Pydantic (request/response)
        services/            # lógica de negocio (un *_Service por dominio)
        routers/             # endpoints (un *_Router por dominio)
  docker/
    docker-compose.yml       # DEV (postgres local)
    docker-compose.prod.yml  # PROD (backend + postgres; Nginx en el host)
    Dockerfile               # imagen de postgres (pgvector + postgis + pg_cron)
    init.sql                 # esquema base (ANTIGUO — ver §11)
    schema_seed.sql          # esquema canónico regenerado (estructura, sin datos)
    seed_roles.sql           # semilla de roles (corre solo en init de volumen vacío)
    migracion_empresa_intentos.sql   # migración: empresa + intentos_acceso
    limpiar_datos_prueba.sql # vacía datos de prueba (deja roles/admin/empresa 99)
    nginx/                   # config de Nginx (reverse proxy + HTTPS)
  triggers.sql               # trigger de validación de asistencia (geofencing)
  ST_Registrar_salida.sql    # función de cierre de día (registra salidas)
```

**Patrón por capas:** `router` (HTTP + auth) → `service` (negocio) → `model` (datos).
Los routers son delgados; los services tienen la lógica; los schemas validan I/O.

---

## 4. Modelo de datos

### Jerarquía multi-tenant
```
Empresa (POLYGON geofence, zona_horaria)
  └─ AreaTrabajo (POLYGON, id_empresa, hora_entrada)
        ├─ Trabajador (id_area)  ── 1:1 ──  Embedding (vector 512, pgvector)
        ├─ Dispositivo (id_area, POINT)        # hardware del escáner
        └─ PuertaAcceso (id_area, id_empresa, POINT, id_dispositivo)
```

- **Trabajador NO tiene `id_empresa` directo** → se deriva vía `Trabajador.id_area → AreaTrabajo.id_empresa`. Este join aparece en todo el código de scoping.
- **Embedding** es 1:1 con Trabajador (`id_trabajador` UNIQUE). Vector `vector(512)` de ArcFace, normalizado L2. Búsqueda por similitud coseno con pgvector (`<=>`).

### Eventos / registros
- **Escaneo** — bitácora cruda de cada escaneo del lector (`id_trabajador`, `id_puerta`, `id_dispositivo`, `tipo_registro`, `fecha_hora`, `confianza_biometrica`, `estado_registro`, `ubicacion`).
- **Asistencia** — entrada/salida validada (la genera el trigger desde el escaneo). Misma forma que Escaneo.
- **Incidencia** — `id_trabajador` (NOT NULL), `tipo_incidencia`, `fecha`, `ruta_foto`, `id_escaneo_ref`. Tipos: `salida_sin_registro`, `entrada_sin_registro`, `falta`, `retardo`, `fuera_de_area`, `acceso_otra_empresa`.
- **IntentoAcceso** — intentos RECHAZADOS en una puerta. `id_puerta`, `id_empresa` (de la puerta), `tipo` (`spoofing`|`desconocido`|`otra_empresa`), `id_trabajador` (NULL salvo otra_empresa), `similitud`, `ruta_foto`, `ubicacion`. **No requiere trabajador** (a diferencia de Incidencia).

### Acceso / seguridad
- **Usuario** — `nombre_usuario` (único), `contrasena` (hash PBKDF2), `id_rol`, `estado`, **`empresa`** (FK a empresas; `99` = super-admin).
- **Rol** — `nombre_rol`, `permisos` JSONB `{"scopes": [...]}`.
- **HistorialAuditoria**, **ParametroSistema** — auxiliares.

---

## 5. Conceptos de dominio clave

### 5.1 Encapsulación por empresa (multi-tenant)
Cada usuario pertenece a una empresa y **solo ve/opera datos de su empresa**. El
**super-admin** es el usuario con `empresa = 99` (`EMPRESA_ADMIN`), que accede a todo.

Implementado en `core/auth.py`:
- `resolver_empresa_scope` (dependencia): devuelve la empresa efectiva — `None` si es admin (sin filtro = todas), o la empresa del usuario si es normal (ignora lo que mande el front). Se usa en los **listados**.
- `exigir_empresa(usuario, id_empresa_objetivo)`: lanza **403** si un usuario normal toca otra empresa. Se usa en GET/PUT/DELETE por id y en CREATE (validando el destino).
- Helpers `empresa_de_*` en los services derivan la empresa de cada entidad (área directa, o vía trabajador/área).

**El scope sale del usuario autenticado, no del front** → no se puede saltar manipulando el request.

### 5.2 Roles + scopes (permisos)
El guard global deriva el scope requerido de la **ruta + método**:
`recurso = primer segmento de la ruta`, `acción = read|write|delete` (GET / POST·PUT·PATCH / DELETE). El scanner exige `scanner:use`.

Scopes con comodines: `"*"`, `"recurso:*"`, `"*:accion"`, `"recurso:accion"`.

Roles seed (`seed_roles.sql`):
- Globales: **`consultor`** (`*:read`), **`operador`** (`*:read`,`*:write`,`scanner:use`), **`administrador`** (`*`), **`kiosko`** (`scanner:use`).
- Granulares: `usuarios_consulta/_gestion/_admin`, `roles_*`, `rrhh`, `supervisor`, `configuracion`, `reportes`.
- El rol del **kiosko** tiene token que **no expira** (`ROLES_TOKEN_SIN_EXPIRACION=kiosko`).

### 5.3 Flujo del scanner (reconocimiento)
Endpoints `POST /scanner/acceso/foto` (1 imagen) y `/scanner/acceso/liveness` (3-5 imágenes).
Pipeline (en `scanner_service.py`):
1. Validar puerta/dispositivo.
2. Detectar rostro + extraer embedding (InsightFace).
3. **Liveness** (solo multi-frame): misma persona entre frames + movimiento de landmarks (rechaza foto estática).
4. **Anti-spoofing** dedicado (MiniFASNet): rechaza foto/pantalla/papel.
5. **Reconocer acotado a la empresa de la puerta** (`buscar_en_bd` con `id_empresa` derivado de la puerta).
6. Si reconoce → registra Escaneo (un trigger genera la Asistencia y valida geocerca).
7. Si NO reconoce/rechaza → registra **IntentoAcceso** (ver 5.6).

Concurrencia: semáforo `asyncio.Semaphore(3)` + `run_in_threadpool` (máx. 3 verificaciones pesadas a la vez, sin bloquear el event loop).

Umbrales (en `scanner_service.py`): `SIMILITUD_UMBRAL=0.5` (match), `UMBRAL_DET_DESCONOCIDO=0.70` (detección clara para registrar desconocido), `DUPLICADO_UMBRAL=0.5`, liveness `MISMA_PERSONA=0.45`/`MOVIMIENTO_MIN=0.004`.

### 5.4 Anti-duplicado de rostro
Al registrar/reemplazar un embedding, se compara contra los existentes **de la misma empresa**; si supera `DUPLICADO_UMBRAL` → **409** (no se permite la misma cara en dos trabajadores de una empresa; sí en empresas distintas).

### 5.5 Incidencias por geolocalización (trigger de BD)
`triggers.sql` → `fn_validar_asistencia_escaneo` (AFTER INSERT en `escaneos`). En el **primer** escaneo del día:
- **`id_puerta = 8080` (CAMPO)** → valida contra el polígono del **área asignada del trabajador**.
- **`id_puerta ≠ 8080` (ADMINISTRATIVO)** → valida contra el polígono de la **empresa** (vía la puerta).

Si el punto cae dentro → Asistencia `exitoso`. Si cae fuera → Asistencia `fuera_de_area` + Incidencia `fuera_de_area` (con foto) + marca el escaneo. ⚠️ **El `8080` es un número mágico**: lógica de negocio acoplada al `id_puerta`.

### 5.6 Intentos de acceso (seguridad de la puerta)
Cuando el scanner rechaza, clasifica (búsqueda global sin filtro de empresa) y guarda foto del rostro en `media/intentos/`:
- **`spoofing`** — el anti-spoof lo rechazó.
- **`otra_empresa`** — match global ≥ 0.5 pero de otra empresa. Genera **intento** (lo ve el admin de la puerta) **+ Incidencia `acceso_otra_empresa`** bajo ese trabajador (lo ve la empresa del trabajador).
- **`desconocido`** — rostro **detectado claro** (`det_score ≥ 0.70`) pero no reconocido. (El filtro es la **calidad de detección**, no la similitud: un extraño real tiene similitud baja.)

### 5.7 Fotos (media)
- Las fotos (incidencias e intentos) se guardan en disco bajo `media/` (`MEDIA_DIR`), nombradas por id.
- Se sirven por **endpoints protegidos** (auth + scope + empresa), NO como estáticos públicos: `GET /incidencias/{id}/foto` y `GET /intentos/{id}/foto` → `FileResponse` JPEG.
- En el front se piden como **blob** con el token (un `<img src>` directo no manda Authorization).
- En prod requiere **volumen Docker** `media_data:/app/media` para persistir.

### 5.8 Vista combinada
`GET /incidencias/combinado` → feed unificado de incidencias + intentos, normalizado (`origen`, `tipo`, `fecha_hora`, `descripcion`, `foto_url`, ...). Cada fila ya trae la `foto_url` del endpoint correcto.

### 5.9 Reportes
`/reportes/*` → descargan **XLSX o CSV** (`?formato=xlsx|csv`), scopeados por empresa:
`asistencias` (filtro `id_trabajador`), `incidencias` (filtro `tipo`, `id_trabajador`),
`retardos`, `faltas`, `fuera-de-area` (atajos por tipo), `intentos`, `trabajadores`.
Scope requerido: `reportes:read`.

---

## 6. Endpoints (por módulo)

| Prefijo | Endpoints |
|---------|-----------|
| `/usuarios` | login, token (OAuth2), CRUD. El login devuelve el usuario con su `empresa`. **No** tiene filtro por empresa (lo gestiona el admin). |
| `/roles` | CRUD |
| `/empresas` | lista (ves la tuya; admin todas), get/put por id; crear/borrar **solo super-admin** |
| `/areas` | CRUD, scope por empresa, búsqueda por `nombre` |
| `/dispositivos` | CRUD, scope por empresa (vía área), búsqueda por `nombre` |
| `/puertas` | CRUD, scope por empresa, búsqueda por `nombre` |
| `/trabajadores` | CRUD + captura de embedding (cámara/foto) + búsqueda `nombre`; antispoof + anti-dup en el registro |
| `/embeddings` | CRUD admin, **borrado total**, reemplazo por foto; lista con `id_empresa` (obligatorio salvo admin) |
| `/escaneos` | CRUD, scope por empresa (vía trabajador) |
| `/asistencias` | lista/get, scope por empresa, búsqueda por nombre del trabajador |
| `/incidencias` | CRUD + `/{id}/foto` + `/combinado`, scope por empresa, búsqueda por nombre |
| `/intentos` | lista/get + `/{id}/foto`, scope por empresa (de la puerta) |
| `/scanner` | `/acceso/foto`, `/acceso/liveness`, `/identificar*` — scope `scanner:use` |
| `/reportes` | asistencias, incidencias, retardos, faltas, fuera-de-area, intentos, trabajadores (XLSX/CSV) |
| `/health` | healthcheck (público) |

Rutas públicas (sin token): `/`, `/health`, `/docs`, `/redoc`, `/openapi.json`, `/usuarios/login`, `/usuarios/token`.

---

## 7. Autenticación

- **Login** (`POST /usuarios/login`) → JWT `access_token`. El `sub` es el `id_usuario`.
- Todas las rutas (salvo públicas) pasan por `guard_scopes` (dependencia global): carga el usuario fresco en cada request, valida el scope del rol, y deja `request.state.usuario`.
- Token: `JWT_EXPIRE_MINUTES` (480 en prod); el rol `kiosko` no expira.

---

## 8. Configuración (env vars — `core/config.py`)

| Var | Descripción |
|-----|-------------|
| `DB_HOST/PORT/USER/PASSWORD/NAME` | PostgreSQL |
| `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES` | JWT |
| `ROLES_TOKEN_SIN_EXPIRACION` | roles cuyo token no expira (`kiosko`) |
| `EMPRESA_ADMIN` | empresa comodín super-admin (`99`) |
| `PRELOAD_FACE_MODEL` | precargar buffalo_l al arrancar |
| `ANTISPOOFING_ACTIVO`, `ANTISPOOF_MODEL_DIR`, `ANTISPOOF_UMBRAL`, `ANTISPOOF_REAL_INDEX`, `ANTISPOOF_DIV255` | anti-spoof (calibrado: `DIV255=false`, `REAL_INDEX=1`, `UMBRAL=0.6`) |
| `MEDIA_DIR`, `MEDIA_URL` | carpeta/URL de fotos (`media` / `/media`) |
| `CORS_ORIGINS` | (definido pero el CORS actual usa un regex de red local; ver §11) |

---

## 9. Despliegue

- **Dev:** `docker-compose.yml` (postgres con `init.sql` montado).
- **Prod:** `docker-compose.prod.yml` — `backend` (gunicorn, 2 workers, escucha `127.0.0.1:8000`) + `postgres`. **Nginx en el host** hace reverse proxy + HTTPS y publica la API bajo `/api`. Dominio: `sl-asistencias.slagricola.cloud`.
- El backend baja el modelo `buffalo_l` (~300 MB) en build (imagen autónoma).
- `init.sql` + `seed_roles.sql` corren **solo con volumen vacío**. Sobre una BD existente, aplicar migraciones con `psql` (ver `migracion_empresa_intentos.sql`).
- Volúmenes: `postgres_data` (BD) y `media_data` (fotos).

Comandos típicos (VPS):
```bash
cd pruebas/docker
sudo docker compose -f docker-compose.prod.yml up -d --build      # recompilar todo
sudo docker compose -f docker-compose.prod.yml exec -T postgres \  # migrar/consultar
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < archivo.sql
```

---

## 10. Decisiones y gotchas importantes

- **Zona horaria.** El sistema trabaja en `America/Mazatlan` (configurado en postgres y pg_cron). Las fechas de incidencias/asistencias se calculan en **local**, NO en UTC. (Bug típico: usar `datetime.now(timezone.utc).date()` mete el registro en "mañana" y se sale del rango de listados por defecto, que usan `date.today()`.)
- **`id_puerta = 8080` mágico.** El trigger de geofencing distingue CAMPO vs ADMINISTRATIVO por este valor. Cualquier rediseño de "Puerta" debe reemplazar este mecanismo.
- **Redundancia de Puerta.** `Empresa`/`Área` son POLYGON; `Dispositivo`/`Puerta` son POINT. Hay ubicación duplicada. La Puerta hoy está infrautilizada (`tipo_acceso`, `requiere_autorizacion` se guardan pero no se usan); su valor real aparece al implementar semánticas de acceso o varios dispositivos por puerta.
- **Incidencia requiere trabajador** (`id_trabajador` NOT NULL) → spoofing/desconocido no caben ahí; por eso existe `intentos_acceso`.
- **Schema drift.** La tabla `empresas` en el VPS tiene `zona_horaria` y `estado` NOT NULL (el modelo `Empresa` sí los incluye). Cuidado al insertar empresas en SQL crudo.
- **CORS.** `main.py` usa `allow_origin_regex` para **red local** (localhost + IPs privadas). En prod el front va **mismo origen** que `/api` (Nginx) → no dispara CORS. Si el front fuera otro origen, hay que añadir el dominio.
- **pgvector sin índice.** Las búsquedas faciales hacen scan exacto (sin índice ANN). Correcto hasta ~decenas de miles de embeddings; a 100k+ conviene un índice HNSW (`vector_cosine_ops`).
- **Pendiente conocido:** agregar 2º modelo al ensemble anti-spoof (`4_0_0_80x80_MiniFASNetV1SE.onnx`) en `models/antispoof/` para más robustez (el servicio promedia todos los `.onnx` de la carpeta).

---

## 11. Propuesta de descomposición en microservicios

El monolito se divide naturalmente por **dominio**. Sugerencia (Strangler-fig: extraer incrementalmente):

| Microservicio | Responsabilidad | Datos propios |
|---------------|-----------------|---------------|
| **identity** (auth) | Login, JWT, usuarios, roles, scopes. Emite el token que el resto valida. | usuarios, roles, historial_auditoria |
| **tenancy / org** | Estructura organizacional e infraestructura física. | empresas, area_trabajo, puertas_acceso, dispositivos |
| **workers (RRHH)** | Trabajadores y su biometría (enrolamiento). | trabajadores, embeddings (pgvector) |
| **recognition** | Motor de reconocimiento facial: detección, liveness, anti-spoof, match. **Stateless y compute-heavy** → escala horizontal independiente. Consume embeddings (de workers) y publica resultados. | (sin estado; modelos ONNX/InsightFace) |
| **access / attendance** | Registro de accesos, asistencias, incidencias, intentos, geofencing. | escaneos, asistencia, incidencias, intentos_acceso |
| **reports** | Lectura agregada + export CSV/XLSX. | (solo lee de los demás / réplicas) |
| **media** | Almacenamiento y servido protegido de fotos. | volumen/objeto (S3-like) |

### Cómo se relacionan
```
[kiosko] → recognition (detecta/valida/match) → access (registra escaneo/asistencia)
                  ↑ embeddings                         ↓ eventos
               workers                          incidencias / intentos (+ media)
identity emite JWT que TODOS validan ; tenancy provee empresas/áreas/puertas/dispositivos
```

### Retos de la migración (a tener muy presentes)
1. **El multi-tenant (`empresa`) es transversal.** Hoy se resuelve con joins (`trabajador→area→empresa`) y `resolver_empresa_scope`. En microservicios cada servicio necesita conocer la empresa del recurso → propaga `id_empresa` en los eventos/tokens, o cada servicio guarda el `id_empresa` desnormalizado. **Recomendado:** incluir `empresa` (y rol/scopes) en el **JWT** para que cada servicio autorice sin llamar a identity.
2. **El geofencing vive en un trigger de BD** (PostGIS) con el `id_puerta=8080` mágico. Al separar `access` de `tenancy`, ese trigger ya no tiene los polígonos a mano → moverlo a lógica de aplicación en `access`, consultando a `tenancy` (o cacheando los polígonos). Reemplazar el `8080` por un flag explícito (ej. tipo de dispositivo/puerta: campo/administrativo).
3. **pgvector** (embeddings) es específico de Postgres. `workers`/`recognition` necesitan esa BD con la extensión; no la mezcles con servicios que no la usan.
4. **Consistencia de FKs entre servicios.** Hoy hay FKs físicas (escaneo→trabajador→área→empresa). Al separar BDs, eso pasa a ser **referencias lógicas** + validación por eventos o llamadas. Decide qué es la fuente de verdad de cada id.
5. **`intentos_acceso` se scopea por la empresa de la PUERTA**, e `incidencias` por la empresa del TRABAJADOR. Dos criterios distintos de tenant → respétalos al diseñar el servicio `access`.
6. **Fotos protegidas:** el endpoint de foto valida auth+scope+empresa. En `media` como servicio, usa URLs firmadas o un gateway que reinyecte la autorización.
7. **Reportes** cruzan varios dominios → o consume vía API (lento) o lee de réplicas/vistas materializadas; considéralo de solo-lectura.

### Orden sugerido de extracción
1. **identity** (lo usan todos; empieza por meter empresa+scopes al JWT).
2. **media** (aislado, fácil, quita acoplamiento de disco).
3. **recognition** (stateless, gran beneficio de escalar aparte).
4. **workers** + **tenancy** (dueños de los datos maestros).
5. **access/attendance** (el más acoplado al trigger/geofencing; déjalo para cuando lo demás esté estable).
6. **reports** al final (solo lectura).

---

## 12. Comandos útiles

```bash
# Local (dev): levantar backend
cd pruebas/app/back_py
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Ver tablas en la BD (docker)
sudo docker compose -f docker-compose.prod.yml exec postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'   # luego \dt, \d tabla

# Migración / limpieza (prod)
... exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < migracion_empresa_intentos.sql
... exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < limpiar_datos_prueba.sql
```
