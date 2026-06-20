import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.models.Dispositivo_PuertaAcceso_Model import PuertaAcceso
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo
from src.schemas.Dispositivo_PuertaAcceso_Schema import PuertaAccesoCreate, PuertaAccesoUpdate
from src.schemas._geo import punto_desde_latlon

logger = logging.getLogger(__name__)


class PuertaAccesoService:

    def registrar_puerta(self, datos: PuertaAccesoCreate, db: Session) -> PuertaAcceso:
        """
        Registra una puerta de acceso. Las FK (id_area, id_dispositivo) son
        opcionales; si se envían deben existir o el INSERT fallará.

        Args:
            datos: Datos de la puerta (nombre_puerta, ubicacion, id_area, ...)
            db: Sesión de BD
        Returns:
            La puerta creada.
        """
        # id_empresa denormalizado: el explícito manda; si no, se deriva del área.
        id_empresa = datos.id_empresa
        if id_empresa is None and datos.id_area is not None:
            fila = db.query(AreaTrabajo.id_empresa).filter(
                AreaTrabajo.id_area == datos.id_area
            ).first()
            id_empresa = fila[0] if fila else None
        puerta = PuertaAcceso(
            nombre_puerta=datos.nombre_puerta,
            ubicacion=punto_desde_latlon(datos.latitud, datos.longitud),
            id_area=datos.id_area,
            id_empresa=id_empresa,
            id_dispositivo=datos.id_dispositivo,
            tipo_puerta=datos.tipo_puerta,
            funcion_puerta=datos.funcion_puerta,
            categoria_zona_destino=datos.categoria_zona_destino,
            tipo_acceso=datos.tipo_acceso,
            requiere_autorizacion=datos.requiere_autorizacion,
            estado=datos.estado,
        )
        db.add(puerta)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al registrar puerta: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo registrar la puerta: {exc.orig}",
            )
        db.refresh(puerta)

        return puerta

    def empresa_de_puerta(self, id_puerta: int, db: Session) -> int | None:
        """Devuelve el id_empresa de la puerta indicada, o None si no existe."""
        fila = (
            db.query(PuertaAcceso.id_empresa)
            .filter(PuertaAcceso.id_puerta == id_puerta)
            .first()
        )
        return fila[0] if fila else None

    def listar_puertas(
        self, db: Session, skip: int = 0, limit: int = 100, id_empresa: int | None = None, nombre: str | None = None
    ) -> list[PuertaAcceso]:
        """
        Devuelve las puertas de acceso registradas, ordenadas por id.

        Args:
            db:         Sesión de BD
            skip:       Cuántos registros saltar (paginación)
            limit:      Máximo de registros a devolver
            id_empresa: Si no es None, filtra por esa empresa. None = todas.
        Returns:
            Lista de puertas de acceso.
        """
        query = db.query(PuertaAcceso)
        if id_empresa is not None:
            query = query.filter(PuertaAcceso.id_empresa == id_empresa)
        if nombre is not None:
            query = query.filter(PuertaAcceso.nombre_puerta.ilike(f"%{nombre}%"))
        return (
            query
            .order_by(PuertaAcceso.id_puerta)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def obtener_puerta(self, id_puerta: int, db: Session) -> PuertaAcceso:
        """
        Devuelve una puerta de acceso por su id o lanza 404 si no existe.

        Args:
            id_puerta: Id de la puerta de acceso
            db:        Sesión de BD
        Returns:
            La puerta de acceso encontrada.
        """
        puerta = db.query(PuertaAcceso).filter(PuertaAcceso.id_puerta == id_puerta).first()
        if not puerta:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Puerta de acceso {id_puerta} no encontrada.",
            )
        return puerta

    def actualizar_puerta(self, id_puerta: int, datos: PuertaAccesoUpdate, db: Session) -> PuertaAcceso:
        """
        Actualiza parcialmente una puerta (solo los campos enviados). Si llegan
        latitud y longitud, reemplaza la ubicación (geography POINT,4326).
        """
        puerta = self.obtener_puerta(id_puerta, db)

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
            puerta.ubicacion = punto_desde_latlon(lat, lon)

        for campo, valor in cambios.items():
            setattr(puerta, campo, valor)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al actualizar puerta: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar la puerta: {exc.orig}",
            )
        db.refresh(puerta)
        return puerta

    def eliminar_puerta(self, id_puerta: int, db: Session) -> PuertaAcceso:
        """Baja lógica (soft delete): marca la puerta como 'inactivo'."""
        puerta = self.obtener_puerta(id_puerta, db)
        puerta.estado = "inactivo"
        db.commit()
        db.refresh(puerta)
        return puerta


puertaacceso_service = PuertaAccesoService()
