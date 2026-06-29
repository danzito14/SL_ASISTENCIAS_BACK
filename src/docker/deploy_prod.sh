#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  deploy_prod.sh — Despliegue/refresco IDEMPOTENTE del stack en el VPS.     ║
# ║                                                                            ║
# ║  Hace las cosas en el ORDEN correcto para evitar el gotcha conocido:       ║
# ║  cambiar POSTGRES_PASSWORD en .env hace que compose RECREE el contenedor   ║
# ║  postgres, y un ALTER ROLE hecho ANTES de ese recreate se pierde. Por eso  ║
# ║  primero se levanta el stack (postgres se estabiliza con el password       ║
# ║  final) y SOLO DESPUÉS se alinean los roles + CHECKPOINT.                   ║
# ║                                                                            ║
# ║  Correr en el VPS, desde esta carpeta (junto al compose y el .env):        ║
# ║    chmod +x deploy_prod.sh && ./deploy_prod.sh                             ║
# ║                                                                            ║
# ║  Requisitos: docker compose v2, .env con las claves FUERTES ya puestas.    ║
# ╚══════════════════════════════════════════════════════════════════════════╝
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE="docker-compose.prod.yml"
ENV_FILE=".env"
DC="docker compose -f $COMPOSE"

[ -f "$ENV_FILE" ] || { echo "ERROR: falta $ENV_FILE junto al compose."; exit 1; }

# Lee UNA variable del .env sin sourcear el archivo (evita romper con valores
# que traen & : @ ? = como las URLs de SYS21). Devuelve el texto tras el 1er '='.
getenv() { grep -E "^$1=" "$ENV_FILE" | head -n1 | cut -d= -f2- || true; }

PGUSER="$(getenv POSTGRES_USER)"; PGUSER="${PGUSER:-root}"
PGDB="$(getenv POSTGRES_DB)";     PGDB="${PGDB:-SL_ASISTENCIAS}"

# Roles que un servicio usa POR LA RED (deben coincidir BD↔.env). svc_access y
# app_cron NO se listan: hoy nadie conecta con ellos por password (backend usa
# root; pg_cron usa workers internos). Si algún día un servicio los usa, agrega
# su *_PASSWORD al .env y una línea aquí.
ROLE_MAP="SVC_IDENTITY_PASSWORD:svc_identity
SVC_RECOGNITION_PASSWORD:svc_recognition
SVC_TENANCY_PASSWORD:svc_tenancy
SVC_WORKERS_PASSWORD:svc_workers
SVC_REPORTS_PASSWORD:svc_reports
SVC_OFFLINE_PASSWORD:svc_offline"

echo "==> 1/6  Pre-flight: ¿quedan placeholders CAMBIAR_* en $ENV_FILE?"
if grep -qE "=CAMBIAR_" "$ENV_FILE"; then
  echo "    ⚠️  Hay valores CAMBIAR_* (cámbialos por claves fuertes antes de prod):"
  grep -nE "=CAMBIAR_" "$ENV_FILE" || true
fi

echo "==> 2/6  Levantar/actualizar el stack (build + up)"
$DC up -d --build

echo "==> 3/6  Esperar a que postgres acepte conexiones"
until $DC exec -T postgres pg_isready -U "$PGUSER" -d "$PGDB" >/dev/null 2>&1; do
  echo "    ...esperando postgres"; sleep 2
done
echo "    postgres OK"

echo "==> 4/6  Aplicar migraciones idempotentes (migrations/*.sql en orden)"
if ls migrations/*.sql >/dev/null 2>&1; then
  for f in $(ls migrations/*.sql | sort); do
    echo "    aplicando $f"
    $DC exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < "$f"
  done
else
  echo "    (sin migraciones)"
fi

echo "==> 5/6  Alinear contraseñas de roles BD ← .env (+ CHECKPOINT para que persista)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
{
  printf '%s\n' "$ROLE_MAP" | while IFS= read -r line; do
    [ -z "$line" ] && continue
    var="${line%%:*}"; role="${line##*:}"
    val="$(getenv "$var")"
    if [ -z "$val" ]; then echo "-- omitido $role ($var vacío en .env)"; continue; fi
    esc="$(printf '%s' "$val" | sed "s/'/''/g")"   # escapa comillas simples
    echo "ALTER ROLE $role PASSWORD '$esc';"
  done
  pgval="$(getenv POSTGRES_PASSWORD)"
  if [ -n "$pgval" ]; then
    pgesc="$(printf '%s' "$pgval" | sed "s/'/''/g")"
    echo "ALTER USER $PGUSER PASSWORD '$pgesc';"
  fi
  echo "CHECKPOINT;"
} > "$TMP/align.sql"
$DC exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < "$TMP/align.sql"
echo "    roles alineados"

echo "==> 6/6  Reiniciar servicios para que reconecten con las claves nuevas"
$DC restart identity recognition tenancy workers reports employee_monitoring offline_sync backend

echo "==> Verificación: que ningún contenedor quede en 'Restarting'"
for _ in $(seq 1 10); do
  n="$($DC ps --format '{{.Status}}' | grep -ci 'Restarting' || true)"
  [ "$n" = "0" ] && break
  echo "    $n en Restarting..."; sleep 3
done
$DC ps
echo
echo "✔ Deploy listo."
echo "  Siguiente: crear el/los usuario(s) kiosko →  ./crear_kiosko.sh <empresa> <usuario> [password]"
