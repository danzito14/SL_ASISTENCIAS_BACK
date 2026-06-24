# workers/services/tenancy_service.py
"""
Facade de lectura de TENANCY que workers necesita: la empresa de un área y si el
área está activa (para validar el destino al crear/mover un trabajador y derivar su
empresa). Lee la tabla area_trabajo con los grants de svc_workers.

Es la costura: HOY es SQL directo (BD compartida); al separar la BD pasa a cliente
HTTP de tenancy sin tocar a los consumidores.
"""
import logging

from sqlalchemy.orm import Session

from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo

logger = logging.getLogger(__name__)


class TenancyService:

    def empresa_de_area(self, id_area: int, db: Session) -> int | None:
        """Empresa a la que pertenece un área, o None si no existe."""
        fila = (
            db.query(AreaTrabajo.id_empresa)
            .filter(AreaTrabajo.id_area == id_area)
            .first()
        )
        return fila[0] if fila else None

    def obtener_area_activa(self, id_area: int, db: Session) -> AreaTrabajo | None:
        """Devuelve el área si existe y está activa, o None."""
        return (
            db.query(AreaTrabajo)
            .filter(AreaTrabajo.id_area == id_area, AreaTrabajo.estado == "activo")
            .first()
        )


tenancy_service = TenancyService()
