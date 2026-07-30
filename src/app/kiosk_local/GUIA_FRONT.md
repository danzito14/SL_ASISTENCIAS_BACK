# Kiosko de Escritorio — Guía Backend → Front

Handoff del backend del **kiosko de escritorio** (Electron + reconocimiento local-first).
Responde al plan del equipo front (`Plan — Kiosko de Escritorio (Electron) local-first`).

**Estado:** backend **completo y probado e2e**. Falta el front (Electron) + validar liveness.

---

## 1. Qué se construyó aquí (backend, esta sesión)

Un micro nuevo **`kiosk_local`** + un mini-stack local. **Cero cambios a prod** (aditivo).

- `src/app/kiosk_local/` — backend local (FastAPI): baja el roster de la nube, reconoce
  offline, ficha local y sube la cola solo.
- `src/docker/docker-compose.local.yml` — mini-stack del kiosko: **postgres+pgvector**,
  **recognition** (misma imagen de prod) y **kiosk_local**.

**Decisión clave:** en la PC usamos **Postgres+pgvector local** (no SQLite como el APK).
Motivo: se **reusa TODO** el motor de prod (`recognition` + `motor.buscar_en_bd` + `init.sql`)
→ **paridad de embeddings/match garantizada**, cero reimplementación.

### Probado end-to-end (todo offline salvo el sync)
| Paso | Resultado real |
|---|---|
| Bajar roster de la nube → BD local | empresa 1 → 2 trabajadores + 2 embeddings 512-D (URIEL, HECTOR) |
| Reconocer **offline** (`/kiosk/identificar`) | foto webcam de URIEL → **match 684, sim 0.611** |
| Fichar **offline** (`/kiosk/acceso`) | "Bienvenido URIEL", escaneo local encolado (UUIDv7) |
| Auto-sync a la nube | loop subió el escaneo solo → la nube consolidó la asistencia (idempotente) |

---

## 2. Arquitectura final

```
PC del kiosko (Docker):
  ├─ kiosk_postgres  (pgvector)      → roster local + cola de escaneos
  ├─ recognition     (buffalo_l)     → MISMO código de prod, apuntando a la BD local
  └─ kiosk_local     (FastAPI :8100) → orquesta: roster / reconocer / fichar / sync
        ▲
        │ HTTP localhost:8100
  Front Electron (Angular)  ──────────►  (escáner apunta SIEMPRE a localhost)
        │
        └─ Auth/Admin/Reportes ─────────►  ☁️ NUBE (gateway prod)
```

La orquestación **local→nube vive en `kiosk_local`** (no en el front), como pedía el plan (§2):
el front pega a `localhost:8100` y el backend decide si responde local o hace fallback a la nube.

---

## 3. Lo que necesita hacer el FRONT

1. **Empaquetar** el front Angular en **Electron** (electron-builder → instalador Windows NSIS).
2. **Apuntar el escáner a `http://localhost:8100`** (el `kiosk_local`), NO a la nube.
3. **Flujo mínimo:**
   - Al **arrancar / primer uso**: `POST /kiosk/roster/sync` (baja el roster; requiere internet 1 vez). Mostrar "Descargando datos…".
   - En cada **fichaje** (frame de la webcam): `POST /kiosk/acceso` (multipart `foto`). Mostrar el `mensaje`/`trabajador` de la respuesta.
   - Auth/Admin/Reportes: siguen yendo **a la nube** directo (como hoy la web).
4. **Arrancar el sidecar**: el instalador/Electron levanta el mini-stack (ver §7 packaging).

> El front **casi no cambia** vs el APK: en vez de plugins nativos (ONNX/SQLite on-device),
> el escáner hace HTTP a `localhost:8100`. La lógica local-first ya vive en el backend.

---

## 4. Contratos de la API local (`http://localhost:8100`)

Sin auth (es local, solo escucha en localhost). Todas las respuestas son JSON.

### ⭐ Escáner: `POST /scanner/*` — las MISMAS rutas que la nube

El escáner ya no tiene un contrato propio. La estación levanta el **mismo `back` de la
nube** (con `MODO_KIOSKO=true`, contra la BD local) y `kiosk_local` le reenvía `/scanner/*`
haciendo de gateway. Para el front eso significa **un solo cliente**: mismas rutas, mismos
parámetros y el mismo `ScanResponse`, cambie o no el host.

| Ruta | Igual que en la nube |
|---|---|
| `POST /scanner/identificar/foto` (multipart `foto`) | sí — dice quién es, no registra |
| `POST /scanner/acceso/foto` (multipart `foto`) | sí — ficha |
| `POST /scanner/acceso/liveness` (multipart `fotos`, 3-5) | sí — ficha con prueba de vida |

Única diferencia a favor: **`id_puerta` es opcional**. En la nube es obligatorio; aquí, si
no lo mandas, se usa la puerta de la estación (la elegida en el front → `KIOSK_PUERTA` →
1ª del roster). Si la mandas, manda la tuya.

```json
{"acceso":true,"mensaje":"Acceso concedido — URIEL ALONSO CARO DIAZ (similitud: 61.10%).",
 "trabajador":{"id_trabajador":684,"nombre":"URIEL ALONSO","apellido":"CARO DIAZ","estado":"activo"},
 "id_escaneo":"019f527f-9e8a-766b-...","estado_registro":"exitoso"}
```

Diferencias de comportamiento respecto a la nube, a tener presentes:

- **No consolida**: la estación encola el escaneo y la nube deriva entrada/salida al
  recibir la cola. Offline no esperes que la respuesta diga "ya fichaste hoy".
- **Sin fallback por default**: si el rostro no está en el roster local, responde "no
  reconocido" sin ir a la nube. Se enciende con `KIOSK_SCANNER_FALLBACK_NUBE=true`, pero
  mete latencia de red en el fichaje; lo correcto es sincronizar el roster tras enrolar.
- `POST /kiosk/acceso` y `POST /kiosk/identificar` siguen existiendo **solo por
  compatibilidad**. Para código nuevo usa `/scanner/*`.

### `POST /kiosk/roster/sync?tipo=oficina`
Baja el roster de la nube y lo carga en la BD local. `tipo` opcional (default `KIOSK_TIPO`).
```json
{"empresa":1,"tipo":"oficina","roster_version":"223809e338defc85",
 "trabajadores":2,"embeddings":2,"areas":1,"puertas":1}
```

### `POST /kiosk/acceso`  (multipart: `foto`; query: `id_puerta?`, `tipo_registro=entrada`)
**El endpoint principal.** Reconoce LOCAL primero; si no hay match y hay internet, fallback a la nube.
- **Match local** → registra escaneo local (en cola) y:
```json
{"acceso":true,"origen":"local",
 "trabajador":{"id_trabajador":684,"nombre":"URIEL ALONSO","apellido":"CARO DIAZ",
               "id_empresa":1,"similitud":0.611},
 "id_escaneo":"019f527f-9e8a-766b-...","mensaje":"Bienvenido URIEL ALONSO CARO DIAZ."}
```
- **Sin match local + internet** → `{"origen":"nube", ...ScanResponse de la nube}`
- **Sin match + sin internet** → `{"acceso":false,"origen":"local","estado":"no_match","mensaje":...}`
- **No rostro / spoof** → `{"acceso":false,"origen":"local","estado":"no_rostro|spoof","mensaje":...}`

### `POST /kiosk/identificar`  (multipart: `foto`)
Igual que acceso pero **sin registrar** (solo dice quién es). Útil para pruebas / previsualización.
```json
{"estado":"match","trabajador":{"id_trabajador":684,...,"similitud":0.611},"det_score":0.816}
```

### `POST /kiosk/sync/eventos`
Fuerza subir YA la cola a la nube (además del loop automático cada 30s).
```json
{"subidos":1,"insertados":1,"duplicados":0,"rechazados":0}   // o {"pendientes":0}
```

### `GET /kiosk/estado`
```json
{"trabajadores":2,"embeddings_activos":2,
 "meta":{"empresa":"1","tipo":"oficina","roster_version":"223809e338defc85"},
 "hay_conexion":true}
```

### `GET /health` — salud del servicio + BD local.

---

## 5. Respuesta a las preguntas del plan (§8)

| # | Pregunta del plan | Respuesta |
|---|---|---|
| 1 | ¿El motor de reconocimiento corre como servicio local en Windows? | **SÍ** — contenedor `recognition` (mismo código). Paridad de embeddings validada (spike, coseno 1.0). |
| 2 | ¿Endpoint que entregue embeddings por empresa? Formato del vector | **SÍ** — `GET /off_sync/roster?tipo=`. Embedding = **array JSON de 512 floats** (buffalo_l L2-norm). 1 por trabajador (el activo). |
| 3 | ¿Subida en lote con resultado por ítem? Estado §4.4 | **SÍ** — `POST /off_sync/asistencias` (CSV, idempotente). §4.4 (derivar entrada/salida, reconciliar, PK por ítem, `/candidatos`) **ya hecho** en la nube. |
| 4 | ¿Auth por token de dispositivo de larga vida? | **SÍ** — rol `escaneador`/`kiosko`, **token SIN expiración**, atado a 1 empresa. `crear_kiosko.sh`. |
| 5 | ¿`offline_sync` reusable tal cual? | **SÍ, entero** — el desktop pega a los mismos endpoints. Desplegado en prod y probado. |

**Diferencia con el APK:** en el desktop el reconocimiento y la orquestación local viven en
`kiosk_local` (backend local con Postgres), NO en el front ni en plugins nativos.

---

## 6. Fases del plan: hecho / pendiente

| Hito del plan | Estado |
|---|---|
| Hito 1 — Desktop contra la nube (sin offline) | listo si el front apunta a la nube (no requiere backend nuevo) |
| Hito 2 — Roster local + reconocimiento local | ✅ **hecho y probado** (`/kiosk/roster/sync` + `/kiosk/acceso`) |
| Hito 3 — Fallback + sync | ✅ **hecho** (fallback a nube + loop de auto-sync) |

---

## 7. Pendientes / opcionales

- **Liveness / anti-spoof:** cableado (toggle `KIOSK_ANTISPOOF`), pero el modelo MiniFASNet
  **falla en selfies de webcam de cerca** (falso spoof, score 0.005 — sensible a encuadre/dominio).
  **Default OFF.** Requiere un **spike de validación** con capturas a distancia de kiosko (o
  re-afinar/cambiar de modelo). No shippear un liveness que rechaza gente real.
- **Refresco periódico del roster:** hoy es manual (`/kiosk/roster/sync`). Agregar un scheduler
  (como el de sync) para bajar altas nuevas cada X. Cambio chico.
- **Enrolamiento offline** desde el desktop: reusar `POST /off_sync/enrolamientos` + un endpoint
  local `/kiosk/enrolar`. Pendiente si lo quieren.
- **Packaging / instalador** (lado front): **A)** instalador que instala Docker en silencio +
  carga imágenes + `compose up`; **B)** nativo sin Docker (PyInstaller + postgres embebido);
  **C)** mini-PC pre-configurado. Recomendado: A para piloto, B/C para producto.
- **Seguridad:** BD local con dato biométrico → cifrar disco/volumen; el backend local ya solo
  escucha en `localhost`.
- **`id_dispositivo_origen`:** hoy va NULL. Setear `KIOSK_DISPOSITIVO` por kiosko para auditar
  el origen offline en la nube.

---

## 8. Cómo correr el mini-stack (dev)

```bash
cd src/docker
# Nube = gateway (dev: http://host.docker.internal:8005 ; prod: https://.../api)
# SIN -p: el proyecto se llama 'kiosk_dev' (ver el compose). Pasar -p kiosk lo haría
# chocar con una instalación real en la misma PC (mismos contenedores y volumen).
docker compose -f docker-compose.local.yml up -d --build
curl -X POST http://localhost:8100/kiosk/roster/sync      # baja el roster
curl -X POST "http://localhost:8100/scanner/acceso/foto" -F "foto=@cara.jpg"   # ficha
docker compose -f docker-compose.local.yml down            # parar
```

### Config (`kiosk_local`, por env — ver `.env.example`)
| Var | Para qué |
|---|---|
| `CLOUD_BASE_URL` | gateway de la nube (`https://<TU-DOMINIO>/api`) |
| `KIOSK_USER` / `KIOSK_PASSWORD` | usuario kiosko (define la EMPRESA del roster) |
| `KIOSK_TIPO` | campo \| oficina \| empaque \| mixto |
| `KIOSK_EMPRESA` | empresa (opcional; el token ya la acota) |
| `KIOSK_PUERTA` | puerta donde ficha (default: 1ª del roster) |
| `KIOSK_SYNC_INTERVAL_SEG` | cada cuánto sube la cola (default 30) |
| `KIOSK_ANTISPOOF` | liveness on/off (default **false**, ver §7) |
| `RECOGNITION_URL` / `RECOGNITION_INTERNAL_TOKEN` | recognition local |

### Referencias del plan (front, otro repo)
- Flujo offline local-first: `src/app/pages/escaneo/escaneo.component.ts`
- Ahora el escáner NO usa `match.service`/`face-engine` on-device: hace **HTTP a `localhost:8100`**.
