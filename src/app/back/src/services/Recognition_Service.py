# app/services/recognition_service.py
"""
Servicio de RECONOCIMIENTO facial (motor, SIN estado de negocio).

Responsabilidades PURAS de visión/IA:
  - Cargar el modelo InsightFace (buffalo_l)
  - Detectar rostro + extraer embedding (ArcFace, 512 dims)
  - Liveness multi-frame (misma persona + movimiento)
  - Anti-spoofing (foto/pantalla/papel)
  - Buscar el embedding más cercano en la BD (pgvector)
  - Recortar el rostro a JPEG

NO registra escaneos/asistencia/incidencias ni devuelve tipos de la API
(ScanResponse). Eso es la ORQUESTACIÓN DE ACCESO (scanner_service). Esta
separación es la costura para extraer 'recognition' como microservicio
compute-heavy y escalable aparte (ver PLAN_MICROSERVICIOS §9).
"""
import logging
import threading

import cv2
import numpy as np
from insightface.app import FaceAnalysis
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi import HTTPException, status

from src.core.config import settings
from src.models.AreaTrabajo_Trabajador_Model import Trabajador
from src.services.antispoof_service import antispoof_service

logger = logging.getLogger(__name__)

# ── Umbral de similitud coseno para considerar un match (0.0 - 1.0) ──────────
SIMILITUD_UMBRAL = 0.5

# ── Umbral anti-spoofing del atributo de InsightFace (score > umbral = real) ──
SPOOFING_UMBRAL = 0.5

# ── Liveness multi-frame (modo permisivo) ────────────────────────────────────
# Mínimo de frames (de los enviados) en los que se debe detectar un rostro.
LIVENESS_MIN_FRAMES_CON_ROSTRO = 2
# Similitud coseno mínima entre los embeddings de los frames para aceptar que
# son la MISMA persona. Si baja de esto, se mezclaron rostros distintos.
LIVENESS_MISMA_PERSONA_UMBRAL = 0.45
# Movimiento mínimo de los landmarks entre frames (desplazamiento promedio
# normalizado por el ancho de la cara). Por debajo = foto estática.
LIVENESS_MOVIMIENTO_MIN = 0.004


class RecognitionService:

    def __init__(self):
        self._app: FaceAnalysis | None = None
        self._lock = threading.Lock()

    def _get_app(self) -> FaceAnalysis:
        """
        Inicializa el modelo InsightFace una sola vez (lazy loading).

        Usa doble verificación con lock: FastAPI corre los endpoints síncronos en
        un threadpool, así que dos requests concurrentes podrían cargar/descargar
        el modelo a la vez. El lock garantiza una sola carga.
        """
        if self._app is None:
            with self._lock:
                if self._app is None:  # Re-chequeo dentro del lock
                    logger.info("Cargando modelo InsightFace buffalo_l...")
                    app = FaceAnalysis(
                        name="buffalo_l",
                        providers=["CPUExecutionProvider"],  # Cambia a CUDAExecutionProvider si tienes GPU
                    )
                    app.prepare(ctx_id=0, det_size=(640, 640))
                    self._app = app  # Se asigna solo cuando ya está listo
                    logger.info("Modelo InsightFace listo.")
        return self._app

    def precargar(self) -> None:
        """Fuerza la carga del modelo (para llamarse al arrancar la app)."""
        self._get_app()

    # ── API pública ───────────────────────────────────────────────────────────

    def leer_imagen(self, contenido: bytes) -> np.ndarray | None:
        """
        Decodifica los bytes de una imagen (JPEG/PNG/etc.) a un frame BGR de OpenCV.
        Retorna None si los bytes están vacíos o no son una imagen válida.
        """
        if not contenido:
            return None
        arr = np.frombuffer(contenido, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return frame  # None si no se pudo decodificar

    def detectar_y_extraer(self, frame: np.ndarray) -> dict | None:
        """
        Recibe un frame BGR de OpenCV.
        Retorna el embedding y datos de la cara detectada, o None si no hay cara.

        Returns:
            {
                "embedding":   list[float],  # 512 dims
                "bbox":        list[int],    # [x1, y1, x2, y2]
                "det_score":   float,        # confianza de detección
                "spoof_score": float | None, # score anti-spoofing
                "es_real":     bool,
            }
        """
        app = self._get_app()
        faces = app.get(frame)

        if not faces:
            logger.debug("No se detectó ningún rostro en el frame.")
            return None

        # Tomar la cara con mayor score de detección
        cara = max(faces, key=lambda f: f.det_score)

        embedding = cara.normed_embedding.tolist()  # Ya normalizado L2 por InsightFace

        # Anti-spoofing — solo si el modelo lo soporta.
        # buffalo_l NO trae modelo anti-spoofing: el atributo existe pero es None,
        # así que hay que comprobar el valor, no solo que el atributo exista.
        spoof_score = None
        es_real = True
        raw_spoof = getattr(cara, "spoofing_score", None)
        if raw_spoof is not None:
            spoof_score = float(raw_spoof)
            es_real = spoof_score > SPOOFING_UMBRAL

        # Landmarks (5 puntos: ojos, nariz, comisuras) — para el liveness multi-frame.
        kps = cara.kps.tolist() if getattr(cara, "kps", None) is not None else None

        return {
            "embedding":   embedding,
            "bbox":        cara.bbox.astype(int).tolist(),
            "kps":         kps,
            "det_score":   float(cara.det_score),
            "spoof_score": spoof_score,
            "es_real":     es_real,
        }

    def buscar_en_bd(
        self,
        embedding: list[float],
        db: Session,
        id_empresa: int | None = None,
        id_area: int | None = None,
    ) -> dict | None:
        """
        Busca el embedding más cercano en la BD usando similitud coseno con pgvector.

        Args:
            id_empresa: si se indica, limita la búsqueda a trabajadores de esa empresa.
            id_area:    si se indica, limita la búsqueda a trabajadores de esa área.
            (El scanner los deriva de la puerta para no buscar fuera de su empresa.)

        Returns:
            { "trabajador": Trabajador, "similitud": float } o None si no hay match.
        """
        vector_str = "[" + ",".join(str(x) for x in embedding) + "]"

        resultado = db.execute(
            text("""
                SELECT
                    t.id_trabajador,
                    t.nombre,
                    t.apellido,
                    t.estado,
                    1 - (e.vector_embedding <=> CAST(:vector AS vector)) AS similitud
                FROM embeddings e
                JOIN trabajadores t ON t.id_trabajador = e.id_trabajador
                WHERE e.estado = 'activo'
                  AND t.estado  = 'activo'
                  AND (:id_empresa IS NULL OR t.id_empresa = :id_empresa)
                  AND (:id_area    IS NULL OR t.id_area    = :id_area)
                ORDER BY e.vector_embedding <=> CAST(:vector AS vector)
                LIMIT 1
            """),
            {"vector": vector_str, "id_empresa": id_empresa, "id_area": id_area},
        ).fetchone()

        if resultado is None:
            return None

        similitud = float(resultado.similitud)
        logger.debug(f"Mejor match: id={resultado.id_trabajador} similitud={similitud:.4f}")

        if similitud < SIMILITUD_UMBRAL:
            return None

        trabajador = db.query(Trabajador).get(resultado.id_trabajador)
        return {"trabajador": trabajador, "similitud": similitud}

    def mejor_candidato_global(self, embedding: list[float], db: Session) -> dict | None:
        """
        Busca el rostro más parecido en TODA la BD (sin filtrar por empresa) y SIN
        aplicar el umbral de match. Sirve para clasificar un acceso no reconocido
        en la empresa de la puerta.

        Returns:
            {"id_trabajador": int, "id_empresa": int, "similitud": float} o None.
        """
        vector_str = "[" + ",".join(str(x) for x in embedding) + "]"
        row = db.execute(
            text("""
                SELECT
                    t.id_trabajador,
                    t.id_empresa,
                    1 - (e.vector_embedding <=> CAST(:vector AS vector)) AS similitud
                FROM embeddings e
                JOIN trabajadores t ON t.id_trabajador = e.id_trabajador
                WHERE e.estado = 'activo'
                  AND t.estado  = 'activo'
                ORDER BY e.vector_embedding <=> CAST(:vector AS vector)
                LIMIT 1
            """),
            {"vector": vector_str},
        ).fetchone()
        if row is None:
            return None
        return {
            "id_trabajador": row.id_trabajador,
            "id_empresa": row.id_empresa,
            "similitud": float(row.similitud),
        }

    def recorte_jpeg(self, frame: np.ndarray, cara: dict) -> bytes | None:
        """Recorta el rostro (clamp a los límites del frame) y lo codifica a JPEG."""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = cara["bbox"]
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(w, int(x2)), min(h, int(y2))
        recorte = frame[y1:y2, x1:x2]
        if recorte.size == 0:
            recorte = frame  # fallback: frame completo si el bbox quedó vacío
        ok, buf = cv2.imencode(".jpg", recorte, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes() if ok else None

    # ── Anti-spoofing dedicado (MiniFASNet vía ONNX) ──────────────────────────
    def evaluar_antispoof(self, frame: np.ndarray, cara: dict) -> dict | None:
        """
        Corre el modelo anti-spoof dedicado (foto/pantalla/hoja) si está activo.
        Devuelve el resultado {"es_real": bool, "score_real": float} o None si el
        anti-spoofing está desactivado o no disponible (= no bloquea). Quien llama
        decide qué hacer con un ataque (rechazar acceso, 422 en enrolamiento, etc.).
        """
        if not settings.ANTISPOOFING_ACTIVO:
            return None

        resultado = antispoof_service.evaluar(frame, cara["bbox"])
        if resultado is None:
            logger.warning(
                "ANTISPOOFING_ACTIVO=True pero el modelo no está disponible; se omite el check."
            )
            return None
        return resultado

    def asegurar_no_spoof(self, frame: np.ndarray, cara: dict) -> None:
        """
        Anti-spoofing para el flujo de REGISTRO/enrolamiento: lanza 422 si la cara
        es un ataque de presentación (foto, pantalla, papel/dibujo). Si el
        anti-spoofing está desactivado o no disponible, no bloquea.
        """
        resultado = self.evaluar_antispoof(frame, cara)
        if resultado is not None and not resultado["es_real"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Anti-spoofing: posible foto, pantalla o papel "
                    f"(score real={resultado['score_real']:.2f}). Usa tu cara real."
                ),
            )

    # ── Liveness multi-frame (modo permisivo) ─────────────────────────────────
    def evaluar_liveness(self, caras: list[dict]) -> dict:
        """
        Liveness pasivo a partir de varios frames ya procesados con detectar_y_extraer.

        Valida dos cosas (modo permisivo):
          1. Misma persona: los embeddings de los frames son consistentes.
          2. Movimiento: los landmarks se desplazan entre frames (una foto
             estática repetida no se mueve → se rechaza).

        Returns:
            { "vivo": bool, "motivo": str, "movimiento": float, "similitud_min": float }
        """
        # 1. Misma persona — similitud coseno mínima entre embeddings (ya normalizados L2)
        embs = [np.array(c["embedding"], dtype=np.float32) for c in caras]
        sim_min = 1.0
        for i in range(len(embs)):
            for j in range(i + 1, len(embs)):
                sim_min = min(sim_min, float(np.dot(embs[i], embs[j])))

        if sim_min < LIVENESS_MISMA_PERSONA_UMBRAL:
            return {
                "vivo": False,
                "motivo": f"Los frames parecen de personas distintas (similitud={sim_min:.2f}).",
                "movimiento": 0.0,
                "similitud_min": sim_min,
            }

        # 2. Movimiento — desplazamiento promedio de landmarks entre frames
        #    consecutivos, normalizado por el ancho de la cara.
        caras_con_kps = [c for c in caras if c.get("kps")]
        movimientos = []
        for a, b in zip(caras_con_kps, caras_con_kps[1:]):
            kps_a = np.array(a["kps"], dtype=np.float32)
            kps_b = np.array(b["kps"], dtype=np.float32)
            ancho = max(((a["bbox"][2] - a["bbox"][0]) + (b["bbox"][2] - b["bbox"][0])) / 2.0, 1.0)
            movimientos.append(float(np.linalg.norm(kps_a - kps_b, axis=1).mean()) / ancho)

        movimiento = max(movimientos) if movimientos else 0.0
        if movimiento < LIVENESS_MOVIMIENTO_MIN:
            return {
                "vivo": False,
                "motivo": f"Sin movimiento entre frames (posible foto estática, mov={movimiento:.4f}).",
                "movimiento": movimiento,
                "similitud_min": sim_min,
            }

        return {"vivo": True, "motivo": "Liveness OK.", "movimiento": movimiento, "similitud_min": sim_min}

    def capturar_desde_camara(self, camara_id: int = 0) -> np.ndarray | None:
        """
        Abre la cámara, espera a detectar un rostro y retorna el frame.
        Uso temporal para pruebas desde el backend.
        """
        cap = cv2.VideoCapture(camara_id)
        if not cap.isOpened():
            logger.error(f"No se pudo abrir la cámara {camara_id}.")
            return None

        app = self._get_app()
        frame_capturado = None

        logger.info("Cámara abierta. Esperando rostro...")

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                faces = app.get(frame)

                # Dibujar bounding boxes en tiempo real
                for face in faces:
                    bbox = face.bbox.astype(int)
                    color = (0, 255, 0) if face.det_score > 0.7 else (0, 165, 255)
                    cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)
                    cv2.putText(
                        frame,
                        f"{face.det_score:.2f}",
                        (bbox[0], bbox[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        color,
                        2,
                    )

                cv2.imshow("FE Scanner — Presiona ESPACIO para capturar, ESC para salir", frame)

                key = cv2.waitKey(1) & 0xFF
                if key == 27:  # ESC — cancelar
                    break
                if key == 32 and faces:  # ESPACIO — capturar si hay cara
                    frame_capturado = frame.copy()
                    logger.info("Frame capturado.")
                    break

        finally:
            cap.release()
            cv2.destroyAllWindows()

        return frame_capturado


recognition_service = RecognitionService()
