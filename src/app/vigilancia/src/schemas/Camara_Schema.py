# vigilancia/schemas/Camara_Schema.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TipoConexion = Literal["ip_directa", "ip_dvr", "analogica"]


class CamaraBase(BaseModel):
    nombre: str
    id_empresa: int
    id_area: int | None = None
    id_puerta: int | None = None
    id_dispositivo: int | None = None
    marca: str = "hikvision"
    host: str | None = None   # si va vacío, hereda la IP del grupo DVR (grupos_dvr.host)
    puerto: int = 80
    canal: int = 101
    ruta_snapshot: str | None = None
    usuario: str | None = None
    tipo_camara: str = "asistencia"   # +'seguimiento' (reid)
    # ip_directa (IP propia) | ip_dvr (IP tras DVR) | analogica (solo DVR, baja res, no caras)
    tipo_conexion: TipoConexion = "ip_directa"
    tipo_registro: str = "entrada"
    habilitada: bool = True
    modo_captura: str = "sondeo"   # 'sondeo' (poll) o 'evento' (webhook del terminal)
    gap_muestreo_seg: float = 0.7
    umbral_movimiento: float = 2.5
    cooldown_seg: int = 90
    # ── Seguimiento (reid) ──────────────────────────────────────────────────────
    # Solo aplican a cámaras 'seguimiento'. La credencial la aporta el grupo (DVR).
    id_grupo_dvr: int | None = None
    roi_poligono: str | None = None                 # "x1,y1;x2,y2;..."
    params_reid: dict | None = None                 # {min_alto, sim_umbral, ...}


class CamaraCreate(CamaraBase):
    # Contraseña EN CLARO del terminal; el servicio la CIFRA (Fernet) antes de
    # guardarla en credencial_cifrada. Nunca se persiste ni se devuelve en claro.
    credencial: str | None = Field(None, description="Contraseña del terminal (se cifra al guardar).")


class CamaraUpdate(BaseModel):
    # Todos opcionales (PATCH parcial).
    nombre: str | None = None
    id_area: int | None = None
    id_puerta: int | None = None
    id_dispositivo: int | None = None
    marca: str | None = None
    host: str | None = None
    puerto: int | None = None
    canal: int | None = None
    ruta_snapshot: str | None = None
    usuario: str | None = None
    credencial: str | None = Field(None, description="Nueva contraseña (se cifra al guardar).")
    tipo_camara: str | None = None
    tipo_registro: str | None = None
    habilitada: bool | None = None
    modo_captura: str | None = None
    tipo_conexion: TipoConexion | None = None
    gap_muestreo_seg: float | None = None
    umbral_movimiento: float | None = None
    cooldown_seg: int | None = None
    id_grupo_dvr: int | None = None
    roi_poligono: str | None = None
    params_reid: dict | None = None
    estado: str | None = None


class CamaraOut(CamaraBase):
    """Salida pública. NUNCA incluye la credencial (ni cifrada ni en claro)."""
    id_camara: int
    estado: str
    ultima_conexion: datetime | None = None
    ultimo_frame_ts: datetime | None = None
    fecha_creacion: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
