# employee_monitoring/schemas/foto_pendiente.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class FotoPendienteResponse(BaseModel):
    id_pendiente:  int
    id_emp:        str
    origen_nomina: str
    id_trabajador: int | None = None
    id_empresa:    int | None = None
    motivo:        str
    detalle:       str | None = None
    fecha:         datetime
    estado:        str

    model_config = {"from_attributes": True}


class FotoPendienteUpdate(BaseModel):
    """Marca una foto pendiente como resuelta/ignorada (revisión manual)."""
    estado: Literal["pendiente", "resuelto", "ignorado"]
