# app/schemas/intento_acceso.py
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


TipoIntento = Literal["spoofing", "desconocido", "otra_empresa"]
# Mismo ciclo de revisión que las incidencias.
EstadoIntento = Literal["pendiente", "revisada", "justificada"]


class IntentoAccesoResponse(BaseModel):
    id_intento:    UUID
    id_puerta:     int | None = None
    id_empresa:    int | None = None
    tipo:          TipoIntento
    id_trabajador: int | None = None
    similitud:     float | None = None
    ruta_foto:     str | None = None
    estado:        EstadoIntento = "pendiente"
    fecha:         datetime | None = None

    # Identidad/nombre resueltos por el backend (JOIN) cuando el intento tiene trabajador.
    id_emp:            str | None = None   # número de empleado (SYS21), para mostrar
    trabajador_nombre: str | None = None

    model_config = {"from_attributes": True}


class IntentoAccesoUpdate(BaseModel):
    # Actualización parcial: hoy solo se gestiona el estado de revisión.
    # Pasar 'estado'='justificada' en un intento 'otra_empresa' crea la asistencia manual.
    estado: EstadoIntento | None = None
