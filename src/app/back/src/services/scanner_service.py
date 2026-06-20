# app/services/facial_service.py
"""
Servicio de reconocimiento facial usando InsightFace.

Responsabilidades:
  - Inicializar el modelo InsightFace (buffalo_l)
  - Detectar rostros en un frame
  - Validar anti-spoofing (cara real vs foto/pantalla)
  - Extraer embedding facial (ArcFace, 512 dims)
  - Comparar embedding contra BD usando pgvector
  - Registrar escaneo
"""

import os
import threading

import cv2
import numpy as np
import insightface
from insightface.app import FaceAnalysis
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.core.config import settings
from src.models.AreaTrabajo_Trabajador_Model import Trabajador
from src.models.Embedding_Model import Embedding
from src.models.Dispositivo_PuertaAcceso_Model import Dispositivo, PuertaAcceso
from src.models.Escaneo_Model import Escaneo
from src.models.Incidencia_Model import Incidencia
from src.models.IntentoAcceso_Model import IntentoAcceso
from src.schemas.Asistencia_HistorialAuditoria import ScanResponse
from src.schemas.AreaTrabajo_Trabajador import TrabajadorBrief
from src.schemas._geo import punto_desde_latlon
from src.services.antispoof_service import antispoof_service
from datetime import date, datetime, timezone
import logging

# Carpeta en disco donde se guardan las fotos de incidencias (ruta absoluta).
_MEDIA_BASE = settings.media_base_dir

logger = logging.getLogger(__name__)

# ── Umbral de similitud coseno para considerar un match (0.0 - 1.0) ──────────
SIMILITUD_UMBRAL = 0.5

# ── Piso de DETECCIÓN para registrar un intento "desconocido" ────────────────
# Un desconocido real se parece POCO a todos (similitud baja), así que el filtro
# NO puede ser la similitud. Se usa la confianza de DETECCIÓN del rostro: si la
# cara se detectó clara (score >= este piso) y no se reconoció, se registra como
# desconocido; si la detección es pobre (rostro borroso/parcial) se ignora.
UMBRAL_DET_DESCONOCIDO = 0.70

# ── Umbral anti-spoofing (score > umbral = cara real) ────────────────────────
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


class FacialService:

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

    def asegurar_no_spoof(self, frame: np.ndarray, cara: dict) -> None:
        """
        Anti-spoofing para el flujo de REGISTRO/enrolamiento: lanza 422 si la cara
        es un ataque de presentación (foto, pantalla, papel/dibujo). Si el
        anti-spoofing está desactivado o no disponible, no bloquea (igual que el
        scanner). Comparte el mismo modelo y umbral que el acceso.
        """
        if not settings.ANTISPOOFING_ACTIVO:
            return

        resultado = antispoof_service.evaluar(frame, cara["bbox"])
        if resultado is None:
            logger.warning(
                "ANTISPOOFING_ACTIVO=True pero el modelo no está disponible; se omite el check en registro."
            )
            return

        if not resultado["es_real"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Anti-spoofing: posible foto, pantalla o papel "
                    f"(score real={resultado['score_real']:.2f}). Usa tu cara real."
                ),
            )

    def _verificar_antispoof(self, frame: np.ndarray, cara: dict) -> ScanResponse | None:
        """
        Corre el modelo anti-spoof dedicado (foto/pantalla/hoja) si está activo.
        Retorna un ScanResponse de rechazo si detecta un ataque, o None si pasa
        (o si el anti-spoofing está desactivado / no disponible → no bloquea).
        """
        if not settings.ANTISPOOFING_ACTIVO:
            return None

        resultado = antispoof_service.evaluar(frame, cara["bbox"])
        if resultado is None:
            logger.warning(
                "ANTISPOOFING_ACTIVO=True pero el modelo no está disponible; se omite el check."
            )
            return None

        if not resultado["es_real"]:
            return ScanResponse(
                acceso=False,
                mensaje=f"Anti-spoofing: posible foto o pantalla "
                        f"(score real={resultado['score_real']:.2f}).",
                trabajador=None,
                id_escaneo=None,
                estado_registro="rechazado",
            )
        return None

    def _resolver_ubicacion(
        self,
        latitud: float | None,
        longitud: float | None,
        id_puerta: int,
        db: Session,
    ):
        """
        Determina la ubicación (geography POINT,4326) a guardar en el escaneo.

        - Si llegan latitud y longitud (GPS del dispositivo), construye ese punto.
        - Si no, hereda la ubicación de la puerta por la que se registra el acceso.
        - Si tampoco la puerta tiene ubicación, devuelve None.

        Nota: en WKT/PostGIS el orden de un punto es (longitud latitud) = (X Y).
        """
        punto = punto_desde_latlon(latitud, longitud)
        if punto is not None:
            return punto

        puerta = db.query(PuertaAcceso).get(id_puerta)
        return puerta.ubicacion if puerta else None

    def _empresa_de_puerta(self, id_puerta: int, db: Session) -> int | None:
        """
        Devuelve el id_empresa de la puerta para acotar la búsqueda facial a esa
        empresa. Si la puerta no tiene empresa asignada, retorna None (no acota →
        busca en todas, comportamiento anterior).
        """
        puerta = db.query(PuertaAcceso).get(id_puerta)
        return puerta.id_empresa if puerta else None

    def _validar_destino(self, id_puerta: int, id_dispositivo: int | None, db: Session) -> None:
        """
        Valida (antes de reconocer) que la puerta exista y, si se indicó, también
        el dispositivo. Lanza 404 con un mensaje claro en lugar de dejar que el
        INSERT del escaneo falle con un 500 por violación de FK.
        """
        if db.query(PuertaAcceso).get(id_puerta) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Puerta {id_puerta} no encontrada.",
            )
        if id_dispositivo is not None and db.query(Dispositivo).get(id_dispositivo) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dispositivo {id_dispositivo} no encontrado.",
            )

    def _registrar_escaneo(self, escaneo: Escaneo, db: Session) -> Escaneo:
        """
        Persiste el escaneo capturando errores de integridad (FK, etc.) y
        devolviéndolos como 400 en lugar de un 500.
        """
        db.add(escaneo)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al registrar escaneo: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo registrar el escaneo: {exc.orig}",
            )
        db.refresh(escaneo)
        return escaneo

    def _validar_escaneo_online(self, escaneo: Escaneo, db: Session) -> None:
        """
        Valida el escaneo recién insertado llamando a validar_escaneos_lote() de la
        BD (reemplaza al viejo trigger AFTER INSERT, eliminado en el esquema nuevo).

        La función evalúa las 3 capas (tipo_puerta vs permiso, empresa, geocerca);
        si alguna falla, marca el escaneo (rechazado/fuera_de_area) y crea la
        incidencia correspondiente. Se acota con p_desde = sincronizado_en del
        propio escaneo para no reprocesar toda la bitácora (idempotente: la función
        solo toca escaneos aún en estado 'exitoso').
        """
        try:
            db.execute(
                text("SELECT * FROM validar_escaneos_lote(:desde)"),
                {"desde": escaneo.sincronizado_en},
            )
            db.commit()
            db.refresh(escaneo)
        except Exception as exc:  # no romper el acceso si la validación falla
            db.rollback()
            logger.error(
                "No se pudo validar en lote el escaneo %s: %s",
                escaneo.id_escaneo, exc,
            )

    def _guardar_foto_si_incidencia(
        self, escaneo: Escaneo, frame: np.ndarray, cara: dict, db: Session
    ) -> None:
        """
        Si el escaneo recién validado generó una incidencia (la crea
        validar_escaneos_lote, p. ej. 'fuera_de_area'/'area_incorrecta'), guarda el
        recorte del rostro como JPEG en disco y setea `incidencias.ruta_foto`. Si no
        hubo incidencia, no hace nada.

        Llamar DESPUÉS de _validar_escaneo_online, para que la incidencia ya exista.
        """
        incidencias = (
            db.query(Incidencia)
            .filter(Incidencia.id_escaneo_ref == escaneo.id_escaneo)
            .all()
        )
        if not incidencias:
            return

        jpeg = self._recorte_jpeg(frame, cara)
        if jpeg is None:
            logger.warning("No se pudo codificar la foto de la incidencia del escaneo %s.", escaneo.id_escaneo)
            return

        ruta_web = self._escribir_media(jpeg, "incidencias", f"escaneo_{escaneo.id_escaneo}.jpg")
        if ruta_web is None:
            return
        for inc in incidencias:
            inc.ruta_foto = ruta_web
        db.commit()
        logger.info("Foto de incidencia guardada para el escaneo %s -> %s", escaneo.id_escaneo, ruta_web)

    # ── Captura de intentos de acceso (spoofing / otra empresa / desconocido) ──
    def _recorte_jpeg(self, frame: np.ndarray, cara: dict) -> bytes | None:
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

    def _escribir_media(self, jpeg: bytes, subcarpeta: str, nombre: str) -> str | None:
        """Guarda los bytes JPEG en media/<subcarpeta>/<nombre> y devuelve la URL web."""
        carpeta = os.path.join(_MEDIA_BASE, subcarpeta)
        os.makedirs(carpeta, exist_ok=True)
        try:
            with open(os.path.join(carpeta, nombre), "wb") as f:
                f.write(jpeg)
        except OSError as exc:
            logger.error("No se pudo guardar la imagen en %s/%s: %s", subcarpeta, nombre, exc)
            return None
        return f"{settings.MEDIA_URL}/{subcarpeta}/{nombre}"

    def _mejor_candidato_global(self, embedding: list[float], db: Session) -> dict | None:
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

    def _guardar_intento(
        self,
        tipo: str,
        frame: np.ndarray,
        cara: dict,
        id_puerta: int,
        db: Session,
        similitud: float | None = None,
        id_trabajador: int | None = None,
    ) -> IntentoAcceso | None:
        """
        Registra un intento de acceso rechazado en la tabla intentos_acceso
        (scopeado por la empresa de la puerta) y guarda la foto del rostro en
        media/intentos/. Tipos: 'spoofing', 'desconocido', 'otra_empresa'.
        """
        intento = IntentoAcceso(
            id_puerta=id_puerta,
            id_empresa=self._empresa_de_puerta(id_puerta, db),
            tipo=tipo,
            id_trabajador=id_trabajador,
            similitud=round(similitud, 3) if similitud is not None else None,
        )
        try:
            db.add(intento)
            db.commit()
            db.refresh(intento)
        except IntegrityError as exc:
            db.rollback()
            logger.error("No se pudo registrar el intento de acceso [%s]: %s", tipo, getattr(exc, "orig", exc))
            return None

        # Guardar la foto y enlazarla (nombrada por el id del intento)
        jpeg = self._recorte_jpeg(frame, cara)
        if jpeg is not None:
            ruta = self._escribir_media(jpeg, "intentos", f"intento_{intento.id_intento}.jpg")
            if ruta is not None:
                intento.ruta_foto = ruta
                db.commit()

        logger.warning(
            "INTENTO de acceso [%s] id=%s puerta=%s similitud=%s trabajador=%s -> %s",
            tipo, intento.id_intento, id_puerta,
            f"{similitud:.4f}" if similitud is not None else "-",
            id_trabajador if id_trabajador is not None else "-",
            intento.ruta_foto,
        )
        return intento

    def _clasificar_no_match(
        self,
        frame: np.ndarray,
        cara: dict,
        id_puerta: int,
        id_empresa_puerta: int | None,
        db: Session,
    ) -> None:
        """
        Un rostro NO se reconoció en la empresa de la puerta. Busca global y
        clasifica el intento: 'otra_empresa' (match alto en otra empresa) o
        'desconocido' (rostro real no enrolado). Si la mejor similitud es baja,
        es ruido y no se registra.
        """
        det = float(cara.get("det_score", 0.0))
        cand = self._mejor_candidato_global(cara["embedding"], db)
        sim = cand["similitud"] if cand else None

        if cand is not None and sim >= SIMILITUD_UMBRAL and cand["id_empresa"] != id_empresa_puerta:
            # Trabajador de OTRA empresa →
            #   - intento_acceso: lo ve el admin de la puerta (su empresa).
            #   - incidencia: alerta a la empresa del propio trabajador.
            self._guardar_intento(
                "otra_empresa", frame, cara, id_puerta, db,
                similitud=sim, id_trabajador=cand["id_trabajador"],
            )
            self._registrar_incidencia_otra_empresa(frame, cara, id_puerta, cand, db)
        elif det >= UMBRAL_DET_DESCONOCIDO:
            # Rostro CLARO pero no reconocido aquí → desconocido (guarda la mejor
            # similitud encontrada, solo informativa; suele ser baja).
            self._guardar_intento("desconocido", frame, cara, id_puerta, db, similitud=sim)
        # else: detección pobre (rostro borroso/parcial) → ruido, se ignora

    def _registrar_incidencia_otra_empresa(
        self, frame: np.ndarray, cara: dict, id_puerta: int, cand: dict, db: Session
    ) -> None:
        """
        Registra una incidencia 'acceso_otra_empresa' para el trabajador detectado
        (que pertenece a OTRA empresa) e intenta entrar por esta puerta. Guarda la
        foto del rostro y la enlaza en `ruta_foto`.

        Nota: la incidencia queda bajo el trabajador, así que la ve el admin de SU
        empresa (alerta de que su empleado anduvo en otra puerta). Si la BD aún no
        admite el tipo, cae a guardar solo la foto como intento (no rompe el acceso).
        """
        try:
            incidencia = Incidencia(
                id_trabajador=cand["id_trabajador"],
                id_empresa=cand["id_empresa"],   # empresa del trabajador detectado (denormalizado)
                tipo_incidencia="acceso_otra_empresa",
                # Fecha LOCAL (no UTC): debe coincidir con date.today() que usa el
                # listado y con la hora del sistema (Mazatlán), si no cae "mañana".
                fecha=date.today(),
                descripcion=(
                    f"Intento de acceso en puerta {id_puerta} por trabajador de otra "
                    f"empresa. Similitud: {cand['similitud']:.4f}."
                ),
                estado="pendiente",
            )
            db.add(incidencia)
            db.commit()
            db.refresh(incidencia)
        except IntegrityError as exc:
            db.rollback()
            logger.error(
                "No se pudo registrar incidencia 'acceso_otra_empresa' (¿falta el tipo "
                "en el CHECK de la tabla?): %s. El intento ya quedó en intentos_acceso.",
                getattr(exc, "orig", exc),
            )
            return

        # Guardar la foto y enlazarla a la incidencia
        jpeg = self._recorte_jpeg(frame, cara)
        if jpeg is not None:
            ruta = self._escribir_media(jpeg, "incidencias", f"incidencia_{incidencia.id_incidencia}.jpg")
            if ruta is not None:
                incidencia.ruta_foto = ruta
                db.commit()

        logger.warning(
            "Incidencia 'acceso_otra_empresa' registrada: incidencia=%s trabajador=%s puerta=%s similitud=%.4f",
            incidencia.id_incidencia, cand["id_trabajador"], id_puerta, cand["similitud"],
        )

    def procesar_frame_acceso(
        self,
        frame: np.ndarray,
        id_puerta: int,
        tipo_registro: str,
        id_dispositivo: int | None,
        db: Session,
        latitud: float | None = None,
        longitud: float | None = None,
    ) -> ScanResponse:
        """
        Pipeline completo: frame → detección → anti-spoofing → búsqueda → registro.
        """
        # 0. Validar destino (puerta/dispositivo) antes de gastar en reconocimiento
        self._validar_destino(id_puerta, id_dispositivo, db)

        # 1. Detectar rostro y extraer embedding
        cara = self.detectar_y_extraer(frame)
        if cara is None:
            return ScanResponse(
                acceso=False,
                mensaje="No se detectó ningún rostro en el frame.",
                trabajador=None,
                id_escaneo=None,
                estado_registro="rechazado",
            )

        # 2. Anti-spoofing dedicado (foto/pantalla/hoja)
        rechazo = self._verificar_antispoof(frame, cara)
        if rechazo is not None:
            self._guardar_intento("spoofing", frame, cara, id_puerta, db)
            return rechazo

        # 3. Buscar en BD (acotado a la empresa de la puerta)
        id_empresa = self._empresa_de_puerta(id_puerta, db)
        match = self.buscar_en_bd(cara["embedding"], db, id_empresa=id_empresa)
        if match is None:
            # No reconocido en esta empresa → clasificar (otra empresa / desconocido)
            self._clasificar_no_match(frame, cara, id_puerta, id_empresa, db)
            return ScanResponse(
                acceso=False,
                mensaje="Rostro no reconocido en esta empresa.",
                trabajador=None,
                id_escaneo=None,
                estado_registro="rechazado",
            )

        trabajador = match["trabajador"]
        similitud  = match["similitud"]

        # 4. Registrar escaneo (con ubicación: GPS del dispositivo o, si no, la de la puerta)
        escaneo = Escaneo(
            id_trabajador=trabajador.id_trabajador,
            id_puerta=id_puerta,
            id_empresa=trabajador.id_empresa,
            id_dispositivo=id_dispositivo,
            tipo_registro=tipo_registro,
            fecha_hora=datetime.now(timezone.utc),
            confianza_biometrica=round(similitud, 2),
            estado_registro="exitoso",
            observaciones=f"Reconocimiento facial. Similitud: {similitud:.4f}",
            ubicacion=self._resolver_ubicacion(latitud, longitud, id_puerta, db),
        )
        escaneo = self._registrar_escaneo(escaneo, db)

        # Validar el escaneo (3 capas) y, si quedó como incidencia, guardar la foto.
        self._validar_escaneo_online(escaneo, db)
        self._guardar_foto_si_incidencia(escaneo, frame, cara, db)

        return ScanResponse(
            acceso=True,
            mensaje=f"Acceso concedido — {trabajador.nombre} {trabajador.apellido} "
                    f"(similitud: {similitud:.2%}).",
            trabajador=TrabajadorBrief.model_validate(trabajador),
            id_escaneo=escaneo.id_escaneo,
            estado_registro="exitoso",
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

    def procesar_frames_acceso(
        self,
        frames: list[np.ndarray],
        id_puerta: int,
        tipo_registro: str,
        id_dispositivo: int | None,
        db: Session,
        latitud: float | None = None,
        longitud: float | None = None,
    ) -> ScanResponse:
        """
        Pipeline con liveness multi-frame:
          frames → detección en cada uno → liveness (misma persona + movimiento)
                 → mejor frame → búsqueda → registro de escaneo.
        """
        # 0. Validar destino (puerta/dispositivo) antes de gastar en reconocimiento
        self._validar_destino(id_puerta, id_dispositivo, db)

        # 1. Detectar rostro en cada frame (conservando el frame de origen)
        pares = [(f, self.detectar_y_extraer(f)) for f in frames]
        pares = [(f, c) for f, c in pares if c is not None]
        caras = [c for _, c in pares]

        if len(caras) < LIVENESS_MIN_FRAMES_CON_ROSTRO:
            return ScanResponse(
                acceso=False,
                mensaje=f"No se detectó rostro en suficientes frames "
                        f"(se necesitan al menos {LIVENESS_MIN_FRAMES_CON_ROSTRO})."
                        f"No. caras detectdas {len(caras)}",
                trabajador=None,
                id_escaneo=None,
                estado_registro="rechazado",
            )

        # 2. Validar liveness
        live = self.evaluar_liveness(caras)
        if not live["vivo"]:
            return ScanResponse(
                acceso=False,
                mensaje=f"Prueba de vida fallida: {live['motivo']}",
                trabajador=None,
                id_escaneo=None,
                estado_registro="rechazado",
            )

        # 3. Anti-spoofing dedicado sobre el frame de mejor calidad
        mejor_frame, mejor = max(pares, key=lambda p: p[1]["det_score"])
        rechazo = self._verificar_antispoof(mejor_frame, mejor)
        if rechazo is not None:
            self._guardar_intento("spoofing", mejor_frame, mejor, id_puerta, db)
            return rechazo

        # 4. Reconocer usando ese frame (acotado a la empresa de la puerta)
        id_empresa = self._empresa_de_puerta(id_puerta, db)
        match = self.buscar_en_bd(mejor["embedding"], db, id_empresa=id_empresa)
        if match is None:
            # No reconocido en esta empresa → clasificar (otra empresa / desconocido)
            self._clasificar_no_match(mejor_frame, mejor, id_puerta, id_empresa, db)
            return ScanResponse(
                acceso=False,
                mensaje="Rostro no reconocido en esta empresa.",
                trabajador=None,
                id_escaneo=None,
                estado_registro="rechazado",
            )

        trabajador = match["trabajador"]
        similitud  = match["similitud"]

        # 4. Registrar escaneo (con ubicación: GPS del dispositivo o, si no, la de la puerta)
        escaneo = Escaneo(
            id_trabajador=trabajador.id_trabajador,
            id_puerta=id_puerta,
            id_empresa=trabajador.id_empresa,
            id_dispositivo=id_dispositivo,
            tipo_registro=tipo_registro,
            fecha_hora=datetime.now(timezone.utc),
            confianza_biometrica=round(similitud, 2),
            estado_registro="exitoso",
            observaciones=f"Facial + liveness. Similitud: {similitud:.4f}, movimiento: {live['movimiento']:.4f}",
            ubicacion=self._resolver_ubicacion(latitud, longitud, id_puerta, db),
        )
        escaneo = self._registrar_escaneo(escaneo, db)

        # Validar el escaneo (3 capas) y, si quedó como incidencia, guardar la foto.
        self._validar_escaneo_online(escaneo, db)
        self._guardar_foto_si_incidencia(escaneo, mejor_frame, mejor, db)

        return ScanResponse(
            acceso=True,
            mensaje=f"Acceso concedido — {trabajador.nombre} {trabajador.apellido} "
                    f"(similitud: {similitud:.2%}, liveness OK).",
            trabajador=TrabajadorBrief.model_validate(trabajador),
            id_escaneo=escaneo.id_escaneo,
            estado_registro="exitoso",
        )

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


facial_service = FacialService()