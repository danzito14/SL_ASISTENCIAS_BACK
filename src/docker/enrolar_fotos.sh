#!/usr/bin/env bash
# ============================================================================
# enrolar_fotos.sh — Registra rostros EN LOTE desde una carpeta de fotos.
#
# Cada archivo se llama con el id de la persona:
#   · modo 'emp'  (default): el nombre es el N° de empleado SYS21 (id_emp).
#                 Se resuelve a id_trabajador por (id_emp, empresa, area).
#   · modo 'trab': el nombre es el id interno (id_trabajador). Se usa directo.
#
# Para cada foto llama a POST /trabajadores/{id}/embedding/foto (workers), que
# detecta la cara, valida y guarda el embedding. 409 = ya tenía rostro (se salta).
#
# Corre EN EL VPS (o donde alcances el gateway). Requiere: bash, curl, python3.
#   chmod +x enrolar_fotos.sh && ./enrolar_fotos.sh
# Override del API:  API=https://sl-asistencias.slagricola.cloud/api ./enrolar_fotos.sh
# ============================================================================
set -euo pipefail

API="${API:-https://sl-asistencias.slagricola.cloud/api}"

# ── Datos (se piden interactivos) ───────────────────────────────────────────
read -rp "Ruta de la carpeta de fotos: " DIR
read -rp "id_empresa: " EMPRESA
read -rp "id_area: " AREA
read -rp "El nombre del archivo es N° de empleado (emp) o id interno (trab)? [emp]: " TIPOID
TIPOID="${TIPOID:-emp}"
read -rp "Usuario admin: " USUARIO
read -rsp "Password: " PASSWD; echo

[ -d "$DIR" ] || { echo "ERROR: no existe la carpeta: $DIR"; exit 1; }

# ── Login → token ───────────────────────────────────────────────────────────
TOKEN=$(curl -s -X POST "$API/usuarios/login" -H 'Content-Type: application/json' \
  -d "{\"nombre_usuario\":\"$USUARIO\",\"contrasena\":\"$PASSWD\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)
[ -n "${TOKEN:-}" ] || { echo "ERROR: login falló (usuario/clave)."; exit 1; }
echo "Login OK."

# ── Recorrer las fotos ──────────────────────────────────────────────────────
shopt -s nullglob nocaseglob
fotos=( "$DIR"/*.jpg "$DIR"/*.jpeg "$DIR"/*.png )
[ ${#fotos[@]} -gt 0 ] || { echo "No se encontraron .jpg/.jpeg/.png en $DIR"; exit 1; }
echo "Encontradas ${#fotos[@]} fotos. Empresa=$EMPRESA Area=$AREA Modo=$TIPOID"
read -rp "¿Continuar? [s/N]: " OK; [ "${OK,,}" = "s" ] || { echo "Cancelado."; exit 0; }

ok=0; skip=0; fail=0
for f in "${fotos[@]}"; do
  base=$(basename "$f")
  idfile="${base%.*}"                 # nombre sin extensión = id
  ext="${base##*.}"; ext="${ext,,}"
  case "$ext" in png) ct=image/png ;; *) ct=image/jpeg ;; esac

  # 1) Resolver id_trabajador
  if [ "$TIPOID" = "trab" ]; then
    idtrab="$idfile"
  else
    idtrab=$(curl -s "$API/trabajadores?id_emp=$idfile&id_empresa=$EMPRESA&id_area=$AREA&limit=100" \
      -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
try: d=json.load(sys.stdin)
except Exception: d=[]
m=[t for t in d if str(t.get('id_emp'))=='$idfile']
print(m[0]['id_trabajador'] if len(m)==1 else '')" 2>/dev/null || true)
  fi

  if [ -z "${idtrab:-}" ]; then
    echo "SKIP  $base — no se resolvió un trabajador único (id_emp=$idfile, empresa=$EMPRESA, area=$AREA)"
    skip=$((skip+1)); continue
  fi

  # 2) Subir la foto → registrar embedding
  code=$(curl -s -o /tmp/enrol_resp.json -w "%{http_code}" -X POST \
    "$API/trabajadores/$idtrab/embedding/foto" \
    -H "Authorization: Bearer $TOKEN" \
    -F "foto=@$f;type=$ct")

  case "$code" in
    201) echo "OK    $base → trabajador $idtrab"; ok=$((ok+1)) ;;
    409) echo "YA    $base → trabajador $idtrab (ya tenía rostro)"; skip=$((skip+1)) ;;
    *)   msg=$(python3 -c "import json;print(json.load(open('/tmp/enrol_resp.json')).get('detail',''))" 2>/dev/null || true)
         echo "FAIL  $base → trabajador $idtrab [HTTP $code] ${msg}"; fail=$((fail+1)) ;;
  esac
done

echo "────────────────────────────────────────"
echo "Terminado.  OK=$ok  SALTADOS=$skip  FALLIDOS=$fail  (total ${#fotos[@]})"
