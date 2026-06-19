# app/schemas/escaneo.py
from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal

from src.schemas._geo import GeografiaWKT


class EscaneoBase(BaseModel):
    id_trabajador:        int
    id_puerta:            int
    tipo_registro:        str            # 'entrada' | 'salida'
    confianza_biometrica: Decimal | None = None
    estado_registro:      str = "exitoso"
    observaciones:        str | None = None
    id_dispositivo:       int | None = None


class EscaneoCreate(EscaneoBase):
    # Ubicación como punto (geography POINT,4326). Opcional.
    latitud:  float | None = None
    longitud: float | None = None


class EscaneoUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    id_trabajador:        int | None = None
    id_puerta:            int | None = None
    tipo_registro:        str | None = None
    confianza_biometrica: Decimal | None = None
    estado_registro:      str | None = None
    observaciones:        str | None = None
    id_dispositivo:       int | None = None
    latitud:  float | None = None
    longitud: float | None = None


class EscaneoResponse(EscaneoBase):
    id_escaneo:     int
    ubicacion:      GeografiaWKT = None   # sale como WKT, ej: 'POINT (-108.72 25.71)'
    fecha_hora:     datetime
    fecha_creacion: datetime

    model_config = {"from_attributes": True}
