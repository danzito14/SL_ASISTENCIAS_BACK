# media/main.py — microservicio de almacenamiento y servido de fotos protegidas.
#
# API INTERNA (no se expone públicamente; solo la llama el backend tras hacer
# auth+empresa). Protegida con un token interno compartido. media NO tiene BD ni
# conoce a qué incidencia/intento pertenece una foto: solo guarda y sirve bytes.
import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse

from src.core.config import settings
from src.almacen import guardar, ruta_archivo

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def exigir_token_interno(x_internal_token: str | None = Header(None)) -> None:
    """Fail-closed: si no hay token configurado, o no coincide, se rechaza."""
    if not settings.MEDIA_INTERNAL_TOKEN or x_internal_token != settings.MEDIA_INTERNAL_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token interno inválido o ausente.",
        )


app = FastAPI(title=settings.APP_TITLE, version=settings.APP_VERSION, debug=settings.DEBUG)


@app.put(
    "/archivos/{subcarpeta}/{nombre}",
    dependencies=[Depends(exigir_token_interno)],
    summary="Guardar archivo (interno)",
    description="Guarda el cuerpo (bytes) en <subcarpeta>/<nombre>. Lo llama el backend.",
)
async def subir(subcarpeta: str, nombre: str, request: Request):
    contenido = await request.body()
    if not contenido:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cuerpo vacío.")
    ruta = guardar(subcarpeta, nombre, contenido)
    if ruta is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="subcarpeta/nombre inválidos o no se pudo guardar.",
        )
    return {"ruta": ruta}


@app.get(
    "/archivos/{subcarpeta}/{nombre}",
    dependencies=[Depends(exigir_token_interno)],
    summary="Servir archivo (interno)",
    description="Devuelve el archivo como JPEG. 404 si no existe. Lo llama el backend.",
    responses={200: {"content": {"image/jpeg": {}}}, 404: {"description": "No encontrado."}},
)
def descargar(subcarpeta: str, nombre: str):
    ruta = ruta_archivo(subcarpeta, nombre)
    if ruta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Archivo no encontrado.")
    return FileResponse(ruta, media_type="image/jpeg")


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "service": "media", "version": settings.APP_VERSION}
