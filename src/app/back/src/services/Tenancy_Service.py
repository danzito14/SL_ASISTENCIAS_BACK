# app/services/tenancy_service.py
"""
Facade de LECTURA de TENANCY para OTROS dominios (workers, access).

Tenancy es dueño de la estructura física: empresas, áreas, puertas y dispositivos.
Otros dominios necesitan ciertos datos estructurales (la empresa de un área, si un
área está activa, …). En vez de que workers/access consulten los modelos de tenancy
directamente, pasan por este facade: HOY es una llamada en proceso; al extraer
'tenancy' como microservicio se reemplaza por un cliente HTTP/evento sin tocar a los
consumidores (ver PLAN_MICROSERVICIOS §3 y §9). Las operaciones CRUD de tenancy
viven en sus services propios (AreaTrabajo/PuertaAcceso/Dispositivo/Empresa); este
facade expone solo lo que el resto del sistema lee de tenancy.
"""
import logging

from sqlalchemy.orm import Session

from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo
from src.models.Dispositivo_PuertaAcceso_Model import Dispositivo, PuertaAcceso

logger = logging.getLogger(__name__)


class TenancyService:

    def empresa_de_area(self, id_area: int, db: Session) -> int | None:
        """Empresa a la que pertenece un área, o None si el área no existe."""
        fila = (
            db.query(AreaTrabajo.id_empresa)
            .filter(AreaTrabajo.id_area == id_area)
            .first()
        )
        return fila[0] if fila else None

    def obtener_area_activa(self, id_area: int, db: Session) -> AreaTrabajo | None:
        """
        Devuelve el área si existe y está activa, o None. La usan workers para
        validar el destino antes de crear/mover un trabajador (y derivar su empresa).
        """
        return (
            db.query(AreaTrabajo)
            .filter(AreaTrabajo.id_area == id_area, AreaTrabajo.estado == "activo")
            .first()
        )

    # ── Puertas / dispositivos (lo que access lee de tenancy) ──────────────────
    def empresa_de_puerta(self, id_puerta: int, db: Session) -> int | None:
        """Empresa a la que pertenece una puerta, o None si no existe. La usa access
        para acotar la búsqueda facial y registrar el intento por la empresa de la puerta."""
        fila = (
            db.query(PuertaAcceso.id_empresa)
            .filter(PuertaAcceso.id_puerta == id_puerta)
            .first()
        )
        return fila[0] if fila else None

    def obtener_puerta(self, id_puerta: int, db: Session) -> PuertaAcceso | None:
        """Devuelve la puerta por id (o None). access la usa para validar el destino
        del escaneo y heredar su ubicación cuando no llega GPS."""
        return db.query(PuertaAcceso).get(id_puerta)

    def obtener_dispositivo(self, id_dispositivo: int, db: Session) -> Dispositivo | None:
        """Devuelve el dispositivo por id (o None). Para validar el destino del escaneo."""
        return db.query(Dispositivo).get(id_dispositivo)


tenancy_service = TenancyService()
