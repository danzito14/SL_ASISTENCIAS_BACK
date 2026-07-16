# kiosk_local/services/Sync_Service.py
# Auto-sync: sube la cola de escaneos LOCALES (sincronizado_en IS NULL) a la nube y los
# marca como subidos. Corre en un loop en background (ver main.py). Idempotente: el
# id_escaneo es UUIDv7, re-subir NO duplica (la nube hace ON CONFLICT DO NOTHING). Si no
# hay internet, el intento falla y se reintenta en el siguiente ciclo — nada se pierde.
import csv
import io
import logging
import threading

from sqlalchemy import bindparam, text

from src.core.config import settings
from src.core.pgdb import SessionLocal
from src.services.Cloud_Client import cloud_client

logger = logging.getLogger(__name__)

_PENDIENTES = text("""
    SELECT id_escaneo, id_trabajador, id_puerta, id_empresa, tipo_registro,
           creado_en_cliente, confianza_biometrica, dentro_de_area, id_dispositivo_origen
    FROM escaneos
    WHERE sincronizado_en IS NULL
    ORDER BY fecha_creacion
    LIMIT :lim
""")
_MARCAR = text(
    "UPDATE escaneos SET sincronizado_en = NOW() WHERE id_escaneo IN :ids"
).bindparams(bindparam("ids", expanding=True))

# Columnas EXACTAS que espera POST /off_sync/asistencias (id_asistencia = id_escaneo).
_COLS = ["id_asistencia", "id_trabajador", "id_puerta", "id_empresa", "tipo_registro",
         "creado_en_cliente", "confianza_biometrica", "dentro_de_area",
         "id_dispositivo_origen", "latitud", "longitud"]


def _csv(filas) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_COLS)
    for f in filas:
        w.writerow([
            f.id_escaneo, f.id_trabajador, f.id_puerta, f.id_empresa, f.tipo_registro,
            f.creado_en_cliente.isoformat() if f.creado_en_cliente else "",
            f.confianza_biometrica if f.confianza_biometrica is not None else "",
            "" if f.dentro_de_area is None else f.dentro_de_area,
            f.id_dispositivo_origen if f.id_dispositivo_origen is not None else "",
            "", "",   # latitud, longitud (el kiosko de escritorio no tiene GPS)
        ])
    return buf.getvalue().encode("utf-8")


class SyncService:

    def subir_pendientes(self) -> dict:
        """Sube UN lote de escaneos pendientes. Devuelve el resumen; lanza si no hay red."""
        db = SessionLocal()
        try:
            filas = db.execute(_PENDIENTES, {"lim": settings.KIOSK_SYNC_BATCH}).all()
            if not filas:
                return {"pendientes": 0}
            resp = cloud_client.subir_asistencias(_csv(filas))     # lanza si no hay internet
            ids = [str(f.id_escaneo) for f in filas]
            db.execute(_MARCAR, {"ids": ids})                      # marca el lote como subido
            db.commit()
            rech = resp.get("rechazados") or []
            logger.info("sync: subidos %d (insertados=%s duplicados=%s rechazados=%d)",
                        len(ids), resp.get("insertados"), resp.get("duplicados"), len(rech))
            if rech:
                logger.warning("sync: la nube rechazó %d filas: %s", len(rech), rech[:5])
            return {"subidos": len(ids), "insertados": resp.get("insertados"),
                    "duplicados": resp.get("duplicados"), "rechazados": len(rech)}
        finally:
            db.close()

    def correr_loop(self, stop: threading.Event) -> None:
        """Loop en background: cada KIOSK_SYNC_INTERVAL_SEG intenta subir la cola. Si no hay
        internet, falla silencioso y reintenta al siguiente ciclo (nada se pierde)."""
        logger.info("sync: loop iniciado (cada %.0fs, lote %d).",
                    settings.KIOSK_SYNC_INTERVAL_SEG, settings.KIOSK_SYNC_BATCH)
        while not stop.is_set():
            try:
                r = self.subir_pendientes()
                if r.get("subidos"):
                    logger.info("sync: %s", r)
            except Exception as exc:
                logger.debug("sync: sin subir (¿sin internet?): %s", exc)
            stop.wait(settings.KIOSK_SYNC_INTERVAL_SEG)
        logger.info("sync: loop detenido.")


sync_service = SyncService()
