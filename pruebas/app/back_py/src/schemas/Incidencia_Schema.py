# app/schemas/incidencia.py
from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Literal


# Valores permitidos por los CHECK de la tabla.
TipoIncidencia = Literal[
    "salida_sin_registro",
    "entrada_sin_registro",
    "falta",
    "retardo",
    "fuera_de_area",
    "acceso_otra_empresa",
]
EstadoIncidencia = Literal["pendiente", "revisada", "justificada"]


class IncidenciaBase(BaseModel):
    id_trabajador:   int
    tipo_incidencia: TipoIncidencia
    fecha:           date
    descripcion:     str | None = None
    ruta_foto:       str | None = None
    id_escaneo_ref:  int | None = None
    estado:          EstadoIncidencia = "pendiente"


class IncidenciaCreate(IncidenciaBase):
    pass


class IncidenciaUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    id_trabajador:   int | None = None
    tipo_incidencia: TipoIncidencia | None = None
    fecha:           date | None = None
    descripcion:     str | None = None
    ruta_foto:       str | None = None
    id_escaneo_ref:  int | None = None
    estado:          EstadoIncidencia | None = None


class IncidenciaResponse(IncidenciaBase):
    id_incidencia:  int
    fecha_creacion: datetime

    # Nombre resuelto por el backend (JOIN) para que el front no consulte /trabajadores.
    trabajador_nombre: str | None = None

    model_config = {"from_attributes": True}


class EventoResponse(BaseModel):
    """
    Vista UNIFICADA de incidencias + intentos de acceso, para mostrarlas juntas en
    una sola pantalla. `origen` indica de qué tabla viene cada fila y `foto_url`
    apunta al endpoint correcto de la foto (protegido).
    """
    origen:            Literal["incidencia", "intento"]
    id:                int
    tipo:              str
    fecha:             date | None = None
    fecha_hora:        datetime | None = None   # para ordenar/mostrar con hora
    descripcion:       str | None = None
    estado:            str | None = None        # solo incidencias (intentos = None)
    id_trabajador:     int | None = None
    trabajador_nombre: str | None = None
    id_puerta:         int | None = None        # solo intentos
    id_empresa:        int | None = None
    similitud:         float | None = None       # solo intentos
    tiene_foto:        bool = False
    foto_url:          str | None = None         # ej. "/incidencias/12/foto" | "/intentos/5/foto"
