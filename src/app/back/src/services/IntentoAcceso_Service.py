# app/services/intento_acceso_service.py
"""
Consulta de intentos de acceso rechazados (spoofing / desconocido / otra empresa).
Los crea el scanner (scanner_service); aquí solo se listan/consultan, scopeados
por la empresa de la PUERTA.
"""
import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from src.models.IntentoAcceso_Model import IntentoAcceso
from src.services.Media_Service import media_service

logger = logging.getLogger(__name__)


class IntentoAccesoService:

    def _enriquecer(self, intento: IntentoAcceso) -> IntentoAcceso:
        """Rellena el nombre del trabajador (transitorio) si el intento tiene uno."""
        trab = intento.trabajador
        intento.trabajador_nombre = f"{trab.nombre} {trab.apellido}" if trab else None
        return intento

    def listar(
        self,
        db: Session,
        id_empresa: int | None = None,
        skip: int = 0,
        limit: int = 100,
        tipo: str | None = None,
        id_puerta: int | None = None,
    ) -> list[IntentoAcceso]:
        """
        Lista intentos de acceso (más reciente primero). Acota por la empresa de la
        puerta salvo que id_empresa sea None (super-admin → todas).
        """
        query = db.query(IntentoAcceso).options(joinedload(IntentoAcceso.trabajador))
        if id_empresa is not None:
            query = query.filter(IntentoAcceso.id_empresa == id_empresa)
        if tipo is not None:
            query = query.filter(IntentoAcceso.tipo == tipo)
        if id_puerta is not None:
            query = query.filter(IntentoAcceso.id_puerta == id_puerta)

        intentos = (
            query.order_by(IntentoAcceso.id_intento.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return [self._enriquecer(i) for i in intentos]

    def obtener(self, id_intento: UUID, db: Session) -> IntentoAcceso:
        """Devuelve un intento por su id o lanza 404."""
        intento = (
            db.query(IntentoAcceso)
            .options(joinedload(IntentoAcceso.trabajador))
            .filter(IntentoAcceso.id_intento == id_intento)
            .first()
        )
        if not intento:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intento de acceso {id_intento} no encontrado.",
            )
        return self._enriquecer(intento)

    def empresa_de_intento(self, id_intento: UUID, db: Session) -> int | None:
        """Empresa (de la puerta) a la que pertenece un intento, o None si no existe."""
        fila = (
            db.query(IntentoAcceso.id_empresa)
            .filter(IntentoAcceso.id_intento == id_intento)
            .first()
        )
        return fila[0] if fila else None

    def foto_bytes(self, id_intento: UUID, db: Session) -> bytes | None:
        """
        Bytes JPEG de la foto del intento, recuperados del servicio media. None si no
        hay foto o media no la encuentra. Lanza 404 si el intento no existe.
        """
        intento = self.obtener(id_intento, db)
        return media_service.obtener_bytes(intento.ruta_foto)


intento_acceso_service = IntentoAccesoService()
