# app/schemas/dispositivo.py
from pydantic import BaseModel
from datetime import datetime, date

from src.schemas._geo import GeografiaWKT


class DispositivoBase(BaseModel):
    nombre_dispositivo: str
    tipo_dispositivo:   str
    ip_dispositivo:     str | None = None
    puerto:             int = 8080
    id_area:            int | None = None
    estado:             str = "activo"
    fecha_instalacion:  date | None = None


class DispositivoCreate(DispositivoBase):
    # Ubicación como punto (geography POINT,4326). Opcional.
    latitud:  float | None = None
    longitud: float | None = None


class DispositivoUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre_dispositivo: str | None = None
    tipo_dispositivo:   str | None = None
    ip_dispositivo:     str | None = None
    puerto:             int | None = None
    id_area:            int | None = None
    estado:             str | None = None
    fecha_instalacion:  date | None = None
    latitud:  float | None = None
    longitud: float | None = None


class DispositivoResponse(DispositivoBase):
    id_dispositivo:  int
    ubicacion:       GeografiaWKT = None   # sale como WKT, ej: 'POINT (-99.13 19.43)'
    ultima_conexion: datetime | None = None
    fecha_creacion:  datetime

    model_config = {"from_attributes": True}


class PuertaAccesoBase(BaseModel):
    nombre_puerta: str
    id_area: int | None = None
    id_empresa: int | None = None
    id_dispositivo: int | None = None
    tipo_acceso: str = "bidireccional"
    requiere_autorizacion: bool = False
    estado: str = "activo"


class PuertaAccesoCreate(PuertaAccesoBase):
    # Ubicación como punto (geography POINT,4326). Opcional.
    latitud:  float | None = None
    longitud: float | None = None


class PuertaAccesoUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre_puerta: str | None = None
    id_area: int | None = None
    id_empresa: int | None = None
    id_dispositivo: int | None = None
    tipo_acceso: str | None = None
    requiere_autorizacion: bool | None = None
    estado: str | None = None
    latitud:  float | None = None
    longitud: float | None = None


class PuertaAccesoResponse(PuertaAccesoBase):
    id_puerta: int
    ubicacion: GeografiaWKT = None   # sale como WKT, ej: 'POINT (-99.13 19.43)'
    fecha_creacion: datetime

    model_config = {"from_attributes": True}
