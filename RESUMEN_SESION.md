# Resumen de sesión — handoff

> Qué se hizo en esta sesión y dónde retomar. El backend sigue siendo un **monolito
> funcionando**, ahora alineado al esquema nuevo y "pre-cortado" por dominios.

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

### D) Prep de microservicios (#1–#6, todos en el monolito, sin cambiar comportamiento)
| # | Dominio | Costura |
|---|---|---|
| 1 | identity | JWT self-contained (`empresa`+`scopes` en claims) |
| 2 | media | `Media_Service` (todo el disco en un punto) |
| 3 | recognition | `Recognition_Service` (motor puro) separado de `scanner_service` |
| 4 | workers+tenancy | `Tenancy_Service` facade; workers/embeddings desacoplados |
| 5 | access | scanner lee tenancy solo por el facade |
| 6 | reports | filtros por `id_empresa` denormalizado |

**Archivos nuevos:** `PLAN_MICROSERVICIOS.md`, `src/docker/roles_microservicio.sql`,
`src/app/back/src/services/{Media,Recognition,Tenancy}_Service.py`.

---

## 2. Estado verificado
- ✅ Python: `compileall` + `configure_mappers()` + import de modelos/schemas/services/routers/`main` en cada paso.
- ⚠️ **NO probado contra Postgres real** (Docker estaba apagado). Pendiente: `docker compose up` con volumen vacío y revisar logs del contenedor `postgres` (valida que `init.sql` carga, incluida `consolidar_asistencia_dia`).

---

## 3. Cosas a recordar (gotchas)
- `init.sql` (+ `roles_microservicio.sql`) **solo corren con volumen vacío**. Reaplicar en dev: `docker compose down -v && up`.
- `roles_microservicio.sql` trae **contraseñas placeholder** (`CAMBIAR_*`) — cambiarlas antes de prod.
- Reasignar el job pg_cron a `app_cron` (`UPDATE cron.job SET username='app_cron' WHERE jobname='consolidar-asistencia-diaria';`).
- El backend alineado **solo funciona contra el `init.sql` NUEVO** (volumen fresco), **no** contra la BD vieja de producción.

---

## 4. Próximo día (lo pesado)
1. **Validar `init.sql` end-to-end** contra Postgres real (`down -v && up`, mirar logs).
2. **Script de migración de datos** producción → esquema nuevo (`serial → UUID`, `id_empresa` denormalizado, enums). Es transformación, no import directo; conservar `db_pruebas.sql` como referencia.
3. **Extracción real** por el orden §9 del plan: empezar por `identity` (JWT ya listo) → `media` → `recognition` → `workers`/`tenancy` → `access` → `reports`. Cada facade pasa a cliente HTTP; definir bus de eventos y BD por dominio.

> Detalle completo en `PLAN_MICROSERVICIOS.md` (§4 fases, §6 contratos, §7 retos, §9 orden, §10 checklist).
