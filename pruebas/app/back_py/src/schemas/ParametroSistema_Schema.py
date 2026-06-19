# app/schemas/parametro_sistema.py
from pydantic import BaseModel
from datetime import datetime


class ParametroSistemaBase(BaseModel):
    clave:       str
    valor:       str
    tipo:        str = "texto"
    descripcion: str | None = None
    editable:    bool = True


class ParametroSistemaCreate(ParametroSistemaBase):
    pass


class ParametroSistemaUpdate(BaseModel):
    valor: str


class ParametroSistemaResponse(ParametroSistemaBase):
    id_parametro:       int
    fecha_actualizacion: datetime

    model_config = {"from_attributes": True}