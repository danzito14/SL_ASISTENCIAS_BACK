# app/api/v1/endpoints/scanner.py
import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.pgdb import get_db
from src.schemas.AreaTrabajo_Trabajador import TrabajadorBrief
from src.schemas.Asistencia_HistorialAuditoria import ScanResponse
from src.services.scanner_service import facial_service

router = APIRouter(prefix="/scanner", tags=["Scanner"])

# ── Límite de verificaciones faciales concurrentes ────────────────────────────
# El reconocimiento (InsightFace/ONNX) es pesado de CPU. Este semáforo permite
# como máximo 3 verificaciones corriendo al mismo tiempo; las peticiones extra
# esperan en cola hasta que se libere un cupo. Es compartido por todos los
# endpoints de acceso porque todos compiten por la misma CPU y el mismo modelo.
MAX_VERIFICACIONES_CONCURRENTES = 3
_sem_verificacion = asyncio.Semaphore(MAX_VERIFICACIONES_CONCURRENTES)


# ── Respuesta del endpoint de identificación (sin registrar asistencia) ───────
class IdentificacionResponse(BaseModel):
    reconocido: bool
    mensaje: str
    trabajador: TrabajadorBrief | None = None
    similitud: float | None = None
    calidad_deteccion: float | None = None


# ── 1. Identificar (solo reconocer, sin registrar asistencia) ─────────────────
@router.post(
    "/identificar",
    response_model=IdentificacionResponse,
    summary="Identificar trabajador por rostro",
    description=(
        "Abre la cámara, detecta el rostro y lo busca en la BD. "
        "Solo informa quién es; NO registra asistencia. "
        "Presiona ESPACIO para capturar o ESC para cancelar."
    ),
)
def identificar(
    camara_id: int = 0,
    db: Session = Depends(get_db),
):
    # 1. Capturar frame desde la cámara
    frame = facial_service.capturar_desde_camara(camara_id=camara_id)
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se capturó ningún frame. Cámara no disponible o captura cancelada.",
        )

    # 2. Detectar rostro y extraer embedding
    cara = facial_service.detectar_y_extraer(frame)
    if cara is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se detectó ningún rostro en el frame capturado.",
        )

    # 3. Buscar el rostro en la BD
    match = facial_service.buscar_en_bd(cara["embedding"], db)
    if match is None:
        return IdentificacionResponse(
            reconocido=False,
            mensaje="Rostro no reconocido en el sistema.",
            calidad_deteccion=round(cara["det_score"], 4),
        )

    trabajador = match["trabajador"]
    similitud = match["similitud"]
    return IdentificacionResponse(
        reconocido=True,
        mensaje=f"Identificado: {trabajador.nombre} {trabajador.apellido} (similitud: {similitud:.2%}).",
        trabajador=TrabajadorBrief.model_validate(trabajador),
        similitud=round(similitud, 4),
        calidad_deteccion=round(cara["det_score"], 4),
    )


# ── 2. Acceso (pipeline completo: reconoce y registra asistencia) ─────────────
@router.post(
    "/acceso",
    response_model=ScanResponse,
    summary="Registrar acceso por rostro",
    description=(
        "Abre la cámara, reconoce al trabajador y registra la asistencia. "
        "Requiere que la puerta exista en la BD."
    ),
)
def acceso(
    id_puerta: int,
    tipo_registro: str = "entrada",
    id_dispositivo: int | None = None,
    camara_id: int = 0,
    latitud: float | None = None,
    longitud: float | None = None,
    db: Session = Depends(get_db),
):
    frame = facial_service.capturar_desde_camara(camara_id=camara_id)
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se capturó ningún frame. Cámara no disponible o captura cancelada.",
        )

    return facial_service.procesar_frame_acceso(
        frame=frame,
        id_puerta=id_puerta,
        tipo_registro=tipo_registro,
        id_dispositivo=id_dispositivo,
        db=db,
        latitud=latitud,
        longitud=longitud,
    )


# ── Helper: decodifica la foto subida a un frame de OpenCV ────────────────────
async def _leer_foto(foto: UploadFile):
    if not (foto.content_type or "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El archivo debe ser una imagen. Recibido: {foto.content_type}.",
        )
    frame = facial_service.leer_imagen(await foto.read())
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo leer la imagen. Formato inválido o archivo corrupto.",
        )
    return frame


# ── 3. Identificar desde una foto subida (sin registrar asistencia) ───────────
@router.post(
    "/identificar/foto",
    response_model=IdentificacionResponse,
    summary="Identificar trabajador desde una foto",
    description="Recibe una imagen, detecta el rostro y lo busca en la BD. NO registra asistencia.",
)
async def identificar_foto(
    foto: UploadFile = File(..., description="Imagen del rostro (JPEG/PNG)"),
    db: Session = Depends(get_db),
):
    frame = await _leer_foto(foto)

    cara = facial_service.detectar_y_extraer(frame)
    if cara is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se detectó ningún rostro en la imagen.",
        )

    match = facial_service.buscar_en_bd(cara["embedding"], db)
    if match is None:
        return IdentificacionResponse(
            reconocido=False,
            mensaje="Rostro no reconocido en el sistema.",
            calidad_deteccion=round(cara["det_score"], 4),
        )

    trabajador = match["trabajador"]
    similitud = match["similitud"]
    return IdentificacionResponse(
        reconocido=True,
        mensaje=f"Identificado: {trabajador.nombre} {trabajador.apellido} (similitud: {similitud:.2%}).",
        trabajador=TrabajadorBrief.model_validate(trabajador),
        similitud=round(similitud, 4),
        calidad_deteccion=round(cara["det_score"], 4),
    )


# ── 4. Acceso desde una foto subida (reconoce y registra asistencia) ──────────
@router.post(
    "/acceso/foto",
    response_model=ScanResponse,
    summary="Registrar acceso desde una foto",
    description=(
        "Recibe una imagen, reconoce al trabajador y registra la asistencia. "
        "Requiere que la puerta exista en la BD."
    ),
)
async def acceso_foto(
    id_puerta: int,
    foto: UploadFile = File(..., description="Imagen del rostro (JPEG/PNG)"),
    tipo_registro: str = "entrada",
    id_dispositivo: int | None = None,
    latitud: float | None = None,
    longitud: float | None = None,
    db: Session = Depends(get_db),
):
    frame = await _leer_foto(foto)

    # Comparte el mismo tope de 3 verificaciones concurrentes que /acceso/liveness.
    async with _sem_verificacion:
        return await run_in_threadpool(
            facial_service.procesar_frame_acceso,
            frame=frame,
            id_puerta=id_puerta,
            tipo_registro=tipo_registro,
            id_dispositivo=id_dispositivo,
            db=db,
            latitud=latitud,
            longitud=longitud,
        )


# ── 5. Acceso con liveness multi-frame (varias fotos) ─────────────────────────
@router.post(
    "/acceso/liveness",
    response_model=ScanResponse,
    summary="Registrar acceso con prueba de vida (multi-frame)",
    description=(
        "Recibe varias fotos (3-5) tomadas con poca diferencia de tiempo, valida "
        "que sean de una persona viva (misma persona + movimiento entre frames), "
        "reconoce al trabajador y registra la asistencia. Requiere que la puerta exista."
    ),
)
async def acceso_liveness(
    id_puerta: int,
    fotos: list[UploadFile] = File(..., description="3 a 5 imágenes del rostro (JPEG/PNG)"),
    tipo_registro: str = "entrada",
    id_dispositivo: int | None = None,
    latitud: float | None = None,
    longitud: float | None = None,
    db: Session = Depends(get_db),
):
    if len(fotos) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Envía al menos 2 fotos (recomendado 3-5) para validar la prueba de vida.",
        )

    frames = [await _leer_foto(foto) for foto in fotos]

    # Máx. 3 verificaciones a la vez; las demás esperan aquí su turno.
    # run_in_threadpool saca el trabajo de CPU del event loop para no bloquear
    # al resto de peticiones del servidor.
    async with _sem_verificacion:
        return await run_in_threadpool(
            facial_service.procesar_frames_acceso,
            frames=frames,
            id_puerta=id_puerta,
            tipo_registro=tipo_registro,
            id_dispositivo=id_dispositivo,
            db=db,
            latitud=latitud,
            longitud=longitud,
        )
