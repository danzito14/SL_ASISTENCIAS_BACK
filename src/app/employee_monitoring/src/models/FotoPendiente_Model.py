# employee_monitoring/models/foto_pendiente.py
# Empleados cuya foto NO pasó las reglas de validación: hay que volver a tomarla.
# La llena el sync con el motivo del rechazo; un admin la consulta por endpoint.
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from src.core.pgdb import Base

# Motivos canónicos de rechazo (deben coincidir con los que emite el pipeline):
#   validación local:  formato_invalido | resolucion_baja | archivo_corrupto | archivo_grande | muy_oscura | muy_clara
#   recognition:       no_rostro | multiples_caras | det_score_bajo | cara_pequena | pose_no_frontal | borrosa | spoofing | recognition_no_disponible | duplicado
#   sin archivo:       sin_foto
#   mapeo:             area_invalida
MOTIVOS = (
    "formato_invalido", "resolucion_baja", "archivo_corrupto", "archivo_grande",
    "muy_oscura", "muy_clara",
    "sin_foto", "no_rostro", "multiples_caras", "det_score_bajo", "cara_pequena",
    "pose_no_frontal", "borrosa", "spoofing", "recognition_no_disponible",
    "duplicado", "area_invalida",
)


class FotoPendiente(Base):
    __tablename__ = "fotos_pendientes"

    id_pendiente  = Column(Integer, primary_key=True, autoincrement=True)
    id_emp        = Column(String(50), nullable=False)
    origen_nomina = Column(String(30), nullable=False)
    id_trabajador = Column(Integer, ForeignKey("trabajadores.id_trabajador", ondelete="CASCADE"), nullable=True)
    id_empresa    = Column(Integer)
    motivo        = Column(String(40), nullable=False)
    detalle       = Column(Text)
    fecha         = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    estado        = Column(String(15), nullable=False, default="pendiente")  # 'pendiente' | 'resuelto' | 'ignorado'
