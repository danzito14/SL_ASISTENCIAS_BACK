# Modelos de SOLO LECTURA para los reportes (sin relaciones → mappers triviales).
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador
from src.models.Asistencia_HistorialAuditoria_Model import Asistencia
from src.models.Incidencia_Model import Incidencia
from src.models.IntentoAcceso_Model import IntentoAcceso
from src.models.Empresa_Model import Empresa

__all__ = ["AreaTrabajo", "Trabajador", "Asistencia", "Incidencia", "IntentoAcceso", "Empresa"]
