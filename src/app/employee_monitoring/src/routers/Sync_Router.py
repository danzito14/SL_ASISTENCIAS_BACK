# employee_monitoring/routers/Sync_Router.py
"""
API del servicio de monitoreo. Prefijo propio /sync (no colisiona con los
endpoints públicos /trabajadores y /embeddings, que son de workers).

Scopes (derivados del primer segmento del path → recurso 'sync'):
  - GET  → sync:read
  - POST/PATCH → sync:write
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.auth import Principal, exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.config import settings
from src.core.pgdb import SessionLocal, get_db
from src.models.FotoPendiente_Model import FotoPendiente
from src.models.SyncEstado_Model import SyncEstado
from src.schemas.FotoPendiente_Schema import FotoPendienteResponse, FotoPendienteUpdate
from src.schemas.Sync_Schema import SyncEstadoResponse, SyncRunAceptado
from src.sync.Sync_Service import sync_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["Sync"])


def _correr_sync_async(origenes: list[str] | None, solo_datos: bool) -> None:
    """Corre el sync con su propia sesión (para BackgroundTasks)."""
    db = SessionLocal()
    try:
        sync_service.ejecutar_sync(db, disparado_por="manual", origenes=origenes, solo_datos=solo_datos)
    except Exception:  # noqa: BLE001
        logger.exception("Sync manual falló")
    finally:
        db.close()


@router.post(
    "/run",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SyncRunAceptado,
    summary="Disparar la sincronización con SYS21 (en segundo plano)",
)
def lanzar_sync(
    background: BackgroundTasks,
    solo_datos: bool = Query(False, description="Solo sincroniza datos; omite fotos/embeddings."),
    origen: str | None = Query(None, description="Origen único a sincronizar (ej. 'agricola'). Vacío = todos."),
    usuario: Principal = Depends(usuario_actual),
):
    origenes = [origen] if origen else None
    background.add_task(_correr_sync_async, origenes, solo_datos)
    return SyncRunAceptado()


@router.get(
    "/estado",
    response_model=list[SyncEstadoResponse],
    summary="Estado de sincronización por empleado",
)
def estado_sync(
    db: Session = Depends(get_db),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    origen: str | None = Query(None),
    estado_foto: str | None = Query(None, description="Filtra por estado_foto: ok | pendiente | sin_foto"),
    skip: int = 0,
    limit: int = Query(100, le=500),
):
    query = db.query(SyncEstado)
    if id_empresa is not None:
        query = query.filter(SyncEstado.id_empresa == id_empresa)
    if origen is not None:
        query = query.filter(SyncEstado.origen_nomina == origen)
    if estado_foto is not None:
        query = query.filter(SyncEstado.estado_foto == estado_foto)
    return query.order_by(SyncEstado.id_sync).offset(skip).limit(limit).all()


@router.get(
    "/fotos-pendientes",
    response_model=list[FotoPendienteResponse],
    summary="Empleados cuya foto hay que volver a tomar",
)
def listar_fotos_pendientes(
    db: Session = Depends(get_db),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    estado: str | None = Query("pendiente", description="pendiente | resuelto | ignorado | (vacío = todas)"),
    origen: str | None = Query(None),
    skip: int = 0,
    limit: int = Query(100, le=500),
):
    query = db.query(FotoPendiente)
    if id_empresa is not None:
        query = query.filter(FotoPendiente.id_empresa == id_empresa)
    if estado:
        query = query.filter(FotoPendiente.estado == estado)
    if origen is not None:
        query = query.filter(FotoPendiente.origen_nomina == origen)
    return query.order_by(FotoPendiente.fecha.desc()).offset(skip).limit(limit).all()


@router.patch(
    "/fotos-pendientes/{id_pendiente}",
    response_model=FotoPendienteResponse,
    summary="Marcar una foto pendiente como resuelta/ignorada",
)
def actualizar_foto_pendiente(
    id_pendiente: int,
    datos: FotoPendienteUpdate,
    db: Session = Depends(get_db),
    usuario: Principal = Depends(usuario_actual),
):
    fp = db.query(FotoPendiente).filter(FotoPendiente.id_pendiente == id_pendiente).first()
    if fp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Foto pendiente {id_pendiente} no encontrada.")
    exigir_empresa(usuario, fp.id_empresa)
    fp.estado = datos.estado
    db.commit()
    db.refresh(fp)
    return fp
