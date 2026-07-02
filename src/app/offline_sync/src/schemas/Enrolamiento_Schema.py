# offline_sync/schemas/Enrolamiento_Schema.py
from pydantic import BaseModel, Field


class EnrolamientoItem(BaseModel):
    """Un rostro a enrolar, en uno de DOS modos (según venga `id_trabajador`):

    • ASIGNAR a existente: manda `id_trabajador` + `embedding`. Le pone (o reemplaza)
      el rostro a un trabajador que YA existe (típico: uno de SYS21 sin rostro). No
      crea ni edita sus datos.
    • WALK-IN (alta nueva): NO mandes `id_trabajador`; manda `id_local` + datos
      (`nombre`, `apellido`, `id_area`). Crea un trabajador con id_emp=id_local y
      origen 'apk' (para gente que NO está en la nómina).
    """
    embedding: list[float]
    id_empresa: int

    # Modo ASIGNAR a existente:
    id_trabajador: int | None = Field(None, description="Si viene, asigna el rostro a este trabajador existente.")

    # Modo WALK-IN (se ignoran si viene id_trabajador):
    id_local: str | None = Field(None, description="UUID del dispositivo; será id_emp con origen 'apk'.")
    nombre: str | None = None
    apellido: str | None = None
    id_area: int | None = None
    permiso_escaneo: str = "campo"

    calidad: float | None = None
    modelo_ia: str | None = None


class EnrolamientoRequest(BaseModel):
    items: list[EnrolamientoItem]


class ItemRechazado(BaseModel):
    indice: int
    id_local: str | None = None
    id_trabajador: int | None = None
    motivo: str


class ItemEnrolado(BaseModel):
    """Resultado OK de un item, para que el APK ligue su id_local con el
    id_trabajador que asignó el server (sin re-descargar todo el roster)."""
    indice: int
    id_local: str | None = None       # el que mandó el dispositivo (walk-in)
    id_trabajador: int                # PK real en la BD (para reconocer offline ya)
    modo: str                         # 'walkin' | 'asignado'
    creado: bool = False              # walk-in: True=alta nueva, False=actualizado


class EnrolamientoResponse(BaseModel):
    creados: int = 0       # walk-in nuevos
    actualizados: int = 0  # walk-in que ya existían (mismo id_local)
    asignados: int = 0     # rostros puestos a un trabajador existente
    enrolados: list[ItemEnrolado] = []   # mapa id_local → id_trabajador de los OK
    rechazados: list[ItemRechazado] = []
