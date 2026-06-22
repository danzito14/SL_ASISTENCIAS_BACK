# Registra los modelos de workers en el registry de Base antes de los mappers.
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador
from src.models.Embedding_Model import Embedding

__all__ = ["AreaTrabajo", "Trabajador", "Embedding"]
