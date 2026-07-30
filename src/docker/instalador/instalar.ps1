# instalar.ps1 — Motor del instalador del kiosko de escritorio (perfil BÁSICA).
# Verifica Docker → pide URLs/credenciales de la empresa → genera .env con secretos
# aleatorios → descarga imágenes (públicas, sin token) → baja el modelo buffalo_l a un
# volumen → levanta el mini-stack → espera health → baja el padrón por primera vez.
# El Electron/NSIS puede invocarlo pasando los parámetros (no interactivo) o dejar que
# pregunte. Requiere Docker Desktop instalado y corriendo.

param(
    [string]$CloudUrl,                       # URL de la nube (ej. https://tu-dominio/api)
    [string]$KioskUser,                      # usuario del kiosko (rol escaneador)
    [string]$KioskPassword,                  # su contraseña
    [string]$Empresa,                        # id de empresa
    [string]$Tipo        = "oficina",        # campo | oficina | empaque | mixto
    [string]$Puerta      = "",               # id de puerta (int, opcional)
    [string]$Dispositivo = "",               # id de dispositivo (int, opcional; para auditar origen)
    [string]$Registry = "ghcr.io/danzito14", # namespace de las imágenes públicas
    [string]$Version  = "1.0.2"
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$compose = Join-Path $here "docker-compose.desktop.yml"

# Log a archivo: el wizard lo LEE en vivo y lo muestra bajo la barra (corre oculto).
try { Start-Transcript -Path (Join-Path $here "instalar.log") -Append -ErrorAction SilentlyContinue | Out-Null } catch {}

# Marcador de fin: el wizard corre este script sin esperar (ewNoWait) y sondea este
# archivo para saber cuándo terminó. El trap lo escribe también si algo falla, para que
# el wizard no se quede colgado esperando.
$marcador = Join-Path $here "instalar.done"
Remove-Item $marcador -ErrorAction SilentlyContinue
trap { "ERROR: $($_.Exception.Message)" | Out-File -FilePath $marcador -Encoding ascii; exit 1 }

# ── 1. Docker ────────────────────────────────────────────────────────────────
Write-Host "== 1/7 Verificando Docker ==" -ForegroundColor Cyan
try { docker info *> $null } catch {
    Write-Error "Docker no está instalado o no está corriendo. Instala Docker Desktop, ábrelo y reintenta."
    exit 1
}

# ── 2. Datos de la empresa (pregunta lo que no venga por parámetro) ──────────
Write-Host "== 2/7 Configuración ==" -ForegroundColor Cyan
if (-not $CloudUrl)      { $CloudUrl = Read-Host "URL de la nube (ej. https://tu-dominio/api)" }
if (-not $KioskUser)     { $KioskUser = Read-Host "Usuario del kiosko" }
if (-not $KioskPassword) {
    $sec = Read-Host "Contraseña del kiosko" -AsSecureString
    $KioskPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
if (-not $Empresa)       { $Empresa = Read-Host "ID de empresa" }

# ── 3. Secretos + .env (UTF-8 sin BOM, para docker compose --env-file) ───────
Write-Host "== 3/7 Generando secretos y .env ==" -ForegroundColor Cyan
function New-Secret { -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 40 | ForEach-Object {[char]$_}) }
$envPath = Join-Path $here ".env"

# El volumen de datos SOBREVIVE a desinstalar la app y a borrar las imágenes: Windows no
# ejecuta Docker al desinstalar. Si ya existe, Postgres conserva la contraseña con la que
# se INICIALIZÓ y ninguna nueva tendrá efecto (POSTGRES_PASSWORD solo aplica en un volumen
# vacío). Reinstalar generando secretos nuevos dejaba todo el stack con
# "password authentication failed for user root". Por eso: si hay volumen previo, se
# REUSAN los secretos del .env anterior y, si ese .env ya no está, se realinea el rol
# más abajo (paso 6) por el socket local, que en la imagen oficial es 'trust'.
$volumenDatos = "kiosk_kiosk_pgdata"
$volumenContenedor = "kiosk_postgres"
$volumenPrevio = [bool](docker volume ls -q --filter "name=^$volumenDatos$")

function Get-EnvValor([string]$ruta, [string]$clave) {
    if (-not (Test-Path $ruta)) { return $null }
    $m = Select-String -Path $ruta -Pattern "^$clave=(.*)$" | Select-Object -First 1
    if ($m) { return $m.Matches[0].Groups[1].Value }
    return $null
}
function Get-SecretoReusable([string]$clave) {
    if ($volumenPrevio) {
        $previo = Get-EnvValor $envPath $clave
        if ($previo) { return $previo }
    }
    return (New-Secret)
}

$dbPassword     = Get-SecretoReusable "KIOSK_DB_PASSWORD"
$dbPasswordNueva = $volumenPrevio -and ((Get-EnvValor $envPath "KIOSK_DB_PASSWORD") -ne $dbPassword)
if ($volumenPrevio) {
    Write-Host "   Detectado un volumen de datos previo ($volumenDatos): se conserva la BD."
}

$contenido = @"
# Generado por instalar.ps1 — NO subir a git. Contiene secretos de ESTA estación.
REGISTRY=$Registry
IMG_VERSION=$Version
KIOSK_DB_PASSWORD=$dbPassword
RECOGNITION_INTERNAL_TOKEN=$(Get-SecretoReusable "RECOGNITION_INTERNAL_TOKEN")
KIOSK_GATEWAY_TOKEN=$(Get-SecretoReusable "KIOSK_GATEWAY_TOKEN")
CLOUD_BASE_URL=$CloudUrl
KIOSK_USER=$KioskUser
KIOSK_PASSWORD=$KioskPassword
KIOSK_TIPO=$Tipo
KIOSK_EMPRESA=$Empresa
KIOSK_PUERTA=$Puerta
KIOSK_DISPOSITIVO=$Dispositivo
"@
[System.IO.File]::WriteAllText($envPath, $contenido, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "   .env creado en $envPath"

# El esquema + roles se montan en postgres: deben estar junto al compose (bundle del
# instalador). Si corres desde el repo, se copian de la carpeta docker padre.
foreach ($f in @("init.sql","roles_microservicio.sql")) {
    $dst = Join-Path $here $f
    if (-not (Test-Path $dst)) { Copy-Item (Join-Path $here ".." $f) $dst }
}

# ── 4. Descargar imágenes (públicas → sin login) ─────────────────────────────
Write-Host "== 4/7 Descargando imágenes ==" -ForegroundColor Cyan
docker compose -f $compose --env-file $envPath pull

# ── 5. Descargar el modelo facial (buffalo_l ~300 MB) al volumen, una vez ─────
Write-Host "== 5/7 Descargando el modelo facial (buffalo_l ~300 MB) ==" -ForegroundColor Cyan
docker run --rm -v kiosk_modelos_insightface:/root/.insightface "$Registry/sl-recognition:$Version" `
    python -c "from insightface.app import FaceAnalysis; FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']).prepare(ctx_id=0, det_size=(640, 640))"

# ── 6. Levantar el mini-stack ────────────────────────────────────────────────
Write-Host "== 6/7 Levantando el kiosko ==" -ForegroundColor Cyan
# Postgres primero: si el volumen venía de una instalación anterior cuyo .env ya no está,
# su rol 'root' tiene la contraseña vieja y hay que realinearla ANTES de levantar el resto.
docker compose -f $compose --env-file $envPath up -d kiosk_postgres
if ($dbPasswordNueva) {
    Write-Host "   Realineando la contraseña de la BD heredada..."
    $listo = $false
    foreach ($i in 1..30) {
        docker exec $volumenContenedor pg_isready -U root -d SL_ASISTENCIAS *> $null
        if ($?) { $listo = $true; break }
        Start-Sleep -Milliseconds 700
    }
    if ($listo) {
        # Por el socket local la imagen oficial autentica con 'trust', así que esto
        # funciona sin conocer la contraseña anterior.
        docker exec $volumenContenedor psql -U root -d SL_ASISTENCIAS `
            -c "ALTER USER root WITH PASSWORD '$dbPassword';" *> $null
        if ($?) { Write-Host "   Contraseña de la BD realineada." }
        else { Write-Warning "No se pudo realinear la contraseña de la BD; revisa los logs de $volumenContenedor." }
    } else {
        Write-Warning "Postgres no aceptó conexiones a tiempo; no se pudo realinear la contraseña."
    }
}
docker compose -f $compose --env-file $envPath up -d

# ── 7. Esperar health + primer sync del padrón ──────────────────────────────
Write-Host "== 7/7 Esperando a que el kiosko esté listo ==" -ForegroundColor Cyan
$ok = $false
foreach ($i in 1..40) {
    try {
        if ((Invoke-RestMethod "http://localhost:8100/health" -TimeoutSec 3).status -eq "ok") { $ok = $true; break }
    } catch {}
    Start-Sleep -Seconds 3
}
if (-not $ok) { Write-Warning "El kiosko no respondió a tiempo. Revisa: docker compose -f `"$compose`" logs" }
else {
    Write-Host "   Bajando el padrón por primera vez..."
    try {
        Invoke-RestMethod -Method Post "http://localhost:8100/kiosk/roster/sync" -TimeoutSec 180 | Out-Null
        Write-Host "   Padrón descargado."
    } catch {
        Write-Warning "No se pudo bajar el padrón (¿credenciales/URL?). Reintenta desde el front."
    }
}

Write-Host ""
Write-Host "== Instalación completa ==" -ForegroundColor Green
Write-Host "El kiosko escucha en http://localhost:8100 (el front apunta ahí)."
Write-Host "Para parar:   docker compose -f `"$compose`" down"
Write-Host "Para arrancar: docker compose -f `"$compose`" up -d"

# Fin OK: el wizard lo detecta y cierra la fase.
"OK" | Out-File -FilePath $marcador -Encoding ascii
