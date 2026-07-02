# offline_sync/routers/Sync_Router.py
import hashlib
import logging
import os

from fastapi import (APIRouter, Depends, File, HTTPException, Query, Request,
                     UploadFile, status)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from src.core.auth import resolver_empresa_scope, usuario_actual
from src.core.config import settings
from src.core.pgdb import get_db
from src.schemas.Candidatos_Schema import CandidatosResponse
from src.schemas.Enrolamiento_Schema import EnrolamientoRequest, EnrolamientoResponse
from src.schemas.Ingesta_Schema import IngestaResponse
from src.schemas.Roster_Schema import RosterResponse
from src.services.Enrolamiento_Service import enrolamiento_service
from src.services.Ingesta_Service import ingesta_service
from src.services.Roster_Service import roster_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/off_sync", tags=["Offline Sync"])

# Modelos ONNX que el APK puede bajar en su 1er arranque (whitelist = anti path-traversal).
_MODELOS_APK = {"w600k_r50.onnx", "2.7_80x80_MiniFASNetV2.onnx"}

# Cache de metadata por modelo (sha256 de 167MB cuesta ~1s → se calcula 1 vez y se
# invalida si cambia mtime/tamaño). version = huella estable para que el APK detecte
# cuándo el modelo del server cambió y re-descargue.
_MODELO_META: dict[str, dict] = {}


def _meta_modelo(nombre: str) -> dict:
    ruta = os.path.join(settings.MODELOS_DIR, nombre)
    if not os.path.isfile(ruta):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"modelo '{nombre}' no está en el servidor")
    st = os.stat(ruta)
    c = _MODELO_META.get(nombre)
    if not c or c["mtime"] != st.st_mtime or c["tamano"] != st.st_size:
        h = hashlib.sha256()
        with open(ruta, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        c = {"mtime": st.st_mtime, "tamano": st.st_size, "sha256": h.hexdigest(),
             "version": f"{int(st.st_mtime)}-{st.st_size}"}
        _MODELO_META[nombre] = c
    return {"nombre": nombre, "tamano": c["tamano"], "sha256": c["sha256"], "version": c["version"]}


# ── Bajada: roster para reconocer offline ─────────────────────────────────────
@router.get(
    "/roster",
    response_model=RosterResponse,
    summary="Roster (trabajadores + embeddings + áreas + puertas) para operar offline",
    description="Acotado a la empresa del usuario kiosko y al `tipo` del dispositivo "
                "(campo|oficina|empaque). Regla A: estricto por tipo de área + 'super'.",
)
def obtener_roster(
    request: Request,
    tipo: str = Query(..., description="Tipo de fichaje del dispositivo: campo | oficina | empaque"),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    db: Session = Depends(get_db),
):
    principal = usuario_actual(request)
    empresa = id_empresa if id_empresa is not None else principal.empresa
    if empresa is None or empresa == settings.EMPRESA_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Indica una empresa concreta (?id_empresa=) para bajar su roster.",
        )
    t = tipo.strip().lower()
    if t not in settings.roster_tipos_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"tipo inválido '{tipo}'. Válidos: {sorted(settings.roster_tipos_set)}.",
        )
    return roster_service.construir_roster(db, empresa, t)


# ── Bajada: candidatos a enrolar (trabajadores SIN rostro) ────────────────────
@router.get(
    "/candidatos",
    response_model=CandidatosResponse,
    summary="Trabajadores activos SIN rostro (para elegir a quién ponerle cara)",
    description="Acotado a la empresa del usuario. El APK los baja para que el operador "
                "elija uno y le asigne el rostro (POST /off_sync/enrolamientos con id_trabajador).",
)
def listar_candidatos(
    request: Request,
    tipo: str | None = Query(None, description="Filtrar por tipo de área: campo | oficina | empaque"),
    nombre: str | None = Query(None, description="Buscar por nombre/apellido (parcial)"),
    limite: int = Query(200, ge=1, le=1000),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    db: Session = Depends(get_db),
):
    principal = usuario_actual(request)
    empresa = id_empresa if id_empresa is not None else principal.empresa
    if empresa is None or empresa == settings.EMPRESA_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Indica una empresa concreta (?id_empresa=) para listar candidatos.",
        )
    t = tipo.strip().lower() if tipo else None
    if t and t not in settings.roster_tipos_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"tipo inválido '{tipo}'. Válidos: {sorted(settings.roster_tipos_set)}.",
        )
    return roster_service.listar_candidatos(db, empresa, t, nombre, limite)


# ── Subida: asistencias (CSV) ─────────────────────────────────────────────────
@router.post(
    "/asistencias",
    response_model=IngestaResponse,
    summary="Subir asistencias capturadas offline (CSV, bulk idempotente)",
    description="CSV: id_asistencia,id_trabajador,id_puerta,id_empresa,tipo_registro,"
                "creado_en_cliente,confianza_biometrica,dentro_de_area,id_dispositivo_origen,"
                "latitud,longitud. Re-subir el mismo archivo NO duplica.",
)
async def subir_asistencias(
    request: Request,
    archivo: UploadFile = File(..., description="CSV de asistencias"),
    db: Session = Depends(get_db),
):
    principal = usuario_actual(request)
    contenido = (await archivo.read()).decode("utf-8-sig")
    return ingesta_service.ingerir_asistencias(db, contenido, principal)


# ── Subida: intentos rechazados (CSV) ─────────────────────────────────────────
@router.post(
    "/intentos",
    response_model=IngestaResponse,
    summary="Subir intentos rechazados offline (CSV, bulk idempotente)",
    description="CSV: id_intento,id_puerta,id_empresa,tipo,id_trabajador,similitud,"
                "creado_en_cliente,id_dispositivo_origen,latitud,longitud. "
                "tipo ∈ spoofing|desconocido|otra_empresa.",
)
async def subir_intentos(
    request: Request,
    archivo: UploadFile = File(..., description="CSV de intentos de acceso"),
    db: Session = Depends(get_db),
):
    principal = usuario_actual(request)
    contenido = (await archivo.read()).decode("utf-8-sig")
    return ingesta_service.ingerir_intentos(db, contenido, principal)


# ── Subida: enrolamientos walk-in (JSON) ──────────────────────────────────────
@router.post(
    "/enrolamientos",
    response_model=EnrolamientoResponse,
    summary="Enrolar rostros desde el APK: asignar a existente o walk-in (JSON)",
    description="Dos modos por item: con `id_trabajador` ASIGNA el rostro a un "
                "trabajador existente (p.ej. de SYS21 sin cara); sin él, crea un "
                "WALK-IN (id_emp=id_local, origen 'apk'). Embedding 512-D, idempotente.",
)
def subir_enrolamientos(
    request: Request,
    body: EnrolamientoRequest,
    db: Session = Depends(get_db),
):
    principal = usuario_actual(request)
    return enrolamiento_service.enrolar(db, body.items, principal)


# ── Bajada: modelos ONNX para el APK (descarga en el 1er arranque) ────────────
@router.get(
    "/modelo/{nombre}",
    summary="Descargar un modelo ONNX para el APK (no se hornea en el APK)",
    description="El APK baja aquí w600k_r50.onnx (reconocimiento) y "
                "2.7_80x80_MiniFASNetV2.onnx (anti-spoof) en su 1er arranque, junto al "
                "roster. Soporta descarga parcial (Range) para reanudar. Solo la whitelist.",
)
def descargar_modelo(nombre: str):
    if nombre not in _MODELOS_APK:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="modelo no disponible")
    ruta = os.path.join(settings.MODELOS_DIR, nombre)
    if not os.path.isfile(ruta):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"modelo '{nombre}' no está en el servidor")
    return FileResponse(ruta, media_type="application/octet-stream", filename=nombre)


@router.get(
    "/modelo/{nombre}/meta",
    summary="Tamaño + sha256 + versión del modelo (el APK verifica la descarga)",
    description="El APK compara el tamaño/versión contra lo que tiene en disco para "
                "saber si debe (re)descargar, y usa el sha256 para verificar integridad.",
)
def modelo_meta(nombre: str):
    if nombre not in _MODELOS_APK:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="modelo no disponible")
    return _meta_modelo(nombre)


# ── Estado/config del servicio ────────────────────────────────────────────────
@router.get("/estado", summary="Salud y configuración del servicio de sync")
def estado():
    return {
        "status": "ok",
        "service": "offline_sync",
        "version": settings.APP_VERSION,
        "roster_incluir_general": settings.ROSTER_INCLUIR_GENERAL,
        "tipos": sorted(settings.roster_tipos_set),
    }
