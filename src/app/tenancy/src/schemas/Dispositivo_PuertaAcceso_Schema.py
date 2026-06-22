# app/schemas/dispositivo.py
from pydantic import BaseModel
from datetime import datetime, date
from typing import Literal

from src.schemas._geo import GeografiaWKT

# ── Enums (espejo de los ENUM nativos de la BD) ──────────────────────────────
TipoDispositivo = Literal["escaner_facial", "huella", "escaner_qr"]
EstadoDispositivo = Literal["activo", "inactivo", "mantenimiento"]
EstadoGenerico = Literal["activo", "inactivo"]
TipoAcceso = Literal["entrada", "salida", "bidireccional"]
TipoPuerta = Literal["campo", "administrativa", "mixta"]
FuncionPuerta = Literal["asistencia", "control_acceso"]
CategoriaZona = Literal["oficina", "empaque", "mixto"]


class DispositivoBase(BaseModel):
    nombre_dispositivo: str
    tipo_dispositivo:   TipoDispositivo
    ip_dispositivo:     str | None = None
    puerto:             int = 8080
    id_area:            int | None = None
    id_empresa:         int | None = None
    estado:             EstadoDispositivo = "activo"
    fecha_instalacion:  date | None = None


class DispositivoCreate(DispositivoBase):
    # Ubicación como punto (geography POINT,4326). Opcional.
    latitud:  float | None = None
    longitud: float | None = None


class DispositivoUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre_dispositivo: str | None = None
    tipo_dispositivo:   TipoDispositivo | None = None
    ip_dispositivo:     str | None = None
    puerto:             int | None = None
    id_area:            int | None = None
    id_empresa:         int | None = None
    estado:             EstadoDispositivo | None = None
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
    # NUEVO: tipo físico (reemplaza el número mágico 8080) y función de la puerta.
    tipo_puerta: TipoPuerta = "campo"
    funcion_puerta: FuncionPuerta = "asistencia"
    # Solo aplica si funcion_puerta='control_acceso' (puerta interna).
    categoria_zona_destino: CategoriaZona | None = None
    tipo_acceso: TipoAcceso = "bidireccional"
    requiere_autorizacion: bool = False
    estado: EstadoGenerico = "activo"


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
    tipo_puerta: TipoPuerta | None = None
    funcion_puerta: FuncionPuerta | None = None
    categoria_zona_destino: CategoriaZona | None = None
    tipo_acceso: TipoAcceso | None = None
    requiere_autorizacion: bool | None = None
    estado: EstadoGenerico | None = None
    latitud:  float | None = None
    longitud: float | None = None


class PuertaAccesoResponse(PuertaAccesoBase):
    id_puerta: int
    ubicacion: GeografiaWKT = None   # sale como WKT, ej: 'POINT (-99.13 19.43)'
    fecha_creacion: datetime

    model_config = {"from_attributes": True}
