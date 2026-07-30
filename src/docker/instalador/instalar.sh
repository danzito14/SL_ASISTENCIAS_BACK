#!/usr/bin/env bash
# instalar.sh — Motor del instalador del kiosko de escritorio en LINUX (perfil BÁSICA).
# Equivalente de instalar.ps1: verifica Docker → pide URL/credenciales → genera el .env con
# secretos → descarga imágenes públicas → baja buffalo_l a un volumen → levanta el stack →
# espera health → baja el padrón. Probado contra Ubuntu LTS y Mint (mismo .deb de Docker).
#
# TODO por TERMINAL: pregunta con read y deja la salida a la vista (además de instalar.log).
# Nada de diálogos gráficos: en una instalación remota o por SSH no sirven, y cuando algo
# falla se necesita ver el error, no una ventana que se cierra.
#
# Uso interactivo:      ./instalar.sh
# Uso no interactivo:   ./instalar.sh --cloud-url https://tu-dominio/api --user kiosko_emp1 \
#                         --password '****' --empresa 1 --tipo oficina
#
# Requisitos: Docker Engine + plugin compose v2, y el usuario en el grupo 'docker'
# (si no, todo esto pediría sudo y el .env quedaría de root). Ver README §Linux.
set -Eeuo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE="$AQUI/docker-compose.desktop.yml"
ENV_FILE="$AQUI/.env"
LOG="$AQUI/instalar.log"
VOLUMEN_DATOS="kiosk_kiosk_pgdata"
VOLUMEN_MODELO="kiosk_modelos_insightface"
CONTENEDOR_PG="kiosk_postgres"

# Todo lo que se imprima va a la terminal Y al log (para soporte). Los prompts de 'read'
# salen por stderr, que también se captura, así que quedan registrados en el log.
exec > >(tee -a "$LOG") 2>&1

CLOUD_URL=""; KIOSK_USER=""; KIOSK_PASSWORD=""; EMPRESA=""
TIPO="oficina"; PUERTA=""; DISPOSITIVO=""
REGISTRY="ghcr.io/danzito14"; VERSION="1.0.2"
# .deb de la app (Electron). Equivale al #define FrontUrl del instalador de Windows.
# Vacío = se omite el paso y se instala la app a mano.
FRONT_URL=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cloud-url)   CLOUD_URL="$2";      shift 2 ;;
        --user)        KIOSK_USER="$2";     shift 2 ;;
        --password)    KIOSK_PASSWORD="$2"; shift 2 ;;
        --empresa)     EMPRESA="$2";        shift 2 ;;
        --tipo)        TIPO="$2";           shift 2 ;;
        --puerta)      PUERTA="$2";         shift 2 ;;
        --dispositivo) DISPOSITIVO="$2";    shift 2 ;;
        --registry)    REGISTRY="$2";       shift 2 ;;
        --version)     VERSION="$2";        shift 2 ;;
        --front-url)   FRONT_URL="$2";      shift 2 ;;
        -h|--help)     sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "Parámetro desconocido: $1" >&2; exit 1 ;;
    esac
done

titulo() { printf '\n\033[1;36m== %s ==\033[0m\n' "$1"; }
paso()   { printf '   %s\n' "$1"; }
aviso()  { printf '\033[1;33mAVISO:\033[0m %s\n' "$1"; }

# El trap ERR se dispara en la función QUE falla y otra vez al propagarse al nivel de
# arriba (por 'set -E'), así que sin esta bandera el mismo error se imprime dos veces con
# líneas distintas y parece que hay dos fallos.
YA_FALLE=false
fatal() {
    if ! $YA_FALLE; then
        YA_FALLE=true
        printf '\n\033[1;31mERROR:\033[0m %s\n' "$1" >&2
    fi
    exit 1
}

# Si el script muere por un error no previsto, DECIRLO con la línea exacta en vez de
# terminar en silencio (que es justo lo que pasaba antes en el paso 3).
trap 'fatal "falló la línea $LINENO. Revisa el detalle arriba o en $LOG"' ERR

# Hay terminal para preguntar? Se comprueba /dev/tty y no 'test -t 0': dentro del .run
# (makeself) la entrada estándar puede no ser el terminal aunque el usuario sí esté ahí.
hay_terminal() { [[ -r /dev/tty ]]; }

preguntar() {  # $1 = etiqueta, $2 = 'oculto' para contraseñas
    local etiqueta="$1" oculto="${2:-}" valor
    hay_terminal || fatal "No hay terminal interactiva: pasa los datos por parámetro (--cloud-url, --user, --password, --empresa)."
    if [[ "$oculto" == "oculto" ]]; then
        read -r -s -p "   $etiqueta: " valor </dev/tty; echo
    else
        read -r -p "   $etiqueta: " valor </dev/tty
    fi
    printf '%s' "$valor"
}

# ── 1. Docker ────────────────────────────────────────────────────────────────
titulo "1/7 Verificando Docker"
instalar_docker() {
    titulo "Instalando Docker Engine (repositorio oficial)"
    # OJO MINT: 'lsb_release -cs' da el codename de Mint (wilma, virginia...) y el repo de
    # Docker NO lo tiene. Hay que usar el de Ubuntu, que Mint expone en UBUNTU_CODENAME.
    . /etc/os-release
    local codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
    [[ -n "$codename" ]] || fatal "No pude determinar el codename de la distro para el repo de Docker."
    paso "Distro: ${PRETTY_NAME:-?} → repo de Docker para '$codename'"
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $codename stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo systemctl enable --now docker
    sudo usermod -aG docker "$USER"
    aviso "Se agregó '$USER' al grupo docker. CIERRA SESIÓN y vuelve a entrar, y vuelve a
       ejecutar este instalador: hasta entonces Docker no te responderá sin sudo."
    exit 0
}

if ! command -v docker >/dev/null 2>&1; then
    paso "Docker no está instalado."
    if hay_terminal; then
        read -r -p "   ¿Lo instalo ahora (repositorio oficial)? [s/N]: " respuesta </dev/tty
        if [[ "$respuesta" =~ ^[sS] ]]; then
            instalar_docker
        else
            fatal "Instala Docker y reintenta (ver README §Linux)."
        fi
    else
        fatal "Docker no está instalado. Instálalo con el repositorio oficial (ver README §Linux) y reintenta."
    fi
fi
if ! docker info >/dev/null 2>&1; then
    fatal "Docker está instalado pero no responde. Prueba 'sudo systemctl start docker', y si el
       error es de permisos: 'sudo usermod -aG docker \$USER' + cerrar sesión y volver a entrar."
fi
docker compose version >/dev/null 2>&1 \
    || fatal "Falta el plugin 'docker compose' v2. Instala docker-compose-plugin del repositorio oficial."
paso "Docker OK: $(docker --version | cut -d, -f1) / $(docker compose version --short 2>/dev/null || echo compose v2)"

# ── 2. Datos de la empresa ───────────────────────────────────────────────────
titulo "2/7 Configuración"
[[ -n "$CLOUD_URL"      ]] || CLOUD_URL="$(preguntar 'URL de la nube (ej. https://tu-dominio/api)')"
[[ -n "$KIOSK_USER"     ]] || KIOSK_USER="$(preguntar 'Usuario del kiosko')"
[[ -n "$KIOSK_PASSWORD" ]] || KIOSK_PASSWORD="$(preguntar 'Contraseña del kiosko' oculto)"
[[ -n "$EMPRESA"        ]] || EMPRESA="$(preguntar 'ID de empresa')"
[[ -n "$CLOUD_URL" && -n "$KIOSK_USER" && -n "$KIOSK_PASSWORD" && -n "$EMPRESA" ]] \
    || fatal "Faltan datos: URL, usuario, contraseña y empresa son obligatorios."
paso "Nube: $CLOUD_URL | usuario: $KIOSK_USER | empresa: $EMPRESA | tipo: $TIPO"

# ── 3. Secretos + .env ───────────────────────────────────────────────────────
titulo "3/7 Generando secretos y .env"
# El volumen de datos SOBREVIVE a desinstalar: Postgres solo aplica POSTGRES_PASSWORD al
# inicializar un volumen VACÍO, así que reinstalar con secretos nuevos dejaba el stack en
# "password authentication failed for user root". Si hay volumen previo se REUSAN los
# secretos del .env anterior; si ese .env ya no está, se realinea el rol en el paso 6.
#
# OJO con 'set -e': un 'cmd && var=true' que falla aborta el script entero (la sentencia
# devuelve 1). Por eso todas estas condiciones van con if/then explícito y no con &&.
volumen_previo=false
if [[ -n "$(docker volume ls -q --filter "name=^${VOLUMEN_DATOS}$")" ]]; then
    volumen_previo=true
    paso "Detectado un volumen de datos previo ($VOLUMEN_DATOS): se conserva la BD."
else
    paso "Sin volumen previo: la BD se creará desde cero con init.sql."
fi

# OJO: nada de 'tr </dev/urandom | head -c 40'. head cierra la tubería al llegar a los 40
# bytes, tr muere con SIGPIPE (141) y con 'pipefail' la tubería devuelve error → set -e
# aborta el script. Se lee una cantidad ACOTADA y se recorta con expansión de bash.
nuevo_secreto() {
    local aleatorio
    aleatorio="$(head -c 1024 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9')"
    printf '%s' "${aleatorio:0:40}"
}
valor_env() {  # $1 = clave; lee el .env anterior si existe (vacío si no)
    # awk lee el archivo directo (sin tubería) y corta en la 1ª coincidencia: así no hay
    # ningún proceso al que cerrarle la salida antes de tiempo.
    if [[ -f "$ENV_FILE" ]]; then
        awk -v clave="$1" 'index($0, clave "=") == 1 { print substr($0, length(clave) + 2); exit }' "$ENV_FILE"
    fi
}
secreto_reusable() {
    local previo=""
    if $volumen_previo; then
        previo="$(valor_env "$1")"
    fi
    if [[ -n "$previo" ]]; then
        printf '%s' "$previo"
    else
        nuevo_secreto
    fi
}

DB_PASSWORD="$(secreto_reusable KIOSK_DB_PASSWORD)"
DB_PASSWORD_ANTERIOR="$(valor_env KIOSK_DB_PASSWORD)"
realinear_password=false
if $volumen_previo && [[ "$DB_PASSWORD_ANTERIOR" != "$DB_PASSWORD" ]]; then
    realinear_password=true
    paso "El .env anterior no está: se realineará la contraseña del rol 'root' (paso 6)."
elif $volumen_previo; then
    paso "Reusando los secretos del .env anterior (la BD sigue siendo válida)."
fi

TZ_SISTEMA="$(timedatectl show -p Timezone --value 2>/dev/null || echo America/Mazatlan)"
umask 077   # el .env lleva secretos: que nazca 600 y no legible por otros usuarios
cat > "$ENV_FILE" <<EOF
# Generado por instalar.sh — NO subir a git. Contiene secretos de ESTA estación.
REGISTRY=$REGISTRY
IMG_VERSION=$VERSION
KIOSK_DB_PASSWORD=$DB_PASSWORD
RECOGNITION_INTERNAL_TOKEN=$(secreto_reusable RECOGNITION_INTERNAL_TOKEN)
KIOSK_GATEWAY_TOKEN=$(secreto_reusable KIOSK_GATEWAY_TOKEN)
CLOUD_BASE_URL=$CLOUD_URL
KIOSK_USER=$KIOSK_USER
KIOSK_PASSWORD=$KIOSK_PASSWORD
KIOSK_TIPO=$TIPO
KIOSK_EMPRESA=$EMPRESA
KIOSK_PUERTA=$PUERTA
KIOSK_DISPOSITIVO=$DISPOSITIVO
KIOSK_TZ=$TZ_SISTEMA
EOF
umask 022
# Si esto corre bajo sudo, el .env nacería de root con permisos 600 y el usuario normal no
# podría ni leerlo: cualquier 'docker compose --env-file .env' posterior fallaría con
# "permission denied". Se le devuelve al usuario real.
if [[ -n "${SUDO_USER:-}" ]] && [[ "$SUDO_USER" != "root" ]]; then
    chown "$(id -u "$SUDO_USER"):$(id -g "$SUDO_USER")" "$ENV_FILE"
    paso "El .env quedó a nombre de $SUDO_USER (para operar el kiosko sin sudo)."
fi
paso ".env creado en $ENV_FILE (permisos 600, zona horaria $TZ_SISTEMA)"

# El esquema + roles se montan en postgres: deben estar junto al compose Y ser LEGIBLES
# por el usuario 'postgres' del contenedor (UID 999). Con 600 no puede leerlos, la
# inicialización se aborta a medias y el volumen queda con una BD sin esquema que ya nunca
# se vuelve a inicializar ("Skipping initialization"). Por eso el chmod explícito.
for f in init.sql roles_microservicio.sql; do
    if [[ ! -f "$AQUI/$f" ]]; then
        cp "$AQUI/../$f" "$AQUI/$f"
        paso "copiado $f desde la carpeta padre"
    fi
    # 'a+r' sin condiciones: es idempotente y no toca los bits de escritura. No se intenta
    # detectar el modo actual porque es fácil equivocarse (600 y 644 empiezan igual).
    chmod a+r "$AQUI/$f" 2>/dev/null || sudo chmod a+r "$AQUI/$f"
done
paso "init.sql y roles_microservicio.sql legibles por el contenedor de Postgres."

# ── 4. Descargar imágenes ────────────────────────────────────────────────────
titulo "4/7 Descargando imágenes (públicas, sin login)"
docker compose -f "$COMPOSE" --env-file "$ENV_FILE" pull

# ── 5. Modelo facial (una vez; persiste en el volumen) ───────────────────────
titulo "5/7 Descargando el modelo facial (buffalo_l ~300 MB)"
paso "Tarda varios minutos y casi no imprime nada. Es normal."
docker run --rm -v "$VOLUMEN_MODELO:/root/.insightface" "$REGISTRY/sl-recognition:$VERSION" \
    python -c "from insightface.app import FaceAnalysis; FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']).prepare(ctx_id=0, det_size=(640, 640))"

# ── 6. Levantar el mini-stack ────────────────────────────────────────────────
titulo "6/7 Levantando el kiosko"
# Postgres primero: si el volumen viene de una instalación anterior cuyo .env ya no está,
# su rol 'root' tiene la contraseña vieja y hay que realinearla ANTES del resto.
docker compose -f "$COMPOSE" --env-file "$ENV_FILE" up -d kiosk_postgres
if $realinear_password; then
    paso "Realineando la contraseña de la BD heredada..."
    listo=false
    for _ in $(seq 1 30); do
        if docker exec "$CONTENEDOR_PG" pg_isready -U root -d SL_ASISTENCIAS >/dev/null 2>&1; then
            listo=true; break
        fi
        sleep 1
    done
    if $listo; then
        # Por el socket local la imagen oficial autentica con 'trust': no hace falta
        # conocer la contraseña anterior.
        if docker exec "$CONTENEDOR_PG" psql -U root -d SL_ASISTENCIAS \
             -c "ALTER USER root WITH PASSWORD '$DB_PASSWORD';"; then
            paso "Contraseña de la BD realineada."
        else
            aviso "No se pudo realinear la contraseña; revisa 'docker logs $CONTENEDOR_PG'."
        fi
    else
        aviso "Postgres no aceptó conexiones a tiempo; no se pudo realinear la contraseña."
    fi
fi
if ! docker compose -f "$COMPOSE" --env-file "$ENV_FILE" up -d; then
    # Sin esto el usuario solo ve "dependency failed to start" y se queda sin la causa,
    # que casi siempre está en el log de postgres (init.sql, pg_cron, permisos del volumen).
    aviso "No se pudieron levantar todos los servicios. Estado y últimas líneas de cada uno:"
    docker compose -f "$COMPOSE" --env-file "$ENV_FILE" ps -a || true
    echo "── log de $CONTENEDOR_PG ──────────────────────────────────────────────"
    docker logs --tail 60 "$CONTENEDOR_PG" 2>&1 || true
    echo "── healthcheck de $CONTENEDOR_PG ──────────────────────────────────────"
    docker inspect --format '{{range .State.Health.Log}}exit={{.ExitCode}} {{.Output}}{{end}}' \
        "$CONTENEDOR_PG" 2>/dev/null | tail -5 || true
    echo "───────────────────────────────────────────────────────────────────────"
    fatal "El stack no arrancó. La causa está en las líneas de arriba (y en $LOG)."
fi
docker compose -f "$COMPOSE" --env-file "$ENV_FILE" ps

# ── 7. Health + primer sync del padrón ───────────────────────────────────────
titulo "7/7 Esperando a que el kiosko esté listo"
ok=false
for intento in $(seq 1 40); do
    # Sin 'curl | grep -q': grep cierra la tubería al primer match y curl puede morir con
    # SIGPIPE, que con pipefail haría fallar la comprobación aunque el kiosko esté sano.
    salud="$(curl -fsS -m 3 http://localhost:8100/health 2>/dev/null || true)"
    if [[ "$salud" == *'"status":"ok"'* ]]; then
        ok=true
        paso "kiosk_local responde OK (intento $intento)."
        break
    fi
    sleep 3
done
if ! $ok; then
    aviso "El kiosko no respondió a tiempo. Mira los logs con:
       docker compose -f \"$COMPOSE\" --env-file \"$ENV_FILE\" logs --tail 50"
else
    paso "Bajando el padrón por primera vez..."
    if curl -fsS -m 180 -X POST http://localhost:8100/kiosk/roster/sync; then
        echo
        paso "Padrón descargado."
    else
        aviso "No se pudo bajar el padrón (¿credenciales/URL?). Reintenta desde la app."
    fi
fi

# ── 8. La app (Electron), si se pasó su .deb ─────────────────────────────────
# El instalador de Windows hace esto solo (#define FrontUrl). Aquí es opcional porque
# necesita sudo y no siempre se instala la app en la misma pasada que el backend.
if [[ -n "$FRONT_URL" ]]; then
    titulo "8/8 Instalando la aplicación"
    deb="$(mktemp -d)/sl-asistencias.deb"
    if curl -fL --progress-bar -o "$deb" "$FRONT_URL"; then
        # apt (no dpkg) para que resuelva las dependencias de Electron por su cuenta.
        if sudo apt install -y "$deb"; then
            paso "Aplicación instalada."
        else
            aviso "No se pudo instalar el .deb. Hazlo a mano: sudo apt install $deb"
        fi
    else
        aviso "No se pudo descargar la aplicación desde $FRONT_URL"
    fi
fi

printf '\n\033[1;32m== Instalación completa ==\033[0m\n'
echo "El kiosko escucha en http://localhost:8100 (la app apunta ahí)."
echo "Log de esta instalación: $LOG"
echo "Parar:    docker compose -f \"$COMPOSE\" --env-file \"$ENV_FILE\" down"
echo "Arrancar: docker compose -f \"$COMPOSE\" --env-file \"$ENV_FILE\" up -d"
echo "Para que arranque solo al encender: sudo systemctl enable --now docker"
