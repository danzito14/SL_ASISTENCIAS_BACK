# app/services/intento_acceso_service.py
"""
Consulta de intentos de acceso rechazados (spoofing / desconocido / otra empresa).
Los crea el scanner (scanner_service); aquí solo se listan/consultan, scopeados
por la empresa de la PUERTA.
"""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from src.models.IntentoAcceso_Model import IntentoAcceso
from src.models.Incidencia_Model import Incidencia
from src.schemas.IntentoAcceso_Schema import IntentoAccesoUpdate
from src.services.Asistencia_Service import asistencia_service
from src.services.Media_Service import media_service

logger = logging.getLogger(__name__)


class IntentoAccesoService:

    def _enriquecer(self, intento: IntentoAcceso) -> IntentoAcceso:
        """Rellena el nombre del trabajador (transitorio) si el intento tiene uno."""
        trab = intento.trabajador
        intento.id_emp = trab.id_emp if trab else None
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

    def actualizar(self, id_intento: UUID, datos: IntentoAccesoUpdate, db: Session) -> IntentoAcceso:
        """
        Actualiza un intento (hoy solo su estado de revisión). Al pasar a
        'justificada' (solo en la transición) un intento 'otra_empresa' crea una
        asistencia manual con la puerta/empresa del intento, en la misma transacción.
        """
        intento = self.obtener(id_intento, db)
        estado_anterior = intento.estado

        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(intento, campo, valor)

        try:
            if intento.estado == "justificada" and estado_anterior != "justificada":
                self._al_justificar(intento, db)
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al actualizar intento: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar el intento: {exc.orig}",
            )
        db.refresh(intento)
        return self._enriquecer(intento)

    # ── Efectos al justificar un intento ───────────────────────────────────────
    def _al_justificar(self, intento: IntentoAcceso, db: Session) -> None:
        """
        Solo 'otra_empresa' genera asistencia: tiene trabajador (el reconocido de
        otra empresa) y puerta. 'spoofing'/'desconocido' no tienen trabajador → nada.
        """
        if intento.tipo != "otra_empresa":
            return
        if intento.id_trabajador is None or intento.id_puerta is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede justificar este intento: faltan trabajador o puerta.",
            )

        momento = intento.fecha or datetime.now(timezone.utc)
        if asistencia_service.existe_asistencia_dia(db, intento.id_trabajador, "entrada", momento):
            logger.info("Intento otra_empresa %s: ya hay entrada ese día; no se duplica.", intento.id_intento)
        else:
            asistencia_service.crear_asistencia_manual(
                db,
                id_trabajador=intento.id_trabajador,
                id_puerta=intento.id_puerta,
                id_empresa=intento.id_empresa,
                tipo_registro="entrada",
                fecha_hora=momento,
                observaciones=f"Asistencia manual al justificar intento otra_empresa {intento.id_intento}.",
                ubicacion=intento.ubicacion,
                id_dispositivo=intento.id_dispositivo,
                confianza_biometrica=round(intento.similitud, 2) if intento.similitud is not None else None,
            )

        self._cascada_incidencia(intento, db)

    def _cascada_incidencia(self, intento: IntentoAcceso, db: Session) -> None:
        """
        Marca como 'justificada' la incidencia 'acceso_otra_empresa' del mismo evento
        (mismo trabajador, día ±1 por desfase de zona horaria) si sigue sin justificar.
        Best-effort: no hay FK entre intento e incidencia, así que se empareja por datos.
        """
        if intento.fecha is None:
            return
        dia = intento.fecha.date()
        incidencias = (
            db.query(Incidencia)
            .filter(
                Incidencia.id_trabajador == intento.id_trabajador,
                Incidencia.tipo_incidencia == "acceso_otra_empresa",
                Incidencia.estado != "justificada",
                Incidencia.fecha >= dia - timedelta(days=1),
                Incidencia.fecha <= dia + timedelta(days=1),
            )
            .all()
        )
        for inc in incidencias:
            inc.estado = "justificada"

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
