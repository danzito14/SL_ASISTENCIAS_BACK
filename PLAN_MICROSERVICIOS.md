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
escaneos, llama `SELECT * FROM validar_escaneos_lote(:desde);`. En online, el backend
ya lo invoca al vuelo tras cada escaneo (implementado en `scanner_service`).

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
8. **Pendiente del esquema (no del código):** `validar_escaneos_lote` no materializa
   la asistencia de **“entrada”** (solo el job nocturno crea la “salida”). Resolver
   esto **antes/durante** la extracción de `access` (que sea la función o el servicio
   quien cree la entrada).

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
| `app_cron` | corre `procesar_salidas_dia()` (job nocturno) |

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
- [ ] Añadir `empresa` y `scopes` a los claims del JWT en `identity` (core/security).
- [ ] Decidir transporte de eventos (cola/broker) para recognition→access y cascadas.
- [ ] Cerrar el gap de asistencia “entrada” en el esquema/función.
- [ ] Definir el contrato de sincronización offline y el descargador por área del escáner.
- [ ] Plan de migración de datos de producción (serial→UUID) — documento aparte.
