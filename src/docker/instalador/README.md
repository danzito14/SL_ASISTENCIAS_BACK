# Instalador del kiosko de escritorio (perfil BÁSICA)

Motor del instalador: baja el backend del kiosko (Docker) a la PC del cliente y lo deja
operando local-first. El front (Electron) envuelve esto y le apunta a `localhost:8100`.

**BÁSICA** = `postgres` + `recognition` + `backend` + `kiosk_local` (reconoce local, sube a la nube).

`backend` es el **mismo micro `back` de la nube** corriendo con `MODO_KIOSKO=true` contra
la BD de la estación. Gracias a eso el escáner offline expone **las mismas rutas
`/scanner/*` y el mismo `ScanResponse`** que el de la nube, y se comporta igual: no hay
una segunda implementación que se desincronice. `kiosk_local` hace de gateway (inyecta los
headers `X-*` que el back espera de Traefik) y sigue encargándose del roster y de subir la
cola. Detalle en `src/app/kiosk_local/GUIA_FRONT.md` §4.

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
- `ghcr.io/<ns>/sl-backend:1.0.0`      (el back de la nube; corre en MODO_KIOSKO)
- `ghcr.io/<ns>/sl-kiosk-local:1.0.0`

### Las DOS versiones (no las confundas)

En `SL-Asistencias.iss` hay dos `#define` separados a propósito:

| Define | Qué versiona | Cuándo subirlo |
|---|---|---|
| `AppVersion` | el **instalador** (`.exe`; también va en su nombre de archivo) | en **cada** build, aunque solo cambies el compose o `instalar.ps1` |
| `ImgVersion` | el **tag de las imágenes** en GHCR (`IMG_VERSION` del `.env`) | **solo** si republicaste con `publicar-imagenes.ps1 -Version <tag>` |

No hay ninguna URL de imágenes que actualizar: el compose arma el nombre con
`${REGISTRY}/<imagen>:${IMG_VERSION}`. `#define Registry` solo cambia si te mudas de
cuenta/organización en GHCR. La única URL del `.iss` es `FrontUrl` (release del Electron),
y esa sí se actualiza en cada versión del front.

⚠️ Si subes `ImgVersion` a un tag que NO está publicado, el `docker compose pull` de la
instalación falla. Cambios que viven en el bundle (`docker-compose.desktop.yml`,
`instalar.ps1`, `init.sql`) **no** requieren imágenes nuevas: viajan dentro del `.exe`.

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

## 2-bis. Instalar en Linux (Ubuntu LTS / Mint)

Las imágenes son `linux/amd64`: en Linux corren **nativas**, sin la VM que Docker Desktop
levanta en Windows. El compose es el mismo; lo único distinto es el instalador (`instalar.sh`
en vez de `instalar.ps1`) y el autoarranque, que aquí lo da systemd.

Requisitos: x86_64, systemd y Docker Engine con el plugin `compose` v2.

```bash
# 1. Docker desde el repositorio OFICIAL (el de la distro suele traer una versión vieja).
#    OJO EN MINT: 'lsb_release -cs' devuelve el nombre de Mint (wilma, virginia...) y el
#    repo de Docker NO lo tiene. Hay que usar el codename de UBUNTU:
. /etc/os-release; CODENAME="${UBUNTU_CODENAME:-$VERSION_CODENAME}"
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODENAME stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 2. Que el kiosko no necesite sudo (y el .env no quede de root). Requiere volver a entrar.
sudo usermod -aG docker "$USER"

# 3. Que Docker arranque solo al encender (equivale al autostart de Docker Desktop).
sudo systemctl enable --now docker

# 4. Instalar el kiosko (interactivo, o con flags para desatendido)
chmod +x instalar.sh
./instalar.sh
./instalar.sh --cloud-url https://tu-dominio/api --user kiosko_emp1 --password '****' \
              --empresa 1 --tipo oficina
```

Los pasos 1-3 los puede hacer el propio instalador: si no encuentra Docker, ofrece
instalarlo (con el arreglo del codename de Mint ya incluido), lo habilita en systemd y
agrega el usuario al grupo `docker`. Sólo hay que cerrar sesión y volver a entrar después.

### Instalador de UN SOLO ARCHIVO (el equivalente del .exe)

`empaquetar-linux.sh` produce un `.run` autoextraíble que pregunta lo mismo que el wizard
de Windows, **todo por terminal**: así funciona igual en local que por SSH, y cuando algo
falla el error queda a la vista (y en `instalar.log`) en vez de en una ventana que se cierra.

```bash
sudo apt install makeself                    # solo en la máquina que empaqueta
./empaquetar-linux.sh 1.1.1 --front-url https://github.com/<org>/<repo>/releases/download/<tag>/SL-Asistencias-Estacion-<ver>.deb
# → Output/SL-Asistencias-Instalador-1.1.1.run
```

El `.run` lleva dentro el compose, `init.sql`, `roles_microservicio.sql` y el instalador,
igual que la sección `[Files]` del `.iss`. Al ejecutarse copia todo a `/opt/sl-asistencias`
(el equivalente de `{app}`) y corre `instalar.sh` desde ahí, para que el compose y el
`.env` sobrevivan al directorio temporal de makeself.

**Se ejecuta desde una terminal**, a diferencia del `.exe`:

```bash
./SL-Asistencias-Instalador-1.1.1.run
```

GNOME/Nautilus **no** ejecuta scripts al doble clic: los abre en el editor de texto, donde
se ve el payload binario y un aviso de *"Invalid Characters Detected"* (si se guarda ahí,
el archivo queda corrupto y hay que volver a empaquetarlo). Desde el explorador se puede
con **clic derecho → «Ejecutar como programa»**; el doble clic solo funciona si se cambia
*Archivos → Preferencias → Archivos de texto ejecutables*, que no es algo razonable de
pedirle a un cliente.

Equivalencias con el instalador de Windows:

| Windows | Linux |
|---|---|
| `SL-Asistencias.iss` (Inno Setup) | `empaquetar-linux.sh` (makeself) |
| `SL-Asistencias-Instalador-X.Y.Z.exe` | `SL-Asistencias-Instalador-X.Y.Z.run` |
| Doble clic | Desde terminal (`./archivo.run`) o clic derecho → «Ejecutar como programa» |
| Página del wizard | Preguntas por terminal (`read`), con log en vivo |
| `{app}` = `C:\Program Files (x86)\SL Asistencias` | `/opt/sl-asistencias` |
| `#define FrontUrl` | `--front-url` (horneado al empaquetar) |
| Docker Desktop: sólo se verifica | Docker Engine: se ofrece **instalarlo** |

`instalar.sh` hace exactamente lo mismo que la versión Windows, incluido el guard del
volumen heredado, y además: crea el `.env` con permisos `600` (en Windows queda con los
del directorio) y toma `KIOSK_TZ` de la zona horaria del sistema.

Con `restart: unless-stopped` en el compose y `docker.service` habilitado, el stack revive
solo al encender la máquina. Para que además abra la app, agrega un `.desktop` en
`~/.config/autostart/` o un servicio systemd de usuario.

### La app (Electron) en Linux

**Compílala desde Linux** (la misma VM sirve): empaquetar Electron para Linux desde Windows
falla por permisos y enlaces simbólicos. Si sólo tienes Windows, hazlo en el contenedor
`electronuserland/builder`.

```bash
# Node 22: el apt de Ubuntu 24.04 trae el 18 y Angular 21 NO arranca con esa versión.
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

git clone <repo del front> && cd FP_ESCANER_FRONT
npm ci                  # respeta el postinstall (patch-package) y la carpeta patches/
npm run dist:linux      # genera AppImage + .deb en release/
```

Después publica el `.deb` como release (igual que el `-setup.exe` de Windows) y pásalo al
instalador, que lo descarga e instala solo:

```bash
./instalar.sh --front-url https://github.com/<org>/<repo>/releases/download/<tag>/SL-Asistencias-Estacion-<ver>.deb
```

Sin `--front-url` el script deja el backend listo y la app se instala a mano
(`sudo apt install ./SL-Asistencias-Estacion-<ver>.deb`).

### Probar en una VM

Sirve para validar instalación, roster, sync y el contrato del escáner. Tres avisos:
la **webcam** necesita pasarse a la VM (en VirtualBox, Extension Pack + USB), y sin ella
sólo puedes probar mandando un JPEG por `curl` a `/scanner/acceso/foto`; **no midas la
velocidad** del reconocimiento ahí (va en CPU, con los núcleos que le des); y da al menos
4 núcleos y 8 GB. No hace falta virtualización anidada: en Linux Docker es nativo.

---

## 3. Operar

```powershell
docker compose -f docker-compose.desktop.yml down    # parar
docker compose -f docker-compose.desktop.yml up -d   # arrancar
docker compose -f docker-compose.desktop.yml logs -f # ver logs
```

- **Autostart**: Docker Desktop arranca al login; los contenedores usan `restart: unless-stopped`.
- **Datos**: el volumen `kiosk_kiosk_pgdata` guarda roster + colas offline en la PC.
- **Actualizar back** en una estación ya instalada, según qué cambió:
  - *Solo el compose/env* (umbrales, flags): copia el `docker-compose.desktop.yml` nuevo
    sobre `{app}` y `docker compose -f ... --env-file .env up -d`. Sin `pull`.
  - *Imágenes nuevas*: edita `IMG_VERSION=<tag nuevo>` en el `.env` de `{app}`, luego
    `docker compose -f ... --env-file .env pull` y `up -d`.
  - *Todo junto*: vuelve a correr el instalador `.exe`.

### Reinstalar sobre una estación existente

Desinstalar la app **no borra el volumen de datos** (`kiosk_kiosk_pgdata`): Windows no
ejecuta Docker al desinstalar. Y `POSTGRES_PASSWORD` solo se aplica al inicializar un
volumen vacío, así que una reinstalación con secretos nuevos dejaba todo el stack en
`password authentication failed for user "root"`.

`instalar.ps1` ya lo maneja: si detecta el volumen, **reutiliza los secretos del `.env`
anterior**; y si ese `.env` ya no existe, levanta Postgres primero y **realinea el rol
`root`** por el socket local (que en la imagen oficial autentica con `trust`, así que no
hace falta conocer la contraseña vieja) antes de arrancar el resto.

Si quieres empezar de cero de verdad, borra el volumen a mano — se pierden el roster local
y lo que no se haya subido:

```powershell
docker compose -f docker-compose.desktop.yml --env-file .env down
docker volume rm kiosk_kiosk_pgdata
```

---

## Archivos

| Archivo | Qué es |
|---|---|
| `docker-compose.desktop.yml` | Mini-stack BÁSICA (pull de GHCR, sin build) |
| `instalar.ps1` | Motor del instalador en **Windows** (Docker check → .env → pull → modelo → up → sync) |
| `instalar.sh` | Lo mismo en **Linux** (Ubuntu LTS / Mint). Ver §2-bis |
| `publicar-imagenes.ps1` | Construye y publica las 3 imágenes en GHCR |
| `init.sql`, `roles_microservicio.sql` | Esquema + roles (se montan en postgres). Van en el bundle; el script los copia del repo si faltan |

## Notas de seguridad

- Las imágenes públicas **no exponen sistemas de la empresa** (todo va en el `.env`).
- El sistema se protege con la **auth de la nube** (login de kiosko): sin credenciales, las imágenes son un cascarón vacío.
- La BD local tiene dato biométrico → cifrar el disco (BitLocker) en la PC dedicada.
- El backend local solo escucha en `localhost`.
