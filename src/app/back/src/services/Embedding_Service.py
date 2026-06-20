# app/services/embedding.py
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models.Embedding_Model import Embedding
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador
from src.schemas.Embedding_Schema import EmbeddingUpdate

logger = logging.getLogger(__name__)

# ── Umbral para considerar que una cara nueva YA está registrada en otro ──────
# trabajador (similitud coseno, 0.0-1.0). DEBE ser <= al umbral de match del
# scanner (SIMILITUD_UMBRAL = 0.5): si el scanner reconocería dos caras como la
# misma persona en el acceso, el registro también debe bloquearlas como duplicado.
# Súbelo si rechaza personas distintas; bájalo si deja pasar duplicados.
DUPLICADO_UMBRAL = 0.5


class EmbeddingService:
    """Administración de los embeddings ya registrados (CRUD de metadatos + borrado total)."""

    def listar(
        self,
        db: Session,
        id_empresa: int | None = None,
        skip: int = 0,
        limit: int = 100,
        estado: str | None = None,
        id_trabajador: int | None = None,
        id_area: int | None = None,
    ) -> list[Embedding]:
        """
        Lista embeddings con paginación y filtros. Acota por empresa (vía
        Trabajador → AreaTrabajo) salvo que id_empresa sea None (super-admin →
        todas las empresas). Sin 'id_area' trae todas las áreas de la empresa.
        """
        query = db.query(Embedding)
        if id_empresa is not None or id_area is not None:
            query = query.join(Trabajador, Trabajador.id_trabajador == Embedding.id_trabajador)
            if id_empresa is not None:
                query = (
                    query.join(AreaTrabajo, AreaTrabajo.id_area == Trabajador.id_area)
                    .filter(AreaTrabajo.id_empresa == id_empresa)
                )
            if id_area is not None:
                query = query.filter(Trabajador.id_area == id_area)
        if estado is not None:
            query = query.filter(Embedding.estado == estado)
        if id_trabajador is not None:
            query = query.filter(Embedding.id_trabajador == id_trabajador)
        return (
            query.order_by(Embedding.id_embedding)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def obtener(self, id_embedding: int, db: Session) -> Embedding:
        """Devuelve un embedding por su id o lanza 404 si no existe."""
        embedding = db.query(Embedding).filter(
            Embedding.id_embedding == id_embedding
        ).first()
        if not embedding:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Embedding {id_embedding} no encontrado.",
            )
        return embedding

    def obtener_por_trabajador(self, id_trabajador: int, db: Session) -> Embedding:
        """Devuelve el embedding de un trabajador (relación 1-a-1) o lanza 404."""
        embedding = db.query(Embedding).filter(
            Embedding.id_trabajador == id_trabajador
        ).first()
        if not embedding:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"El trabajador {id_trabajador} no tiene embedding registrado.",
            )
        return embedding

    def actualizar(self, id_embedding: int, datos: EmbeddingUpdate, db: Session) -> Embedding:
        """Actualiza parcialmente los metadatos de un embedding (no el vector)."""
        embedding = self.obtener(id_embedding, db)

        cambios = datos.model_dump(exclude_unset=True)
        for campo, valor in cambios.items():
            setattr(embedding, campo, valor)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al actualizar embedding: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar el embedding: {exc.orig}",
            )
        db.refresh(embedding)
        return embedding

    def empresa_de_trabajador(self, id_trabajador: int, db: Session) -> int | None:
        """Resuelve la empresa de un trabajador vía su área (Trabajador → AreaTrabajo)."""
        fila = (
            db.query(AreaTrabajo.id_empresa)
            .join(Trabajador, Trabajador.id_area == AreaTrabajo.id_area)
            .filter(Trabajador.id_trabajador == id_trabajador)
            .first()
        )
        return fila[0] if fila else None

    def empresa_de_embedding(self, id_embedding: int, db: Session) -> int | None:
        """Resuelve la empresa de un embedding (Embedding → Trabajador → AreaTrabajo)."""
        fila = (
            db.query(AreaTrabajo.id_empresa)
            .join(Trabajador, Trabajador.id_area == AreaTrabajo.id_area)
            .join(Embedding, Embedding.id_trabajador == Trabajador.id_trabajador)
            .filter(Embedding.id_embedding == id_embedding)
            .first()
        )
        return fila[0] if fila else None

    def buscar_duplicado(
        self,
        embedding: list[float],
        db: Session,
        excluir_id_trabajador: int | None = None,
        id_empresa: int | None = None,
    ) -> dict | None:
        """
        Busca la cara YA registrada más parecida a 'embedding' (similitud coseno con
        pgvector). Si supera DUPLICADO_UMBRAL la considera la misma persona.

        Args:
            excluir_id_trabajador: trabajador a ignorar (ej. al reemplazar su propia cara).
            id_empresa: si se indica, solo compara contra caras de esa empresa (una
                        misma persona puede estar legítimamente en empresas distintas).

        Returns:
            {"id_trabajador": int, "similitud": float} si hay un duplicado, o None.
        """
        vector_str = "[" + ",".join(str(x) for x in embedding) + "]"

        resultado = db.execute(
            text("""
                SELECT
                    e.id_trabajador,
                    1 - (e.vector_embedding <=> CAST(:vector AS vector)) AS similitud
                FROM embeddings e
                JOIN trabajadores t ON t.id_trabajador = e.id_trabajador
                JOIN area_trabajo a ON a.id_area = t.id_area
                WHERE e.estado = 'activo'
                  AND (:excluir IS NULL OR e.id_trabajador <> :excluir)
                  AND (:id_empresa IS NULL OR a.id_empresa = :id_empresa)
                ORDER BY e.vector_embedding <=> CAST(:vector AS vector)
                LIMIT 1
            """),
            {"vector": vector_str, "excluir": excluir_id_trabajador, "id_empresa": id_empresa},
        ).fetchone()

        if resultado is None:
            logger.debug("Anti-duplicado: no hay embeddings con que comparar.")
            return None

        similitud = float(resultado.similitud)
        logger.debug(
            "Anti-duplicado: cara más parecida = trabajador %s (similitud %.4f, umbral %.2f).",
            resultado.id_trabajador, similitud, DUPLICADO_UMBRAL,
        )
        if similitud < DUPLICADO_UMBRAL:
            return None

        return {"id_trabajador": resultado.id_trabajador, "similitud": similitud}

    def asegurar_no_duplicado(
        self,
        embedding: list[float],
        db: Session,
        excluir_id_trabajador: int | None = None,
        id_empresa: int | None = None,
    ) -> None:
        """Lanza 409 si la cara ya está registrada en otro trabajador. Si no, no hace nada."""
        dup = self.buscar_duplicado(embedding, db, excluir_id_trabajador, id_empresa)
        if dup is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Esta cara ya está registrada en el trabajador "
                    f"{dup['id_trabajador']} (similitud: {dup['similitud']:.2%}). "
                    "No se puede registrar el mismo rostro en dos trabajadores."
                ),
            )

    def reemplazar_vector_por_trabajador(self, id_trabajador: int, cara: dict, db: Session) -> Embedding:
        """
        Reemplaza el vector (y metadatos de captura) del embedding de un trabajador con
        los datos de un rostro recién detectado. Actualiza la misma fila; no crea otra.

        Args:
            cara: dict devuelto por facial_service.detectar_y_extraer(...).
        """
        embedding = self.obtener_por_trabajador(id_trabajador, db)
        return self._aplicar_cara(embedding, cara, db)

    def _aplicar_cara(self, embedding: Embedding, cara: dict, db: Session) -> Embedding:
        """Vuelca los datos de un rostro detectado sobre un embedding existente y guarda."""
        embedding.vector_embedding  = cara["embedding"]
        embedding.calidad_embedding = round(cara["det_score"], 2)
        embedding.modelo_ia         = "insightface-buffalo_l"
        embedding.tipo_embedding    = "facial"
        embedding.fecha_captura     = datetime.now(timezone.utc)
        embedding.estado            = "activo"

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al reemplazar embedding: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo reemplazar el embedding: {exc.orig}",
            )
        db.refresh(embedding)
        logger.info("Embedding %s (trabajador %s) recapturado desde foto.",
                    embedding.id_embedding, embedding.id_trabajador)
        return embedding

    def eliminar_total(self, id_embedding: int, db: Session) -> dict:
        """
        BORRADO TOTAL (hard delete): elimina la fila de la BD de forma definitiva.
        A diferencia del resto del sistema (baja lógica), aquí el embedding se borra
        físicamente para liberar el cupo 1-a-1 del trabajador y poder recapturar.
        """
        embedding = self.obtener(id_embedding, db)
        id_trabajador = embedding.id_trabajador

        db.delete(embedding)
        db.commit()
        logger.info("Embedding %s del trabajador %s eliminado totalmente.", id_embedding, id_trabajador)

        return {
            "eliminado": True,
            "id_embedding": id_embedding,
            "id_trabajador": id_trabajador,
            "mensaje": f"Embedding {id_embedding} eliminado por completo.",
        }

    def eliminar_total_por_trabajador(self, id_trabajador: int, db: Session) -> dict:
        """BORRADO TOTAL del embedding de un trabajador (útil para recapturar su rostro)."""
        embedding = self.obtener_por_trabajador(id_trabajador, db)
        id_embedding = embedding.id_embedding

        db.delete(embedding)
        db.commit()
        logger.info("Embedding %s del trabajador %s eliminado totalmente.", id_embedding, id_trabajador)

        return {
            "eliminado": True,
            "id_embedding": id_embedding,
            "id_trabajador": id_trabajador,
            "mensaje": f"Embedding del trabajador {id_trabajador} eliminado por completo.",
        }


embedding_service = EmbeddingService()
