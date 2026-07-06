# employee_monitoring/schemas/foto_pendiente.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class FotoPendienteResponse(BaseModel):
    id_pendiente:      int
    id_emp:            str
    origen_nomina:     str
    id_trabajador:     int | None = None
    id_empresa:        int | None = None
    trabajador_nombre: str | None = None   # nombre resuelto (para mostrar en la tabla)
    motivo:            str
    detalle:           str | None = None
    fecha:             datetime
    estado:            str

    model_config = {"from_attributes": True}


class MotivoCatalogo(BaseModel):
    """Un motivo de rechazo + su etiqueta legible (para la leyenda/filtros del panel)."""
    motivo: str
    label:  str


class FotoPendienteUpdate(BaseModel):
    """Marca una foto pendiente como resuelta/ignorada (revisión manual)."""
    estado: Literal["pendiente", "resuelto", "ignorado"]
