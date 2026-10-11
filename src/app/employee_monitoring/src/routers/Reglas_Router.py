# employee_monitoring/routers/Reglas_Router.py
"""
Reglas del clasificador del sync SYS21: puesto (agrícola) / departamento (comercial)
→ grupo (oficina/empaque/campo) + reemplazos opcionales de permiso/nivel.

Cuelga de /emp_sync, así que los scopes salen solos del primer segmento:
  - GET    → emp_sync:read
  - POST/PATCH → emp_sync:write
  - DELETE → emp_sync:delete
Además, crear/editar/borrar exige SUPER-ADMIN: las reglas aplican a todas las empresas.
Los cambios entran en la siguiente corrida del sync (POST /emp_sync/run).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.auth import Principal, es_admin, usuario_actual
from src.core.pgdb import get_db
from src.schemas.ReglaClasificacion_Schema import (OpcionesReglas, PuestoSinRegla,
                                                   ReglaCreate, ReglaResponse, ReglaUpdate)
from src.services.ReglaClasificacion_Service import regla_service

router = APIRouter(prefix="/emp_sync/reglas", tags=["Reglas de clasificación"])


def solo_super_admin(usuario: Principal = Depends(usuario_actual)) -> Principal:
    if not es_admin(usuario):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Solo el super-admin puede modificar las reglas de clasificación.")
    return usuario


@router.get("/opciones", response_model=OpcionesReglas,
            summary="Catálogos para los selectores (orígenes, grupos, permisos, niveles)")
def opciones():
    return regla_service.opciones()


@router.get(
    "/sin-regla",
    response_model=list[PuestoSinRegla],
    summary="Puestos/departamentos que llegaron de la nómina SIN regla",
    description="Sale de los rechazos 'area_invalida' de la última corrida, agrupados por "
                "puesto, con cuántas personas arrastra cada uno. `con_regla=true` = ya se "
                "le creó regla y entra en el próximo sync.",
)
def puestos_sin_regla(
    db: Session = Depends(get_db),
    origen: str | None = Query(None, description="agricola | agricola_com"),
):
    return regla_service.sin_regla(db, origen)


@router.get("", response_model=list[ReglaResponse], summary="Listar reglas")
def listar_reglas(
    db: Session = Depends(get_db),
    origen: str | None = Query(None, description="agricola | agricola_com"),
    grupo: str | None = Query(None, description="oficina | empaque | campo"),
    buscar: str | None = Query(None, description="Texto dentro del puesto/departamento."),
):
    return regla_service.listar(db, origen, grupo, buscar)


@router.post("", response_model=ReglaResponse, status_code=status.HTTP_201_CREATED,
             summary="Crear regla (solo super-admin)")
def crear_regla(
    datos: ReglaCreate,
    db: Session = Depends(get_db),
    usuario: Principal = Depends(solo_super_admin),
):
    return regla_service.crear(db, datos, usuario.nombre_usuario)


@router.patch("/{id_regla}", response_model=ReglaResponse,
              summary="Editar regla (solo super-admin)")
def actualizar_regla(
    id_regla: int,
    datos: ReglaUpdate,
    db: Session = Depends(get_db),
    usuario: Principal = Depends(solo_super_admin),
):
    return regla_service.actualizar(db, id_regla, datos, usuario.nombre_usuario)


@router.delete("/{id_regla}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Borrar regla (solo super-admin)")
def eliminar_regla(
    id_regla: int,
    db: Session = Depends(get_db),
    usuario: Principal = Depends(solo_super_admin),
):
    regla_service.eliminar(db, id_regla)
