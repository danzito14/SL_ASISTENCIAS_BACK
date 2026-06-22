# Registra los modelos de tenancy en el registry de Base antes de los mappers.
from src.models.Empresa_Model import Empresa
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo
from src.models.Dispositivo_PuertaAcceso_Model import Dispositivo, PuertaAcceso

__all__ = ["Empresa", "AreaTrabajo", "Dispositivo", "PuertaAcceso"]
