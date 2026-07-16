# Registra los modelos propios en el registry de Base antes de los mappers.
from src.models.Camara_Model import Camara
from src.models.EventoCamara_Model import EventoCamara
from src.models.GrupoDvr_Model import GrupoDvr

__all__ = ["Camara", "EventoCamara", "GrupoDvr"]
