#!/usr/bin/env bash
# ============================================================================
# enrolar_fotos.sh — Registra rostros EN LOTE desde una carpeta de fotos.
#
# Cada archivo se llama con el N° de empleado (id_emp), p.ej. 01112.jpg,
# 100111.png. El script resuelve id_emp → id_trabajador y sube la foto a
#   POST /trabajadores/{id}/embedding/foto   (servicio workers)
# que detecta la cara, valida y GUARDA el embedding en ese trabajador.
#   · 201 = registrado   · 409 = ya tenía rostro (se salta)   · 422 = foto mala.
#
# empresa/área son OPCIONALES: solo hacen falta si un mismo id_emp aparece en
# varias empresas (ahí desambiguan). Si lo dejas en blanco, busca en todo tu
# alcance y exige que el id_emp sea ÚNICO.
#
# Corre EN EL VPS (o donde alcances el gateway). Requiere: bash, curl, python3.
#   chmod +x enrolar_fotos.sh && ./enrolar_fotos.sh
# Override del API:  API=https://sl-asistencias.slagricola.cloud/api ./enrolar_fotos.sh
# ============================================================================
set -euo pipefail
API="${API:-https://sl-asistencias.slagricola.cloud/api}"

read -rp "Ruta de la carpeta de fotos: " DIR
read -rp "id_empresa (Enter = todas): " EMPRESA
read -rp "id_area   (Enter = cualquiera): " AREA
read -rp "Usuario admin: " USUARIO
read -rsp "Password: " PASSWD; echo
[ -d "$DIR" ] || { echo "ERROR: no existe la carpeta: $DIR"; exit 1; }

# ── Login → token ───────────────────────────────────────────────────────────
TOKEN=$(curl -s -X POST "$API/usuarios/login" -H 'Content-Type: application/json' \
  -d "{\"nombre_usuario\":\"$USUARIO\",\"contrasena\":\"$PASSWD\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)
[ -n "${TOKEN:-}" ] || { echo "ERROR: login falló (usuario/clave)."; exit 1; }
echo "Login OK."

# Filtros opcionales para resolver el id_emp
Q=""
[ -n "${EMPRESA:-}" ] && Q="$Q&id_empresa=$EMPRESA"
[ -n "${AREA:-}" ]    && Q="$Q&id_area=$AREA"

# ── Recorrer las fotos ──────────────────────────────────────────────────────
shopt -s nullglob nocaseglob
fotos=( "$DIR"/*.jpg "$DIR"/*.jpeg "$DIR"/*.png )
[ ${#fotos[@]} -gt 0 ] || { echo "No se encontraron .jpg/.jpeg/.png en $DIR"; exit 1; }
echo "Encontradas ${#fotos[@]} fotos."
read -rp "¿Continuar? [s/N]: " OK; [ "${OK,,}" = "s" ] || { echo "Cancelado."; exit 0; }

ok=0; ya=0; skip=0; fail=0
for f in "${fotos[@]}"; do
  base=$(basename "$f")
  idemp="${base%.*}"                          # nombre sin extensión = N° de empleado
  ext="${base##*.}"; ext="${ext,,}"
  case "$ext" in png) ct=image/png ;; *) ct=image/jpeg ;; esac

  # 1) Resolver id_emp → id_trabajador (match EXACTO y ÚNICO)
  idtrab=$(curl -s "$API/trabajadores?id_emp=$idemp&limit=100$Q" \
    -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
try: d=json.load(sys.stdin)
except Exception: d=[]
m=[t for t in d if str(t.get('id_emp'))=='$idemp']
print(m[0]['id_trabajador'] if len(m)==1 else ('MULTI' if len(m)>1 else ''))" 2>/dev/null || true)

  if [ "${idtrab:-}" = "MULTI" ]; then
    echo "SKIP  $base — id_emp=$idemp coincide con VARIOS trabajadores (indica id_empresa)"
    skip=$((skip+1)); continue
  fi
  if [ -z "${idtrab:-}" ]; then
    echo "SKIP  $base — no hay trabajador con id_emp=$idemp"
    skip=$((skip+1)); continue
  fi

  # 2) Subir la foto → registrar embedding
  code=$(curl -s -o /tmp/enrol.json -w "%{http_code}" -X POST \
    "$API/trabajadores/$idtrab/embedding/foto" \
    -H "Authorization: Bearer $TOKEN" \
    -F "foto=@$f;type=$ct")

  case "$code" in
    201) echo "OK    $base → trabajador $idtrab"; ok=$((ok+1)) ;;
    409) echo "YA    $base → trabajador $idtrab (ya tenía rostro)"; ya=$((ya+1)) ;;
    *)   msg=$(python3 -c "import json;print(json.load(open('/tmp/enrol.json')).get('detail',''))" 2>/dev/null || true)
         echo "FAIL  $base → trabajador $idtrab [HTTP $code] ${msg}"; fail=$((fail+1)) ;;
  esac
done

echo "────────────────────────────────────────"
echo "Terminado.  OK=$ok  YA_TENÍAN=$ya  SALTADOS=$skip  FALLIDOS=$fail  (total ${#fotos[@]})"
