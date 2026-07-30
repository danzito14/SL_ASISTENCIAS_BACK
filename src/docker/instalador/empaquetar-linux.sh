#!/usr/bin/env bash
# empaquetar-linux.sh — Genera el instalador de UN SOLO ARCHIVO para Linux.
#
# Es el equivalente de compilar SL-Asistencias.iss con Inno Setup: produce
# SL-Asistencias-Instalador-<version>.run, autoextraíble, que pregunta lo mismo que el
# wizard de Windows —con ventanas si hay escritorio y por consola si no.
#
# OJO: se ejecuta desde una TERMINAL (./archivo.run). GNOME/Nautilus NO ejecuta scripts al
# doble clic: los abre en el editor de texto (se ve el payload binario y un aviso de
# "Invalid Characters Detected"). Desde el explorador funciona con clic derecho →
# "Ejecutar como programa".
#
# Requisitos:  sudo apt install makeself
# Uso:         ./empaquetar-linux.sh [version] [--front-url URL]
#              La URL del front queda HORNEADA en el .run, así el cliente no la teclea.
#              Sin --front-url se usa la de FRONT_URL de abajo (actualízala por release).
set -Eeuo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${1:-1.1.2}"; shift || true
# .deb de la app (Electron) que el .run descargará e instalará. Cumple el mismo papel que
# el '#define FrontUrl' del .iss en Windows: actualízalo en CADA release del front, porque
# el escáner offline solo funciona con un front que traiga el cambio de scannerUrl.
FRONT_URL="https://github.com/danzito14/FP_ESCANER_FRONT/releases/download/0.2.7_Linux/SL-Asistencias-Estacion-0.2.7.deb"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --front-url) FRONT_URL="$2"; shift 2 ;;
        *) echo "Parámetro desconocido: $1" >&2; exit 1 ;;
    esac
done

command -v makeself >/dev/null 2>&1 || {
    echo "Falta makeself. Instálalo con: sudo apt install makeself" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Mismos archivos que [Files] del .iss: compose + instalador + esquema + roles.
cp "$AQUI/docker-compose.desktop.yml" "$AQUI/instalar.sh" "$AQUI/arranque.sh" "$STAGE/"
cp "$AQUI/../init.sql" "$AQUI/../roles_microservicio.sql" "$STAGE/"
chmod +x "$STAGE/instalar.sh" "$STAGE/arranque.sh"

SALIDA="$AQUI/Output/SL-Asistencias-Instalador-$VERSION.run"
mkdir -p "$AQUI/Output"

# --notemp NO: queremos que extraiga en temporal; arranque.sh copia a /opt (ver su cabecera).
makeself --gzip --nooverwrite \
    "$STAGE" "$SALIDA" \
    "SL Asistencias - Kiosko $VERSION" \
    ./arranque.sh ${FRONT_URL:+--front-url "$FRONT_URL"}

chmod +x "$SALIDA"
echo
echo "Listo: $SALIDA"
echo "Se ejecuta DESDE UNA TERMINAL:  ./$(basename "$SALIDA")"
echo "(al doble clic, GNOME lo abre en el editor de texto; ahí usa clic derecho →"
echo " 'Ejecutar como programa')"
