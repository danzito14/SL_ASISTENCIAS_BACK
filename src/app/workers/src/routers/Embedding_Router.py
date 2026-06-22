# app/api/v1/endpoints/embeddings.py
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from src.core.auth import exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.core.auth import Principal as Usuario
from src.schemas.Embedding_Schema import (
    EmbeddingDeleteResponse,
    EmbeddingResponse,
    EmbeddingUpdate,
)
from src.services.Embedding_Service import embedding_service
from src.services.Recognition_Service import recognition_service

router = APIRouter(prefix="/embeddings", tags=["Embeddings"])


# ── Listar embeddings ─────────────────────────────────────────────────────────
@router.get(
    "",
    response_model=list[EmbeddingResponse],
    summary="Listar embeddings",
    description="Devuelve los embeddings registrados (metadatos, sin el vector). "
                "Permite filtrar por 'estado' y por 'id_trabajador'.",
)
def listar_embeddings(
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    estado: str | None = Query(None, description="Filtrar por estado: 'activo' | 'inactivo'."),
    id_trabajador: int | None = Query(None, description="Filtrar por trabajador."),
    id_area: int | None = Query(None, description="Filtrar por área (opcional, dentro de la empresa)."),
    db: Session = Depends(get_db),
):
    return embedding_service.listar(
        db=db, id_empresa=id_empresa, skip=skip, limit=limit,
        estado=estado, id_trabajador=id_trabajador, id_area=id_area,
    )


# ── Obtener embedding por id ──────────────────────────────────────────────────
@router.get(
    "/{id_embedding}",
    response_model=EmbeddingResponse,
    summary="Obtener embedding",
    description="Devuelve un embedding por su id (sin el vector).",
)
def obtener_embedding(
    id_embedding: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, embedding_service.empresa_de_embedding(id_embedding, db))
    return embedding_service.obtener(id_embedding=id_embedding, db=db)


# ── Obtener el embedding de un trabajador ─────────────────────────────────────
@router.get(
    "/trabajador/{id_trabajador}",
    response_model=EmbeddingResponse,
    summary="Obtener el embedding de un trabajador",
    description="Devuelve el embedding (relación 1-a-1) del trabajador indicado.",
)
def obtener_embedding_de_trabajador(
    id_trabajador: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, embedding_service.empresa_de_trabajador(id_trabajador, db))
    return embedding_service.obtener_por_trabajador(id_trabajador=id_trabajador, db=db)


# ── Actualizar metadatos del embedding ────────────────────────────────────────
@router.put(
    "/{id_embedding}",
    response_model=EmbeddingResponse,
    summary="Actualizar embedding",
    description="Actualiza los metadatos enviados (estado, calidad, modelo, tipo). "
                "No modifica el vector; para cambiar el rostro recaptura el embedding.",
)
def actualizar_embedding(
    id_embedding: int,
    datos: EmbeddingUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, embedding_service.empresa_de_embedding(id_embedding, db))
    return embedding_service.actualizar(id_embedding=id_embedding, datos=datos, db=db)


# ── Reemplazar el vector de un trabajador desde una foto ──────────────────────
@router.put(
    "/trabajador/{id_trabajador}/foto",
    response_model=EmbeddingResponse,
    summary="Reemplazar el embedding de un trabajador desde una foto",
    description=(
        "Recibe una nueva imagen (JPEG/PNG) del rostro, detecta la cara, extrae el "
        "embedding con InsightFace y ACTUALIZA la fila existente del trabajador (no "
        "crea otra). Misma lógica de reconocimiento que /trabajadores/{id}/embedding/foto."
    ),
)
async def reemplazar_embedding_foto(
    id_trabajador: int,
    foto: UploadFile = File(..., description="Imagen del rostro (JPEG/PNG)"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # 0. Encapsulación: el trabajador debe ser de tu empresa.
    exigir_empresa(usuario, embedding_service.empresa_de_trabajador(id_trabajador, db))

    # 1. Validar que el trabajador tenga embedding (404 si no) antes de procesar la imagen
    embedding_service.obtener_por_trabajador(id_trabajador=id_trabajador, db=db)

    # 2. Validar que sea una imagen y decodificarla
    if not (foto.content_type or "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El archivo debe ser una imagen. Recibido: {foto.content_type}.",
        )

    contenido = await foto.read()

    # 3. Extraer el embedding vía el microservicio recognition
    res = recognition_service.extraer(contenido)
    if res is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Servicio de reconocimiento no disponible.")
    if res.get("estado") == "no_rostro":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="No se detectó ningún rostro en la imagen. Envía una foto frontal y nítida.")
    if not res.get("es_real"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Spoofing detectado (score: {res.get('spoof_score') or 0:.2f}).")
    anti = res.get("antispoof")
    if anti is not None and not anti.get("es_real"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Anti-spoofing: posible foto, pantalla o papel (score real={anti.get('score_real', 0):.2f}).")

    # 4. Evitar que la nueva cara pertenezca a OTRO trabajador de la misma empresa (excluyéndose)
    id_empresa = embedding_service.empresa_de_trabajador(id_trabajador, db)
    embedding_service.asegurar_no_duplicado(
        res["embedding"], db, excluir_id_trabajador=id_trabajador, id_empresa=id_empresa
    )

    # 5. Actualizar la fila existente con el nuevo vector
    cara = {"embedding": res["embedding"], "det_score": res["det_score"]}
    return embedding_service.reemplazar_vector_por_trabajador(
        id_trabajador=id_trabajador, cara=cara, db=db
    )


# ── Eliminar embedding (BORRADO TOTAL) ────────────────────────────────────────
@router.delete(
    "/{id_embedding}",
    response_model=EmbeddingDeleteResponse,
    summary="Eliminar embedding (total)",
    description="BORRADO TOTAL (hard delete): elimina la fila de la BD de forma "
                "definitiva. No es reversible.",
)
def eliminar_embedding(
    id_embedding: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, embedding_service.empresa_de_embedding(id_embedding, db))
    return embedding_service.eliminar_total(id_embedding=id_embedding, db=db)


# ── Eliminar el embedding de un trabajador (BORRADO TOTAL) ─────────────────────
@router.delete(
    "/trabajador/{id_trabajador}",
    response_model=EmbeddingDeleteResponse,
    summary="Eliminar el embedding de un trabajador (total)",
    description="BORRADO TOTAL del embedding del trabajador. Útil para liberar el "
                "cupo 1-a-1 y poder recapturar su rostro. No es reversible.",
)
def eliminar_embedding_de_trabajador(
    id_trabajador: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, embedding_service.empresa_de_trabajador(id_trabajador, db))
    return embedding_service.eliminar_total_por_trabajador(id_trabajador=id_trabajador, db=db)
