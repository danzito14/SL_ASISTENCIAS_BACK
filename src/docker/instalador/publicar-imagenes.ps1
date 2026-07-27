# publicar-imagenes.ps1
# Construye y publica en GHCR las imágenes del perfil BÁSICA del kiosko de escritorio.
# Requisitos: haber hecho `docker login ghcr.io -u <usuario>` con un token write:packages.
# Uso:   .\publicar-imagenes.ps1                 (usa los defaults de abajo)
#        .\publicar-imagenes.ps1 -Namespace ghcr.io/miorg -Version 1.0.1
#
# Tras subir, marca CADA paquete como PÚBLICO en GitHub > tu perfil > Packages > (paquete)
# > Package settings > Change visibility > Public. Las imágenes NO llevan datos de la
# empresa (URLs/credenciales van en el .env de la instalación).

param(
    [string]$Namespace = "ghcr.io/danzito14",   # <-- ajusta a tu usuario/org de GitHub
    [string]$Version   = "1.0.0"
)
$ErrorActionPreference = "Stop"
$docker = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)  # -> src/docker

Write-Host "== 1/3 Construyendo imágenes (postgres + recognition LIGERA + kiosk_local) ==" -ForegroundColor Cyan
docker compose -f "$docker/docker-compose.prod.yml" build postgres
# recognition SIN hornear buffalo_l (imagen ligera): el modelo se baja en la instalación.
docker build --build-arg BAKE_MODEL=false -t sl-recognition:desktop "$docker/../app/recognition"
docker compose -f "$docker/docker-compose.local.yml" -p kiosk build kiosk_local

# Mapa imagen LOCAL -> imagen REMOTA (GHCR). postgres mantiene su tag pg17.
$map = [ordered]@{
    "pgvector-postgis:pg17" = "$Namespace/pgvector-postgis:pg17"
    "sl-recognition:desktop" = "$Namespace/sl-recognition:$Version"
    "sl-kiosk-local:latest" = "$Namespace/sl-kiosk-local:$Version"
}

Write-Host "== 2/3 Etiquetando y subiendo ==" -ForegroundColor Cyan
foreach ($local in $map.Keys) {
    $remote = $map[$local]
    Write-Host "   $local  ->  $remote"
    docker tag $local $remote
    docker push $remote
}

Write-Host "== 3/3 Listo ==" -ForegroundColor Green
Write-Host "Ahora marca cada paquete como PÚBLICO en GitHub > Packages." -ForegroundColor Yellow
Write-Host "Imágenes publicadas:"
$map.Values | ForEach-Object { Write-Host "   $_" }
