# employee_monitoring/schemas/area_trabajo_trabajador.py
# Solo los schemas de Trabajador que necesitan los servicios reutilizados
# (Trabajador_Service). employee_monitoring NO expone CRUD de áreas ni de
# trabajadores, así que no se incluyen los schemas geográficos de AreaTrabajo
# (eso evita arrastrar geoalchemy2/shapely).
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# ── Enums (espejo de los ENUM nativos de la BD) ──────────────────────────────
EstadoGenerico = Literal["activo", "inactivo"]
EstadoTrabajador = Literal["activo", "inactivo", "suspendido"]
PermisoEscaneo = Literal["campo", "administrativo", "general", "super"]
NivelAccesoInterno = Literal["oficina", "empaque", "mixto"]


class TrabajadorBase(BaseModel):
    nombre: str
    apellido: str
    id_area: int
    estado: EstadoTrabajador = "activo"
    permiso_escaneo: PermisoEscaneo = "campo"
    nivel_acceso_interno: NivelAccesoInterno | None = None


class TrabajadorCreate(TrabajadorBase):
    # id_empresa se deriva del área en el servicio; no se pide al cliente.
    pass


class TrabajadorUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre:   str | None = None
    apellido: str | None = None
    id_area:  int | None = None
    estado:   EstadoTrabajador | None = None
    permiso_escaneo: PermisoEscaneo | None = None
    nivel_acceso_interno: NivelAccesoInterno | None = None


class TrabajadorResponse(TrabajadorBase):
    id_trabajador: int
    id_empresa: int | None = None
    fecha_creacion: datetime
    fecha_actualizacion: datetime
    tiene_embedding: bool = False

    model_config = {"from_attributes": True}
