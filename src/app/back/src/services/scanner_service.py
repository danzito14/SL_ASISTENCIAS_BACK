# app/services/scanner_service.py
"""
Orquestación de ACCESO por reconocimiento facial (dominio access/attendance).

Recibe la(s) imagen(es), las manda al microservicio recognition (cliente HTTP) y,
según el resultado COARSE (estado + match/candidato + recorte de cara en base64):
  - registra el Escaneo, lo valida (validar_escaneos_lote) y consolida la asistencia
  - clasifica y registra los intentos rechazados (spoofing / desconocido / otra_empresa)
  - guarda las fotos (media_service) de incidencias e intentos

Ya NO procesa imágenes localmente (sin OpenCV): el recorte de cara lo devuelve
recognition. Lee puerta/dispositivo por el facade de tenancy.
"""
import base64
import logging
from datetime import date, datetime, timezone

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
from src.services.Recognition_Service import recognition_service

logger = logging.getLogger(__name__)

# Umbral de similitud (debe coincidir con el de recognition) para clasificar el
# no-match: un candidato global con similitud alta en OTRA empresa = 'otra_empresa'.
SIMILITUD_UMBRAL = 0.5
# Piso de DETECCIÓN para registrar un 'desconocido' (rostro claro no enrolado aquí).
UMBRAL_DET_DESCONOCIDO = 0.70


def _b64d(s: str | None) -> bytes | None:
    return base64.b64decode(s) if s else None


def _rechazo(mensaje: str) -> ScanResponse:
    return ScanResponse(acceso=False, mensaje=mensaje, trabajador=None, id_escaneo=None, estado_registro="rechazado")


class ScannerService:

    # ── Destino / ubicación (vía facade de tenancy) ────────────────────────────
    def _resolver_ubicacion(self, latitud, longitud, id_puerta: int, db: Session):
        punto = punto_desde_latlon(latitud, longitud)
        if punto is not None:
            return punto
        puerta = tenancy_service.obtener_puerta(id_puerta, db)
        return puerta.ubicacion if puerta else None

    def _validar_destino(self, id_puerta: int, id_dispositivo: int | None, db: Session) -> None:
        if tenancy_service.obtener_puerta(id_puerta, db) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Puerta {id_puerta} no encontrada.")
        if id_dispositivo is not None and tenancy_service.obtener_dispositivo(id_dispositivo, db) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dispositivo {id_dispositivo} no encontrado.")

    # ── Registro y validación del escaneo ──────────────────────────────────────
    def _registrar_escaneo(self, escaneo: Escaneo, db: Session) -> Escaneo:
        db.add(escaneo)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al registrar escaneo: %s", exc.orig)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"No se pudo registrar el escaneo: {exc.orig}")
        db.refresh(escaneo)
        return escaneo

    def _validar_escaneo_online(self, escaneo: Escaneo, db: Session) -> None:
        """
        validar_escaneos_lote() (3 capas) + consolidar_asistencia_dia(0, trab, FALSE)
        (entrada del día EN VIVO). Misma transacción; no rompe el acceso si falla.
        """
        try:
            db.execute(text("SELECT * FROM validar_escaneos_lote(:desde)"), {"desde": escaneo.sincronizado_en})
            db.execute(text("SELECT * FROM consolidar_asistencia_dia(0, :trab, FALSE)"), {"trab": escaneo.id_trabajador})
            db.commit()
            db.refresh(escaneo)
        except Exception as exc:
            db.rollback()
            logger.error("No se pudo validar/consolidar el escaneo %s: %s", escaneo.id_escaneo, exc)

    def _guardar_foto_si_incidencia(self, escaneo: Escaneo, recorte: bytes | None, db: Session) -> None:
        """Si validar_escaneos_lote dejó una incidencia para este escaneo, le adjunta el recorte."""
        incidencias = db.query(Incidencia).filter(Incidencia.id_escaneo_ref == escaneo.id_escaneo).all()
        if not incidencias or recorte is None:
            return
        ruta_web = media_service.guardar_bytes(recorte, "incidencias", f"escaneo_{escaneo.id_escaneo}.jpg")
        if ruta_web is None:
            return
        for inc in incidencias:
            inc.ruta_foto = ruta_web
        db.commit()
        logger.info("Foto de incidencia guardada para el escaneo %s -> %s", escaneo.id_escaneo, ruta_web)

    # ── Intentos rechazados (spoofing / otra empresa / desconocido) ────────────
    def _guardar_intento(self, tipo: str, recorte: bytes | None, id_puerta: int, db: Session,
                         similitud: float | None = None, id_trabajador: int | None = None) -> IntentoAcceso | None:
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
            logger.error("No se pudo registrar el intento [%s]: %s", tipo, getattr(exc, "orig", exc))
            return None

        if recorte is not None:
            ruta = media_service.guardar_bytes(recorte, "intentos", f"intento_{intento.id_intento}.jpg")
            if ruta is not None:
                intento.ruta_foto = ruta
                db.commit()
        logger.warning("INTENTO [%s] id=%s puerta=%s similitud=%s trabajador=%s",
                       tipo, intento.id_intento, id_puerta,
                       f"{similitud:.4f}" if similitud is not None else "-",
                       id_trabajador if id_trabajador is not None else "-")
        return intento

    def _clasificar_no_match(self, recorte: bytes | None, det_score: float,
                             candidato_global: dict | None, id_puerta: int,
                             id_empresa_puerta: int | None, db: Session) -> None:
        """Clasifica el rostro no reconocido usando el candidato global que devolvió recognition."""
        cand = candidato_global
        sim = cand["similitud"] if cand else None
        if cand is not None and sim >= SIMILITUD_UMBRAL and cand["id_empresa"] != id_empresa_puerta:
            self._guardar_intento("otra_empresa", recorte, id_puerta, db, similitud=sim, id_trabajador=cand["id_trabajador"])
            self._registrar_incidencia_otra_empresa(recorte, id_puerta, cand, db)
        elif det_score >= UMBRAL_DET_DESCONOCIDO:
            self._guardar_intento("desconocido", recorte, id_puerta, db, similitud=sim)
        # else: detección pobre → ruido, se ignora

    def _registrar_incidencia_otra_empresa(self, recorte: bytes | None, id_puerta: int, cand: dict, db: Session) -> None:
        try:
            incidencia = Incidencia(
                id_trabajador=cand["id_trabajador"],
                id_empresa=cand["id_empresa"],
                tipo_incidencia="acceso_otra_empresa",
                fecha=date.today(),
                descripcion=(f"Intento de acceso en puerta {id_puerta} por trabajador de otra empresa. "
                             f"Similitud: {cand['similitud']:.4f}."),
                estado="pendiente",
            )
            db.add(incidencia)
            db.commit()
            db.refresh(incidencia)
        except IntegrityError as exc:
            db.rollback()
            logger.error("No se pudo registrar incidencia 'acceso_otra_empresa': %s", getattr(exc, "orig", exc))
            return

        if recorte is not None:
            ruta = media_service.guardar_bytes(recorte, "incidencias", f"incidencia_{incidencia.id_incidencia}.jpg")
            if ruta is not None:
                incidencia.ruta_foto = ruta
                db.commit()
        logger.warning("Incidencia 'acceso_otra_empresa': incidencia=%s trabajador=%s puerta=%s",
                       incidencia.id_incidencia, cand["id_trabajador"], id_puerta)

    # ── Registro del escaneo exitoso (común a foto y liveness) ─────────────────
    def _registrar_match(self, res: dict, recorte: bytes | None, id_puerta: int, tipo_registro: str,
                         id_dispositivo: int | None, db: Session, latitud, longitud, observaciones: str) -> ScanResponse:
        trab = res["trabajador"]  # {id_trabajador, nombre, apellido, id_empresa, similitud}
        similitud = trab["similitud"]
        escaneo = Escaneo(
            id_trabajador=trab["id_trabajador"],
            id_puerta=id_puerta,
            id_empresa=trab["id_empresa"],
            id_dispositivo=id_dispositivo,
            tipo_registro=tipo_registro,
            fecha_hora=datetime.now(timezone.utc),
            confianza_biometrica=round(similitud, 2),
            estado_registro="exitoso",
            observaciones=observaciones,
            ubicacion=self._resolver_ubicacion(latitud, longitud, id_puerta, db),
        )
        escaneo = self._registrar_escaneo(escaneo, db)
        self._validar_escaneo_online(escaneo, db)
        self._guardar_foto_si_incidencia(escaneo, recorte, db)
        return ScanResponse(
            acceso=True,
            mensaje=f"Acceso concedido — {trab['nombre']} {trab['apellido']} (similitud: {similitud:.2%}).",
            trabajador=TrabajadorBrief(id_trabajador=trab["id_trabajador"], nombre=trab["nombre"],
                                       apellido=trab["apellido"], estado="activo"),
            id_escaneo=escaneo.id_escaneo,
            estado_registro="exitoso",
        )

    # ── Pipelines de acceso ─────────────────────────────────────────────────────
    def procesar_foto_acceso(self, foto_bytes: bytes, id_puerta: int, tipo_registro: str,
                             id_dispositivo: int | None, db: Session, latitud=None, longitud=None) -> ScanResponse:
        self._validar_destino(id_puerta, id_dispositivo, db)
        id_empresa = tenancy_service.empresa_de_puerta(id_puerta, db)
        res = recognition_service.reconocer(foto_bytes, id_empresa)
        if res is None:
            return _rechazo("Servicio de reconocimiento no disponible.")

        estado = res.get("estado")
        recorte = _b64d(res.get("recorte_b64"))
        if estado == "no_rostro":
            return _rechazo("No se detectó ningún rostro en la imagen.")
        if estado == "spoof":
            self._guardar_intento("spoofing", recorte, id_puerta, db)
            return _rechazo(f"Anti-spoofing: posible foto o pantalla (score real={res.get('score_real', 0):.2f}).")
        if estado == "no_match":
            self._clasificar_no_match(recorte, res.get("det_score", 0.0), res.get("candidato_global"), id_puerta, id_empresa, db)
            return _rechazo("Rostro no reconocido en esta empresa.")
        # match
        sim = res["trabajador"]["similitud"]
        return self._registrar_match(res, recorte, id_puerta, tipo_registro, id_dispositivo, db, latitud, longitud,
                                      observaciones=f"Reconocimiento facial. Similitud: {sim:.4f}")

    def procesar_fotos_acceso(self, fotos_bytes: list[bytes], id_puerta: int, tipo_registro: str,
                              id_dispositivo: int | None, db: Session, latitud=None, longitud=None) -> ScanResponse:
        self._validar_destino(id_puerta, id_dispositivo, db)
        id_empresa = tenancy_service.empresa_de_puerta(id_puerta, db)
        res = recognition_service.reconocer_liveness(fotos_bytes, id_empresa)
        if res is None:
            return _rechazo("Servicio de reconocimiento no disponible.")

        estado = res.get("estado")
        recorte = _b64d(res.get("recorte_b64"))
        if estado == "pocos_rostros":
            return _rechazo(f"No se detectó rostro en suficientes frames (detectadas: {res.get('n', 0)}).")
        if estado == "no_vivo":
            return _rechazo(f"Prueba de vida fallida: {res.get('motivo', '')}")
        if estado == "spoof":
            self._guardar_intento("spoofing", recorte, id_puerta, db)
            return _rechazo(f"Anti-spoofing: posible foto o pantalla (score real={res.get('score_real', 0):.2f}).")
        if estado == "no_match":
            self._clasificar_no_match(recorte, res.get("det_score", 0.0), res.get("candidato_global"), id_puerta, id_empresa, db)
            return _rechazo("Rostro no reconocido en esta empresa.")
        # match
        sim = res["trabajador"]["similitud"]
        mov = res.get("movimiento", 0.0)
        return self._registrar_match(res, recorte, id_puerta, tipo_registro, id_dispositivo, db, latitud, longitud,
                                      observaciones=f"Facial + liveness. Similitud: {sim:.4f}, movimiento: {mov:.4f}")


scanner_service = ScannerService()
