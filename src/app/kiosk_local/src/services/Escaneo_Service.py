# kiosk_local/services/Escaneo_Service.py
# Registra el fichaje LOCAL (offline) en la tabla escaneos, en cola para subir a la nube.
# sincronizado_en = NULL marca "pendiente de subir" (la Fase 3 sube WHERE sincronizado_en IS NULL).
# El id_escaneo es UUIDv7 (gen_uuid_v7) → re-subir a la nube es idempotente (ON CONFLICT).
# NO se consolida entrada/salida aquí: eso lo hace la nube al recibir el lote (mismo modelo
# que el APK offline). El kiosko solo encola escaneos crudos.
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core import meta
from src.core.config import settings

logger = logging.getLogger(__name__)

_INSERT = text("""
    INSERT INTO escaneos (id_trabajador, id_puerta, id_empresa, tipo_registro,
                          confianza_biometrica, creado_en_cliente, id_dispositivo_origen,
                          estado_registro, sincronizado_en)
    VALUES (:trab, :puerta, :empresa, CAST(:tipo AS tipo_registro), :conf, NOW(),
            :disp, 'exitoso', NULL)
    RETURNING id_escaneo
""")
_PUERTA_DEFAULT = text(
    "SELECT id_puerta FROM puertas_acceso WHERE estado = 'activo' ORDER BY id_puerta LIMIT 1")


class EscaneoService:

    def _puerta(self, db: Session, id_puerta: int | None) -> int:
        # Prioridad: la de la request → la elegida en el front (kiosk_meta) → KIOSK_PUERTA
        # (env) → 1ª puerta activa del roster.
        p = id_puerta
        if p is None:
            p = meta.puerta_actual(db)
        if p is None:
            p = settings.KIOSK_PUERTA
        if p is None:
            p = db.execute(_PUERTA_DEFAULT).scalar()
        if p is None:
            raise ValueError("no hay puerta en el roster local; baja el roster primero.")
        return p

    def registrar_local(self, db: Session, id_trabajador: int, similitud: float | None,
                        id_puerta: int | None = None, tipo_registro: str = "entrada",
                        id_empresa: int | None = None) -> str:
        puerta = self._puerta(db, id_puerta)
        conf = None if similitud is None else min(max(float(similitud), 0.0), 1.0)
        # Sella el escaneo con la empresa ACTIVA (la del usuario logueado / último sync);
        # si no se pasó, cae al KIOSK_EMPRESA de respaldo. Debe ser la correcta: la nube
        # deriva entrada/salida y consolida por empresa al recibir el lote.
        empresa = id_empresa if id_empresa is not None else settings.KIOSK_EMPRESA
        id_esc = db.execute(_INSERT, {
            "trab": id_trabajador, "puerta": puerta, "empresa": empresa,
            "tipo": tipo_registro, "conf": conf, "disp": settings.KIOSK_DISPOSITIVO,
        }).scalar()
        db.commit()
        logger.info("escaneo local %s → trabajador %s (puerta %s, sim %.3f) [pendiente sync]",
                    id_esc, id_trabajador, puerta, conf or 0.0)
        return str(id_esc)


escaneo_service = EscaneoService()
