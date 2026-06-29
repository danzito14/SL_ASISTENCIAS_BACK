# employee_monitoring/services/bulk_service.py
"""
Operaciones en LOTE (bulk) con SQLAlchemy 2.0 + dialecto PostgreSQL, centralizadas
para el orquestador del sync:

  - upsert_trabajadores: una sola sentencia INSERT ... ON CONFLICT (id_emp,
    origen_nomina) DO UPDATE para nuevos y modificados, con RETURNING para mapear
    (id_emp, origen) → id_trabajador (incluidos los recién creados).
  - upsert_sync_estado: idem sobre sync_estado (clave natural (id_emp, origen)).
  - cargar_estado / resetear_visto / soft_delete_no_vistos: utilidades del ciclo.

No hace commit: el orquestador controla las transacciones (commit por lote).
"""
import logging
from collections.abc import Iterable, Iterator

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.models.AreaTrabajo_Trabajador_Model import Trabajador
from src.models.SyncEstado_Model import SyncEstado

logger = logging.getLogger(__name__)

# Columnas de trabajadores que el sync sobrescribe en un UPDATE (no id_emp/origen,
# que son la clave de conflicto; no timestamps, que los maneja la BD/trigger).
_COLS_UPDATE_TRABAJADOR = (
    "nombre", "apellido", "id_area", "id_empresa",
    "permiso_escaneo", "nivel_acceso_interno", "estado",
)


def _chunks(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


class BulkService:

    # ── Trabajadores ──────────────────────────────────────────────────────────
    def upsert_trabajadores(
        self,
        db: Session,
        filas: list[dict],
        batch_size: int = 500,
    ) -> dict[tuple[str, str], int]:
        """
        Upsert por (id_emp, origen_nomina). Devuelve {(id_emp, origen): id_trabajador}
        con TODAS las filas afectadas (nuevas y actualizadas), para la fase de foto.
        """
        mapeo: dict[tuple[str, str], int] = {}
        for lote in _chunks(filas, batch_size):
            if not lote:
                continue
            stmt = pg_insert(Trabajador).values(lote)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id_emp", "origen_nomina"],
                index_where=text("id_emp IS NOT NULL"),   # casa con el índice único PARCIAL
                set_={c: getattr(stmt.excluded, c) for c in _COLS_UPDATE_TRABAJADOR},
            ).returning(Trabajador.id_trabajador, Trabajador.id_emp, Trabajador.origen_nomina)
            for fila in db.execute(stmt):
                mapeo[(fila.id_emp, fila.origen_nomina)] = fila.id_trabajador
        return mapeo

    def soft_delete_no_vistos(self, db: Session, origen: str) -> int:
        """
        Baja lógica (estado='inactivo') de los trabajadores de un origen cuyo
        sync_estado quedó visto=False (desaparecieron de la nómina). No borra filas;
        el trigger de cascada inactiva su embedding. Devuelve cuántos cambiaron.
        """
        sub = select(SyncEstado.id_emp).where(
            SyncEstado.origen_nomina == origen,
            SyncEstado.visto_en_ultima_corrida.is_(False),
        )
        stmt = (
            update(Trabajador)
            .where(
                Trabajador.origen_nomina == origen,
                Trabajador.id_emp.in_(sub),
                Trabajador.estado != "inactivo",
            )
            .values(estado="inactivo")
        )
        return db.execute(stmt).rowcount or 0

    # ── sync_estado ───────────────────────────────────────────────────────────
    def resetear_visto(self, db: Session, origen: str) -> None:
        """Marca visto=False para todo el origen al inicio de la corrida."""
        db.execute(
            update(SyncEstado)
            .where(SyncEstado.origen_nomina == origen)
            .values(visto_en_ultima_corrida=False)
        )

    def cargar_estado(self, db: Session, origen: str) -> dict[tuple[str, str], dict]:
        """
        Estado previo del sync de un origen, como dicts PLANOS (no ORM, para que no
        expiren tras el commit). Indexado por (id_emp, origen).
        """
        filas = db.execute(
            select(
                SyncEstado.id_emp, SyncEstado.hash_datos, SyncEstado.hash_foto,
                SyncEstado.foto_mtime, SyncEstado.foto_size, SyncEstado.estado_foto,
            ).where(SyncEstado.origen_nomina == origen)
        ).all()
        return {
            (f.id_emp, origen): {
                "hash_datos": f.hash_datos, "hash_foto": f.hash_foto,
                "foto_mtime": f.foto_mtime, "foto_size": f.foto_size,
                "estado_foto": f.estado_foto,
            }
            for f in filas
        }

    def cargar_id_trabajadores(self, db: Session, origen: str) -> dict[tuple[str, str], int]:
        """Mapa (id_emp, origen) → id_trabajador para TODOS los empleados del origen."""
        filas = db.execute(
            select(Trabajador.id_emp, Trabajador.id_trabajador).where(
                Trabajador.origen_nomina == origen,
                Trabajador.id_emp.isnot(None),
            )
        ).all()
        return {(f.id_emp, origen): f.id_trabajador for f in filas}

    def cargar_registrados(self, db: Session, origen: str, limite: int | None = None) -> list:
        """
        Trabajadores ACTIVOS ya registrados de un origen, con (id_emp, id_empresa,
        id_trabajador). Para el endpoint dedicado de fotos (/sync/fotos).
        """
        q = (
            select(Trabajador.id_emp, Trabajador.id_empresa, Trabajador.id_trabajador)
            .where(
                Trabajador.origen_nomina == origen,
                Trabajador.id_emp.isnot(None),
                Trabajador.estado == "activo",
            )
            .order_by(Trabajador.id_trabajador)
        )
        if limite:
            q = q.limit(limite)
        return db.execute(q).all()

    def upsert_sync_estado(
        self,
        db: Session,
        registros: list[dict],
        columnas_update: Iterable[str],
        batch_size: int = 500,
    ) -> None:
        """
        Upsert genérico sobre sync_estado por (id_emp, origen_nomina). 'registros'
        son dicts uniformes; 'columnas_update' son las columnas a refrescar en
        conflicto (las demás se dejan como estaban).
        """
        cols = tuple(columnas_update)
        for lote in _chunks(registros, batch_size):
            if not lote:
                continue
            stmt = pg_insert(SyncEstado).values(lote)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id_emp", "origen_nomina"],
                set_={c: getattr(stmt.excluded, c) for c in cols},
            )
            db.execute(stmt)


bulk_service = BulkService()
