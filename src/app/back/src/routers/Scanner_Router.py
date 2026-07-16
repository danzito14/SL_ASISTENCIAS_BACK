# app/routers/scanner.py
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.pgdb import get_db
from src.schemas.AreaTrabajo_Trabajador import TrabajadorBrief
from src.schemas.Asistencia_HistorialAuditoria import ScanResponse
from src.services.scanner_service import scanner_service
from src.services.Recognition_Service import recognition_service

router = APIRouter(prefix="/scanner", tags=["Scanner"])


class IdentificacionResponse(BaseModel):
    reconocido: bool
    mensaje: str
    trabajador: TrabajadorBrief | None = None
    similitud: float | None = None
    calidad_deteccion: float | None = None


async def _leer_bytes(foto: UploadFile) -> bytes:
    """Lee y valida la imagen subida. No la decodifica (eso lo hace recognition)."""
    if not (foto.content_type or "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El archivo debe ser una imagen. Recibido: {foto.content_type}.",
        )
    data = await foto.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La imagen está vacía.")
    return data


def _trab_brief(trab: dict) -> TrabajadorBrief:
    return TrabajadorBrief(id_trabajador=trab["id_trabajador"], nombre=trab["nombre"],
                           apellido=trab["apellido"], estado="activo")


# ── 1. Identificar desde una foto (sin registrar asistencia) ──────────────────
@router.post(
    "/identificar/foto",
    response_model=IdentificacionResponse,
    summary="Identificar trabajador desde una foto",
    description="Recibe una imagen, la manda a recognition y dice quién es. NO registra asistencia.",
)
async def identificar_foto(
    foto: UploadFile = File(..., description="Imagen del rostro (JPEG/PNG)"),
    db: Session = Depends(get_db),
):
    data = await _leer_bytes(foto)
    res = await run_in_threadpool(recognition_service.identificar, data, None)
    if res is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Servicio de reconocimiento no disponible.")
    det = res.get("det_score")
    if not res.get("reconocido"):
        mensaje = "No se detectó ningún rostro en la imagen." if res.get("estado") == "no_rostro" else "Rostro no reconocido en el sistema."
        return IdentificacionResponse(reconocido=False, mensaje=mensaje,
                                      calidad_deteccion=round(det, 4) if det is not None else None)
    trab = res["trabajador"]
    return IdentificacionResponse(
        reconocido=True,
        mensaje=f"Identificado: {trab['nombre']} {trab['apellido']} (similitud: {res['similitud']:.2%}).",
        trabajador=_trab_brief(trab),
        similitud=round(res["similitud"], 4),
        calidad_deteccion=round(det, 4) if det is not None else None,
    )


# ── 2. Acceso desde una foto (reconoce y registra asistencia) ─────────────────
@router.post(
    "/acceso/foto",
    response_model=ScanResponse,
    summary="Registrar acceso desde una foto",
    description="Recibe una imagen, reconoce al trabajador (vía recognition) y registra la asistencia.",
)
async def acceso_foto(
    id_puerta: int,
    foto: UploadFile = File(..., description="Imagen del rostro (JPEG/PNG)"),
    tipo_registro: str = "entrada",
    id_dispositivo: int | None = None,
    latitud: float | None = None,
    longitud: float | None = None,
    nombre_hint: str | None = None,
    db: Session = Depends(get_db),
):
    data = await _leer_bytes(foto)
    return await run_in_threadpool(
        scanner_service.procesar_foto_acceso,
        data, id_puerta, tipo_registro, id_dispositivo, db, latitud, longitud, nombre_hint,
    )


# ── 3. Acceso con liveness multi-frame (varias fotos) ─────────────────────────
@router.post(
    "/acceso/liveness",
    response_model=ScanResponse,
    summary="Registrar acceso con prueba de vida (multi-frame)",
    description="Recibe 3-5 fotos, valida liveness, reconoce y registra la asistencia (vía recognition).",
)
async def acceso_liveness(
    id_puerta: int,
    fotos: list[UploadFile] = File(..., description="3 a 5 imágenes del rostro (JPEG/PNG)"),
    tipo_registro: str = "entrada",
    id_dispositivo: int | None = None,
    latitud: float | None = None,
    longitud: float | None = None,
    nombre_hint: str | None = None,
    db: Session = Depends(get_db),
):
    if len(fotos) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Envía al menos 2 fotos (recomendado 3-5) para validar la prueba de vida.",
        )
    datos = [await _leer_bytes(f) for f in fotos]
    return await run_in_threadpool(
        scanner_service.procesar_fotos_acceso,
        datos, id_puerta, tipo_registro, id_dispositivo, db, latitud, longitud, nombre_hint,
    )
