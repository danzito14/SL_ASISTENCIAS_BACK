# Rediseño de Base de Datos — FE Scanner

> Sistema de control de asistencia biométrico
> Documento de contexto y cambios · Junio 2026

---

## 1. Resumen ejecutivo

Se rediseñó y consolidó el esquema de la base de datos (`init.sql`) para soportar un cambio de escala y alcance del sistema. El proyecto pasó de un prototipo de una sola empresa a un sistema **multi-tenant** (varias empresas en la misma base de datos), pensado para **+20,000 trabajadores**, con un nuevo modo de operación **offline-first** (la app móvil registra sin conexión y sincroniza después) y un módulo nuevo de **control de acceso interno** a zonas restringidas.

Todos los cambios se consolidaron en un único archivo `init.sql` idempotente, reemplazando la estructura anterior que estaba repartida en varios scripts sueltos (`init.sql` + `fks_on_delete_cascade.sql` + `triggers_cascada_estado.sql` + `seed_roles.sql`).

El esquema fue **validado de punta a punta** contra una instancia real de PostgreSQL: carga sin errores y cada pieza de lógica (UUIDv7, validación de escaneos en 3 capas, cascada de estado, control de acceso por zona) se probó con datos reales.

---

## 2. Contexto del sistema

### 2.1 Qué hace el sistema

Es un sistema de **control de asistencia por reconocimiento facial**. Los trabajadores registran su entrada y salida escaneando su rostro en dispositivos colocados en puntos de acceso. El sistema:

- Reconoce al trabajador por su rostro (embeddings vectoriales de 512 dimensiones, búsqueda por similitud con pgvector / HNSW).
- Valida que el registro sea legítimo: que la persona esté **dentro del área geográfica permitida** (validación geoespacial con PostGIS) y que tenga **permiso** de estar ahí.
- Registra asistencias, detecta incidencias (faltas, retardos, accesos fuera de área, etc.) y genera reportes.
- Corre un proceso nocturno que cierra el día: infiere salidas y levanta incidencias para quienes solo marcaron una vez.

### 2.2 Arquitectura general

- **Backend**: API en Python (FastAPI), desplegada en un VPS detrás de Nginx (reverse proxy + HTTPS). El backend solo escucha en `127.0.0.1:8000`; únicamente Nginx lo alcanza.
- **Base de datos**: PostgreSQL 17 con tres extensiones — `pgvector` (embeddings faciales), `postgis` (geolocalización de áreas y puertas) y `pg_cron` (job nocturno).
- **Front**: aplicación web para administración, reportes y gestión.
- **App móvil (APK)**: el escáner. Aquí entra el cambio grande (ver offline-first).

### 2.3 Los cambios de alcance que motivaron el rediseño

Durante la planeación se definieron cuatro cambios mayores respecto al diseño original:

1. **Multi-tenant real**: varias empresas comparten la misma base de datos y las mismas tablas, con aislamiento entre ellas.
2. **Escala a +20,000 trabajadores**: lo que obliga a repensar índices, tipos de datos y crecimiento de tablas.
3. **Offline-first**: la app móvil tendrá su propio backend ligero con SQLite. Podrá hacer el reconocimiento facial **sin conexión** y guardará los registros localmente; un microservicio los subirá al servidor cuando haya internet. El escáner solo descargará de la BD la información que necesita (la de su área).
4. **Control de acceso interno**: además de fichar asistencia, habrá puertas internas que validan permisos y dan acceso a zonas restringidas (sin fichar), eventualmente apoyadas por cámaras de seguridad.

---

## 3. Decisiones de diseño (el "por qué")

Esta sección documenta las decisiones tomadas y el razonamiento, para que queden registradas y se entiendan al mantener el sistema.

### 3.1 UUIDv7 para registros que nacen offline

**Decisión**: las tablas `escaneos`, `asistencia`, `incidencias` y `accesos_internos` usan **UUIDv7** como llave primaria, en lugar del `SERIAL` (entero autoincremental) anterior.

**Por qué**: cuando la app móvil genera registros sin conexión, no puede pedirle un ID al servidor. Con enteros autoincrementales, dos dispositivos offline generarían el mismo ID (`1`, `2`, `3`...) y colisionarían al sincronizar. El UUID lo genera el cliente y es único globalmente sin coordinación.

**Por qué v7 y no v4**: UUIDv7 lleva un **timestamp** (milisegundos Unix) en sus primeros bits, lo que lo hace *ordenable por tiempo* (k-sortable). Esto da:
- **Localidad en el índice**: los inserts caen casi siempre al final del índice B-tree (como un entero secuencial), evitando la fragmentación brutal que causa el UUIDv4 aleatorio. Crítico a escala de +20k.
- **Ordenamiento cronológico** sin columna extra: `ORDER BY id` ≈ orden temporal.
- **Cursor de sincronización** natural: "dame todo lo posterior a este UUID".

**Implementación**: PostgreSQL 17 no trae `uuidv7()` nativo (llega en PG18), así que el `init.sql` incluye una función `gen_uuid_v7()` para los registros que nacen en el servidor. La app móvil genera sus propios UUIDv7. La función se construyó sin depender de extensiones extra (usa `gen_random_uuid()` nativo como fuente de aleatoriedad).

### 3.2 Multi-tenant: aislamiento por empresa

**Decisiones**:
- **`id_empresa` denormalizado** en las tablas calientes (`trabajadores`, `escaneos`, `asistencia`, `incidencias`, `accesos_internos`). Aunque la empresa se puede deducir por joins (trabajador → área → empresa), tenerla directa evita 2-3 joins en cada consulta filtrada por empresa y deja la puerta abierta a Row-Level Security (RLS) en el futuro. Es práctica estándar en multi-tenant a escala.
- **Unicidad por empresa, no global**: `nombre_area` ahora es único por `(id_empresa, nombre_area)` — dos empresas pueden tener un área "Almacén" sin chocar. Lo mismo con la IP de dispositivos: única por `(id_empresa, ip_dispositivo)`, porque empresas en redes separadas pueden repetir IPs.
- **Validación de tenant en los escaneos**: un trabajador no puede fichar en una puerta de otra empresa (salvo permiso `super`). Esto activa el tipo de incidencia `acceso_otra_empresa`, que existía en el diseño pero nunca se usaba.

### 3.3 Reemplazo del número mágico `8080` por tipos de puerta

**Problema del diseño anterior**: la función de validación usaba `IF id_puerta = 8080` como bandera para distinguir si un escaneo era de "campo" o "administrativo". El `8080` no era una puerta real — era una bandera disfrazada de ID. En multi-tenant esto se rompe: cada empresa tiene sus propias puertas con IDs reales, y `8080` no significa lo mismo para todas.

**Decisión**: se agregó la columna `tipo_puerta` (ENUM) a `puertas_acceso`, con tres valores:
- `campo` — puertas en parcelas/campo abierto.
- `administrativa` — puertas en oficinas.
- `mixta` — zonas como el **empaque**, que está físicamente junto a las oficinas pero donde también trabaja gente de campo. Una puerta mixta acepta a todos los perfiles.

La validación pasó de `IF id_puerta = 8080` a `IF tipo_puerta = 'campo'`: legible, multi-tenant, sin números mágicos.

### 3.4 Sistema de permisos de escaneo (rango)

**Decisión**: se agregó la columna `permiso_escaneo` (ENUM) a `trabajadores`, que define **dónde** puede fichar cada quién:

| Permiso | Dónde puede fichar | ¿Otras empresas? |
|---|---|---|
| `campo` | Puertas `campo` (y `mixta`) | No |
| `administrativo` | Puertas `administrativa` (y `mixta`) | No |
| `general` | Cualquier tipo de puerta | No |
| `super` | Cualquier tipo de puerta | **Sí, cualquier empresa** |

Default: `campo` (la mayoría de los trabajadores son de campo).

### 3.5 Validación de escaneos en lote (no en trigger)

**Problema del diseño anterior**: la validación corría en un trigger `AFTER INSERT`, fila por fila, asumiendo que los escaneos llegaban **en tiempo real** y en orden cronológico (su lógica dependía de "¿es el primer escaneo del día?"). Con offline-first esto se rompe: cuando un dispositivo sincroniza tras 8 horas sin conexión, llegan 200 escaneos viejos de golpe y en desorden.

**Decisión**: se eliminó el trigger y se creó la función `validar_escaneos_lote()`, que el microservicio llama **después** de ingerir cada lote de sincronización. Evalúa **3 capas de validación en orden de costo** (de la más barata a la más cara):

1. **Tipo de puerta vs. permiso** (comparación de ENUMs, baratísima) → incidencia `area_incorrecta` si no coinciden (ej. un trabajador de campo en puerta administrativa).
2. **Empresa correcta** (comparación de enteros) → incidencia `acceso_otra_empresa` si el trabajador es de otra empresa y no es `super`.
3. **Geolocalización** (`ST_Covers` con PostGIS, la más cara) → incidencia `fuera_de_area` si la coordenada GPS no cae dentro del polígono permitido.

Un escaneo solo se marca exitoso si pasa las tres. La función es idempotente (solo procesa escaneos aún en estado `exitoso`, no re-evalúa lo ya marcado) y devuelve un conteo de cuántos marcó en cada categoría.

### 3.6 Validación geográfica: cliente vs. servidor

**Decisión**: el reconocimiento facial corre **en la app móvil** (autónomo, offline). La validación geográfica de área también puede pre-calcularse en el cliente:

- La app descarga el polígono de su área y valida localmente con un algoritmo *point-in-polygon* (no necesita PostGIS; es matemática simple que corre en cualquier lenguaje sin librerías pesadas). Manda el escaneo con un flag `dentro_de_area` ya calculado, más las coordenadas crudas.
- El servidor **confía pero verifica**: guarda lo que mandó el cliente y, como sí tiene PostGIS, puede re-auditar con `ST_Covers` sobre las coordenadas crudas. Si el cliente tenía un polígono viejo o el dato fue manipulado, el servidor lo detecta.

**Sobre el GPS**: el sistema **siempre** captura la ubicación en tiempo real al momento del escaneo, sin importar dónde esté la persona (campo, oficina o empaque). La coordenada siempre viaja al backend, así que las 3 capas de validación aplican idéntico para todos. La diferencia entre online y offline es solo *cuándo* se valida (inmediato si hay internet, diferido si se sincroniza después), no *qué* se valida.

### 3.7 La misma BD sirve para online y offline

**Aclaración importante**: el esquema funciona igual para registros que nacen online (oficina con internet) y offline (campo sin conexión). Las columnas de sincronización son **opcionales por diseño**: un registro online simplemente llena menos campos.

- `creado_en_cliente`: hora real del evento en el dispositivo. En offline es clave (la sincronización llega horas después); en online coincide con `fecha_hora`.
- `sincronizado_en`: cuándo llegó al servidor. En online ≈ `fecha_hora`; en offline es cuando se subió el lote.
- `id_dispositivo_origen`: qué dispositivo lo generó (auditoría de sincronización).

No hay tablas duplicadas ni lógica bifurcada: un solo modelo de datos, unos registros con más metadatos de sincronización que otros. Lo único que decide el backend es **cuándo** llamar la validación: inmediato tras cada escaneo online, o al entrar el lote offline.

### 3.8 Control de acceso interno (puertas internas + zonas)

**Contexto**: además de las puertas que fichan asistencia, hay **puertas internas** que no fichan, sino que **validan permiso y dan paso** a una zona restringida (ej. de oficinas al empaque). El registro que generan no es asistencia — es un *log de acceso* (quién pasó a qué zona, permitido/negado). En el empaque, las puertas de administrativos y de empaque son físicamente distintas y están en lugares diferentes.

**Decisiones**:
- Las puertas ahora tienen **dos dimensiones independientes**: `tipo_puerta` (la zona donde está) y `funcion_puerta` (qué hace: `asistencia` o `control_acceso`). Default `asistencia`, así que ninguna puerta existente cambia de comportamiento.
- Las puertas internas (`control_acceso`) tienen `categoria_zona_destino`: a qué categoría de zona dan paso.
- Cada trabajador tiene un `nivel_acceso_interno` (ENUM **genérico**): `oficina`, `empaque` o `mixto`. La regla:

| Nivel del trabajador | Puede entrar a zonas |
|---|---|
| `oficina` | `oficina` (y `mixto`) |
| `empaque` | `empaque` (y `mixto`) |
| `mixto` | ambas (oficina ↔ empaque) |

El caso "trabajador de oficina que pasa al empaque y viceversa" se resuelve dándole nivel `mixto`.

- Se creó la tabla **`accesos_internos`** (separada de `asistencia` para no ensuciar los reportes de fichaje), que registra cada paso por una puerta interna: quién, qué zona, resultado (`permitido`/`negado`), motivo, GPS, dispositivo. Con UUIDv7 y columnas de sincronización por consistencia y futuro offline.
- La función `evaluar_acceso_interno(trabajador, puerta)` decide permitido/negado en tiempo real (el control de acceso físico ocurre en sitio con conexión), respeta el aislamiento por empresa y registra el intento. Una puerta de asistencia rechaza esta función (no es su propósito).

### 3.9 Cámaras de seguridad (en evaluación, no modelado aún)

El papel de las cámaras aún se está definiendo (¿reconocen rostros y fichan, o solo vigilan?). Como van a *apoyar* las puertas internas de control de acceso, su diseño se dejó preparado pero **no modelado**:

- El ENUM `tipo_dispositivo` está listo para agregar el valor cuando se decida: `ALTER TYPE tipo_dispositivo ADD VALUE 'camara_seguridad';` (agregar un valor a un ENUM no recrea tablas ni constraints — una ventaja de haber migrado de CHECK a ENUM).
- Si las cámaras reconocen rostros → son un tipo de dispositivo más, generan escaneos normales.
- Si solo graban → necesitarán una tabla nueva para lo que producen (clips, eventos), porque eso es otro tipo de dato distinto de un escaneo. Hay una nota en `accesos_internos` indicando dónde engancharía el módulo de evidencias.

### 3.10 ENUMs nativos en lugar de CHECK

**Decisión**: los `CHECK (campo IN (...))` del diseño anterior se reemplazaron por **tipos ENUM nativos** de PostgreSQL. Ventajas a escala:
- Más compactos y rápidos en comparaciones masivas.
- Agregar un valor nuevo es `ALTER TYPE ... ADD VALUE` (no requiere recrear el constraint ni la tabla).

### 3.11 Job nocturno corregido (zona horaria por empresa)

**Problema del diseño anterior**: `procesar_salidas_dia()` usaba `CURRENT_DATE` (la fecha del servidor, en `America/Mazatlan`). En multi-tenant con empresas en husos distintos, "el día" se cortaba a la hora equivocada para algunas.

**Decisión**: el job ahora calcula "el día" usando `empresas.zona_horaria` por empresa, y usa `creado_en_cliente` (la hora real del evento) cuando existe, no la hora de llegada al servidor.

---

## 4. Cambios aplicados al esquema (resumen técnico)

### 4.1 Extensiones requeridas
`vector` (pgvector), `postgis`, `pg_cron`. Ya no se requiere `pgcrypto` (la función UUIDv7 usa `gen_random_uuid()` nativo).

### 4.2 Tipos ENUM (18 en total)
Estado: `estado_generico`, `estado_trabajador`, `estado_dispositivo`, `estado_registro`, `estado_incidencia`.
Registro/asistencia: `tipo_registro`, `tipo_incidencia`.
Dispositivos/puertas: `tipo_dispositivo`, `tipo_acceso`, `tipo_puerta`, `funcion_puerta`.
Permisos/zonas: `permiso_escaneo`, `nivel_acceso_interno`, `categoria_zona`, `resultado_acceso`.
Otros: `tipo_embedding`, `tipo_operacion`, `tipo_parametro`.

### 4.3 Tablas (14 en total)
`roles`, `empresas`, `usuarios`, `area_trabajo`, `dispositivos`, `puertas_acceso`, `trabajadores`, `embeddings`, `escaneos`, `asistencia`, `incidencias`, **`accesos_internos`** (nueva), `historial_auditoria`, `parametros_sistema`.

### 4.4 Columnas nuevas destacadas
- `puertas_acceso`: `tipo_puerta`, `funcion_puerta`, `categoria_zona_destino`.
- `trabajadores`: `permiso_escaneo`, `nivel_acceso_interno`, `id_empresa` (denormalizado).
- `escaneos` / `asistencia` / `incidencias`: PK UUIDv7, `id_empresa`, `dentro_de_area`, `creado_en_cliente`, `sincronizado_en`, `id_dispositivo_origen`.
- Todas las entidades hijas: `inactivo_por_cascada` (para la reactivación inteligente).

### 4.5 Funciones
- `gen_uuid_v7()` — genera UUIDv7 en el servidor.
- `set_fecha_actualizacion()` — auto-touch de `fecha_actualizacion`.
- `validar_escaneos_lote(p_desde)` — validación de escaneos en 3 capas, post-sincronización.
- `evaluar_acceso_interno(...)` — decisión de acceso por puerta interna, en tiempo real.
- `procesar_salidas_dia()` — job nocturno de cierre, con zona horaria por empresa.
- Funciones de cascada de estado (empresa, área, trabajador) y protección de empresa 99.

### 4.6 Índices afinados para escala
- Compuestos `(id_trabajador, fecha_hora DESC)` y `(id_empresa, fecha_hora)` en escaneos/asistencia/accesos.
- **BRIN** sobre `fecha_hora` (tablas append-only ordenadas por tiempo → índice de pocos KB).
- Parciales para tableros: `WHERE estado_registro = 'fuera_de_area'`, `WHERE resultado = 'negado'`.
- **HNSW** afinado en embeddings (`m=16, ef_construction=64`) para búsqueda facial.

### 4.7 Cascada de estado (conservada del diseño anterior)
Activación/desactivación en cascada por jerarquía (empresa → áreas/puertas/usuarios; área → trabajadores/dispositivos/puertas; trabajador → embeddings), con **reactivación inteligente**: la columna `inactivo_por_cascada` recuerda quién apagó cada fila, de modo que al reactivar el padre solo revive lo que la cascada apagó (lo desactivado a mano se queda apagado). La **empresa 99** (super-admin) está protegida contra borrado y desactivación.

### 4.8 Roles (seed integrado)
Los 14 roles base ahora viven **dentro de `init.sql`** (antes en `seed_roles.sql` aparte). Incluye una aclaración documentada: los scopes `reportes:read` e `intentos:read` NO son routers REST — son banderas que el **front** lee para mostrar/ocultar secciones (la sección "Reportes" y la de "Intentos", esta última ligada a incidencias).

---

## 5. Decisiones de despliegue

### 5.1 Consolidación en un solo archivo
Toda la estructura (esquema + roles + triggers + FK + funciones + seeds) se unificó en `init.sql`. Los scripts sueltos anteriores (`fks_on_delete_cascade.sql`, `triggers_cascada_estado.sql`, `seed_roles.sql`) quedaron integrados y se pueden retirar.

### 5.2 docker-compose.prod.yml actualizado
- Se quitó la carga separada de `seed_roles.sql` (ya está en el init): **una sola fuente de verdad**.
- Se agregó **tuning de PostgreSQL** para +20k trabajadores: `shared_buffers`, `effective_cache_size`, `maintenance_work_mem` (crítico para construir el índice HNSW), `work_mem`, workers paralelos, `wal_compression`. **Los valores asumen ~4 GB de RAM; ajustar al VPS real.**

### 5.3 Nota operativa importante
`init.sql` solo se ejecuta cuando el volumen de datos está **vacío** (primera inicialización). Para reaplicar cambios en dev/staging: `docker compose down -v && docker compose up` (el `-v` borra el volumen). En producción con datos, los cambios de esquema se aplican con migraciones manuales (`psql`), no recreando el volumen.

---

## 6. Estado y pendientes

### 6.1 Hecho y validado
- Esquema consolidado, idempotente, cargando sin errores contra PostgreSQL real.
- UUIDv7 verificado: versión y variante correctas, 0 duplicados en 10,000 generaciones, ordenamiento temporal confirmado, timestamp decodificable.
- Validación de escaneos en 3 capas: probada con 6 casos (todos los resultados esperados).
- Control de acceso interno por zona: probado con 5 casos (incluido oficina↔empaque vía nivel mixto).
- Cascada de estado con reactivación inteligente: probada.
- Protección de empresa 99: probada.

### 6.2 Pendiente — lado del microservicio / backend (fuera del SQL)
- Tras ingerir cada lote de escaneos, el microservicio debe llamar `SELECT * FROM validar_escaneos_lote();` para disparar la validación de las 3 capas (la validación ya no está en trigger).
- En registros online, puede llamarse inmediatamente con `validar_escaneos_lote(p_desde => <timestamp reciente>)` para validar al vuelo sin reprocesar todo.
- El control de acceso interno llama `evaluar_acceso_interno(...)` en tiempo real al pasar por una puerta interna.
- Definir el contrato de sincronización del microservicio y el descargador de datos por área del escáner.

### 6.3 Pendiente — migración de datos de producción
Los datos actuales de producción están en el **esquema viejo** y se migrarán después. **No será un import directo**: cambió el tipo de PK (serial → UUID en escaneos/asistencia/incidencias), hay columnas nuevas (`id_empresa` denormalizado, `permiso_escaneo`, `nivel_acceso_interno`) y ENUMs en lugar de texto. Se necesitará un **script de transformación**.

> **Importante**: conservar los dumps del esquema viejo (`schema_seed.sql` / `db_pruebas.sql`) hasta completar la migración — son la referencia para escribir el script de transformación.

### 6.4 Pendiente — módulo de cámaras
Definir el papel de las cámaras de seguridad (reconocimiento facial vs. vigilancia pasiva). Según eso: agregar un valor al ENUM `tipo_dispositivo` (si fichan) y/o crear una tabla de evidencias/grabaciones (si graban).

---

## 7. Archivos del proyecto

| Archivo | Estado |
|---|---|
| `init.sql` | **Nuevo consolidado.** Reemplaza al viejo. |
| `docker-compose.prod.yml` | **Actualizado.** Sin doble carga de roles + tuning. |
| `docker-compose.yml` (dev) | Actualizado con tuning. |
| `Dockerfile` | Sin cambios (pgvector + postgis + pg_cron). |
| `fks_on_delete_cascade.sql` | Integrado en init → retirable. |
| `triggers_cascada_estado.sql` | Integrado en init → retirable. |
| `seed_roles.sql` | Integrado en init → retirable. |
| `migracion_empresa_intentos.sql` | Ya aplicado → retirable. |
| `limpiar_datos_prueba.sql` | Utilidad de prueba → retirable. |
| `schema_seed.sql` / `db_pruebas.sql` | **Conservar** hasta migrar datos. |
| `.env` | **Nunca borrar** (credenciales). |
| `env.example`, `nginx/` | Conservar (producción). |
