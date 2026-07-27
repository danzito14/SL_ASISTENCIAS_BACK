# Instalador del kiosko de escritorio (perfil BÁSICA)

Motor del instalador: baja el backend del kiosko (Docker) a la PC del cliente y lo deja
operando local-first. El front (Electron) envuelve esto y le apunta a `localhost:8100`.

**BÁSICA** = `postgres` + `recognition` + `kiosk_local` (reconoce local, sube a la nube).

---

## 1. Publicar las imágenes (una vez, lo hace el equipo — no el cliente)

Las imágenes son **públicas en GHCR** y **no llevan datos de la empresa** (URLs/credenciales
van en el `.env` de cada instalación). `recognition` se publica **LIGERA** (sin hornear
buffalo_l; el modelo se baja en la instalación).

```powershell
# 1. Token de GitHub (classic) con scope write:packages
docker login ghcr.io -u <tu-usuario>       # password = el token

# 2. Construir y subir (ajusta -Namespace/-Version si aplica)
.\publicar-imagenes.ps1 -Namespace ghcr.io/danzito14 -Version 1.0.0
```
Luego marca cada paquete como **Público** en GitHub → Packages.

Imágenes resultantes:
- `ghcr.io/<ns>/pgvector-postgis:pg17`
- `ghcr.io/<ns>/sl-recognition:1.0.0`  (ligera)
- `ghcr.io/<ns>/sl-kiosk-local:1.0.0`

---

## 2. Instalar en la PC del cliente

Requisito único: **Docker Desktop** instalado y corriendo.

```powershell
# Interactivo (pregunta URL/usuario/clave/empresa):
.\instalar.ps1

# O no interactivo (lo llama el Electron/NSIS):
.\instalar.ps1 -CloudUrl "https://tu-dominio/api" -KioskUser "kiosko_emp1" `
               -KioskPassword "****" -Empresa 1 -Tipo oficina `
               -Registry ghcr.io/danzito14 -Version 1.0.0
```

Qué hace `instalar.ps1`:
1. Verifica Docker.
2. Pide (o recibe) URL de la nube + credenciales del kiosko.
3. Genera el `.env` con **secretos aleatorios** (DB, token interno) — nunca en la imagen.
4. `docker compose pull` (imágenes públicas, sin login).
5. Descarga **buffalo_l** (~300 MB) a un volumen (una vez; persiste).
6. `docker compose up -d`.
7. Espera health y baja el padrón por primera vez.

---

## 3. Operar

```powershell
docker compose -f docker-compose.desktop.yml down    # parar
docker compose -f docker-compose.desktop.yml up -d   # arrancar
docker compose -f docker-compose.desktop.yml logs -f # ver logs
```

- **Autostart**: Docker Desktop arranca al login; los contenedores usan `restart: unless-stopped`.
- **Datos**: el volumen `kiosk_kiosk_pgdata` guarda roster + colas offline en la PC.
- **Actualizar back**: `docker compose pull && up -d`.

---

## Archivos

| Archivo | Qué es |
|---|---|
| `docker-compose.desktop.yml` | Mini-stack BÁSICA (pull de GHCR, sin build) |
| `instalar.ps1` | Motor del instalador (Docker check → .env → pull → modelo → up → sync) |
| `publicar-imagenes.ps1` | Construye y publica las 3 imágenes en GHCR |
| `init.sql`, `roles_microservicio.sql` | Esquema + roles (se montan en postgres). Van en el bundle; el script los copia del repo si faltan |

## Notas de seguridad

- Las imágenes públicas **no exponen sistemas de la empresa** (todo va en el `.env`).
- El sistema se protege con la **auth de la nube** (login de kiosko): sin credenciales, las imágenes son un cascarón vacío.
- La BD local tiene dato biométrico → cifrar el disco (BitLocker) en la PC dedicada.
- El backend local solo escucha en `localhost`.
