# vigilancia/schemas/GrupoDvr_Schema.py
# Grupo de cámaras de seguimiento (reid) por DVR. La contraseña del DVR llega EN CLARO
# (credencial) y el servicio la CIFRA (Fernet) antes de persistir; nunca se devuelve.
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GrupoDvrBase(BaseModel):
    nombre: str
    id_empresa: int
    host: str | None = None       # IP del DVR (opcional)
    usuario: str | None = None


class GrupoDvrCreate(GrupoDvrBase):
    # Contraseña EN CLARO del DVR; el servicio la CIFRA (Fernet) antes de guardarla en
    # credencial_cifrada. Nunca se persiste ni se devuelve en claro.
    credencial: str | None = Field(None, description="Contraseña del DVR (se cifra al guardar).")
    credencial_camaras: str | None = Field(
        None, description="Opcional: contraseña de las CÁMARAS del DVR para acceso por IP directa.")


class GrupoDvrUpdate(BaseModel):
    # Todos opcionales (PATCH parcial).
    nombre: str | None = None
    host: str | None = None
    usuario: str | None = None
    credencial: str | None = Field(None, description="Nueva contraseña del DVR (se cifra al guardar).")
    credencial_camaras: str | None = Field(
        None, description="Nueva contraseña de las cámaras (acceso por IP directa; se cifra).")
    estado: str | None = None


class GrupoDvrOut(GrupoDvrBase):
    """Salida pública. NUNCA incluye la credencial (ni cifrada ni en claro)."""
    id_grupo_dvr: int
    estado: str
    fecha_creacion: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
