# Registra los modelos de employee_monitoring en el registry de Base antes de los mappers.
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador
from src.models.Embedding_Model import Embedding
from src.models.SyncEstado_Model import SyncEstado
from src.models.FotoPendiente_Model import FotoPendiente

__all__ = ["AreaTrabajo", "Trabajador", "Embedding", "SyncEstado", "FotoPendiente"]
