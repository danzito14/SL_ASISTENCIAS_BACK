# employee_monitoring/routers/Sync_Router.py
"""
API del servicio de monitoreo. Prefijo propio /emp_sync (employee sync): no
colisiona con /trabajadores ni /embeddings (workers) ni con /off_sync (offline_sync).

Scopes (derivados del primer segmento del path → recurso 'emp_sync'):
  - GET  → emp_sync:read
  - POST/PATCH → emp_sync:write
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.auth import Principal, exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.config import settings
from src.core.pgdb import SessionLocal, get_db
from src.models.AreaTrabajo_Trabajador_Model import Trabajador
from src.models.FotoPendiente_Model import MOTIVOS, FotoPendiente
from src.models.SyncEstado_Model import SyncEstado
from src.schemas.FotoPendiente_Schema import (FotoPendienteResponse,
                                              FotoPendienteUpdate, MotivoCatalogo)
from src.schemas.Sync_Schema import SyncEstadoResponse, SyncRunAceptado
from src.sync.Sync_Service import sync_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emp_sync", tags=["Sync"])


def _correr_sync_async(origenes: list[str] | None, solo_datos: bool) -> None:
    """Corre el sync con su propia sesión (para BackgroundTasks)."""
    db = SessionLocal()
    try:
        sync_service.ejecutar_sync(db, disparado_por="manual", origenes=origenes, solo_datos=solo_datos)
    except Exception:  # noqa: BLE001
        logger.exception("Sync manual falló")
    finally:
        db.close()


def _correr_fotos_async(origenes: list[str] | None, limite: int | None, forzar: bool) -> None:
    """Procesa solo fotos con su propia sesión (para BackgroundTasks)."""
    db = SessionLocal()
    try:
        sync_service.ejecutar_fotos(db, origenes=origenes, limite=limite, forzar=forzar)
    except Exception:  # noqa: BLE001
        logger.exception("Procesamiento de fotos falló")
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


@router.post(
    "/fotos",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SyncRunAceptado,
    summary="Procesar SOLO fotos de los trabajadores ya registrados",
)
def lanzar_fotos(
    background: BackgroundTasks,
    origen: str | None = Query(None, description="Origen único (ej. 'agricola'). Vacío = todos."),
    limite: int | None = Query(None, description="Procesar a lo más N por origen (útil para pruebas)."),
    forzar: bool = Query(False, description="Reprocesar aunque la foto no haya cambiado (mtime/size)."),
    usuario: Principal = Depends(usuario_actual),
):
    origenes = [origen] if origen else None
    background.add_task(_correr_fotos_async, origenes, limite, forzar)
    return SyncRunAceptado(
        mensaje="Procesamiento de fotos lanzado en segundo plano. Revisa /sync/fotos-pendientes y los logs."
    )


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
    origen: str | None = Query(None, description="agricola | agricola_com"),
    motivo: str | None = Query(None, description="Filtra por motivo (sin_foto, area_invalida, no_rostro, …)."),
    skip: int = 0,
    limit: int = Query(100, le=500),
):
    # LEFT JOIN a trabajadores para traer el nombre (area_invalida no tiene trabajador).
    q = (db.query(FotoPendiente, Trabajador.nombre, Trabajador.apellido)
           .outerjoin(Trabajador, Trabajador.id_trabajador == FotoPendiente.id_trabajador))
    if id_empresa is not None:
        q = q.filter(FotoPendiente.id_empresa == id_empresa)
    if estado:
        q = q.filter(FotoPendiente.estado == estado)
    if origen is not None:
        q = q.filter(FotoPendiente.origen_nomina == origen)
    if motivo is not None:
        q = q.filter(FotoPendiente.motivo == motivo)

    filas = q.order_by(FotoPendiente.fecha.desc()).offset(skip).limit(limit).all()
    salida = []
    for fp, nombre, apellido in filas:
        fp.trabajador_nombre = f"{nombre} {apellido}".strip() if nombre else None
        salida.append(fp)
    return salida


@router.get(
    "/fotos-pendientes/resumen",
    summary="Conteo de fotos pendientes por motivo",
    description="Agrupa las fotos pendientes por (origen, motivo) con su total. Para el "
                "tablero de calidad de fotos. Por defecto solo las 'pendiente'.",
)
def resumen_fotos_pendientes(
    db: Session = Depends(get_db),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    estado: str | None = Query("pendiente", description="pendiente | resuelto | ignorado | (vacío = todas)"),
):
    q = db.query(FotoPendiente.origen_nomina, FotoPendiente.motivo,
                 func.count(FotoPendiente.id_pendiente).label("total"))
    if id_empresa is not None:
        q = q.filter(FotoPendiente.id_empresa == id_empresa)
    if estado:
        q = q.filter(FotoPendiente.estado == estado)
    filas = (q.group_by(FotoPendiente.origen_nomina, FotoPendiente.motivo)
              .order_by(func.count(FotoPendiente.id_pendiente).desc()).all())
    return [{"origen_nomina": o, "motivo": m, "total": n} for o, m, n in filas]


@router.get(
    "/fotos-pendientes/areas-invalidas",
    summary="Áreas/puestos SIN clasificar (area_invalida) por origen",
    description="Desglose de los rechazos 'area_invalida' por su detalle "
                "(empresa/area_codigo/area_nombre), ordenado por cuántos trabajadores "
                "arrastra cada uno. Sirve para saber qué áreas etiquetar o mapear. "
                "Nota: 'area_invalida' viene sin empresa, así que lo ve el super-admin.",
)
def areas_invalidas(
    db: Session = Depends(get_db),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    limite: int = Query(100, ge=1, le=1000),
):
    q = (db.query(FotoPendiente.origen_nomina, FotoPendiente.detalle,
                  func.count(FotoPendiente.id_pendiente).label("total"))
           .filter(FotoPendiente.motivo == "area_invalida",
                   FotoPendiente.estado == "pendiente"))
    if id_empresa is not None:
        q = q.filter(FotoPendiente.id_empresa == id_empresa)
    filas = (q.group_by(FotoPendiente.origen_nomina, FotoPendiente.detalle)
              .order_by(func.count(FotoPendiente.id_pendiente).desc()).limit(limite).all())
    return [{"origen_nomina": o, "detalle": d, "total": n} for o, d, n in filas]


# Etiquetas legibles de los motivos (para la leyenda/filtros del panel).
_MOTIVO_LABEL: dict[str, str] = {
    "sin_foto":                   "Sin foto en el servidor",
    "area_invalida":              "Área/puesto sin clasificar",
    "no_rostro":                  "No se detectó rostro",
    "multiples_caras":            "Varias caras en la foto",
    "det_score_bajo":             "Detección de baja calidad",
    "cara_pequena":               "Rostro muy pequeño / lejano",
    "pose_no_frontal":            "Rostro no frontal",
    "borrosa":                    "Foto borrosa",
    "spoofing":                   "Posible foto/pantalla (spoofing)",
    "duplicado":                  "Rostro duplicado (ya registrado en otro)",
    "recognition_no_disponible":  "Reconocimiento no disponible (reintentar)",
    "formato_invalido":           "Formato de imagen inválido",
    "resolucion_baja":            "Resolución baja",
    "archivo_corrupto":           "Archivo corrupto",
    "archivo_grande":             "Archivo demasiado grande",
    "muy_oscura":                 "Foto muy oscura",
    "muy_clara":                  "Foto muy clara / sobreexpuesta",
}


@router.get(
    "/fotos-pendientes/motivos",
    response_model=list[MotivoCatalogo],
    summary="Catálogo de motivos de rechazo (con etiqueta legible)",
    description="Todos los motivos posibles + su etiqueta para la UI (leyenda y filtros "
                "del tablero), exista o no una foto con ese motivo ahora mismo.",
)
def catalogo_motivos():
    return [MotivoCatalogo(motivo=m, label=_MOTIVO_LABEL.get(m, m)) for m in MOTIVOS]


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
