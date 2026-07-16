# vigilancia/schemas/Evento_Schema.py
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EventoOut(BaseModel):
    id_evento: UUID
    id_camara: int
    id_empresa: int | None = None
    id_puerta: int | None = None
    tipo_evento: str
    id_escaneo: UUID | None = None
    id_trabajador: int | None = None
    confianza: float | None = None
    face_px: int | None = None
    mensaje: str | None = None
    fecha_hora: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
