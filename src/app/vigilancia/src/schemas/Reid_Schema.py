# vigilancia/schemas/Reid_Schema.py
from pydantic import BaseModel, Field


class AvistamientoIn(BaseModel):
    """Lo que manda el motor de seguimiento por cada detección NUEVA de una cámara."""
    id_camara: int
    embedding: list[float] = Field(..., description="Firma OSNet-AIN L2-norm (512 floats).")
    bbox: str | None = None            # "x1,y1,x2,y2" en el frame
    ruta_crop: str | None = None       # foto de la vestimenta (opcional)
    umbral: float | None = None        # override del umbral coseno (default del servicio)
