# app/schemas/intento_acceso.py
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


TipoIntento = Literal["spoofing", "desconocido", "otra_empresa"]


class IntentoAccesoResponse(BaseModel):
    id_intento:    UUID
    id_puerta:     int | None = None
    id_empresa:    int | None = None
    tipo:          TipoIntento
    id_trabajador: int | None = None
    similitud:     float | None = None
    ruta_foto:     str | None = None
    fecha:         datetime | None = None

    # Nombre resuelto por el backend (JOIN) cuando el intento tiene trabajador.
    trabajador_nombre: str | None = None

    model_config = {"from_attributes": True}
