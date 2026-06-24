# app/schemas/incidencia.py
from pydantic import BaseModel
from datetime import date, datetime
from typing import Literal
from uuid import UUID


# Valores permitidos por el ENUM tipo_incidencia de la tabla.
TipoIncidencia = Literal[
    "salida_sin_registro",
    "entrada_sin_registro",
    "falta",
    "retardo",
    "fuera_de_area",
    "acceso_otra_empresa",
    "area_incorrecta",
]
EstadoIncidencia = Literal["pendiente", "revisada", "justificada"]


class IncidenciaBase(BaseModel):
    id_trabajador:   int
    tipo_incidencia: TipoIncidencia
    fecha:           date
    descripcion:     str | None = None
    ruta_foto:       str | None = None
    id_escaneo_ref:  UUID | None = None
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
    id_escaneo_ref:  UUID | None = None
    estado:          EstadoIncidencia | None = None


class IncidenciaResponse(IncidenciaBase):
    id_incidencia:  UUID
    id_empresa:     int | None = None
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
    id:                UUID
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
    foto_url:          str | None = None         # ej. "/incidencias/<uuid>/foto" | "/intentos/<uuid>/foto"
    # Escaneo que originó la incidencia (UUID → escaneos.id_escaneo). Permite pedir
    # GET /escaneos/{id} para la info completa. Solo en filas 'incidencia' nacidas de
    # un escaneo; en 'intento' (acceso fallido, sin escaneo) va en None.
    id_escaneo_ref:    UUID | None = None
