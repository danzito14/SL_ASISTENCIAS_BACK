# app/services/incidencia_service.py
"""
Servicio CRUD de incidencias.

Algunas incidencias las crea la BD automáticamente (triggers/funciones de
cierre de día); estos endpoints permiten registrarlas y gestionarlas a mano
desde el panel (revisar, justificar, corregir).
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.core.config import settings
from src.models.Incidencia_Model import Incidencia
from src.models.IntentoAcceso_Model import IntentoAcceso
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador
from src.schemas.Incidencia_Schema import IncidenciaCreate, IncidenciaUpdate

# Texto legible para describir un intento en la vista combinada.
_DESC_INTENTO = {
    "spoofing": "Posible foto/pantalla (spoofing)",
    "desconocido": "Rostro desconocido",
    "otra_empresa": "Trabajador de otra empresa",
}

logger = logging.getLogger(__name__)

# Ventana por defecto cuando no se indica un rango de fechas.
DIAS_RANGO_POR_DEFECTO = 7


def resolver_rango_fechas(
    fecha_inicio: date | None,
    fecha_fin: date | None,
    dias_por_defecto: int = DIAS_RANGO_POR_DEFECTO,
) -> tuple[date, date]:
    """
    Resuelve el rango de fechas a consultar:
      - fecha_fin sin valor → hoy.
      - fecha_inicio sin valor → fecha_fin menos `dias_por_defecto` días.
    Así, sin parámetros, devuelve los últimos `dias_por_defecto` días.
    Lanza 400 si fecha_inicio queda después de fecha_fin.
    """
    if fecha_fin is None:
        fecha_fin = date.today()
    if fecha_inicio is None:
        fecha_inicio = fecha_fin - timedelta(days=dias_por_defecto)
    if fecha_inicio > fecha_fin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fecha_inicio no puede ser posterior a fecha_fin.",
        )
    return fecha_inicio, fecha_fin


class IncidenciaService:

    def _enriquecer(self, i: Incidencia) -> Incidencia:
        """Rellena el nombre resuelto (transitorio) que lee IncidenciaResponse."""
        trab = i.trabajador
        i.trabajador_nombre = f"{trab.nombre} {trab.apellido}" if trab else None
        return i

    def registrar_incidencia(self, datos: IncidenciaCreate, db: Session) -> Incidencia:
        """
        Registra una incidencia. Valida que el trabajador exista.

        Args:
            datos: Datos de la incidencia (trabajador, tipo, fecha, etc.)
            db:    Sesión de BD

        Returns:
            La incidencia creada.
        """
        # Validar que el trabajador exista
        trabajador = db.query(Trabajador).filter(
            Trabajador.id_trabajador == datos.id_trabajador
        ).first()
        if not trabajador:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Trabajador {datos.id_trabajador} no encontrado.",
            )

        incidencia = Incidencia(
            id_trabajador=datos.id_trabajador,
            tipo_incidencia=datos.tipo_incidencia,
            fecha=datos.fecha,
            descripcion=datos.descripcion,
            ruta_foto=datos.ruta_foto,
            id_escaneo_ref=datos.id_escaneo_ref,
            estado=datos.estado,
        )
        db.add(incidencia)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al registrar la incidencia: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo registrar la incidencia: {exc.orig}",
            )
        db.refresh(incidencia)
        return self._enriquecer(incidencia)

    def listar_incidencias(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        id_trabajador: int | None = None,
        tipo_incidencia: str | None = None,
        estado: str | None = None,
        id_empresa: int | None = None,
        nombre: str | None = None,
        fecha_inicio: date | None = None,
        fecha_fin: date | None = None,
    ) -> list[Incidencia]:
        """
        Devuelve las incidencias registradas (con paginación y filtros opcionales),
        ordenadas de la más reciente a la más antigua.

        Si id_empresa se indica, solo se devuelven las incidencias de trabajadores
        de esa empresa (vía Trabajador -> AreaTrabajo.id_empresa).

        Si nombre se indica, filtra por nombre/apellido del trabajador asociado
        (parcial, insensible a mayúsculas).

        El rango de fechas (sobre el campo `fecha`) es inclusivo en ambos extremos;
        si no se indica, por defecto devuelve los últimos 7 días.
        """
        fecha_inicio, fecha_fin = resolver_rango_fechas(fecha_inicio, fecha_fin)

        query = db.query(Incidencia).options(joinedload(Incidencia.trabajador))
        # fecha es DATE: rango inclusivo en ambos extremos.
        query = query.filter(
            Incidencia.fecha >= fecha_inicio,
            Incidencia.fecha <= fecha_fin,
        )

        # El join a Trabajador se hace UNA sola vez si se necesita por empresa o por nombre.
        if id_empresa is not None or nombre is not None:
            query = query.join(
                Trabajador, Trabajador.id_trabajador == Incidencia.id_trabajador
            )
        if id_empresa is not None:
            query = (
                query
                .join(AreaTrabajo, AreaTrabajo.id_area == Trabajador.id_area)
                .filter(AreaTrabajo.id_empresa == id_empresa)
            )
        if nombre is not None:
            query = query.filter(
                or_(
                    Trabajador.nombre.ilike(f"%{nombre}%"),
                    Trabajador.apellido.ilike(f"%{nombre}%"),
                )
            )
        if id_trabajador is not None:
            query = query.filter(Incidencia.id_trabajador == id_trabajador)
        if tipo_incidencia is not None:
            query = query.filter(Incidencia.tipo_incidencia == tipo_incidencia)
        if estado is not None:
            query = query.filter(Incidencia.estado == estado)

        incidencias = (
            query
            .order_by(Incidencia.fecha.desc(), Incidencia.id_incidencia.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return [self._enriquecer(i) for i in incidencias]

    def listar_combinado(
        self,
        db: Session,
        id_empresa: int | None = None,
        skip: int = 0,
        limit: int = 100,
        tipo: str | None = None,
        origen: str | None = None,            # 'incidencia' | 'intento' | None (ambos)
        fecha_inicio: date | None = None,
        fecha_fin: date | None = None,
    ) -> list[dict]:
        """
        Vista UNIFICADA: incidencias + intentos de acceso en una sola lista,
        ordenada por fecha/hora descendente. Cada tabla se acota por su propia
        empresa (incidencia → empresa del trabajador; intento → empresa de la
        puerta). Sin filtro de fechas trae lo más reciente según `limit`.
        """
        eventos: list[dict] = []
        tope = skip + limit  # se sobre-trae de cada tabla para paginar tras el merge

        # ── Incidencias ───────────────────────────────────────────────────────
        if origen in (None, "incidencia"):
            q = db.query(Incidencia).options(joinedload(Incidencia.trabajador))
            if id_empresa is not None:
                q = (
                    q.join(Trabajador, Trabajador.id_trabajador == Incidencia.id_trabajador)
                    .join(AreaTrabajo, AreaTrabajo.id_area == Trabajador.id_area)
                    .filter(AreaTrabajo.id_empresa == id_empresa)
                )
            if tipo is not None:
                q = q.filter(Incidencia.tipo_incidencia == tipo)
            if fecha_inicio is not None:
                q = q.filter(Incidencia.fecha >= fecha_inicio)
            if fecha_fin is not None:
                q = q.filter(Incidencia.fecha <= fecha_fin)
            for i in q.order_by(Incidencia.fecha_creacion.desc()).limit(tope).all():
                trab = i.trabajador
                eventos.append({
                    "origen": "incidencia",
                    "id": i.id_incidencia,
                    "tipo": i.tipo_incidencia,
                    "fecha": i.fecha,
                    "fecha_hora": i.fecha_creacion,
                    "descripcion": i.descripcion,
                    "estado": i.estado,
                    "id_trabajador": i.id_trabajador,
                    "trabajador_nombre": f"{trab.nombre} {trab.apellido}" if trab else None,
                    "id_puerta": None,
                    "id_empresa": None,
                    "similitud": None,
                    "tiene_foto": bool(i.ruta_foto),
                    "foto_url": f"/incidencias/{i.id_incidencia}/foto" if i.ruta_foto else None,
                })

        # ── Intentos de acceso ────────────────────────────────────────────────
        if origen in (None, "intento"):
            q = db.query(IntentoAcceso).options(joinedload(IntentoAcceso.trabajador))
            if id_empresa is not None:
                q = q.filter(IntentoAcceso.id_empresa == id_empresa)
            if tipo is not None:
                q = q.filter(IntentoAcceso.tipo == tipo)
            if fecha_inicio is not None:
                q = q.filter(IntentoAcceso.fecha >= fecha_inicio)
            if fecha_fin is not None:  # fecha es timestamptz → < fecha_fin + 1 día (inclusivo)
                q = q.filter(IntentoAcceso.fecha < fecha_fin + timedelta(days=1))
            for t in q.order_by(IntentoAcceso.fecha.desc()).limit(tope).all():
                trab = t.trabajador
                sim = float(t.similitud) if t.similitud is not None else None
                desc = _DESC_INTENTO.get(t.tipo, t.tipo)
                if t.id_puerta is not None:
                    desc += f" en puerta {t.id_puerta}"
                if sim is not None:
                    desc += f" (similitud {sim:.0%})"
                eventos.append({
                    "origen": "intento",
                    "id": t.id_intento,
                    "tipo": t.tipo,
                    "fecha": t.fecha.date() if t.fecha else None,
                    "fecha_hora": t.fecha,
                    "descripcion": desc,
                    "estado": None,
                    "id_trabajador": t.id_trabajador,
                    "trabajador_nombre": f"{trab.nombre} {trab.apellido}" if trab else None,
                    "id_puerta": t.id_puerta,
                    "id_empresa": t.id_empresa,
                    "similitud": sim,
                    "tiene_foto": bool(t.ruta_foto),
                    "foto_url": f"/intentos/{t.id_intento}/foto" if t.ruta_foto else None,
                })

        # Merge: ordenar por fecha/hora desc y paginar sobre el conjunto combinado.
        _min = datetime(1970, 1, 1, tzinfo=timezone.utc)
        eventos.sort(key=lambda e: e["fecha_hora"] or _min, reverse=True)
        return eventos[skip: skip + limit]

    def obtener_incidencia(self, id_incidencia: int, db: Session) -> Incidencia:
        """Devuelve una incidencia por su id o lanza 404 si no existe."""
        incidencia = db.query(Incidencia).options(
            joinedload(Incidencia.trabajador)
        ).filter(
            Incidencia.id_incidencia == id_incidencia
        ).first()
        if not incidencia:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incidencia {id_incidencia} no encontrada.",
            )
        return self._enriquecer(incidencia)

    def actualizar_incidencia(
        self,
        id_incidencia: int,
        datos: IncidenciaUpdate,
        db: Session,
    ) -> Incidencia:
        """
        Actualiza parcialmente una incidencia (solo los campos enviados). Si se
        cambia el trabajador, valida que exista.
        """
        incidencia = self.obtener_incidencia(id_incidencia, db)

        cambios = datos.model_dump(exclude_unset=True)

        if "id_trabajador" in cambios and cambios["id_trabajador"] is not None:
            trabajador = db.query(Trabajador).filter(
                Trabajador.id_trabajador == cambios["id_trabajador"]
            ).first()
            if not trabajador:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Trabajador {cambios['id_trabajador']} no encontrado.",
                )

        for campo, valor in cambios.items():
            setattr(incidencia, campo, valor)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al actualizar incidencia: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar la incidencia: {exc.orig}",
            )
        db.refresh(incidencia)
        return self._enriquecer(incidencia)

    # ── Derivación de empresa (para la encapsulación por empresa) ──────────────
    def empresa_de_trabajador(self, id_trabajador: int, db: Session) -> int | None:
        """Empresa de un trabajador (vía su área), o None si no existe."""
        fila = (
            db.query(AreaTrabajo.id_empresa)
            .join(Trabajador, Trabajador.id_area == AreaTrabajo.id_area)
            .filter(Trabajador.id_trabajador == id_trabajador)
            .first()
        )
        return fila[0] if fila else None

    def empresa_de_incidencia(self, id_incidencia: int, db: Session) -> int | None:
        """
        Empresa de una incidencia (vía Incidencia -> Trabajador -> AreaTrabajo),
        o None si la incidencia no existe.
        """
        fila = (
            db.query(AreaTrabajo.id_empresa)
            .join(Trabajador, Trabajador.id_area == AreaTrabajo.id_area)
            .join(Incidencia, Incidencia.id_trabajador == Trabajador.id_trabajador)
            .filter(Incidencia.id_incidencia == id_incidencia)
            .first()
        )
        return fila[0] if fila else None

    def ruta_archivo_foto(self, id_incidencia: int, db: Session) -> str | None:
        """
        Resuelve la ruta ABSOLUTA en disco de la foto de una incidencia, mapeando
        `ruta_foto` (URL web, ej. '/media/incidencias/escaneo_5.jpg') a la carpeta
        de media. Devuelve None si la incidencia no tiene foto o el archivo no existe.
        Lanza 404 si la incidencia no existe.
        """
        incidencia = self.obtener_incidencia(id_incidencia, db)
        if not incidencia.ruta_foto:
            return None

        rel = incidencia.ruta_foto
        if rel.startswith(settings.MEDIA_URL):
            rel = rel[len(settings.MEDIA_URL):]
        rel = rel.lstrip("/\\")

        base = os.path.normpath(settings.media_base_dir)
        ruta = os.path.normpath(os.path.join(base, rel))
        # Defensa anti path-traversal: la ruta debe quedar dentro de la carpeta media.
        if not ruta.startswith(base):
            logger.warning("Ruta de foto fuera de media (posible traversal): %s", incidencia.ruta_foto)
            return None
        return ruta if os.path.isfile(ruta) else None


incidencia_service = IncidenciaService()
