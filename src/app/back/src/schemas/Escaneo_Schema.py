# app/schemas/escaneo.py
from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from src.schemas._geo import GeografiaWKT

TipoRegistro = Literal["entrada", "salida"]
EstadoRegistro = Literal["exitoso", "rechazado", "manual", "fuera_de_area", "cancelado"]


class EscaneoBase(BaseModel):
    id_trabajador:        int
    id_puerta:            int
    tipo_registro:        TipoRegistro
    confianza_biometrica: Decimal | None = None
    estado_registro:      EstadoRegistro = "exitoso"
    observaciones:        str | None = None
    id_dispositivo:       int | None = None


class EscaneoCreate(EscaneoBase):
    # Ubicación como punto (geography POINT,4326). Opcional.
    latitud:  float | None = None
    longitud: float | None = None
    # Metadata de sincronización (offline-first). Opcionales: un escaneo online
    # los deja vacíos; uno que nace en la APK los manda al sincronizar.
    dentro_de_area:        bool | None = None
    creado_en_cliente:     datetime | None = None
    id_dispositivo_origen: int | None = None


class EscaneoUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    id_trabajador:        int | None = None
    id_puerta:            int | None = None
    tipo_registro:        TipoRegistro | None = None
    confianza_biometrica: Decimal | None = None
    estado_registro:      EstadoRegistro | None = None
    observaciones:        str | None = None
    id_dispositivo:       int | None = None
    latitud:  float | None = None
    longitud: float | None = None


class EscaneoResponse(EscaneoBase):
    id_escaneo:            UUID
    id_empresa:            int | None = None
    dentro_de_area:        bool | None = None
    ubicacion:             GeografiaWKT = None   # sale como WKT, ej: 'POINT (-108.72 25.71)'
    fecha_hora:            datetime
    creado_en_cliente:     datetime | None = None
    sincronizado_en:       datetime | None = None
    id_dispositivo_origen: int | None = None
    fecha_creacion:        datetime

    model_config = {"from_attributes": True}
