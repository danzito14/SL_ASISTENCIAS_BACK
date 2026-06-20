# app/api/v1/endpoints/trabajadores.py
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from src.core.auth import exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.models.AreaTrabajo_Trabajador_Model import Trabajador
from src.models.Rol_Usuario_Model import Usuario
from src.models.Embedding_Model import Embedding, VECTOR_DIM
from src.schemas.AreaTrabajo_Trabajador import (
    TrabajadorCreate,
    TrabajadorRegistroResponse,
    TrabajadorResponse,
    TrabajadorUpdate,
)
from src.services.Trabajador_Service import trabajador_service
from src.services.Recognition_Service import recognition_service
from src.services.Embedding_Service import embedding_service
from src.services.Tenancy_Service import tenancy_service

router = APIRouter(prefix="/trabajadores", tags=["Trabajadores"])


# ── 1. Registrar trabajador (solo datos, sin embedding) ───────────────────────
@router.post(
    "",
    response_model=TrabajadorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar trabajador",
    description="Crea un trabajador con sus datos básicos. El embedding facial se registra por separado.",
)
def registrar_trabajador(
    datos: TrabajadorCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Encapsulación: solo puedes crear trabajadores en un área de TU empresa.
    exigir_empresa(usuario, tenancy_service.empresa_de_area(datos.id_area, db))
    return trabajador_service.registrar_trabajador(datos=datos, db=db)


# ── Listar trabajadores ───────────────────────────────────────────────────────
@router.get(
    "",
    response_model=list[TrabajadorResponse],
    summary="Listar trabajadores",
    description="Devuelve todos los trabajadores registrados (con paginación).",
)
def listar_trabajadores(
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    id_area: int | None = Query(None, description="Filtrar por área (opcional, dentro de la empresa)."),
    nombre: str | None = Query(None, description="Buscar por nombre (parcial, insensible a mayúsculas)."),
    db: Session = Depends(get_db),
):
    return trabajador_service.listar_trabajadores(
        db=db, skip=skip, limit=limit, id_empresa=id_empresa, id_area=id_area, nombre=nombre
    )


# ── Obtener trabajador por id ─────────────────────────────────────────────────
@router.get(
    "/{id_trabajador}",
    response_model=TrabajadorResponse,
    summary="Obtener trabajador",
    description="Devuelve un trabajador por su id.",
)
def obtener_trabajador(
    id_trabajador: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, trabajador_service.empresa_de_trabajador(id_trabajador, db))
    return trabajador_service.obtener_trabajador(id_trabajador=id_trabajador, db=db)


# ── Actualizar trabajador ─────────────────────────────────────────────────────
@router.put(
    "/{id_trabajador}",
    response_model=TrabajadorResponse,
    summary="Actualizar trabajador",
    description="Actualiza los campos enviados de un trabajador (nombre, apellido, área, estado).",
)
def actualizar_trabajador(
    id_trabajador: int,
    datos: TrabajadorUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # El trabajador debe ser de tu empresa...
    exigir_empresa(usuario, trabajador_service.empresa_de_trabajador(id_trabajador, db))
    # ...y si lo cambias de área, la nueva área también debe ser de tu empresa.
    if datos.id_area is not None:
        exigir_empresa(usuario, tenancy_service.empresa_de_area(datos.id_area, db))
    return trabajador_service.actualizar_trabajador(id_trabajador=id_trabajador, datos=datos, db=db)


# ── Eliminar trabajador (baja lógica) ─────────────────────────────────────────
@router.delete(
    "/{id_trabajador}",
    response_model=TrabajadorResponse,
    summary="Desactivar trabajador",
    description="Baja lógica: marca el trabajador como 'inactivo' (no borra la fila ni su historial).",
)
def eliminar_trabajador(
    id_trabajador: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, trabajador_service.empresa_de_trabajador(id_trabajador, db))
    return trabajador_service.eliminar_trabajador(id_trabajador=id_trabajador, db=db)


# ── 2. Capturar embedding facial desde cámara ─────────────────────────────────
@router.post(
    "/{id_trabajador}/embedding",
    response_model=TrabajadorRegistroResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Capturar embedding facial",
    description=(
        "Abre la cámara de la laptop, detecta el rostro del trabajador y guarda su embedding. "
        "Presiona ESPACIO para capturar o ESC para cancelar."
    ),
)
def capturar_embedding(
    id_trabajador: int,
    camara_id: int = 0,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # 0. Encapsulación: el trabajador debe ser de tu empresa.
    exigir_empresa(usuario, trabajador_service.empresa_de_trabajador(id_trabajador, db))

    # 1. Validar que el trabajador exista
    trabajador = db.query(Trabajador).filter(
        Trabajador.id_trabajador == id_trabajador,
        Trabajador.estado == "activo",
    ).first()

    if not trabajador:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trabajador {id_trabajador} no encontrado o inactivo.",
        )

    # 2. Validar que no tenga embedding previo
    embedding_existente = db.query(Embedding).filter(
        Embedding.id_trabajador == id_trabajador
    ).first()

    if embedding_existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El trabajador {id_trabajador} ya tiene un embedding registrado. "
                   "Usa el endpoint de actualización si deseas reemplazarlo.",
        )

    # 3. Abrir cámara y capturar frame
    frame = recognition_service.capturar_desde_camara(camara_id=camara_id)
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se capturó ningún frame. Cámara no disponible o captura cancelada.",
        )

    # 4. Detectar rostro y extraer embedding
    cara = recognition_service.detectar_y_extraer(frame)
    if cara is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se detectó ningún rostro en el frame capturado. Intenta de nuevo.",
        )

    if not cara["es_real"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Spoofing detectado (score: {cara['spoof_score']:.2f}). Usa tu cara real.",
        )

    # 4.a Anti-spoofing dedicado: rechaza foto/pantalla/papel (422)
    recognition_service.asegurar_no_spoof(frame, cara)

    # 4.b Evitar que este rostro ya esté registrado en OTRO trabajador de la empresa (409)
    id_empresa = embedding_service.empresa_de_trabajador(id_trabajador, db)
    embedding_service.asegurar_no_duplicado(cara["embedding"], db, id_empresa=id_empresa)

    # 5. Guardar embedding
    embedding = Embedding(
        id_trabajador=id_trabajador,
        vector_embedding=cara["embedding"],
        tipo_embedding="facial",
        calidad_embedding=round(cara["det_score"], 2),
        modelo_ia="insightface-buffalo_l",
        estado="activo",
    )
    db.add(embedding)
    db.commit()
    db.refresh(embedding)

    return TrabajadorRegistroResponse(
        trabajador=trabajador,
        embedding_id=embedding.id_embedding,
        modelo_ia=embedding.modelo_ia,
        dimensiones=VECTOR_DIM,
        calidad=float(embedding.calidad_embedding),
        mensaje=f"Embedding de {trabajador.nombre} {trabajador.apellido} registrado correctamente.",
    )


# ── 3. Registrar embedding facial desde una foto subida ───────────────────────
@router.post(
    "/{id_trabajador}/embedding/foto",
    response_model=TrabajadorRegistroResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar embedding facial desde una foto",
    description=(
        "Recibe una imagen (JPEG/PNG) del rostro del trabajador, detecta la cara y "
        "guarda su embedding. Pensado para que el cliente envíe la foto (no usa la "
        "cámara del servidor; funciona en entornos sin cámara como Docker)."
    ),
)
async def registrar_embedding_foto(
    id_trabajador: int,
    foto: UploadFile = File(..., description="Imagen del rostro (JPEG/PNG)"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # 0. Encapsulación: el trabajador debe ser de tu empresa.
    exigir_empresa(usuario, trabajador_service.empresa_de_trabajador(id_trabajador, db))

    # 1. Validar que el trabajador exista
    trabajador = db.query(Trabajador).filter(
        Trabajador.id_trabajador == id_trabajador,
        Trabajador.estado == "activo",
    ).first()

    if not trabajador:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trabajador {id_trabajador} no encontrado o inactivo.",
        )

    # 2. Validar que no tenga embedding previo
    embedding_existente = db.query(Embedding).filter(
        Embedding.id_trabajador == id_trabajador
    ).first()

    if embedding_existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El trabajador {id_trabajador} ya tiene un embedding registrado. "
                   "Usa el endpoint de actualización si deseas reemplazarlo.",
        )

    # 3. Validar que sea una imagen y decodificarla
    if not (foto.content_type or "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El archivo debe ser una imagen. Recibido: {foto.content_type}.",
        )

    contenido = await foto.read()
    frame = recognition_service.leer_imagen(contenido)
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo leer la imagen. Formato inválido o archivo corrupto.",
        )

    # 4. Detectar rostro y extraer embedding
    cara = recognition_service.detectar_y_extraer(frame)
    if cara is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se detectó ningún rostro en la imagen. Envía una foto frontal y nítida.",
        )

    if not cara["es_real"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Spoofing detectado (score: {cara['spoof_score']:.2f}).",
        )

    # 4.a Anti-spoofing dedicado: rechaza foto/pantalla/papel (422)
    recognition_service.asegurar_no_spoof(frame, cara)

    # 4.b Evitar que este rostro ya esté registrado en OTRO trabajador de la empresa (409)
    id_empresa = embedding_service.empresa_de_trabajador(id_trabajador, db)
    embedding_service.asegurar_no_duplicado(cara["embedding"], db, id_empresa=id_empresa)

    # 5. Guardar embedding
    embedding = Embedding(
        id_trabajador=id_trabajador,
        vector_embedding=cara["embedding"],
        tipo_embedding="facial",
        calidad_embedding=round(cara["det_score"], 2),
        modelo_ia="insightface-buffalo_l",
        estado="activo",
    )
    db.add(embedding)
    db.commit()
    db.refresh(embedding)

    return TrabajadorRegistroResponse(
        trabajador=trabajador,
        embedding_id=embedding.id_embedding,
        modelo_ia=embedding.modelo_ia,
        dimensiones=VECTOR_DIM,
        calidad=float(embedding.calidad_embedding),
        mensaje=f"Embedding de {trabajador.nombre} {trabajador.apellido} registrado desde foto.",
    )
