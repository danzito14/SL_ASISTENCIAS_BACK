# app/services/incidencia_service.py
"""
Servicio CRUD de incidencias.

Algunas incidencias las crea la BD automáticamente (triggers/funciones de
cierre de día); estos endpoints permiten registrarlas y gestionarlas a mano
desde el panel (revisar, justificar, corregir).
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.models.Incidencia_Model import Incidencia
from src.models.IntentoAcceso_Model import IntentoAcceso
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador
from src.models.Asistencia_HistorialAuditoria_Model import Asistencia
from src.models.Escaneo_Model import Escaneo
from src.models.Empresa_Model import Empresa
from src.schemas.Incidencia_Schema import IncidenciaCreate, IncidenciaUpdate
from src.services.Media_Service import media_service
from src.services.Asistencia_Service import asistencia_service

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
        i.id_emp = trab.id_emp if trab else None
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
            id_empresa=trabajador.id_empresa,   # denormalizado (multi-tenant)
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

        # Empresa: filtro directo por id_empresa denormalizado (sin joins).
        if id_empresa is not None:
            query = query.filter(Incidencia.id_empresa == id_empresa)
        # Nombre: requiere unir Trabajador para buscar por nombre/apellido.
        if nombre is not None:
            query = query.join(
                Trabajador, Trabajador.id_trabajador == Incidencia.id_trabajador
            ).filter(
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
                q = q.filter(Incidencia.id_empresa == id_empresa)
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
                    "id_emp": trab.id_emp if trab else None,
                    "trabajador_nombre": f"{trab.nombre} {trab.apellido}" if trab else None,
                    "id_puerta": None,
                    "id_empresa": None,
                    "similitud": None,
                    "tiene_foto": bool(i.ruta_foto),
                    "foto_url": f"/incidencias/{i.id_incidencia}/foto" if i.ruta_foto else None,
                    # Escaneo origen → el front pide GET /escaneos/{id} para el detalle.
                    "id_escaneo_ref": i.id_escaneo_ref,
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
                    "id_emp": trab.id_emp if trab else None,
                    "trabajador_nombre": f"{trab.nombre} {trab.apellido}" if trab else None,
                    "id_puerta": t.id_puerta,
                    "id_empresa": t.id_empresa,
                    "similitud": sim,
                    "tiene_foto": bool(t.ruta_foto),
                    "foto_url": f"/intentos/{t.id_intento}/foto" if t.ruta_foto else None,
                    # Un intento es un acceso FALLIDO: no genera escaneo → sin referencia.
                    "id_escaneo_ref": None,
                })

        # Merge: ordenar por fecha/hora desc y paginar sobre el conjunto combinado.
        _min = datetime(1970, 1, 1, tzinfo=timezone.utc)
        eventos.sort(key=lambda e: e["fecha_hora"] or _min, reverse=True)
        return eventos[skip: skip + limit]

    def retardos_calculados(
        self,
        db: Session,
        id_empresa: int | None = None,
        fecha_inicio: date | None = None,
        fecha_fin: date | None = None,
        id_trabajador: int | None = None,
        tolerancia_min: int = 0,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """
        Retardos CALCULADOS al vuelo (no son incidencias guardadas). Por cada
        trabajador y día toma su PRIMERA entrada y, si su hora local supera la
        hora_entrada del área (más la tolerancia), la reporta con los minutos de
        retraso. UNA fila por trabajador/día. Sin rango, usa los últimos 7 días.
        """
        fecha_inicio, fecha_fin = resolver_rango_fechas(fecha_inicio, fecha_fin)

        q = (
            db.query(Asistencia, Trabajador, AreaTrabajo, Empresa)
            .join(Trabajador, Trabajador.id_trabajador == Asistencia.id_trabajador)
            .join(AreaTrabajo, AreaTrabajo.id_area == Trabajador.id_area)
            .join(Empresa, Empresa.id_empresa == Asistencia.id_empresa)
            .filter(Asistencia.tipo_registro == "entrada")
            .filter(AreaTrabajo.hora_entrada.isnot(None))
            .filter(Asistencia.fecha_hora >= fecha_inicio)
            .filter(Asistencia.fecha_hora < datetime.combine(fecha_fin + timedelta(days=1), time.min))
        )
        if id_empresa is not None:
            q = q.filter(Asistencia.id_empresa == id_empresa)
        if id_trabajador is not None:
            q = q.filter(Asistencia.id_trabajador == id_trabajador)

        # ASC: la primera fila por (trabajador, día local) es su entrada más temprana.
        vistos: set = set()
        filas: list[dict] = []
        for a, t, ar, e in q.order_by(Asistencia.fecha_hora.asc()).all():
            try:
                tz = ZoneInfo(e.zona_horaria) if e.zona_horaria else timezone.utc
            except Exception:
                tz = timezone.utc
            dt = a.fecha_hora if a.fecha_hora.tzinfo else a.fecha_hora.replace(tzinfo=timezone.utc)
            local = dt.astimezone(tz)
            clave = (t.id_trabajador, local.date())
            if clave in vistos:
                continue
            vistos.add(clave)
            esperada = ar.hora_entrada
            retraso = (local.hour * 60 + local.minute) - (esperada.hour * 60 + esperada.minute)
            if retraso <= tolerancia_min:
                continue
            filas.append({
                "id_trabajador": t.id_trabajador,
                "id_emp": t.id_emp,
                "trabajador_nombre": f"{t.nombre} {t.apellido}",
                "id_area": ar.id_area,
                "area_nombre": ar.nombre_area,
                "id_empresa": e.id_empresa,
                "fecha": local.date(),
                "hora_esperada": esperada.strftime("%H:%M"),
                "hora_real": local.strftime("%H:%M"),
                "minutos_retardo": retraso,
            })

        # Más recientes / mayor retraso primero; paginar tras el cálculo.
        filas.sort(key=lambda r: (r["fecha"], r["minutos_retardo"]), reverse=True)
        return filas[skip: skip + limit]

    def obtener_incidencia(self, id_incidencia: UUID, db: Session) -> Incidencia:
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
        id_incidencia: UUID,
        datos: IncidenciaUpdate,
        db: Session,
    ) -> Incidencia:
        """
        Actualiza parcialmente una incidencia (solo los campos enviados). Si se
        cambia el trabajador, valida que exista.
        """
        incidencia = self.obtener_incidencia(id_incidencia, db)
        estado_anterior = incidencia.estado

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
            # Al pasar a 'justificada' (solo en la transición) algunas incidencias
            # generan una asistencia manual, en la MISMA transacción que la
            # justificación (o ninguna si algo falla).
            if incidencia.estado == "justificada" and estado_anterior != "justificada":
                self._al_justificar(incidencia, db)
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

    # ── Efectos al justificar una incidencia ───────────────────────────────────
    def _al_justificar(self, incidencia: Incidencia, db: Session) -> None:
        """
        Despacha la creación de asistencia manual según el tipo de incidencia:
          · area_incorrecta     → asistencia manual copiando el escaneo rechazado.
          · entrada_sin_registro → SALIDA manual al fin del día (hay entrada, falta salida).
          · acceso_otra_empresa → NO aquí: la asistencia la crea justificar el INTENTO
                                   'otra_empresa' (par del mismo evento, con puerta).
          · fuera_de_area y demás → no se crea nada.
        """
        tipo = incidencia.tipo_incidencia
        if tipo == "area_incorrecta":
            self._crear_asistencia_area_incorrecta(incidencia, db)
        elif tipo == "entrada_sin_registro":
            self._crear_salida_entrada_sin_registro(incidencia, db)

    def _escaneo_de_incidencia(self, incidencia: Incidencia, db: Session) -> Escaneo:
        """Escaneo que originó la incidencia, o 400 si no hay (no se puede crear asistencia)."""
        if incidencia.id_escaneo_ref is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede justificar con asistencia: la incidencia no tiene escaneo asociado.",
            )
        escaneo = db.query(Escaneo).filter(Escaneo.id_escaneo == incidencia.id_escaneo_ref).first()
        if escaneo is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede justificar con asistencia: el escaneo asociado ya no existe.",
            )
        return escaneo

    def _fin_de_dia_utc(self, id_empresa: int | None, fecha: date, db: Session) -> datetime:
        """23:59:59 de `fecha` en la zona horaria de la empresa (tz-aware)."""
        zona = None
        if id_empresa is not None:
            fila = db.query(Empresa.zona_horaria).filter(Empresa.id_empresa == id_empresa).first()
            zona = fila[0] if fila else None
        try:
            tz = ZoneInfo(zona) if zona else timezone.utc
        except Exception:
            tz = timezone.utc
        return datetime.combine(fecha, time(23, 59, 59), tzinfo=tz)

    def _crear_asistencia_area_incorrecta(self, incidencia: Incidencia, db: Session) -> None:
        escaneo = self._escaneo_de_incidencia(incidencia, db)
        if asistencia_service.existe_asistencia_dia(
            db, escaneo.id_trabajador, escaneo.tipo_registro, escaneo.fecha_hora
        ):
            logger.info("Incidencia area_incorrecta %s: ya hay asistencia ese día; no se duplica.",
                        incidencia.id_incidencia)
            return
        asistencia_service.crear_asistencia_manual(
            db,
            id_trabajador=escaneo.id_trabajador,
            id_puerta=escaneo.id_puerta,
            id_empresa=escaneo.id_empresa,
            tipo_registro=escaneo.tipo_registro,
            fecha_hora=escaneo.fecha_hora,
            observaciones=f"Asistencia manual al justificar incidencia area_incorrecta {incidencia.id_incidencia}.",
            ubicacion=escaneo.ubicacion,
            id_dispositivo=escaneo.id_dispositivo,
            confianza_biometrica=escaneo.confianza_biometrica,
            dentro_de_area=escaneo.dentro_de_area,
        )

    def _crear_salida_entrada_sin_registro(self, incidencia: Incidencia, db: Session) -> None:
        escaneo = self._escaneo_de_incidencia(incidencia, db)
        fecha_hora_salida = self._fin_de_dia_utc(incidencia.id_empresa, incidencia.fecha, db)
        if asistencia_service.existe_asistencia_dia(
            db, escaneo.id_trabajador, "salida", fecha_hora_salida
        ):
            logger.info("Incidencia entrada_sin_registro %s: ya hay salida ese día; no se duplica.",
                        incidencia.id_incidencia)
            return
        asistencia_service.crear_asistencia_manual(
            db,
            id_trabajador=escaneo.id_trabajador,
            id_puerta=escaneo.id_puerta,
            id_empresa=escaneo.id_empresa,
            tipo_registro="salida",
            fecha_hora=fecha_hora_salida,
            observaciones=(f"Salida manual al justificar incidencia entrada_sin_registro "
                           f"{incidencia.id_incidencia} (fin del día)."),
            ubicacion=escaneo.ubicacion,
            id_dispositivo=escaneo.id_dispositivo,
        )

    # ── Derivación de empresa (para la encapsulación por empresa) ──────────────
    def empresa_de_trabajador(self, id_trabajador: int, db: Session) -> int | None:
        """Empresa de un trabajador (id_empresa denormalizado), o None si no existe."""
        fila = (
            db.query(Trabajador.id_empresa)
            .filter(Trabajador.id_trabajador == id_trabajador)
            .first()
        )
        return fila[0] if fila else None

    def empresa_de_incidencia(self, id_incidencia: UUID, db: Session) -> int | None:
        """Empresa de una incidencia (id_empresa denormalizado), o None si no existe."""
        fila = (
            db.query(Incidencia.id_empresa)
            .filter(Incidencia.id_incidencia == id_incidencia)
            .first()
        )
        return fila[0] if fila else None

    def foto_bytes(self, id_incidencia: UUID, db: Session) -> bytes | None:
        """
        Bytes JPEG de la foto de la incidencia, recuperados del servicio media. None
        si no tiene foto o media no la encuentra. Lanza 404 si la incidencia no existe.
        """
        incidencia = self.obtener_incidencia(id_incidencia, db)
        return media_service.obtener_bytes(incidencia.ruta_foto)


incidencia_service = IncidenciaService()
