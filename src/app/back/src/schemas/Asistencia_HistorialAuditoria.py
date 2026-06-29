# app/schemas/asistencia.py
from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from src.schemas.AreaTrabajo_Trabajador import TrabajadorBrief
from src.schemas.Escaneo_Schema import TipoRegistro, EstadoRegistro
from src.schemas._geo import GeografiaWKT


class AsistenciaBase(BaseModel):
    id_trabajador:        int
    id_puerta:            int
    tipo_registro:        TipoRegistro
    confianza_biometrica: Decimal | None = None
    estado_registro:      EstadoRegistro = "exitoso"
    observaciones:        str | None = None
    ubicacion:            GeografiaWKT = None   # geography(POINT,4326) como WKT
    id_dispositivo:       int | None = None


class AsistenciaCreate(AsistenciaBase):
    pass


class AsistenciaResponse(AsistenciaBase):
    id_asistencia:  UUID
    id_empresa:     int | None = None
    dentro_de_area: bool | None = None
    fecha_hora:     datetime
    fecha_creacion: datetime

    # Identidad/nombres resueltos por el backend (JOIN) para que el front muestre todo
    # sin consultar /trabajadores, /puertas, /areas, /empresas ni pedir esos scopes.
    id_emp:             str | None = None   # número de empleado (SYS21) del trabajador, para MOSTRAR
    trabajador_nombre:  str | None = None
    puerta_nombre:      str | None = None
    dispositivo_nombre: str | None = None
    area_nombre:        str | None = None
    empresa_nombre:     str | None = None

    model_config = {"from_attributes": True}


class AsistenciaDetalle(AsistenciaResponse):
    """Respuesta enriquecida con datos del trabajador"""
    trabajador: TrabajadorBrief

    model_config = {"from_attributes": True}


# ── Schema específico para el endpoint del escáner ──────────────────────────
class ScanRequest(BaseModel):
    """Lo que envía el dispositivo al hacer un scan"""
    codigo:         str            # Código leído del barcode / QR
    id_puerta:      int
    id_dispositivo: int | None = None
    tipo_registro:  TipoRegistro = "entrada"


class ScanResponse(BaseModel):
    """Respuesta inmediata al dispositivo"""
    acceso:        bool           # True = permitido, False = denegado
    mensaje:       str
    trabajador:    TrabajadorBrief | None = None
    id_escaneo:    UUID | None = None
    estado_registro: str


class HistorialAuditoriaBase(BaseModel):
    id_usuario: int | None = None
    tabla_modificada: str
    tipo_operacion: str
    # TEXT en BD: puede ser una PK entera o un UUID de las tablas nuevas.
    id_registro_afectado: str | None = None
    valores_anteriores: dict[str, Any] | None = None
    valores_nuevos: dict[str, Any] | None = None
    ip_origen: str | None = None
    user_agent: str | None = None


class HistorialAuditoriaCreate(HistorialAuditoriaBase):
    pass


class HistorialAuditoriaResponse(HistorialAuditoriaBase):
    id_auditoria: int
    fecha_hora: datetime

    model_config = {"from_attributes": True}
