import logging
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.models.Escaneo_Model import Escaneo
from src.models.AreaTrabajo_Trabajador_Model import Trabajador
from src.schemas.Escaneo_Schema import EscaneoCreate, EscaneoUpdate
from src.schemas._geo import punto_desde_latlon

logger = logging.getLogger(__name__)


class EscaneoService:

    def registrar_escaneo(self, datos: EscaneoCreate, db: Session) -> Escaneo:
        """
        Registra manualmente un escaneo. La ubicación llega como latitud/longitud
        y se guarda como geography(POINT,4326). id_empresa se deriva del trabajador
        (denormalizado, multi-tenant). El id_escaneo (UUIDv7) lo genera la BD.
        """
        escaneo = Escaneo(
            id_trabajador=datos.id_trabajador,
            id_puerta=datos.id_puerta,
            id_empresa=self.empresa_de_trabajador(datos.id_trabajador, db),
            tipo_registro=datos.tipo_registro,
            confianza_biometrica=datos.confianza_biometrica,
            estado_registro=datos.estado_registro,
            observaciones=datos.observaciones,
            id_dispositivo=datos.id_dispositivo,
            ubicacion=punto_desde_latlon(datos.latitud, datos.longitud),
            dentro_de_area=datos.dentro_de_area,
            creado_en_cliente=datos.creado_en_cliente,
            id_dispositivo_origen=datos.id_dispositivo_origen,
        )
        db.add(escaneo)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al registrar escaneo: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo registrar el escaneo: {exc.orig}",
            )
        db.refresh(escaneo)
        return escaneo

    def listar_escaneos(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        id_trabajador: int | None = None,
        id_empresa: int | None = None,
    ) -> list[Escaneo]:
        """
        Devuelve los escaneos, ordenados de más reciente a más antiguo.
        Opcionalmente se filtran por trabajador y/o empresa (id_empresa denormalizado).
        """
        query = db.query(Escaneo)
        if id_trabajador is not None:
            query = query.filter(Escaneo.id_trabajador == id_trabajador)
        if id_empresa is not None:
            query = query.filter(Escaneo.id_empresa == id_empresa)
        return (
            query.order_by(Escaneo.fecha_hora.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def obtener_escaneo(self, id_escaneo: UUID, db: Session) -> Escaneo:
        """Devuelve un escaneo por su id o lanza 404 si no existe."""
        escaneo = db.query(Escaneo).filter(Escaneo.id_escaneo == id_escaneo).first()
        if not escaneo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Escaneo {id_escaneo} no encontrado.",
            )
        return escaneo

    def actualizar_escaneo(self, id_escaneo: UUID, datos: EscaneoUpdate, db: Session) -> Escaneo:
        """
        Actualiza parcialmente un escaneo (solo los campos enviados). Si llegan
        latitud y longitud, reemplaza la ubicación (geography POINT,4326).
        """
        escaneo = self.obtener_escaneo(id_escaneo, db)

        cambios = datos.model_dump(exclude_unset=True)
        tiene_lat = "latitud" in cambios
        tiene_lon = "longitud" in cambios
        lat = cambios.pop("latitud", None)
        lon = cambios.pop("longitud", None)
        if tiene_lat or tiene_lon:
            if not (tiene_lat and tiene_lon):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Para actualizar la ubicación envía latitud y longitud juntas.",
                )
            escaneo.ubicacion = punto_desde_latlon(lat, lon)

        for campo, valor in cambios.items():
            setattr(escaneo, campo, valor)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al actualizar escaneo: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar el escaneo: {exc.orig}",
            )
        db.refresh(escaneo)
        return escaneo

    def eliminar_escaneo(self, id_escaneo: UUID, db: Session) -> Escaneo:
        """
        Baja lógica (soft delete): marca el escaneo como 'cancelado' en
        estado_registro. No borra la fila, para conservar la bitácora.
        """
        escaneo = self.obtener_escaneo(id_escaneo, db)
        escaneo.estado_registro = "cancelado"
        db.commit()
        db.refresh(escaneo)
        return escaneo

    # ── Derivación de empresa (para la encapsulación por empresa) ──────────────
    def empresa_de_trabajador(self, id_trabajador: int, db: Session) -> int | None:
        """Empresa de un trabajador (id_empresa denormalizado), o None si no existe."""
        fila = (
            db.query(Trabajador.id_empresa)
            .filter(Trabajador.id_trabajador == id_trabajador)
            .first()
        )
        return fila[0] if fila else None

    def empresa_de_escaneo(self, id_escaneo: UUID, db: Session) -> int | None:
        """Empresa de un escaneo (id_empresa denormalizado), o None si no existe."""
        fila = (
            db.query(Escaneo.id_empresa)
            .filter(Escaneo.id_escaneo == id_escaneo)
            .first()
        )
        return fila[0] if fila else None


escaneo_service = EscaneoService()
