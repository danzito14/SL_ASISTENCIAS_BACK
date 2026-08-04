# media/main.py — microservicio de almacenamiento y servido de fotos protegidas.
#
# API INTERNA (no se expone públicamente; solo la llama el backend tras hacer
# auth+empresa). Protegida con un token interno compartido. media NO tiene BD ni
# conoce a qué incidencia/intento pertenece una foto: solo guarda y sirve bytes.
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse

from src.core.config import settings
from src.almacen import guardar, purgar_antiguos, ruta_archivo

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


async def _bucle_purga() -> None:
    """Borra periódicamente las fotos que superan la retención. Vive aquí y no en un
    cron externo porque media es el único que toca el disco, y así la retención se
    cumple aunque nadie llame a la API."""
    intervalo = max(settings.MEDIA_PURGA_INTERVALO_HORAS, 0.5) * 3600
    while True:
        try:
            await asyncio.to_thread(
                purgar_antiguos, settings.MEDIA_RETENCION_DIAS, settings.purga_subcarpetas
            )
        except Exception as exc:  # nunca debe tumbar el servicio de fotos
            logger.error("Purga de fotos falló: %s", exc)
        await asyncio.sleep(intervalo)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tarea = None
    if settings.MEDIA_RETENCION_DIAS > 0:
        logger.info("Retención de fotos: %d días (subcarpetas: %s).",
                    settings.MEDIA_RETENCION_DIAS, ", ".join(settings.purga_subcarpetas))
        tarea = asyncio.create_task(_bucle_purga())
    else:
        logger.info("Retención de fotos DESACTIVADA (MEDIA_RETENCION_DIAS=0).")
    try:
        yield
    finally:
        if tarea:
            tarea.cancel()


app = FastAPI(title=settings.APP_TITLE, version=settings.APP_VERSION, debug=settings.DEBUG,
              lifespan=lifespan)


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


@app.post(
    "/mantenimiento/purgar",
    dependencies=[Depends(exigir_token_interno)],
    summary="Purgar fotos vencidas (interno)",
    description="Fuerza el barrido de retención sin esperar al ciclo diario. Útil para "
                "liberar disco o para verificar la configuración tras un cambio.",
)
def purgar(dias: int | None = None):
    return purgar_antiguos(
        settings.MEDIA_RETENCION_DIAS if dias is None else dias,
        settings.purga_subcarpetas,
    )


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "service": "media", "version": settings.APP_VERSION,
            "retencion_dias": settings.MEDIA_RETENCION_DIAS}
