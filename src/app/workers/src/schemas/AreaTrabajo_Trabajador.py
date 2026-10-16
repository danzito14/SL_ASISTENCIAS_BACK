# app/schemas/area_trabajo.py
from pydantic import BaseModel, Field
from datetime import datetime, time
from typing import Literal

from src.schemas._geo import GeografiaWKT

# ── Enums (espejo de los ENUM nativos de la BD) ──────────────────────────────
EstadoGenerico = Literal["activo", "inactivo"]
EstadoTrabajador = Literal["activo", "inactivo", "suspendido"]
# Dónde puede fichar el trabajador.
PermisoEscaneo = Literal["campo", "administrativo", "general", "super"]
# Acceso a zonas internas (puertas de control_acceso).
NivelAccesoInterno = Literal["oficina", "empaque", "mixto"]


class AreaTrabajoBase(BaseModel):
    nombre_area:  str
    descripcion:  str | None = None
    id_empresa:   int | None = None
    hora_entrada: time | None = None
    estado:       EstadoGenerico = "activo"


class AreaTrabajoCreate(AreaTrabajoBase):
    # Ubicación como zona (geography POLYGON,4326): lista de [longitud, latitud].
    # El anillo se cierra solo; mínimo 3 puntos. Opcional.
    coordenadas: list[tuple[float, float]] | None = Field(
        default=None,
        min_length=3,
        description="Vértices del polígono como [longitud, latitud]; mínimo 3.",
    )


class AreaTrabajoUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre_area:  str | None = None
    descripcion:  str | None = None
    id_empresa:   int | None = None
    hora_entrada: time | None = None
    estado:       str | None = None
    coordenadas: list[tuple[float, float]] | None = Field(
        default=None,
        min_length=3,
        description="Nueva zona como [longitud, latitud]; mínimo 3 puntos.",
    )


class AreaTrabajoResponse(AreaTrabajoBase):
    id_area:       int
    ubicacion:     GeografiaWKT = None   # sale como WKT, ej: 'POLYGON ((...))'
    fecha_creacion: datetime

    model_config = {"from_attributes": True}


class TrabajadorBase(BaseModel):
    nombre: str
    apellido: str
    id_area: int
    estado: EstadoTrabajador = "activo"
    # Dónde puede fichar (default 'campo': la mayoría son de campo).
    permiso_escaneo: PermisoEscaneo = "campo"
    # Acceso a zonas internas. NULL = sin acceso interno (lo típico de los de campo).
    # El servicio FUERZA NULL cuando permiso_escaneo='campo'.
    nivel_acceso_interno: NivelAccesoInterno | None = None


class TrabajadorCreate(TrabajadorBase):
    # id_empresa se deriva del área en el servicio; no se pide al cliente.
    pass


class TrabajadorUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre:   str | None = None
    apellido: str | None = None
    id_area:  int | None = None
    estado:   EstadoTrabajador | None = None
    permiso_escaneo: PermisoEscaneo | None = None
    nivel_acceso_interno: NivelAccesoInterno | None = None
    # Número de empleado externo (nómina SYS21). Normalmente lo pobla el sync, pero
    # se permite corregirlo a mano cuando el número en SYS cambió (ej. 100219 → 20417).
    # OJO: si el trabajador viene de SYS21, cambiarlo aquí no cambia SYS21; en la
    # siguiente corrida el sync casa por (id_emp, origen_nomina), así que el nuevo
    # número debe coincidir con el que tenga SYS21.
    id_emp: str | None = None


class TrabajadorResponse(TrabajadorBase):
    id_trabajador: int
    # Identidad EXTERNA (nómina SYS21): es lo que el FRONT muestra como "número de
    # empleado". id_trabajador es la PK interna (FK de asistencias). id_emp puede ser
    # NULL (trabajadores creados a mano) y solo es único junto con origen_nomina.
    id_emp: str | None = None
    origen_nomina: str | None = None
    id_empresa: int | None = None
    fecha_creacion: datetime
    fecha_actualizacion: datetime
    tiene_embedding: bool = False  # True si el trabajador ya tiene un embedding facial registrado
    foto_url: str | None = None    # última foto aceptada en Cloudinary (panel o sync SYS21)

    model_config = {"from_attributes": True}


class TrabajadorBrief(BaseModel):
    """Schema reducido para respuestas embebidas (ej: dentro de Asistencia)"""
    id_trabajador: int
    id_emp: str | None = None   # número de empleado (SYS21) para mostrar en el front
    nombre: str
    apellido: str
    estado: str

    model_config = {"from_attributes": True}


class TrabajadorRegistroResponse(BaseModel):
    """Respuesta del endpoint de registro: trabajador + info del embedding"""
    trabajador: TrabajadorResponse
    embedding_id: int
    modelo_ia: str
    dimensiones: int
    calidad: float
    mensaje: str = "Trabajador registrado correctamente."
    foto_url: str | None = None    # copia en Cloudinary; None = no se pudo subir (rostro registrado igual)

    model_config = {"from_attributes": True}


# ── Limpieza de duplicados ────────────────────────────────────────────────────
class TrabajadorDuplicadoInfo(BaseModel):
    """Ficha mínima de un trabajador dentro de un grupo de homónimos."""
    id_trabajador:  int
    id_emp:         str | None = None
    origen_nomina:  str | None = None
    nombre:         str
    apellido:       str
    id_empresa:     int | None = None
    tiene_embedding: bool = False


class DuplicadoNoEliminado(BaseModel):
    """Duplicado que no se pudo borrar (tiene FK dependientes)."""
    id_trabajador: int
    nombre:        str
    apellido:      str
    motivo:        str


class GrupoDuplicados(BaseModel):
    """Un grupo de homónimos: el que se conserva y los que se (van a) eliminar."""
    nombre_clave: str  # nombre normalizado, sin acentos ni numeral romano
    conservado:   TrabajadorDuplicadoInfo
    eliminados:   list[TrabajadorDuplicadoInfo]


class LimpiezaDuplicadosResponse(BaseModel):
    """Resultado del limpiador de duplicados (o su simulación)."""
    simulado:              bool
    grupos_con_duplicados: int
    duplicados_detectados: int
    eliminados:            int  # 0 en modo simulación
    no_eliminados:         list[DuplicadoNoEliminado]
    detalle:               list[GrupoDuplicados]
