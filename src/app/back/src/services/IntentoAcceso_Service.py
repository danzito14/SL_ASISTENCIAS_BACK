# app/services/intento_acceso_service.py
"""
Consulta de intentos de acceso rechazados (spoofing / desconocido / otra empresa).
Los crea el scanner (scanner_service); aquí solo se listan/consultan, scopeados
por la empresa de la PUERTA.
"""
import logging
import os
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from src.core.config import settings
from src.models.IntentoAcceso_Model import IntentoAcceso

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

    def ruta_archivo_foto(self, id_intento: UUID, db: Session) -> str | None:
        """
        Resuelve la ruta ABSOLUTA en disco de la foto del intento (mapea ruta_foto
        '/media/intentos/...' a la carpeta de media). None si no hay foto o falta el
        archivo. Lanza 404 si el intento no existe.
        """
        intento = self.obtener(id_intento, db)
        if not intento.ruta_foto:
            return None

        rel = intento.ruta_foto
        if rel.startswith(settings.MEDIA_URL):
            rel = rel[len(settings.MEDIA_URL):]
        rel = rel.lstrip("/\\")

        base = os.path.normpath(settings.media_base_dir)
        ruta = os.path.normpath(os.path.join(base, rel))
        if not ruta.startswith(base):  # defensa anti path-traversal
            logger.warning("Ruta de foto fuera de media (posible traversal): %s", intento.ruta_foto)
            return None
        return ruta if os.path.isfile(ruta) else None


intento_acceso_service = IntentoAccesoService()
