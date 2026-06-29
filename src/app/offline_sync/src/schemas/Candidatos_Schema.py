# offline_sync/schemas/Candidatos_Schema.py
from pydantic import BaseModel


class CandidatoTrabajador(BaseModel):
    """Trabajador activo SIN rostro: candidato a que el operador le asigne uno."""
    id_trabajador: int
    nombre: str
    apellido: str
    id_area: int | None = None
    tipo_area: str | None = None
    permiso_escaneo: str
    id_emp: str | None = None        # identidad en SYS21 (si vino de la nómina)
    origen_nomina: str | None = None


class CandidatosResponse(BaseModel):
    empresa: int
    tipo: str | None = None
    total: int
    candidatos: list[CandidatoTrabajador]
