# PLAN — Instalador de la App de Escritorio (SL Asistencias)

> **Estado:** idea de referencia (no mandato). Diseño del asistente de instalación que
> empaqueta el back (Docker) + el front (Electron) en un instalador único para Windows.
> Basado en lo que YA existe y está probado: `kiosk_local` + mini-stack local-first
> (ver `src/app/kiosk_local/GUIA_FRONT.md`).

---

## 1. Objetivo

Un **instalador único (.exe)** que deja una PC dedicada lista para operar como estación
de asistencias, **sin que el usuario sepa de Docker ni de línea de comandos**. El asistente:

1. Verifica requisitos (Docker).
2. Deja elegir **qué módulos** instalar (modo BÁSICA / PERSONALIZADA).
3. Descarga las imágenes del back desde un registry y las levanta.
4. Instala y arranca el front (Electron).
5. Configura autostart para que todo reviva al prender la PC.

**Principio rector:** local-first tipo APK — reconoce y guarda **local primero**, sube a la
nube cuando hay red; si se cae el internet, **no falla**. Esa lógica ya vive en el backend
(`kiosk_local`), no hay que reprogramarla.

---

## 2. Modelo de distribución (importante)

El back **NO es una sola imagen**: son ~12 servicios orquestados por Docker Compose. El
instalador NO buildea en la máquina del cliente (lento y necesitaría el código fuente).

```
Una vez (nosotros)                    En cada instalación (el cliente)
──────────────────────                ────────────────────────────────
build de las imágenes         ───►    docker compose pull   (baja imágenes)
push al registry (GHCR)               docker compose up -d   (levanta)
```

- **Unidad de despliegue:** un `docker-compose.desktop.yml` + imágenes ya publicadas.
- **Registry:** GHCR (ya usas GitHub). Públicas = gratis; privadas = el instalador hace
  `docker login` con un token de solo-lectura embebido/pedido.
- **Ventaja:** actualizar el back del cliente = `docker compose pull && up -d` (sin reinstalar).

---

## 3. Requisitos y la duda de licencias (resuelta)

| Cosa | ¿Se paga? |
|---|---|
| **Docker Desktop** | Gratis salvo empresas con **≥250 empleados Y ≥$10M USD/año**. Fallback gratis: Docker Engine sobre WSL2 (sin GUI). |
| **Subir imágenes a un registry** | Públicas = gratis. Privadas = cuotas chicas (GHCR entra en el storage de GitHub). |

**Para una PC dedicada interna: prácticamente $0.**

**Límite real:** el asistente **no puede instalar Docker Desktop en silencio** (requiere WSL2,
permisos de admin y reinicio). Lo máximo: detectarlo y, si falta, lanzar su instalador o
mandar al usuario a instalarlo. Ese es el único paso con fricción.

---

## 4. Modos de instalación

### 4.1 Mapa módulo → servicios (el corazón del instalador)

| Módulo (lo que marca el usuario) | Servicios que levanta | Arrastra por dependencia | Peso |
|---|---|---|---|
| **BÁSICA** — reconocimiento local + subir al server | `postgres` + `recognition` + `kiosk_local` | — (habla con el `off_sync` **del server central** por internet) | Ligero |
| **Cámaras** (vigilancia) | `vigilancia_api` + `vigilancia_capture` | `backend` + `recognition` + `postgres` + `identity` + `traefik` | **Pesado** |
| **Seguimiento** (reid) | `reid` (+ su sub-stack) | `postgres` + `recognition` | Medio-pesado |
| **Reportes** | `reports` | `postgres` + `identity` + `traefik` | Medio |
| **Sync SYS21** (nómina) | `employee_monitoring` | `postgres` + `recognition` | Normalmente NO en escritorio |

> **Auto-resolución de dependencias:** si el usuario marca "Cámaras", el instalador incluye
> `recognition`+`backend`+`postgres` aunque no los marque. El instalador tiene ese mapa.

### 4.2 Los dos modos

- **BÁSICA** (recomendado para el piloto): 3 servicios, sin Traefik ni identity local. Súper
  ligero. Es exactamente `kiosk_local` + mini-stack, **ya probado e2e**.
- **PERSONALIZADA:** el usuario elige módulos (incluye cámaras / seguimiento). El instalador
  **avisa en pantalla** cuando un módulo baja el motor completo: *"Este módulo requiere el
  motor completo (~X GB y más RAM)"*, para que nadie elija cámaras esperando algo ligero.

### 4.3 El salto de peso (a tener presente)

Hay un escalón grande entre BÁSICA y lo demás: marcar "Cámaras" prácticamente **baja el stack
central completo** al escritorio, porque `vigilancia_capture` reconoce mandando los frames al
scanner del `backend`. BÁSICA no necesita nada de eso.

---

## 5. Arquitectura instalada (modo BÁSICA)

```
PC del kiosko (Docker Desktop):
  ├─ kiosk_postgres  (pgvector)   → roster local + cola de escaneos offline
  ├─ recognition     (buffalo_l)  → MISMO código de prod, apuntando a la BD local
  └─ kiosk_local     (:8100)      → orquesta: roster / reconocer / fichar / sync
        ▲
        │ HTTP localhost:8100  (el escáner SIEMPRE pega aquí)
  Front Electron  ─────────────────►
        │
        └─ Login / Admin / Reportes ─────► ☁️ NUBE (gateway :8005/443)
```

- **Escáner/fichaje → `localhost:8100`** (`kiosk_local`, local-first + gate de calidad).
- **Login/admin/reportes → la nube** (`8005` en dev, HTTPS en prod).
- El escáner nunca pega directo a la nube; `kiosk_local` decide local vs fallback.

---

## 6. Flujo del asistente (paso a paso)

```
1. Bienvenida
2. Chequeo de requisitos
   ├─ ¿Docker instalado y corriendo?  (docker info)
   │    · Sí  → continuar
   │    · No  → lanzar instalador de Docker Desktop / instrucción + reintentar
   └─ ¿Recursos mínimos? (RAM/disco según módulos elegidos)
3. Modo de instalación
   ├─ BÁSICA        → 3 servicios
   └─ PERSONALIZADA → checklist de módulos (auto-resuelve dependencias + avisa peso)
4. Configuración
   ├─ URL de la nube (CLOUD_BASE_URL)
   ├─ Usuario/clave del kiosko (define la EMPRESA del roster)
   ├─ Tipo (campo|oficina|empaque|mixto) y puerta
   └─ (Genera el .env con SECRETOS ALEATORIOS: DB pass, tokens internos)
5. Descarga y arranque del back
   ├─ docker login (si el registry es privado)
   ├─ docker compose -f docker-compose.desktop.yml pull   [barra de progreso]
   └─ docker compose up -d   +   espera healthchecks
6. Primer roster
   └─ POST /kiosk/roster/sync   (baja el padrón; requiere internet 1 vez)
7. Instala el front (Electron) + accesos directos
8. Autostart (Docker Desktop al login + Electron)
9. Prueba rápida y "Listo"
```

---

## 7. Generación del `.env` y secretos

El instalador **autogenera** en el primer arranque (nunca deja los `CAMBIAR_*` del repo):

- `KIOSK_DB_PASSWORD`, `RECOGNITION_INTERNAL_TOKEN` → aleatorios por instalación.
- `CLOUD_BASE_URL`, `KIOSK_USER`, `KIOSK_PASSWORD`, `KIOSK_TIPO`, `KIOSK_EMPRESA`, `KIOSK_PUERTA`
  → de lo que el usuario capturó en el paso 4.
- `KIOSK_DISPOSITIVO` → id único de la PC (para auditar el origen offline en la nube).
- Umbrales del **gate de calidad** (`CALIDAD_*`) → valores por defecto, editables luego.

`CORS_ORIGINS` debe permitir el origen de Electron (`app://` / `file://`).

---

## 8. Ciclo de vida en la PC

- **Autostart:** Docker Desktop arranca al login; los contenedores usan `restart: unless-stopped`
  → reviven solos. El Electron arranca con Windows y pega a `localhost:8100`.
- **Persistencia:** el volumen `kiosk_pgdata` guarda roster + cola offline en la PC.
- **Actualizar back:** `docker compose pull && up -d` (un botón "Actualizar" en el front, o tarea programada).
- **Actualizar front:** auto-update de electron-builder (opcional).
- **Refresco del roster:** hoy manual (`/kiosk/roster/sync`); a futuro, scheduler que baje altas nuevas cada X.

---

## 9. Seguridad

- La BD local guarda **dato biométrico** → cifrar el disco/volumen (BitLocker en la PC dedicada).
- `kiosk_local` y `recognition` solo escuchan en **`localhost`** (nunca a la LAN/Internet).
- Token del kiosko de **larga vida sin expiración** (rol `kiosko`, atado a 1 empresa) — ya existe.
- Registry privado → token de **solo lectura** para el `pull`; no embeber credenciales de escritura.

---

## 10. Fases de implementación

| Fase | Entregable | Estado |
|---|---|---|
| 0 | Back local-first (`kiosk_local` + mini-stack) | ✅ hecho y probado e2e |
| 0.1 | Gate de calidad (descartar frames borrosos/parciales) | ✅ hecho (este repo) |
| 1 | Publicar imágenes en el registry (GHCR) + `docker-compose.desktop.yml` por perfiles | ⬜ pendiente |
| 2 | Front Electron: escáner → `localhost:8100`, resto → nube; sidecar que levanta el stack | ⬜ pendiente (repo del front) |
| 3 | Asistente de instalación (electron-builder NSIS): chequeo Docker, modos, `.env`, pull+up, autostart | ⬜ pendiente |
| 4 | Auto-update + botón "Actualizar back" | ⬜ opcional |
| 5 | Endurecer: cifrado de disco, calibrar umbrales del gate con webcam real | ⬜ pendiente |

**Alternativas de packaging** (de `GUIA_FRONT.md §7`): **A)** instalador + Docker (este plan,
recomendado para piloto); **B)** nativo sin Docker (PyInstaller + postgres embebido) para
producto; **C)** mini-PC pre-configurado.

---

## 11. Decisiones abiertas

1. **Registry público o privado.** Privado = imágenes protegidas (recomendado, `recognition`
   trae tu modelo) pero el instalador necesita token de lectura.
2. **¿Docker Desktop o Docker Engine/WSL2?** Desktop es más simple para el piloto; Engine evita
   el tema de licencia si SL Agrícola crece.
3. **Alcance de PERSONALIZADA en escritorio.** ¿De verdad tiene sentido cámaras/seguimiento por
   PC, o esos quedan solo en el server central? (Definir qué módulos se ofrecen).
4. **Actualizaciones automáticas** del back: ¿botón manual, o tarea programada silenciosa?
```
