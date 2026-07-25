# kiosk_local/services/Intento_Service.py
# Registra intentos de acceso FALLIDOS (offline) en la tabla local intentos_acceso, en
# cola para subir a la nube. sincronizado_en = NULL marca "pendiente"; el loop de subida
# los manda a POST /off_sync/intentos. id_intento es UUIDv7 (gen_uuid_v7, default de la
# tabla) → generado en la ESTACIÓN, idempotente al re-subir (la nube hace ON CONFLICT).
import base64
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.config import settings

logger = logging.getLogger(__name__)

# Verdicto de recognition → tipo_intento que espera la nube (spoofing|desconocido|otra_empresa).
# Solo se registran los intentos de IDENTIDAD claros (hubo un rostro y falló). Los estados
# 'no_rostro'/'pocos_rostros'/'baja_calidad' NO se registran: son "captura insuficiente"
# (cámara vacía / frame malo) y en captura continua generarían cientos de intentos basura;
# se tratan como reintento. 'otra_empresa' no aplica (padrón local de UNA sola empresa).
# Para registrar también no_rostro/pocos_rostros, basta agregarlos aquí.
_TIPO_POR_ESTADO = {
    "spoof":    "spoofing",     # anti-spoof pasivo (foto/pantalla)
    "no_vivo":  "spoofing",     # liveness: foto estática sin movimiento
    "no_match": "desconocido",  # cara detectada pero sin match
}

_INSERT = text("""
    INSERT INTO intentos_acceso (id_puerta, id_empresa, tipo, id_trabajador, similitud,
                                 id_dispositivo_origen, creado_en_cliente, sincronizado_en, foto_bytes)
    VALUES (:puerta, :empresa, CAST(:tipo AS tipo_intento), NULL, :sim,
            :disp, NOW(), NULL, :foto)
    RETURNING id_intento
""")
_PUERTA_DEFAULT = text(
    "SELECT id_puerta FROM puertas_acceso WHERE estado = 'activo' ORDER BY id_puerta LIMIT 1")


class IntentoService:

    def _puerta(self, db: Session, id_puerta: int | None) -> int | None:
        p = id_puerta if id_puerta is not None else settings.KIOSK_PUERTA
        if p is None:
            p = db.execute(_PUERTA_DEFAULT).scalar()
        return p

    def registrar_fallido(self, db: Session, estado: str, id_empresa: int | None,
                          id_puerta: int | None = None, similitud: float | None = None,
                          recorte_b64: str | None = None) -> str | None:
        """Encola un intento fallido local (con su foto de evidencia si viene). Devuelve
        id_intento, o None si el estado no es registrable (p.ej. baja_calidad) o no hay
        puerta en el roster local. La foto (recorte JPEG de recognition) se guarda en
        foto_bytes y el loop la sube a media; luego se limpia."""
        tipo = _TIPO_POR_ESTADO.get(estado)
        if tipo is None:
            return None
        puerta = self._puerta(db, id_puerta)
        if puerta is None:
            logger.warning("intento %s no registrado: no hay puerta en el roster local.", estado)
            return None
        empresa = id_empresa if id_empresa is not None else settings.KIOSK_EMPRESA
        sim = None if similitud is None else min(max(float(similitud), 0.0), 1.0)
        foto = None
        if recorte_b64:
            try:
                foto = base64.b64decode(recorte_b64)
            except (ValueError, TypeError):
                foto = None
        id_int = db.execute(_INSERT, {
            "puerta": puerta, "empresa": empresa, "tipo": tipo,
            "sim": sim, "disp": settings.KIOSK_DISPOSITIVO, "foto": foto,
        }).scalar()
        db.commit()
        logger.info("intento local %s (%s) → puerta %s [pendiente sync%s]",
                    id_int, tipo, puerta, ", con foto" if foto else "")
        return str(id_int)


intento_service = IntentoService()
