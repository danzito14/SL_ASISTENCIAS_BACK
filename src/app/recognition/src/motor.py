# recognition/motor.py
"""
Motor de reconocimiento facial (InsightFace + liveness + anti-spoof + match pgvector).

Sin estado de negocio: detecta, extrae embeddings, valida liveness/anti-spoof y
busca el match en la BD (SOLO LECTURA de embeddings/trabajadores como svc_recognition).
NO registra escaneos ni conoce la lógica de acceso — eso es del backend.
"""
import logging
import re
import threading
import unicodedata

import cv2
import numpy as np
from insightface.app import FaceAnalysis
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.config import settings
from src.antispoof import antispoof_service

logger = logging.getLogger(__name__)

SIMILITUD_UMBRAL = 0.5
# Umbral MÁS PERMISIVO cuando la búsqueda ya está acotada por nombre a pocos
# candidatos: al no haber con quién confundirse, se pueden atrapar matches borderline
# (típico entre la cámara del terminal y la foto de SYS21, fuentes distintas). Tuneable.
SIMILITUD_UMBRAL_ACOTADO = 0.40
SPOOFING_UMBRAL = 0.5
LIVENESS_MIN_FRAMES_CON_ROSTRO = 2
LIVENESS_MISMA_PERSONA_UMBRAL = 0.45
LIVENESS_MOVIMIENTO_MIN = 0.004
# Margen alrededor de la cara al recortar (fracción del tamaño del box, por lado).
# >0 deja cabeza/hombros/aire para que la foto del intento o incidencia se pueda
# reutilizar (p. ej. enrolar a un 'desconocido' desde esa misma foto).
RECORTE_MARGEN = 0.5

# Palabras a IGNORAR del nombre que manda un terminal externo (roles/áreas/ruido,
# no identidad). El nombre sirve solo como PISTA para acotar el universo de match.
_ROLES_NOMBRE = {
    "logistica", "logis", "slp", "compras", "nominas", "conta", "contabilidad",
    "sistemas", "sis", "rh", "rrhh", "admin", "administracion", "planta", "oficina",
    "de", "del", "la", "las", "los", "y", "el",
}


def _tokens_nombre(nombre: str | None) -> list[str]:
    """Normaliza el nombre (sin acentos, minúsculas, solo letras), quita roles y
    palabras cortas. Devuelve los tokens 'reales' para acotar la búsqueda por nombre."""
    if not nombre:
        return []
    s = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode("ascii").lower()
    return [t for t in re.findall(r"[a-z]+", s) if len(t) >= 3 and t not in _ROLES_NOMBRE]


class Motor:

    def __init__(self):
        # buffalo_l trae 5 sub-modelos y, sin acotar, los corre TODOS en cada cara:
        # det_10g (detección), w600k_r50 (embedding), 2d106det (landmarks 2D),
        # 1k3d68 (landmarks 3D → pose) y genderage. El camino caliente (/reconocer,
        # /identificar, liveness) solo necesita detección + embedding → app LIGERA.
        # 2d106det y genderage no se usan en ningún lado; la pose (1k3d68) solo la
        # consume /extraer (calidad de enrolamiento), que usa la app CON POSE,
        # cargada aparte y perezosamente para no pesar en el camino caliente.
        self._app: FaceAnalysis | None = None
        self._app_pose: FaceAnalysis | None = None
        self._lock = threading.Lock()

    def _construir_app(self, modulos: list[str]) -> FaceAnalysis:
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"],
                           allowed_modules=modulos)
        app.prepare(ctx_id=0, det_size=(640, 640))
        return app

    def _get_app(self) -> FaceAnalysis:
        if self._app is None:
            with self._lock:
                if self._app is None:
                    logger.info("Cargando InsightFace buffalo_l (detección+embedding)...")
                    self._app = self._construir_app(["detection", "recognition"])
                    logger.info("Modelo InsightFace (ligero) listo.")
        return self._app

    def _get_app_pose(self) -> FaceAnalysis:
        if self._app_pose is None:
            with self._lock:
                if self._app_pose is None:
                    logger.info("Cargando InsightFace buffalo_l (+pose, solo enrolamiento)...")
                    self._app_pose = self._construir_app(["detection", "recognition", "landmark_3d_68"])
                    logger.info("Modelo InsightFace (con pose) listo.")
        return self._app_pose

    def precargar(self) -> None:
        self._get_app()

    def leer_imagen(self, contenido: bytes) -> np.ndarray | None:
        if not contenido:
            return None
        arr = np.frombuffer(contenido, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def detectar_y_extraer(self, frame: np.ndarray, con_pose: bool = False) -> dict | None:
        # con_pose=True (solo /extraer) usa la app con landmark_3d_68 para poblar
        # `pose`; en el camino caliente la app ligera no la calcula (pose → None).
        app = self._get_app_pose() if con_pose else self._get_app()
        faces = app.get(frame)
        if not faces:
            return None
        cara = max(faces, key=lambda f: f.det_score)
        embedding = cara.normed_embedding.tolist()
        spoof_score = None
        es_real = True
        raw_spoof = getattr(cara, "spoofing_score", None)
        if raw_spoof is not None:
            spoof_score = float(raw_spoof)
            es_real = spoof_score > SPOOFING_UMBRAL
        kps = cara.kps.tolist() if getattr(cara, "kps", None) is not None else None
        bbox = cara.bbox.astype(int).tolist()

        # Señales de CALIDAD para validar fotos de enrolamiento (las usa /extraer):
        #   num_caras  → cuántas caras se detectaron (para exigir UNA sola)
        #   face_ratio → área de la cara / área de la imagen (cara no muy lejana)
        #   pose       → [pitch, yaw, roll] en grados (frontalidad), o None
        #   blur       → varianza del Laplaciano (mayor = más nítida)
        h, w = frame.shape[:2]
        fx1, fy1, fx2, fy2 = bbox
        face_area = max(0, fx2 - fx1) * max(0, fy2 - fy1)
        face_ratio = float(face_area) / float(max(w * h, 1))
        pose_attr = getattr(cara, "pose", None)
        pose = [float(p) for p in pose_attr.tolist()] if pose_attr is not None else None
        return {
            "embedding": embedding,
            "bbox": bbox,
            "kps": kps,
            "det_score": float(cara.det_score),
            "spoof_score": spoof_score,
            "es_real": es_real,
            "num_caras": len(faces),
            "frame_w": int(w),
            "frame_h": int(h),
            "face_ratio": face_ratio,
            "pose": pose,
            "blur": self._nitidez(frame, bbox),
        }

    def _nitidez(self, frame: np.ndarray, bbox) -> float:
        """Varianza del Laplaciano sobre el recorte de la cara (mayor = más nítida)."""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = (int(v) for v in bbox)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            crop = frame
        gris = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gris, cv2.CV_64F).var())

    def _match_pgvector(self, embedding: list[float], db: Session, id_empresa, id_area,
                        tokens: list[str], umbral: float = SIMILITUD_UMBRAL) -> dict | None:
        """Una consulta pgvector (coseno) acotada por empresa/área y, si hay `tokens` de
        nombre, SOLO entre quienes matcheen TODOS (palabra completa, sin acentos)."""
        vector_str = "[" + ",".join(str(x) for x in embedding) + "]"
        params: dict = {"vector": vector_str, "id_empresa": id_empresa, "id_area": id_area}
        cond_nombre = ""
        if tokens:
            partes = []
            for i, tok in enumerate(tokens):
                partes.append(
                    f"unaccent(lower(t.nombre || ' ' || t.apellido)) ~ ('\\y' || :tok{i} || '\\y')"
                )
                params[f"tok{i}"] = tok
            cond_nombre = " AND " + " AND ".join(partes)
        row = db.execute(
            text(f"""
                SELECT t.id_trabajador, t.nombre, t.apellido, t.id_empresa,
                       1 - (e.vector_embedding <=> CAST(:vector AS vector)) AS similitud
                FROM embeddings e
                JOIN trabajadores t ON t.id_trabajador = e.id_trabajador
                WHERE e.estado = 'activo' AND t.estado = 'activo'
                  AND (:id_empresa IS NULL OR t.id_empresa = :id_empresa)
                  AND (:id_area    IS NULL OR t.id_area    = :id_area){cond_nombre}
                ORDER BY e.vector_embedding <=> CAST(:vector AS vector)
                LIMIT 1
            """),
            params,
        ).fetchone()
        if row is None or float(row.similitud) < umbral:
            return None
        return {
            "id_trabajador": row.id_trabajador,
            "nombre": row.nombre,
            "apellido": row.apellido,
            "id_empresa": row.id_empresa,
            "similitud": float(row.similitud),
        }

    def buscar_en_bd(self, embedding: list[float], db: Session,
                     id_empresa: int | None = None, id_area: int | None = None,
                     nombre_hint: str | None = None) -> dict | None:
        """Match coseno con pgvector, acotado por empresa/área. Si viene `nombre_hint`
        (p. ej. el nombre que reconoció un terminal externo), primero busca SOLO entre
        quienes matcheen ese nombre — reduce el universo y baja falsos positivos. Si ahí
        no hay match (nombre ambiguo/erróneo/no enrolado), CAE a la búsqueda completa."""
        tokens = _tokens_nombre(nombre_hint)
        if tokens:
            # Acotado por nombre → umbral más permisivo (pocos candidatos, sin confusión).
            m = self._match_pgvector(embedding, db, id_empresa, id_area, tokens,
                                     SIMILITUD_UMBRAL_ACOTADO)
            if m is not None:
                return m
        # Búsqueda completa (sin hint o fallback) → umbral estándar.
        return self._match_pgvector(embedding, db, id_empresa, id_area, None)

    def mejor_candidato_global(self, embedding: list[float], db: Session) -> dict | None:
        """Rostro más parecido en TODA la BD, sin umbral (para clasificar no-match)."""
        vector_str = "[" + ",".join(str(x) for x in embedding) + "]"
        row = db.execute(
            text("""
                SELECT t.id_trabajador, t.id_empresa,
                       1 - (e.vector_embedding <=> CAST(:vector AS vector)) AS similitud
                FROM embeddings e
                JOIN trabajadores t ON t.id_trabajador = e.id_trabajador
                WHERE e.estado = 'activo' AND t.estado = 'activo'
                ORDER BY e.vector_embedding <=> CAST(:vector AS vector)
                LIMIT 1
            """),
            {"vector": vector_str},
        ).fetchone()
        if row is None:
            return None
        return {"id_trabajador": row.id_trabajador, "id_empresa": row.id_empresa, "similitud": float(row.similitud)}

    def recorte_jpeg(self, frame: np.ndarray, cara: dict) -> bytes | None:
        """
        Recorte JPEG de la cara CON MARGEN alrededor (no pega al bounding box). Así la
        foto del intento/incidencia es reutilizable: para enrolar a un 'desconocido'
        desde esa misma foto, recognition necesita re-detectar la cara, y un recorte
        ajustado al milímetro (sin frente, mentón ni aire) lo dificulta.
        """
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = (int(v) for v in cara["bbox"])
        # Expandir el box RECORTE_MARGEN de su tamaño por cada lado (clamp al frame).
        dx = int((x2 - x1) * RECORTE_MARGEN)
        dy = int((y2 - y1) * RECORTE_MARGEN)
        x1, y1 = max(0, x1 - dx), max(0, y1 - dy)
        x2, y2 = min(w, x2 + dx), min(h, y2 + dy)
        recorte = frame[y1:y2, x1:x2]
        if recorte.size == 0:
            recorte = frame
        ok, buf = cv2.imencode(".jpg", recorte, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return buf.tobytes() if ok else None

    def evaluar_antispoof(self, frame: np.ndarray, cara: dict) -> dict | None:
        """{ es_real, score_real } o None si desactivado/no disponible (no bloquea)."""
        if not settings.ANTISPOOFING_ACTIVO:
            return None
        resultado = antispoof_service.evaluar(frame, cara["bbox"])
        if resultado is None:
            logger.warning("ANTISPOOFING_ACTIVO=True pero el modelo no está disponible; se omite el check.")
            return None
        return resultado

    def evaluar_liveness(self, caras: list[dict]) -> dict:
        embs = [np.array(c["embedding"], dtype=np.float32) for c in caras]
        sim_min = 1.0
        for i in range(len(embs)):
            for j in range(i + 1, len(embs)):
                sim_min = min(sim_min, float(np.dot(embs[i], embs[j])))
        if sim_min < LIVENESS_MISMA_PERSONA_UMBRAL:
            return {"vivo": False,
                    "motivo": f"Los frames parecen de personas distintas (similitud={sim_min:.2f}).",
                    "movimiento": 0.0, "similitud_min": sim_min}
        caras_con_kps = [c for c in caras if c.get("kps")]
        movimientos = []
        for a, b in zip(caras_con_kps, caras_con_kps[1:]):
            kps_a = np.array(a["kps"], dtype=np.float32)
            kps_b = np.array(b["kps"], dtype=np.float32)
            ancho = max(((a["bbox"][2] - a["bbox"][0]) + (b["bbox"][2] - b["bbox"][0])) / 2.0, 1.0)
            movimientos.append(float(np.linalg.norm(kps_a - kps_b, axis=1).mean()) / ancho)
        movimiento = max(movimientos) if movimientos else 0.0
        if movimiento < LIVENESS_MOVIMIENTO_MIN:
            return {"vivo": False,
                    "motivo": f"Sin movimiento entre frames (posible foto estática, mov={movimiento:.4f}).",
                    "movimiento": movimiento, "similitud_min": sim_min}
        return {"vivo": True, "motivo": "Liveness OK.", "movimiento": movimiento, "similitud_min": sim_min}


motor = Motor()
