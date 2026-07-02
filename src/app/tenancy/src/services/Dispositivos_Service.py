import logging

from sqlalchemy import cast, String
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.models.Dispositivo_PuertaAcceso_Model import Dispositivo
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo
from src.schemas.Dispositivo_PuertaAcceso_Schema import DispositivoBase, DispositivoCreate, DispositivoResponse, DispositivoUpdate
from src.schemas._geo import punto_desde_latlon

logger = logging.getLogger(__name__)

class DispositivosService:

    def registrar_dispositivo(self, datos: DispositivoCreate, db: Session) -> Dispositivo:
        """
            Registra en la db un nuevo dispositivo que se usara para utilizar el programa

            Args:
                datos: Datos del dispositivo (nombre_dispositivo, tipo, ip_dispositivo, puerto, ubicacion, id_area, estado y fecha)

            Returns:
                Dispositivo creado
        """
        # id_empresa denormalizado: el explícito manda; si no, se deriva del área.
        id_empresa = datos.id_empresa
        if id_empresa is None and datos.id_area is not None:
            id_empresa = self.empresa_de_area(datos.id_area, db)
        dispositivo = Dispositivo(
            nombre_dispositivo = datos.nombre_dispositivo,
            tipo_dispositivo = datos.tipo_dispositivo,
            ip_dispositivo = datos.ip_dispositivo,
            puerto= datos.puerto,
            ubicacion = punto_desde_latlon(datos.latitud, datos.longitud),
            id_area = datos.id_area,
            id_empresa = id_empresa,
            estado= datos.estado,
                )
        db.add(dispositivo)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al registrar el dispositivo: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo registrar el dispositivo: {exc.orig}",
            )
        db.refresh(dispositivo)

        return dispositivo

    def listar_dispositivos(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        id_empresa: int | None = None,
        nombre: str | None = None,
    ) -> list[Dispositivo]:
        """
        Devuelve los dispositivos registrados, ordenados por id.

        Args:
            db:         Sesión de BD
            skip:       Cuántos registros saltar (paginación)
            limit:      Máximo de registros a devolver
            id_empresa: Si se indica, solo dispositivos de esa empresa (vía su área).
                        None = todas (admin).
        Returns:
            Lista de dispositivos.
        """
        query = db.query(Dispositivo)
        if id_empresa is not None:
            query = query.filter(Dispositivo.id_empresa == id_empresa)

        if nombre is not None:
            query = query.filter(Dispositivo.nombre_dispositivo.ilike(f"%{nombre}%"))

        return (
            query
            .order_by(Dispositivo.id_dispositivo)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def buscar_dispositivos_por_id(
        self,
        db: Session,
        id_dispositivo: str,
        skip: int = 0,
        limit: int = 100,
        id_empresa: int | None = None,
    ) -> list[Dispositivo]:
        """
        Busca dispositivos por su id con coincidencia PARCIAL (el id se compara como
        texto) y paginación. Si id_empresa no es None, acota a esa empresa.
        """
        query = db.query(Dispositivo).filter(
            cast(Dispositivo.id_dispositivo, String).ilike(f"%{id_dispositivo}%")
        )
        if id_empresa is not None:
            query = query.filter(Dispositivo.id_empresa == id_empresa)
        return (
            query
            .order_by(Dispositivo.id_dispositivo)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def obtener_dispositivo(self, id_dispositivo: int, db: Session) -> Dispositivo:
        """Devuelve un dispositivo por su id o lanza 404 si no existe."""
        dispositivo = db.query(Dispositivo).filter(
            Dispositivo.id_dispositivo == id_dispositivo
        ).first()
        if not dispositivo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dispositivo {id_dispositivo} no encontrado.",
            )
        return dispositivo

    def actualizar_dispositivo(self, id_dispositivo: int, datos: DispositivoUpdate, db: Session) -> Dispositivo:
        """
        Actualiza parcialmente un dispositivo (solo los campos enviados). Si llegan
        latitud y longitud, reemplaza la ubicación (geography POINT,4326).
        """
        dispositivo = self.obtener_dispositivo(id_dispositivo, db)

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
            dispositivo.ubicacion = punto_desde_latlon(lat, lon)

        # Si cambia el área y no se mandó id_empresa explícito, se recalcula
        # el id_empresa denormalizado para que siga al área.
        if "id_area" in cambios and "id_empresa" not in cambios and cambios["id_area"] is not None:
            cambios["id_empresa"] = self.empresa_de_area(cambios["id_area"], db)

        for campo, valor in cambios.items():
            setattr(dispositivo, campo, valor)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al actualizar dispositivo: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar el dispositivo: {exc.orig}",
            )
        db.refresh(dispositivo)
        return dispositivo

    def eliminar_dispositivo(self, id_dispositivo: int, db: Session) -> Dispositivo:
        """Baja lógica (soft delete): marca el dispositivo como 'inactivo'."""
        dispositivo = self.obtener_dispositivo(id_dispositivo, db)
        dispositivo.estado = "inactivo"
        db.commit()
        db.refresh(dispositivo)
        return dispositivo

    # ── Derivación de empresa (para la encapsulación por empresa) ──────────────
    def empresa_de_area(self, id_area: int, db: Session) -> int | None:
        """Empresa a la que pertenece un área, o None si el área no existe."""
        fila = db.query(AreaTrabajo.id_empresa).filter(AreaTrabajo.id_area == id_area).first()
        return fila[0] if fila else None

    def empresa_de_dispositivo(self, id_dispositivo: int, db: Session) -> int | None:
        """Empresa de un dispositivo (id_empresa denormalizado), o None si no existe."""
        fila = (
            db.query(Dispositivo.id_empresa)
            .filter(Dispositivo.id_dispositivo == id_dispositivo)
            .first()
        )
        return fila[0] if fila else None

dispositivo_service = DispositivosService()


