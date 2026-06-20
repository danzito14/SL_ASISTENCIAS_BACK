# app/services/scanner_service.py
"""
Orquestación de ACCESO por reconocimiento facial (dominio access/attendance).

Toma el resultado del motor de reconocimiento (recognition_service) y:
  - registra el Escaneo, lo valida (validar_escaneos_lote) y consolida la asistencia
    del día (consolidar_asistencia_dia)
  - clasifica y registra los intentos rechazados (spoofing / desconocido / otra_empresa)
  - guarda las fotos (media_service) de incidencias e intentos

El reconocimiento PURO (detección, embedding, liveness, anti-spoof, match) vive en
recognition_service. Esta separación es la costura para extraer 'recognition' como
microservicio compute-heavy (ver PLAN_MICROSERVICIOS §9): aquí queda lo que escribe
en la BD (dominio access); allá lo que solo computa.
"""
import logging
from datetime import date, datetime, timezone

import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.models.Escaneo_Model import Escaneo
from src.models.Incidencia_Model import Incidencia
from src.models.IntentoAcceso_Model import IntentoAcceso
from src.schemas.Asistencia_HistorialAuditoria import ScanResponse
from src.schemas.AreaTrabajo_Trabajador import TrabajadorBrief
from src.schemas._geo import punto_desde_latlon
from src.services.Media_Service import media_service
from src.services.Tenancy_Service import tenancy_service
from src.services.Recognition_Service import (
    recognition_service,
    SIMILITUD_UMBRAL,
    LIVENESS_MIN_FRAMES_CON_ROSTRO,
)

logger = logging.getLogger(__name__)

# ── Piso de DETECCIÓN para registrar un intento "desconocido" ────────────────
# Un desconocido real se parece POCO a todos (similitud baja), así que el filtro
# NO puede ser la similitud. Se usa la confianza de DETECCIÓN del rostro: si la
# cara se detectó clara (score >= este piso) y no se reconoció, se registra como
# desconocido; si la detección es pobre (rostro borroso/parcial) se ignora.
UMBRAL_DET_DESCONOCIDO = 0.70


class ScannerService:

    # ── Destino / ubicación (dominio access) ───────────────────────────────────
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

        puerta = tenancy_service.obtener_puerta(id_puerta, db)
        return puerta.ubicacion if puerta else None

    def _validar_destino(self, id_puerta: int, id_dispositivo: int | None, db: Session) -> None:
        """
        Valida (antes de reconocer) que la puerta exista y, si se indicó, también
        el dispositivo. Lanza 404 con un mensaje claro en lugar de dejar que el
        INSERT del escaneo falle con un 500 por violación de FK. Lee tenancy a
        través de su facade (access no consulta los modelos de tenancy directo).
        """
        if tenancy_service.obtener_puerta(id_puerta, db) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Puerta {id_puerta} no encontrada.",
            )
        if id_dispositivo is not None and tenancy_service.obtener_dispositivo(id_dispositivo, db) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dispositivo {id_dispositivo} no encontrado.",
            )

    # ── Registro y validación del escaneo ──────────────────────────────────────
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
        Valida el escaneo recién insertado y consolida la asistencia del día:

          1. validar_escaneos_lote(): evalúa las 3 capas (tipo_puerta vs permiso,
             empresa, geocerca). Si alguna falla, marca el escaneo
             (rechazado/fuera_de_area) y crea la incidencia. Acotado con
             p_desde = sincronizado_en del propio escaneo (idempotente: solo toca
             escaneos aún en estado 'exitoso'), para no reprocesar la bitácora.
          2. consolidar_asistencia_dia(0, <trab>, FALSE): materializa la ENTRADA
             del día en 'asistencia' EN VIVO (acotada a este trabajador, sin salida
             —la salida se infiere en el cierre nocturno—). Si el escaneo quedó
             rechazado en el paso 1, la consolidación lo ignora (solo cuenta los
             'exitoso'/'manual'), así que no genera una entrada inválida.

        Ambas corren en la misma transacción; si algo falla no se rompe el acceso.
        """
        try:
            db.execute(
                text("SELECT * FROM validar_escaneos_lote(:desde)"),
                {"desde": escaneo.sincronizado_en},
            )
            db.execute(
                text("SELECT * FROM consolidar_asistencia_dia(0, :trab, FALSE)"),
                {"trab": escaneo.id_trabajador},
            )
            db.commit()
            db.refresh(escaneo)
        except Exception as exc:  # no romper el acceso si la validación falla
            db.rollback()
            logger.error(
                "No se pudo validar/consolidar el escaneo %s: %s",
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

        jpeg = recognition_service.recorte_jpeg(frame, cara)
        if jpeg is None:
            logger.warning("No se pudo codificar la foto de la incidencia del escaneo %s.", escaneo.id_escaneo)
            return

        ruta_web = media_service.guardar_bytes(jpeg, "incidencias", f"escaneo_{escaneo.id_escaneo}.jpg")
        if ruta_web is None:
            return
        for inc in incidencias:
            inc.ruta_foto = ruta_web
        db.commit()
        logger.info("Foto de incidencia guardada para el escaneo %s -> %s", escaneo.id_escaneo, ruta_web)

    # ── Intentos rechazados (spoofing / otra empresa / desconocido) ────────────
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
            id_empresa=tenancy_service.empresa_de_puerta(id_puerta, db),
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
        jpeg = recognition_service.recorte_jpeg(frame, cara)
        if jpeg is not None:
            ruta = media_service.guardar_bytes(jpeg, "intentos", f"intento_{intento.id_intento}.jpg")
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
        cand = recognition_service.mejor_candidato_global(cara["embedding"], db)
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
        jpeg = recognition_service.recorte_jpeg(frame, cara)
        if jpeg is not None:
            ruta = media_service.guardar_bytes(jpeg, "incidencias", f"incidencia_{incidencia.id_incidencia}.jpg")
            if ruta is not None:
                incidencia.ruta_foto = ruta
                db.commit()

        logger.warning(
            "Incidencia 'acceso_otra_empresa' registrada: incidencia=%s trabajador=%s puerta=%s similitud=%.4f",
            incidencia.id_incidencia, cand["id_trabajador"], id_puerta, cand["similitud"],
        )

    # ── Pipelines de acceso ─────────────────────────────────────────────────────
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

        # 1. Detectar rostro y extraer embedding (motor de reconocimiento)
        cara = recognition_service.detectar_y_extraer(frame)
        if cara is None:
            return ScanResponse(
                acceso=False,
                mensaje="No se detectó ningún rostro en el frame.",
                trabajador=None,
                id_escaneo=None,
                estado_registro="rechazado",
            )

        # 2. Anti-spoofing dedicado (foto/pantalla/hoja)
        anti = recognition_service.evaluar_antispoof(frame, cara)
        if anti is not None and not anti["es_real"]:
            self._guardar_intento("spoofing", frame, cara, id_puerta, db)
            return ScanResponse(
                acceso=False,
                mensaje=f"Anti-spoofing: posible foto o pantalla "
                        f"(score real={anti['score_real']:.2f}).",
                trabajador=None,
                id_escaneo=None,
                estado_registro="rechazado",
            )

        # 3. Buscar en BD (acotado a la empresa de la puerta)
        id_empresa = tenancy_service.empresa_de_puerta(id_puerta, db)
        match = recognition_service.buscar_en_bd(cara["embedding"], db, id_empresa=id_empresa)
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
        pares = [(f, recognition_service.detectar_y_extraer(f)) for f in frames]
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
        live = recognition_service.evaluar_liveness(caras)
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
        anti = recognition_service.evaluar_antispoof(mejor_frame, mejor)
        if anti is not None and not anti["es_real"]:
            self._guardar_intento("spoofing", mejor_frame, mejor, id_puerta, db)
            return ScanResponse(
                acceso=False,
                mensaje=f"Anti-spoofing: posible foto o pantalla "
                        f"(score real={anti['score_real']:.2f}).",
                trabajador=None,
                id_escaneo=None,
                estado_registro="rechazado",
            )

        # 4. Reconocer usando ese frame (acotado a la empresa de la puerta)
        id_empresa = tenancy_service.empresa_de_puerta(id_puerta, db)
        match = recognition_service.buscar_en_bd(mejor["embedding"], db, id_empresa=id_empresa)
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

        # 5. Registrar escaneo (con ubicación: GPS del dispositivo o, si no, la de la puerta)
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


scanner_service = ScannerService()
