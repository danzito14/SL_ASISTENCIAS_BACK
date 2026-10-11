# employee_monitoring/schemas/regla_clasificacion.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Origen = Literal["agricola", "agricola_com"]
Grupo = Literal["oficina", "empaque", "campo"]
Permiso = Literal["campo", "administrativo", "general", "super"]
Nivel = Literal["oficina", "empaque", "mixto"]


class ReglaCreate(BaseModel):
    """Alta de una regla. `nombre` es el puesto (agrícola) o departamento (comercial)
    tal como viene en la nómina; se normaliza para empatar (sin acentos/mayúsculas)."""
    origen_nomina:        Origen
    nombre:               str = Field(min_length=1, max_length=150)
    grupo:                Grupo
    permiso_escaneo:      Permiso | None = None   # None = default del grupo
    nivel_acceso_interno: Nivel | None = None     # None = default del grupo


class ReglaUpdate(BaseModel):
    """Cambio parcial. Para volver al default del grupo, manda el campo en null."""
    nombre:               str | None = Field(None, min_length=1, max_length=150)
    grupo:                Grupo | None = None
    permiso_escaneo:      Permiso | None = None
    nivel_acceso_interno: Nivel | None = None


class ReglaResponse(BaseModel):
    id_regla:             int
    origen_nomina:        str
    clave:                str
    nombre:               str
    grupo:                str
    permiso_escaneo:      str | None = None
    nivel_acceso_interno: str | None = None
    # Lo que el trabajador recibe al final (override o default del grupo).
    permiso_efectivo:     str
    nivel_efectivo:       str | None = None
    actualizado_por:      str | None = None
    fecha_actualizacion:  datetime | None = None

    model_config = {"from_attributes": True}


class PuestoSinRegla(BaseModel):
    """Puesto/departamento que llegó de la nómina sin regla (pendiente de clasificar)."""
    origen_nomina: str
    nombre:        str            # como viene en la nómina
    clave:         str            # normalizado (lo que se guardará en la regla)
    personas:      int            # empleados rechazados con ese puesto en la última corrida
    empresas:      list[str]      # empresas (según la nómina) donde aparece
    con_regla:     bool           # ya se le creó regla; entra en el próximo sync


class OpcionesReglas(BaseModel):
    """Catálogos para los selectores del front."""
    origenes:      list[str]
    grupos:        list[str]
    permisos:      list[str]
    niveles:       list[str]
    default_por_grupo: dict[str, dict[str, str | None]]
