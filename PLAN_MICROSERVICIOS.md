# Plan de separación en microservicios — FB_ESCANER

> Hoja de ruta para descomponer el backend monolítico (FastAPI) en microservicios
> por dominio, con **estrategia strangler-fig** (extraer incremental) y una fase
> intermedia de **BD compartida + un rol de PostgreSQL por servicio**.
>
> Acompaña a `src/docker/init.sql` (esquema) y `src/docker/roles_microservicio.sql`
> (roles y permisos). Orden de aplicación en una BD nueva:
> `init.sql` → `roles_microservicio.sql`.

---

## 1. Principios

1. **No “big bang”.** El monolito sigue vivo; cada servicio se extrae cuando su
   dominio está estable. Nada se reescribe de cero.
2. **Primero los roles, después las bases.** Introducir un rol por servicio en la
   **misma BD** da el 80% del beneficio de aislamiento y prepara el split físico.
   Separar BDs es la última fase, dominio por dominio.
3. **El tenant (`id_empresa`) es transversal.** Ya está denormalizado en las tablas
   calientes; además viajará en el **JWT** (empresa + scopes) para que cada servicio
   autorice sin llamar a `identity`.
4. **Mínimo privilegio.** Cada rol toca solo sus tablas; los accesos cruzados son
   explícitos y se recortan al pasar de SQL directo a API/eventos.

---

## 2. Mapa de servicios

| Servicio | Responsabilidad | Tablas propias | Extensiones |
|---|---|---|---|
| **identity** | Login, JWT, usuarios, roles, scopes, auditoría, config | `usuarios`, `roles`, `historial_auditoria`, `parametros_sistema` | — |
| **tenancy** | Estructura física: empresas, áreas, puertas, dispositivos | `empresas`, `area_trabajo`, `puertas_acceso`, `dispositivos` | PostGIS (polígonos/puntos) |
| **workers** (RRHH) | Trabajadores + biometría (enrolamiento) | `trabajadores`, `embeddings` | pgvector |
| **recognition** | Motor facial: detección, liveness, anti-spoof, match. **Sin estado.** | — (modelos ONNX/InsightFace) | pgvector (lectura) |
| **access** | Eventos: escaneos, asistencia, incidencias, intentos, accesos internos, geofencing | `escaneos`, `asistencia`, `incidencias`, `intentos_acceso`, `accesos_internos` | PostGIS, pg_cron |
| **reports** | Lectura agregada + export CSV/XLSX | — (solo lee / réplica) | — |
| **media** | Almacenamiento y servido protegido de fotos | — (disco / objeto S3-like) | — |

---

## 3. Propiedad de datos y dependencias cruzadas

En la **fase de BD compartida**, hay lecturas/escrituras que cruzan dominios vía
SQL. Esto es la “deuda” que el strangler-fig va pagando: cada flecha cruzada es un
candidato a convertirse en llamada API/evento (o caché) al separar bases.

**Lecturas cruzadas (SELECT):**

| Servicio | Lee de | Para qué |
|---|---|---|
| workers | tenancy (`area_trabajo`, `empresas`) | validar área y derivar `id_empresa` del trabajador |
| recognition | workers (`embeddings`, `trabajadores`), tenancy (`puertas_acceso`, `area_trabajo`, `empresas`) | match facial acotado a la empresa de la puerta |
| access | workers (`trabajadores`), tenancy (`puertas_acceso`, `area_trabajo`, `empresas`) | `validar_escaneos_lote` y `evaluar_acceso_interno` (permiso, tipo de puerta, geocerca) |
| reports | todo | exportes |
| todos | identity (`parametros_sistema`) | config compartida (solo lectura) |

**Escrituras cruzadas (vía trigger de cascada de estado):**

| Disparador | Escribe en | Solución |
|---|---|---|
| `tenancy` desactiva empresa | `usuarios` (identity), `area_trabajo`/`puertas_acceso` (tenancy) | `SECURITY DEFINER` (fase BD compartida) → **evento** “empresa desactivada” (fase split) |
| `tenancy` desactiva área | `trabajadores` (workers), `dispositivos`/`puertas_acceso` (tenancy) | igual |
| `workers` desactiva trabajador | `embeddings` (workers) | sin problema (mismo dominio) |

> En `roles_microservicio.sql` las funciones de cascada se vuelven `SECURITY
> DEFINER` para no otorgarle a `tenancy` escritura sobre `usuarios`/`trabajadores`.

---

## 4. Estrategia de datos por fase

| Fase | Topología | Acción |
|---|---|---|
| **0 — Hoy** | Monolito, 1 BD | Aplicar `roles_microservicio.sql`: el monolito puede seguir con un rol amplio, pero ya creas los roles por dominio y empiezas a conectar cada flujo con el suyo. |
| **1 — Servicios, BD compartida** | N servicios, 1 BD | Cada servicio se despliega aparte y se conecta con SU rol. Los accesos cruzados siguen por SQL (GRANTs de §3). Aquí se introducen los **contratos** (§6). |
| **2 — BD por dominio** | N servicios, N BD | Se separa la BD de un dominio estable. Los SELECT cruzados se reemplazan por API/eventos o réplicas. Las FKs físicas pasan a **referencias lógicas**. |

**Qué NO separar junto:** `workers` y `recognition` dependen de **pgvector**; manténlos
en la(s) BD con esa extensión. `access` depende de **PostGIS + pg_cron**. No mezcles
estos con servicios que no los usan.

---

## 5. Autenticación entre servicios

- **identity emite el JWT** con `sub` (id_usuario), **`empresa`** y **`scopes`** en los claims.
- El resto de servicios **valida el token localmente** (firma compartida HS256 o,
  mejor a futuro, clave pública RS256) → **no llaman a identity en cada request**.
- El scope se sigue derivando de ruta+método como hoy; cada servicio solo conoce
  los scopes de SUS recursos.
- El **kiosko** conserva token sin expiración (rol `kiosko`).

Esto resuelve el reto “multi-tenant transversal”: la empresa efectiva sale del token,
no del request, en cualquier servicio.

---

## 6. Contratos entre servicios

| De → A | Tipo | Contenido |
|---|---|---|
| recognition → access | Evento (offline/batch) o REST (online) | “escaneo reconocido”: trabajador, puerta, GPS, confianza, `creado_en_cliente`. access inserta el escaneo y llama `validar_escaneos_lote`. |
| access → tenancy | REST / caché | polígonos de área/empresa y `tipo_puerta` para la geocerca. La APK ya pre-calcula *point-in-polygon* (CONTEXTO_CAMBIOS §3.6). |
| recognition/access → workers | REST / réplica | embeddings y `id_empresa`/`permiso_escaneo` del trabajador. |
| access/incidencias → media | REST | guardar/servir foto (URL firmada o gateway que reinyecta auth). |
| todos → identity | Sin llamada | validan el JWT con la clave compartida. |
| reports → (todos) | Réplica / vistas materializadas | lectura agregada de solo lectura. |

**Sincronización offline (microservicio de ingesta):** tras subir cada lote de
escaneos, llama `validar_escaneos_lote(:desde)` y luego `consolidar_asistencia_dia(<días>)`
para materializar entrada/salida del/los día(s) del lote. En online, el backend ya
invoca ambas al vuelo tras cada escaneo (implementado en `scanner_service`).

---

## 7. Retos específicos y cómo se resuelven

1. **Multi-tenant transversal** → `id_empresa` denormalizado (hecho) + empresa en el JWT.
2. **Geofencing en función de BD** (`validar_escaneos_lote`) y el viejo `8080` → ya
   reemplazado por `tipo_puerta` (campo/administrativa/mixta). Al separar `access` de
   `tenancy`, mover el cálculo a la app de `access` (consume polígonos de tenancy o
   los cachea); la APK ya valida en cliente.
3. **Cascada de estado cruza dominios** → `SECURITY DEFINER` ahora; **eventos** al
   separar bases (“empresa/área desactivada” → cada servicio apaga lo suyo).
4. **pgvector atado a Postgres** → workers/recognition viven con esa extensión; no se
   mezclan con servicios que no la usan.
5. **FKs físicas → lógicas** al separar BDs → define la **fuente de verdad** de cada
   id y valida por evento/llamada (p. ej. `escaneo.id_trabajador` lo valida workers).
6. **Dos criterios de tenant**: `intentos_acceso` se scopea por la empresa de la
   **puerta**; `incidencias` por la empresa del **trabajador**. Respetarlo en `access`.
7. **Fotos protegidas** → `media` con URLs firmadas o un gateway que valide auth+scope+empresa.
8. **Asistencia entrada+salida (RESUELTO):** `asistencia` se **deriva** de `escaneos`
   con `consolidar_asistencia_dia(p_dias_atras, p_id_trabajador, p_incluir_salida)`,
   idempotente. Se llama en vivo tras cada escaneo (entrada del día), tras cada lote
   offline, y en el cierre nocturno (cron **3 AM**, consolida *ayer* → captura salidas
   posteriores a las 23:30). `escaneos` sigue siendo la fuente de verdad.

---

## 8. Roles de BD por microservicio

Definidos en `src/docker/roles_microservicio.sql` (derivados de este esquema):

| Rol | Privilegios |
|---|---|
| `app_ddl` / dueño | dueño de tablas + migraciones (NO lo usan las apps). Hoy puede ser el superusuario que corre `init.sql`. |
| `svc_identity` | DML en usuarios/roles/auditoría/parámetros |
| `svc_tenancy` | DML en empresas/áreas/puertas/dispositivos |
| `svc_workers` | DML en trabajadores/embeddings + SELECT tenancy |
| `svc_recognition` | **SELECT** en embeddings/trabajadores/puertas/áreas/empresas |
| `svc_access` | DML en escaneos/asistencia/incidencias/intentos/accesos + SELECT workers/tenancy + EXECUTE de las funciones de validación |
| `svc_reports` | **SELECT** en todo (mejor contra réplica) |
| `app_cron` | corre `consolidar_asistencia_dia()` (cierre diario 3 AM) |

Decisiones clave del script: **dueño (DDL) separado del runtime (DML)** para que una
app comprometida no pueda `DROP`/`ALTER`; **reports de solo lectura**; **secuencias**
otorgadas solo a tablas `SERIAL` (las UUID no las necesitan); **EXECUTE explícito** de
las funciones custom; cascadas en `SECURITY DEFINER`.

---

## 9. Orden de extracción recomendado

| # | Servicio | Por qué en este orden | “Listo para separar BD” cuando… |
|---|---|---|---|
| 1 | **identity** | Lo usan todos; primero meter empresa+scopes al JWT | el resto valida token sin llamarlo |
| 2 | **media** | Aislado, sin lógica de negocio | las fotos se sirven con URL firmada/gateway |
| 3 | **recognition** | Sin estado, gran ganancia al escalar aparte | solo consume embeddings/polígonos por API; no escribe BD |
| 4 | **workers** + **tenancy** | Dueños de los datos maestros | sus lecturas cruzadas salen por API/eventos |
| 5 | **access** | El más acoplado (trigger/geofencing/job) | geocerca movida a app + asistencia “entrada” resuelta + cascada por eventos |
| 6 | **reports** | Solo lectura | lee de réplicas/vistas materializadas |

---

## 10. Próximos pasos

- [ ] Aplicar `roles_microservicio.sql` en dev y conectar el monolito (o cada flujo) con su rol.
- [x] Añadir `empresa` y `scopes` a los claims del JWT (`core/security` + `core/auth.token_para_usuario`).
- [x] Aislar el acoplamiento a disco de fotos en `Media_Service` (scanner/incidencias/intentos delegan ahí) — costura para extraer `media`. Falta: URLs firmadas / object storage.
- [x] Separar el motor de reconocimiento (`Recognition_Service`, sin estado) de la orquestación de acceso (`scanner_service`) — costura para extraer `recognition`. Falta: que consuma embeddings por API/réplica (no por SQL directo) y reciba/publique eventos en vez de devolver `ScanResponse`.
- [x] Decoupling workers↔tenancy: facade `Tenancy_Service` (lecturas que otros dominios necesitan de tenancy). Workers consume el facade para validar área/derivar empresa; `Embedding_Service` ya no toca tenancy (usa `trabajadores.id_empresa` denormalizado). Falta: el facade pasa a cliente HTTP al separar BD; tenancy expondrá también puerta/dispositivo para access (#5).
- [x] Cerrar el seam access→tenancy del scanner: lee puerta/dispositivo (empresa, existencia, ubicación) por `Tenancy_Service`, ya no por los modelos de tenancy. Falta para extraer `access`: geocerca en app (point-in-polygon con polígonos de tenancy en vez de `ST_Covers` en la BD), cascada por eventos, y el enriquecimiento de nombres de `Asistencia` (hoy `joinedload` a tenancy/puerta).
- [x] Reports: los filtros por empresa usan el `id_empresa` denormalizado (asistencia/incidencias/trabajadores), quitando joins a tenancy innecesarios. `reports` sigue siendo agregador **read-only**; su extracción real = leer de **réplicas/vistas materializadas** (decisión de infra, no un seam de código).

### Extracción real — en progreso
- [x] **identity (1er microservicio extraído):** FastAPI independiente en `src/app/identity/` (imagen ligera, sin visión/IA). Es el único que **emite JWT** y posee login + `/usuarios` + `/roles`; se conecta como **`svc_identity`** (mínimo privilegio). El monolito quitó esos routers y ahora **autoriza stateless** desde los claims del JWT (`core/auth.Principal`). Compose (servicio `identity` en 8001) y Nginx (`/usuarios`,`/roles` → 8001) listos. **Verificado end-to-end** contra la BD viva: identity emite el token y el monolito lo valida sin tocar la BD. Falta para DB-per-service: BD propia de identity + `usuarios.empresa` como referencia lógica (validada por evento/llamada a tenancy).
- [x] **media (2º microservicio extraído):** `src/app/media/` — servicio **mínimo (sin BD)** dueño del volumen `media_data`. Expone una API interna `PUT/GET /archivos/{sub}/{nombre}` con **token compartido** (no se expone en Nginx; solo red interna). El backend ya **no toca el disco**: `Media_Service` es un **cliente HTTP** (`guardar_bytes`=PUT, `obtener_bytes`=GET); los endpoints `/incidencias/{id}/foto` e `/intentos/{id}/foto` siguen sirviendo JPEG tras auth+empresa (**sin cambio para el front** — patrón gateway/proxy §7.6). **Verificado**: round-trip HTTP (guardar+recuperar), 404→None y token inválido→401. Falta: object storage (S3/MinIO) y/o URLs firmadas como optimización.
- [x] **recognition (3er microservicio extraído):** `src/app/recognition/` — **motor facial compute-heavy** (InsightFace + anti-spoof + match pgvector). Conecta como **`svc_recognition`** (solo lectura de embeddings/trabajadores). API interna **coarse** con token: `/reconocer`, `/reconocer-liveness`, `/extraer`, `/identificar` → devuelve estado + match/candidato + el **recorte de cara en base64**. El backend pasó a **cliente HTTP** (`Recognition_Service`), borró el motor local y `antispoof_service`, y **soltó todo el stack de visión** (insightface/cv2/onnx) → imagen del backend mucho más liviana y arranque rápido. Enrolamiento (Trabajadores/Embedding) y scanner llaman a recognition; se quitaron los endpoints de **cámara del servidor** (no hay cámara en contenedores). Compose: servicio `recognition` pesado, **sin puertos** (réplicas para escalar). **Verificado**: backend libre de visión, compila/importa, compose válido (5 servicios), `svc_recognition` lee embeddings pero **no** usuarios. Pendiente: probar el flujo facial completo con `docker compose up --build` (descarga/carga el modelo). Falta para DB-per-service: que consuma embeddings por API de workers en vez de SQL directo.
- [x] **tenancy (4º — parte 1 de "workers+tenancy"):** `src/app/tenancy/` — CRUD de **empresas/áreas/puertas/dispositivos**, conecta como **`svc_tenancy`**. Modelos recortados (sin relaciones a workers/access). El backend dejó de servir esos endpoints (Nginx → 8002) pero **mantiene su read-facade `Tenancy_Service` EN PROCESO** (lee las tablas compartidas con sus grants — el facade→cliente HTTP se difiere al split de BD) y conserva los modelos (para el enriquecimiento de `Asistencia`). **Verificado**: tenancy compila/importa/mappers, `svc_tenancy` lee empresas pero **no** usuarios; backend OK; compose **6 servicios**. Falta la **parte 2: workers** (trabajadores + embeddings).
- [x] **workers (4º — parte 2):** `src/app/workers/` — CRUD de **trabajadores + embeddings**, conecta como **`svc_workers`**. Llama a **recognition** (cliente HTTP) para enrolar (`/extraer`) y mantiene su read-facade `Tenancy_Service` en proceso (valida el área con el grant SELECT sobre `area_trabajo`). Modelos recortados (Trabajador solo con su relación a Embedding; `AreaTrabajo` mínimo para el facade). El backend dejó de servir `/trabajadores` `/embeddings` (Nginx → 8003), conserva los modelos Trabajador/Embedding (para FKs + enriquecimiento de Asistencia). **Verificado**: workers compila/importa/mappers, `svc_workers` lee trabajadores/area_trabajo pero **no** usuarios; backend OK; **compose 7 servicios**. → El "backend" quedó reducido a **access + reports**.
- [x] **reports (6º):** `src/app/reports/` — generación/exportación de reportes (asistencias, incidencias, retardos, faltas, fuera-de-área, intentos, trabajadores) en CSV/XLSX. **SOLO LECTURA**: conecta como **`svc_reports`** (SELECT a todo; idealmente a una réplica). Truco clave: **modelos mínimos SIN relaciones** (solo las columnas que consulta) → `configure_mappers` trivial, sin arrastrar el grafo de relaciones cross-domain. Imagen liviana (openpyxl; sin visión/geo). El backend dejó de servir `/reportes` (Nginx → 8004). **Verificado**: reports compila/importa/mappers, `svc_reports` lee asistencia/incidencias/intentos/trabajadores/áreas/empresas; backend OK; **compose 8 servicios**.

### ✅ Extracción COMPLETA — el "backend" quedó como puro **access**

| Servicio    | Puerto host    | Rol DB           | Sirve                                                        |
|-------------|----------------|------------------|-------------------------------------------------------------|
| identity    | 8001           | svc_identity     | `/usuarios` `/roles` (+ login/JWT)                          |
| tenancy     | 8002           | svc_tenancy      | `/empresas` `/areas` `/puertas` `/dispositivos`            |
| workers     | 8003           | svc_workers      | `/trabajadores` `/embeddings`                              |
| reports     | 8004           | svc_reports      | `/reportes/*` (solo lectura)                               |
| media       | interno        | — (sin BD)       | fotos protegidas (API interna con token)                   |
| recognition | interno        | svc_recognition  | motor facial (API interna con token; réplicas para escalar)|
| **backend** | 8000 (access)  | (rol a definir)  | `/asistencias` `/escaneos` `/incidencias` `/intentos` `/scanner` |

**API Gateway:** **Traefik** (servicio `traefik` en compose) es el único punto de entrada
(80/443). Enruta por **labels** (`exposedByDefault=false`; backend = catch-all `/`, el resto
por prefijo; `media`/`recognition` con `enable=false`), centraliza `rate-limit`+`secure-headers` y la **validación de JWT** (ForwardAuth → identity
`/validate`, **activo**: autentica una vez en el borde y los servicios solo autorizan por scope
leyendo headers `X-*`; el `JWT_SECRET` quedó solo en identity). Deja listo (comentado) TLS
Let's Encrypt. Los servicios **ya no publican puertos al host**; agregar uno nuevo es solo
ponerle sus labels. Config en `src/docker/traefik/{traefik.yml,dynamic.yml}`; reemplaza al
Nginx del host (`nginx/fe-scanner.conf`, ahora solo referencia). **Nota Docker Engine 29+:**
Traefik no puede hablar directo con el socket (el Engine rechaza su versión de API vieja con
400), así que se interpone un mini-proxy nginx (`dockerproxy`, `traefik/dockerproxy.conf`) que
reescribe `/vX.YZ/`→`/v1.44/`; Traefik usa `endpoint: tcp://dockerproxy:2375`. **Stack probado
en vivo** (10 contenedores): routing, ForwardAuth/JWT, 401 sin token y 200 con token válido.

**Costuras que siguen EN PROCESO (a convertir en clientes HTTP al separar la BD por servicio):**
- `Tenancy_Service` (facade de lectura de áreas/puertas/empresas) en **backend/access** y en **workers** → cliente HTTP de tenancy.
- `Recognition_Service` y `Media_Service` ya son clientes HTTP (patrón a replicar).
- `recognition` lee embeddings por SQL directo (svc_recognition) → consumir API de workers.
- El **backend/access** aún corre con un rol amplio; falta crear/asignar **`svc_access`** (de `roles_microservicio.sql`) en su `.env`/compose.

**Pendientes operativos antes de prod:** cambiar todas las contraseñas `CAMBIAR_*`; reasignar el job de `pg_cron` a `app_cron`; generar `JWT_SECRET` y los `*_INTERNAL_TOKEN`; probar el flujo facial completo con `docker compose up --build` (recognition descarga/carga el modelo).
- [ ] Decidir transporte de eventos (cola/broker) para recognition→access y cascadas.
- [x] Cerrar el gap de asistencia “entrada” → `consolidar_asistencia_dia` (vivo + offline + cron 3 AM).
- [ ] Definir el contrato de sincronización offline y el descargador por área del escáner.
- [ ] Plan de migración de datos de producción (serial→UUID) — documento aparte.
