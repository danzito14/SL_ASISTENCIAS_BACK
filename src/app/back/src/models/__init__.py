# Paquete de modelos (SQLAlchemy).
#
# Importar TODOS los modelos aquí garantiza que sus clases queden registradas
# en el mismo registry de Base antes de que SQLAlchemy configure los mappers.
# Si no, las relaciones por nombre (p. ej. relationship("Dispositivo")) fallan
# con "failed to locate a name" cuando la clase aún no se importó.

from src.models.Rol_Usuario_Model import Rol, Usuario
from src.models.Empresa_Model import Empresa
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador
from src.models.Embedding_Model import Embedding
from src.models.Dispositivo_PuertaAcceso_Model import Dispositivo, PuertaAcceso
from src.models.Asistencia_HistorialAuditoria_Model import Asistencia, HistorialAuditoria
from src.models.Escaneo_Model import Escaneo
from src.models.Incidencia_Model import Incidencia
from src.models.IntentoAcceso_Model import IntentoAcceso
from src.models.ParametroSistema_Model import ParametroSistema

__all__ = [
    "Rol",
    "Usuario",
    "Empresa",
    "AreaTrabajo",
    "Trabajador",
    "Embedding",
    "Dispositivo",
    "PuertaAcceso",
    "Asistencia",
    "HistorialAuditoria",
    "Escaneo",
    "Incidencia",
    "IntentoAcceso",
    "ParametroSistema",
]
