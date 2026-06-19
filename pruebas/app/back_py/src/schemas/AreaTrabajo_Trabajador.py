# app/schemas/area_trabajo.py
from pydantic import BaseModel, Field
from datetime import datetime, time

from src.schemas._geo import GeografiaWKT


class AreaTrabajoBase(BaseModel):
    nombre_area:  str
    descripcion:  str | None = None
    id_empresa:   int | None = None
    hora_entrada: time | None = None
    estado:       str = "activo"


class AreaTrabajoCreate(AreaTrabajoBase):
    # Ubicación como zona (geography POLYGON,4326): lista de [longitud, latitud].
    # El anillo se cierra solo; mínimo 3 puntos. Opcional.
    coordenadas: list[tuple[float, float]] | None = Field(
        default=None,
        min_length=3,
        description="Vértices del polígono como [longitud, latitud]; mínimo 3.",
    )


class AreaTrabajoUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre_area:  str | None = None
    descripcion:  str | None = None
    id_empresa:   int | None = None
    hora_entrada: time | None = None
    estado:       str | None = None
    coordenadas: list[tuple[float, float]] | None = Field(
        default=None,
        min_length=3,
        description="Nueva zona como [longitud, latitud]; mínimo 3 puntos.",
    )


class AreaTrabajoResponse(AreaTrabajoBase):
    id_area:       int
    ubicacion:     GeografiaWKT = None   # sale como WKT, ej: 'POLYGON ((...))'
    fecha_creacion: datetime

    model_config = {"from_attributes": True}


class TrabajadorBase(BaseModel):
    nombre: str
    apellido: str
    id_area: int
    estado: str = "activo"


class TrabajadorCreate(TrabajadorBase):
    pass


class TrabajadorUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre:   str | None = None
    apellido: str | None = None
    id_area:  int | None = None
    estado:   str | None = None


class TrabajadorResponse(TrabajadorBase):
    id_trabajador: int
    fecha_creacion: datetime
    fecha_actualizacion: datetime
    tiene_embedding: bool = False  # True si el trabajador ya tiene un embedding facial registrado

    model_config = {"from_attributes": True}


class TrabajadorBrief(BaseModel):
    """Schema reducido para respuestas embebidas (ej: dentro de Asistencia)"""
    id_trabajador: int
    nombre: str
    apellido: str
    estado: str

    model_config = {"from_attributes": True}


class TrabajadorRegistroResponse(BaseModel):
    """Respuesta del endpoint de registro: trabajador + info del embedding"""
    trabajador: TrabajadorResponse
    embedding_id: int
    modelo_ia: str
    dimensiones: int
    calidad: float
    mensaje: str = "Trabajador registrado correctamente."

    model_config = {"from_attributes": True}
