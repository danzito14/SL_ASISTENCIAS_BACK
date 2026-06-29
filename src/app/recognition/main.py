# recognition/main.py — microservicio de reconocimiento facial (compute-heavy).
#
# API INTERNA (no se expone públicamente; la llama el backend con token compartido).
# Endpoints COARSE: cada uno hace el pipeline completo (detectar→anti-spoof→match→
# recorte) y devuelve el resultado + el recorte de cara en base64, para que el
# backend registre el escaneo/intento y guarde la foto SIN necesitar OpenCV.
import base64
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.pgdb import engine, get_db
from src.motor import motor, LIVENESS_MIN_FRAMES_CON_ROSTRO

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Limita la inferencia pesada concurrente (CPU). Las peticiones extra esperan turno.
_SEM = threading.Semaphore(3)


def exigir_token_interno(x_internal_token: str | None = Header(None)) -> None:
    if not settings.RECOGNITION_INTERNAL_TOKEN or x_internal_token != settings.RECOGNITION_INTERNAL_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token interno inválido o ausente.")


def _b64(data: bytes | None) -> str | None:
    return base64.b64encode(data).decode("ascii") if data else None


def _frame_de(foto: UploadFile):
    frame = motor.leer_imagen(foto.file.read())
    if frame is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Imagen inválida o ilegible.")
    return frame


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("recognition: conexión a la BD OK (%s como %s).", settings.DB_NAME, settings.DB_USER)
    except Exception as exc:
        logger.error("recognition: no se pudo conectar a la BD: %s", exc)
        raise RuntimeError("recognition: sin conexión a la base de datos.") from exc
    if settings.PRELOAD_FACE_MODEL:
        logger.info("recognition: precargando modelo facial...")
        motor.precargar()
    yield


app = FastAPI(title=settings.APP_TITLE, version=settings.APP_VERSION, debug=settings.DEBUG, lifespan=lifespan)


# ── 1. Reconocer (1 imagen): pipeline completo, sin registrar ─────────────────
@app.post("/reconocer", dependencies=[Depends(exigir_token_interno)], summary="Reconocer (1 imagen)")
def reconocer(foto: UploadFile = File(...), id_empresa: int | None = Form(None), db: Session = Depends(get_db)):
    frame = _frame_de(foto)
    with _SEM:
        cara = motor.detectar_y_extraer(frame)
        if cara is None:
            return {"estado": "no_rostro"}
        anti = motor.evaluar_antispoof(frame, cara)
        if anti is not None and not anti["es_real"]:
            return {"estado": "spoof", "score_real": anti["score_real"], "recorte_b64": _b64(motor.recorte_jpeg(frame, cara))}
        match = motor.buscar_en_bd(cara["embedding"], db, id_empresa=id_empresa)
        recorte = _b64(motor.recorte_jpeg(frame, cara))
        if match is None:
            return {"estado": "no_match", "det_score": cara["det_score"],
                    "candidato_global": motor.mejor_candidato_global(cara["embedding"], db),
                    "recorte_b64": recorte}
        return {"estado": "match", "trabajador": match, "det_score": cara["det_score"], "recorte_b64": recorte}


# ── 2. Reconocer con liveness (N imágenes) ────────────────────────────────────
@app.post("/reconocer-liveness", dependencies=[Depends(exigir_token_interno)], summary="Reconocer con liveness (N imágenes)")
def reconocer_liveness(fotos: list[UploadFile] = File(...), id_empresa: int | None = Form(None), db: Session = Depends(get_db)):
    frames = [f for f in (motor.leer_imagen(x.file.read()) for x in fotos) if f is not None]
    with _SEM:
        pares = [(f, motor.detectar_y_extraer(f)) for f in frames]
        pares = [(f, c) for f, c in pares if c is not None]
        caras = [c for _, c in pares]
        if len(caras) < LIVENESS_MIN_FRAMES_CON_ROSTRO:
            return {"estado": "pocos_rostros", "n": len(caras)}
        live = motor.evaluar_liveness(caras)
        if not live["vivo"]:
            return {"estado": "no_vivo", "motivo": live["motivo"]}
        mejor_frame, mejor = max(pares, key=lambda p: p[1]["det_score"])
        anti = motor.evaluar_antispoof(mejor_frame, mejor)
        if anti is not None and not anti["es_real"]:
            return {"estado": "spoof", "score_real": anti["score_real"], "recorte_b64": _b64(motor.recorte_jpeg(mejor_frame, mejor))}
        match = motor.buscar_en_bd(mejor["embedding"], db, id_empresa=id_empresa)
        recorte = _b64(motor.recorte_jpeg(mejor_frame, mejor))
        if match is None:
            return {"estado": "no_match", "det_score": mejor["det_score"],
                    "candidato_global": motor.mejor_candidato_global(mejor["embedding"], db),
                    "recorte_b64": recorte}
        return {"estado": "match", "trabajador": match, "det_score": mejor["det_score"],
                "movimiento": live["movimiento"], "recorte_b64": recorte}


# ── 3. Extraer embedding (enrolamiento) ───────────────────────────────────────
@app.post("/extraer", dependencies=[Depends(exigir_token_interno)], summary="Extraer embedding (enrolamiento)")
def extraer(foto: UploadFile = File(...)):
    frame = _frame_de(foto)
    with _SEM:
        cara = motor.detectar_y_extraer(frame)
        if cara is None:
            return {"estado": "no_rostro"}
        anti = motor.evaluar_antispoof(frame, cara)
        return {"estado": "ok", "embedding": cara["embedding"], "det_score": cara["det_score"],
                "es_real": cara["es_real"], "spoof_score": cara["spoof_score"], "antispoof": anti,
                # Señales de calidad para validación de enrolamiento:
                "num_caras": cara["num_caras"], "face_ratio": cara["face_ratio"],
                "pose": cara["pose"], "blur": cara["blur"]}


# ── 4. Identificar (1 imagen): solo match, sin registrar ──────────────────────
@app.post("/identificar", dependencies=[Depends(exigir_token_interno)], summary="Identificar (match, sin registrar)")
def identificar(foto: UploadFile = File(...), id_empresa: int | None = Form(None), db: Session = Depends(get_db)):
    frame = _frame_de(foto)
    with _SEM:
        cara = motor.detectar_y_extraer(frame)
        if cara is None:
            return {"reconocido": False, "estado": "no_rostro"}
        match = motor.buscar_en_bd(cara["embedding"], db, id_empresa=id_empresa)
        if match is None:
            return {"reconocido": False, "det_score": cara["det_score"]}
        return {"reconocido": True, "trabajador": match, "similitud": match["similitud"], "det_score": cara["det_score"]}


@app.get("/health", tags=["Health"])
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.warning("recognition healthcheck: BD no disponible: %s", exc)
        db_ok = False
    payload = {"status": "ok" if db_ok else "degraded", "service": "recognition",
               "version": settings.APP_VERSION, "database": "ok" if db_ok else "down"}
    if not db_ok:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload
