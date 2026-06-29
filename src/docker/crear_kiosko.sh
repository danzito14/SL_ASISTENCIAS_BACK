#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  crear_kiosko.sh <empresa> <nombre_usuario> [password]                     ║
# ║                                                                            ║
# ║  Crea (idempotente) un usuario KIOSKO (rol 'escaneador') atado a UNA       ║
# ║  empresa, para que el APK haga login y baje SU roster. El token de ese rol ║
# ║  NO expira (ROLES_TOKEN_SIN_EXPIRACION). El hash se calcula DENTRO del     ║
# ║  contenedor identity, con el MISMO PBKDF2 que valida el login (sin drift). ║
# ║                                                                            ║
# ║  Uso (en el VPS, con el stack arriba):                                     ║
# ║    ./crear_kiosko.sh 1 kiosko_emp1            # genera password al azar     ║
# ║    ./crear_kiosko.sh 1 kiosko_emp1 'MiClave'  # password explícita          ║
# ║                                                                            ║
# ║  NOTA: si el usuario ya existe, ON CONFLICT no cambia su contraseña.        ║
# ║        Para cambiarla usa la API de identity (PUT /usuarios/{id}).          ║
# ╚══════════════════════════════════════════════════════════════════════════╝
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE="docker-compose.prod.yml"
DC="docker compose -f $COMPOSE"

EMPRESA="${1:-}"; USERNAME="${2:-}"; PASS="${3:-}"

case "$EMPRESA" in
  ''|*[!0-9]*) echo "Uso: $0 <empresa:entero> <nombre_usuario> [password]"; exit 1;;
esac
printf '%s' "$USERNAME" | grep -qE '^[A-Za-z0-9_]+$' \
  || { echo "nombre_usuario inválido (solo letras, números y _)."; exit 1; }

if [ -z "$PASS" ]; then
  PASS="$(openssl rand -hex 12 2>/dev/null || (head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-24))"
  GEN=1
fi

echo "==> Calculando hash en el contenedor identity (mismo algoritmo que el login)"
HASH="$($DC exec -T -e KPW="$PASS" identity \
        python -c "import os;from src.core.security import hash_password;print(hash_password(os.environ['KPW']))" \
        | tr -d '\r\n')"
[ -n "$HASH" ] || { echo "ERROR: no se pudo calcular el hash (¿identity está arriba?)."; exit 1; }

echo "==> Insertando usuario '$USERNAME' (empresa $EMPRESA, rol escaneador)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
USESC="$(printf '%s' "$USERNAME" | sed "s/'/''/g")"
HESC="$(printf '%s' "$HASH" | sed "s/'/''/g")"
# El heredoc expande $USESC/$HESC/$EMPRESA UNA vez; los '$' internos del hash
# (pbkdf2_sha256$240000$...) NO se re-expanden (resultado de expansión no se
# re-escanea), así que el literal entra intacto.
cat > "$TMP/kiosko.sql" <<EOF
SELECT setval('usuarios_id_usuario_seq', (SELECT COALESCE(MAX(id_usuario),0) FROM usuarios), true);
INSERT INTO usuarios (nombre_usuario, contrasena, id_rol, empresa, estado)
SELECT '$USESC', '$HESC', r.id_rol, $EMPRESA, 'activo'
  FROM roles r WHERE r.nombre_rol = 'escaneador'
ON CONFLICT (nombre_usuario) DO NOTHING;
SELECT u.id_usuario, u.nombre_usuario, u.empresa, r.nombre_rol
  FROM usuarios u JOIN roles r ON r.id_rol = u.id_rol
  WHERE u.nombre_usuario = '$USESC';
EOF
$DC exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -P pager=off' < "$TMP/kiosko.sql"

echo
echo "✔ Usuario kiosko listo."
echo "   usuario:  $USERNAME"
echo "   password: $PASS${GEN:+   (generada al azar — anótala, no se recupera)}"
echo "   empresa:  $EMPRESA    rol: escaneador (token sin expiración)"
