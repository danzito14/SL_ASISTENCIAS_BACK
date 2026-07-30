#!/usr/bin/env bash
# arranque.sh — Punto de entrada del instalador .run (makeself) de Linux.
#
# makeself extrae el paquete en un directorio TEMPORAL y lo borra al terminar. El kiosko
# necesita que el compose, el .env y los .sql sobrevivan (el stack se levanta y se opera
# desde ahí), así que este script primero copia el bundle a una ruta permanente y recién
# ahí ejecuta el instalador. Equivale a lo que hace Inno Setup con {app} en Windows.
set -Eeuo pipefail

DESTINO="${SL_DESTINO:-/opt/sl-asistencias}"
ORIGEN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Dueño de la instalación: el usuario REAL, no root. Si esto se lanzó con sudo, id -u da 0
# y todo quedaría de root: el .env (600) sería ilegible para el usuario normal y luego un
# 'docker compose ... --env-file .env' fallaría con "permission denied", que es justo lo
# que pasó en una instalación real. SUDO_USER conserva quién invocó realmente.
if [[ -n "${SUDO_USER:-}" ]] && [[ "$SUDO_USER" != "root" ]]; then
    DUENIO="$(id -u "$SUDO_USER"):$(id -g "$SUDO_USER")"
else
    DUENIO="$(id -u):$(id -g)"
fi

# Cómo pedir privilegios para escribir en /opt. Con doble clic desde el explorador NO hay
# terminal donde teclear la contraseña de sudo, así que ahí se usa pkexec, que abre el
# diálogo gráfico del sistema. Se eleva UNA sola vez (un único prompt), no por comando.
if sudo -n true 2>/dev/null || [[ -t 0 ]]; then
    ELEVAR=(sudo)
elif command -v pkexec >/dev/null 2>&1; then
    ELEVAR=(pkexec)
else
    echo "No hay forma de pedir permisos de administrador. Ejecútalo desde una terminal:" >&2
    echo "  ./$(basename "$0")" >&2
    exit 1
fi

echo "Instalando el motor del kiosko en $DESTINO ..."
# El dueño queda el usuario que instala, NO root: así el .env con los secretos es suyo y
# el kiosko se opera después sin sudo (con el usuario en el grupo docker).
"${ELEVAR[@]}" bash -c '
    set -Eeuo pipefail
    destino="$1"; origen="$2"; duenio="$3"
    install -d -m 0755 "$destino"
    cp -f "$origen"/docker-compose.desktop.yml "$origen"/instalar.sh \
          "$origen"/init.sql "$origen"/roles_microservicio.sql "$destino"/
    chown -R "$duenio" "$destino"
    # Modos EXPLÍCITOS, no heredados del umask de quien instala. Los .sql se montan en el
    # contenedor de Postgres, que corre como el usuario "postgres" (UID 999): si quedan en
    # 600, NO puede leerlos, la inicialización se aborta y el volumen queda con una BD
    # vacía. Y como initdb ya creó el directorio, los arranques siguientes dicen
    # "Skipping initialization" y el esquema NUNCA se crea. Pasó en una instalación real.
    chmod 0644 "$destino/init.sql" "$destino/roles_microservicio.sql" \
               "$destino/docker-compose.desktop.yml"
    chmod 0755 "$destino/instalar.sh"
' _ "$DESTINO" "$ORIGEN" "$DUENIO"

exec "$DESTINO/instalar.sh" "$@"
