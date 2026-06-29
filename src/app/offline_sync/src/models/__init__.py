# Registra los modelos compartidos en el registry de Base antes de los mappers.
# offline_sync usa principalmente SQL crudo (text()) para roster/ingesta/enrolamiento;
# estos modelos existen por consistencia con el resto del repo y para validar el esquema.
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador
from src.models.Embedding_Model import Embedding

__all__ = ["AreaTrabajo", "Trabajador", "Embedding"]
