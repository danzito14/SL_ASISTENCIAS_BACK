# app/routers/intento_acceso.py
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from src.core.auth import exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.models.Rol_Usuario_Model import Usuario
from src.schemas.IntentoAcceso_Schema import IntentoAccesoResponse, IntentoAccesoUpdate, TipoIntento
from src.services.IntentoAcceso_Service import intento_acceso_service

router = APIRouter(prefix="/intentos", tags=["Intentos de acceso"])


# ── Listar intentos de acceso ─────────────────────────────────────────────────
@router.get(
    "",
    response_model=list[IntentoAccesoResponse],
    summary="Listar intentos de acceso rechazados",
    description="Intentos rechazados en las puertas (spoofing, desconocido, otra "
                "empresa), acotados a la empresa del usuario. El super-admin ve todos.",
)
def listar_intentos(
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    tipo: TipoIntento | None = Query(None, description="Filtrar por tipo."),
    id_puerta: int | None = Query(None, description="Filtrar por puerta."),
    db: Session = Depends(get_db),
):
    return intento_acceso_service.listar(
        db=db, id_empresa=id_empresa, skip=skip, limit=limit, tipo=tipo, id_puerta=id_puerta
    )


# ── Obtener un intento por id ─────────────────────────────────────────────────
@router.get(
    "/{id_intento}",
    response_model=IntentoAccesoResponse,
    summary="Obtener intento de acceso",
    description="Devuelve un intento por su id.",
)
def obtener_intento(
    id_intento: UUID,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, intento_acceso_service.empresa_de_intento(id_intento, db))
    return intento_acceso_service.obtener(id_intento=id_intento, db=db)


# ── Actualizar intento (estado de revisión) ───────────────────────────────────
@router.put(
    "/{id_intento}",
    response_model=IntentoAccesoResponse,
    summary="Actualizar intento de acceso",
    description="Actualiza el estado de un intento. Marcar 'justificada' un intento "
                "'otra_empresa' crea una asistencia manual (entrada) con la puerta/empresa "
                "del intento y marca la incidencia 'acceso_otra_empresa' ligada.",
)
def actualizar_intento(
    id_intento: UUID,
    datos: IntentoAccesoUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Encapsulación: el intento (su puerta) debe ser de tu empresa.
    exigir_empresa(usuario, intento_acceso_service.empresa_de_intento(id_intento, db))
    return intento_acceso_service.actualizar(id_intento=id_intento, datos=datos, db=db)


# ── Foto del intento (protegida) ──────────────────────────────────────────────
@router.get(
    "/{id_intento}/foto",
    summary="Foto del intento de acceso",
    description="Devuelve la imagen del rostro del intento (JPEG). Requiere permiso "
                "de lectura y que el intento sea de tu empresa.",
    responses={
        200: {"content": {"image/jpeg": {}}, "description": "Imagen JPEG."},
        404: {"description": "El intento no existe o no tiene foto."},
    },
)
def foto_intento(
    id_intento: UUID,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, intento_acceso_service.empresa_de_intento(id_intento, db))
    data = intento_acceso_service.foto_bytes(id_intento, db)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Este intento no tiene foto.",
        )
    return Response(content=data, media_type="image/jpeg")
