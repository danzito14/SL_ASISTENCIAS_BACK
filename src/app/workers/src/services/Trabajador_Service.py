# app/services/trabajador_service.py
"""
Servicio para registrar trabajadores (solo datos).

Flujo:
  1. Valida que el área exista y esté activa
  2. Crea el trabajador SIN embedding
  3. Retorna el trabajador creado

El embedding facial se registra por separado mediante el endpoint
POST /trabajadores/{id_trabajador}/embedding.
"""

import logging
import re
import unicodedata

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.models.AreaTrabajo_Trabajador_Model import Trabajador
from src.models.Embedding_Model import Embedding
from src.schemas.AreaTrabajo_Trabajador import TrabajadorCreate, TrabajadorUpdate
from src.services.Tenancy_Service import tenancy_service

logger = logging.getLogger(__name__)

# ── Limpieza de duplicados por nombre ─────────────────────────────────────────
# Sufijos romanos que marcan a un duplicado en la nómina ("JUAN PEREZ", "JUAN
# PEREZ II"...). Se ignoran al comparar nombres. (Solo I..V, según el dato real.)
_ROMANOS = {"I", "II", "III", "IV", "V"}

# Prioridad de qué fila CONSERVAR cuando el mismo nombre está en varios orígenes:
# la nómina comercial (agricola_com) manda sobre la agrícola; lo manual/otro, al final.
_ORIGEN_PRIORIDAD = {"agricola_com": 0, "agricola": 1}


def _tokens_nombre(nombre: str | None, apellido: str | None) -> list[str]:
    """Nombre+apellido → tokens EN MAYÚSCULAS, sin acentos ni signos (para comparar)."""
    completo = f"{nombre or ''} {apellido or ''}"
    completo = unicodedata.normalize("NFKD", completo)
    completo = "".join(c for c in completo if not unicodedata.combining(c))
    return re.findall(r"[A-Z]+", completo.upper())


def _tiene_sufijo_romano(nombre: str | None, apellido: str | None) -> bool:
    """True si el nombre termina en un numeral romano I..V (marca de duplicado)."""
    tokens = _tokens_nombre(nombre, apellido)
    return bool(tokens) and tokens[-1] in _ROMANOS


def _clave_nombre(nombre: str | None, apellido: str | None) -> str:
    """Clave de agrupación: nombre normalizado SIN el sufijo romano final.
    'Juan Pérez' y 'JUAN PEREZ III' comparten clave 'JUAN PEREZ'."""
    tokens = _tokens_nombre(nombre, apellido)
    while tokens and tokens[-1] in _ROMANOS:
        tokens.pop()
    return " ".join(tokens)


class TrabajadorService:

    def registrar_trabajador(
        self,
        datos: TrabajadorCreate,
        db: Session,
    ) -> Trabajador:
        """
        Registra un trabajador con sus datos básicos (sin embedding).

        Args:
            datos: Datos del trabajador (nombre, apellido, id_area, estado)
            db:    Sesión de BD

        Returns:
            El trabajador creado.
        """
        # 1. Validar que el área exista y esté activa (tenancy)
        area = tenancy_service.obtener_area_activa(datos.id_area, db)
        if not area:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Área {datos.id_area} no encontrada o inactiva.",
            )

        # 2. Crear trabajador (solo datos). id_empresa se deriva del área
        #    (denormalizado, multi-tenant); permiso_escaneo y nivel_acceso_interno
        #    definen dónde puede fichar y a qué zonas internas accede.
        trabajador = Trabajador(
            nombre=datos.nombre,
            apellido=datos.apellido,
            id_area=datos.id_area,
            id_empresa=area.id_empresa,
            permiso_escaneo=datos.permiso_escaneo,
            # Regla: los de campo NO tienen acceso a zonas internas → nivel NULL,
            # ignorando lo que mande el cliente. Los demás conservan su nivel.
            nivel_acceso_interno=(None if datos.permiso_escaneo == "campo"
                                  else datos.nivel_acceso_interno),
            estado=datos.estado,
        )
        db.add(trabajador)
        db.commit()
        db.refresh(trabajador)

        return trabajador

    def listar_trabajadores(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        id_empresa: int | None = None,
        id_area: int | None = None,
        nombre: str | None = None,
        id_emp: str | None = None,
        con_rostro: bool | None = None,
    ) -> list[Trabajador]:
        """
        Devuelve los trabajadores registrados, ordenados por id. Todos los filtros
        se COMPONEN (se aplican juntos).

        Args:
            db:         Sesión de BD
            skip:       Cuántos registros saltar (paginación)
            limit:      Máximo de registros a devolver
            id_empresa: Si se indica, solo trabajadores de esa empresa (vía su área).
            id_area:    Si se indica, solo trabajadores de esa área.
            nombre:     Búsqueda parcial por nombre/apellido (insensible a mayúsculas).
            id_emp:     Búsqueda parcial por número de empleado (SYS21).
            con_rostro: True = solo con embedding facial; False = solo SIN embedding;
                        None = todos.

        Returns:
            Lista de trabajadores.
        """
        query = db.query(Trabajador)
        if id_area is not None:
            query = query.filter(Trabajador.id_area == id_area)
        if id_empresa is not None:
            query = query.filter(Trabajador.id_empresa == id_empresa)
        if nombre is not None:
            query = query.filter(
                or_(
                    Trabajador.nombre.ilike(f"%{nombre}%"),
                    Trabajador.apellido.ilike(f"%{nombre}%"),
                )
            )
        if id_emp is not None:
            query = query.filter(Trabajador.id_emp.ilike(f"%{id_emp}%"))
        if con_rostro is not None:
            # Correlacionado: ¿tiene (o no) embedding facial?
            existe = (
                db.query(Embedding.id_embedding)
                .filter(Embedding.id_trabajador == Trabajador.id_trabajador)
                .exists()
            )
            query = query.filter(existe if con_rostro else ~existe)

        trabajadores = (
            query
            .order_by(Trabajador.id_trabajador)
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Marcar qué trabajadores tienen embedding facial (una sola consulta, sin N+1)
        ids = [t.id_trabajador for t in trabajadores]
        ids_con_embedding = {
            id_trab
            for (id_trab,) in db.query(Embedding.id_trabajador)
            .filter(Embedding.id_trabajador.in_(ids))
            .distinct()
            .all()
        } if ids else set()

        for t in trabajadores:
            t.tiene_embedding = t.id_trabajador in ids_con_embedding

        return trabajadores

    def buscar_por_id_emp(
        self,
        db: Session,
        id_emp: str,
        skip: int = 0,
        limit: int = 100,
        id_empresa: int | None = None,
    ) -> list[Trabajador]:
        """
        Busca trabajadores por su número de empleado externo (id_emp, nómina SYS21)
        con coincidencia PARCIAL (ILIKE) y paginación.

        id_emp NO es único por sí solo (solo lo es junto con origen_nomina) y puede
        ser NULL en trabajadores creados a mano; por eso esto devuelve una LISTA, no
        un único registro. Los trabajadores sin id_emp nunca coinciden.

        Args:
            db:         Sesión de BD
            id_emp:     Texto a buscar dentro del número de empleado (parcial).
            skip:       Cuántos registros saltar (paginación)
            limit:      Máximo de registros a devolver
            id_empresa: Si se indica, solo trabajadores de esa empresa.
        Returns:
            Lista de trabajadores cuyo id_emp contiene el texto buscado.
        """
        query = db.query(Trabajador).filter(Trabajador.id_emp.ilike(f"%{id_emp}%"))
        if id_empresa is not None:
            query = query.filter(Trabajador.id_empresa == id_empresa)

        trabajadores = (
            query
            .order_by(Trabajador.id_trabajador)
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Marcar qué trabajadores tienen embedding facial (una sola consulta, sin N+1)
        ids = [t.id_trabajador for t in trabajadores]
        ids_con_embedding = {
            id_trab
            for (id_trab,) in db.query(Embedding.id_trabajador)
            .filter(Embedding.id_trabajador.in_(ids))
            .distinct()
            .all()
        } if ids else set()

        for t in trabajadores:
            t.tiene_embedding = t.id_trabajador in ids_con_embedding

        return trabajadores

    def obtener_trabajador(self, id_trabajador: int, db: Session) -> Trabajador:
        """
        Devuelve un trabajador por su id o lanza 404 si no existe.

        Args:
            id_trabajador: Id del trabajador
            db:            Sesión de BD

        Returns:
            El trabajador encontrado.
        """
        trabajador = db.query(Trabajador).filter(
            Trabajador.id_trabajador == id_trabajador
        ).first()
        if not trabajador:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Trabajador {id_trabajador} no encontrado.",
            )

        trabajador.tiene_embedding = (
            db.query(Embedding.id_embedding)
            .filter(Embedding.id_trabajador == id_trabajador)
            .first()
            is not None
        )
        return trabajador

    def actualizar_trabajador(
        self,
        id_trabajador: int,
        datos: TrabajadorUpdate,
        db: Session,
    ) -> Trabajador:
        """
        Actualiza parcialmente un trabajador (solo los campos enviados). Si se
        cambia el área, valida que exista y esté activa.
        """
        trabajador = self.obtener_trabajador(id_trabajador, db)

        cambios = datos.model_dump(exclude_unset=True)

        # id_emp (no. de nómina SYS21) es único por (id_emp, origen_nomina). Si lo
        # cambian a uno ya tomado por otro trabajador del mismo origen, avisar claro
        # en vez de dejar reventar el UNIQUE de la BD.
        if cambios.get("id_emp"):
            origen = trabajador.origen_nomina
            ocupado = (
                db.query(Trabajador.id_trabajador)
                .filter(
                    Trabajador.id_emp == cambios["id_emp"],
                    Trabajador.origen_nomina == origen,
                    Trabajador.id_trabajador != id_trabajador,
                )
                .first()
            )
            if ocupado:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Ya existe otro trabajador con el número de empleado "
                        f"'{cambios['id_emp']}' en el origen '{origen or 'manual'}'."
                    ),
                )

        if "id_area" in cambios and cambios["id_area"] is not None:
            area = tenancy_service.obtener_area_activa(cambios["id_area"], db)
            if not area:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Área {cambios['id_area']} no encontrada o inactiva.",
                )
            # El id_empresa denormalizado sigue al área del trabajador.
            cambios["id_empresa"] = area.id_empresa

        # Regla: si el trabajador queda como 'campo', su nivel de acceso interno
        # debe ser NULL (no entra a zonas internas), ignore lo que mande el cliente.
        permiso_efectivo = cambios.get("permiso_escaneo", trabajador.permiso_escaneo)
        if permiso_efectivo == "campo":
            cambios["nivel_acceso_interno"] = None

        for campo, valor in cambios.items():
            setattr(trabajador, campo, valor)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al actualizar trabajador: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar el trabajador: {exc.orig}",
            )
        db.refresh(trabajador)
        return trabajador

    # ── Limpieza de duplicados por nombre ──────────────────────────────────────
    def _orden_canonico(self, t: Trabajador, con_embedding: set[int]) -> tuple:
        """Clave de orden: el MENOR es el que se CONSERVA dentro de un grupo de
        homónimos. Prioridad: 1) origen comercial (agricola_com) sobre agrícola,
        2) nombre SIN numeral romano, 3) con rostro registrado, 4) con id_emp de
        SYS21, 5) el más antiguo (menor id)."""
        return (
            _ORIGEN_PRIORIDAD.get(t.origen_nomina, 2),
            1 if _tiene_sufijo_romano(t.nombre, t.apellido) else 0,
            0 if t.id_trabajador in con_embedding else 1,
            0 if t.id_emp else 1,
            t.id_trabajador,
        )

    @staticmethod
    def _brief_dup(t: Trabajador, con_embedding: set[int]) -> dict:
        return {
            "id_trabajador": t.id_trabajador,
            "id_emp": t.id_emp,
            "origen_nomina": t.origen_nomina,
            "nombre": t.nombre,
            "apellido": t.apellido,
            "id_empresa": t.id_empresa,
            "tiene_embedding": t.id_trabajador in con_embedding,
        }

    def limpiar_duplicados(self, db: Session, simular: bool = True) -> dict:
        """
        Detecta trabajadores ACTIVOS con el mismo nombre (ignorando acentos y el
        sufijo romano I..V) y, por grupo, conserva uno y BORRA TOTALMENTE el resto.

        Agrupa CRUZANDO orígenes/empresas: si 'Juan Pérez' está en la comercial y en
        la agrícola, conserva la comercial (ver _orden_canonico). El borrado es físico;
        embeddings caen por CASCADE, pero si un duplicado tiene asistencias/escaneos/
        incidencias (FK RESTRICT) no se puede borrar: se salta y se reporta, sin
        abortar el resto (cada borrado va en su propio savepoint).

        Args:
            simular: si True (default) NO borra nada; solo devuelve el plan.

        Returns:
            dict con el resumen y el detalle por grupo (ver LimpiezaDuplicadosResponse).
        """
        activos = db.query(Trabajador).filter(Trabajador.estado == "activo").all()
        ids = [t.id_trabajador for t in activos]
        con_embedding = {
            id_trab
            for (id_trab,) in db.query(Embedding.id_trabajador)
            .filter(Embedding.id_trabajador.in_(ids))
            .distinct()
            .all()
        } if ids else set()

        # Agrupar por nombre normalizado (sin numeral romano). Ignora sin nombre.
        grupos: dict[str, list[Trabajador]] = {}
        for t in activos:
            clave = _clave_nombre(t.nombre, t.apellido)
            if clave:
                grupos.setdefault(clave, []).append(t)

        detalle: list[dict] = []
        eliminados = 0
        no_eliminados: list[dict] = []

        for clave, grupo in grupos.items():
            if len(grupo) < 2:
                continue
            grupo.sort(key=lambda t: self._orden_canonico(t, con_embedding))
            conservado, duplicados = grupo[0], grupo[1:]

            for d in duplicados:
                if not simular:
                    try:
                        with db.begin_nested():
                            db.delete(d)
                            db.flush()
                        eliminados += 1
                    except IntegrityError:
                        no_eliminados.append({
                            "id_trabajador": d.id_trabajador,
                            "nombre": d.nombre,
                            "apellido": d.apellido,
                            "motivo": "tiene registros dependientes (asistencias/"
                                      "escaneos/incidencias); dalo de baja en su lugar.",
                        })

            detalle.append({
                "nombre_clave": clave,
                "conservado": self._brief_dup(conservado, con_embedding),
                "eliminados": [self._brief_dup(d, con_embedding) for d in duplicados],
            })

        if not simular:
            db.commit()

        return {
            "simulado": simular,
            "grupos_con_duplicados": len(detalle),
            "duplicados_detectados": sum(len(g["eliminados"]) for g in detalle),
            "eliminados": eliminados,
            "no_eliminados": no_eliminados,
            "detalle": detalle,
        }

    def eliminar_trabajador(self, id_trabajador: int, db: Session) -> Trabajador:
        """
        Baja lógica (soft delete): marca el trabajador como 'inactivo'. No borra
        la fila para conservar sus asistencias y embedding.
        """
        trabajador = self.obtener_trabajador(id_trabajador, db)
        trabajador.estado = "inactivo"
        db.commit()
        db.refresh(trabajador)
        return trabajador

    # ── Derivación de empresa (para la encapsulación por empresa) ──────────────
    def empresa_de_trabajador(self, id_trabajador: int, db: Session) -> int | None:
        """Empresa de un trabajador (id_empresa denormalizado), o None si no existe."""
        fila = (
            db.query(Trabajador.id_empresa)
            .filter(Trabajador.id_trabajador == id_trabajador)
            .first()
        )
        return fila[0] if fila else None


trabajador_service = TrabajadorService()
