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

# Pendientes = sin subir Y no rechazados por la nube (mismo criterio que los intentos:
# sync_rechazado evita reintentar en bucle una fila que la nube rechaza fila-por-fila).
_PENDIENTES = text("""
    SELECT id_escaneo, id_trabajador, id_puerta, id_empresa, tipo_registro,
           creado_en_cliente, confianza_biometrica, dentro_de_area, id_dispositivo_origen
    FROM escaneos
    WHERE sincronizado_en IS NULL AND NOT sync_rechazado
    ORDER BY fecha_creacion
    LIMIT :lim
""")
_MARCAR = text(
    "UPDATE escaneos SET sincronizado_en = NOW() WHERE id_escaneo IN :ids"
).bindparams(bindparam("ids", expanding=True))
_MARCAR_RECH = text(
    "UPDATE escaneos SET sync_rechazado = TRUE WHERE id_escaneo IN :ids"
).bindparams(bindparam("ids", expanding=True))

# Columnas EXACTAS que espera POST /off_sync/asistencias (id_asistencia = id_escaneo).
_COLS = ["id_asistencia", "id_trabajador", "id_puerta", "id_empresa", "tipo_registro",
         "creado_en_cliente", "confianza_biometrica", "dentro_de_area",
         "id_dispositivo_origen", "latitud", "longitud"]

# ── Intentos fallidos (mismo mecanismo, contra /off_sync/intentos) ────────────
# Pendientes = sin subir Y no rechazados por la nube (sync_rechazado se marca aparte
# para no reintentar en bucle una fila que la nube rechaza fila-por-fila, p.ej. por FK).
_PENDIENTES_INT = text("""
    SELECT id_intento, id_puerta, id_empresa, tipo, id_trabajador, similitud,
           creado_en_cliente, id_dispositivo_origen
    FROM intentos_acceso
    WHERE sincronizado_en IS NULL AND NOT sync_rechazado
    ORDER BY fecha
    LIMIT :lim
""")
_MARCAR_INT_OK = text(
    "UPDATE intentos_acceso SET sincronizado_en = NOW() WHERE id_intento IN :ids"
).bindparams(bindparam("ids", expanding=True))
_MARCAR_INT_RECH = text(
    "UPDATE intentos_acceso SET sync_rechazado = TRUE WHERE id_intento IN :ids"
).bindparams(bindparam("ids", expanding=True))

# Columnas EXACTAS que espera POST /off_sync/intentos.
_COLS_INT = ["id_intento", "id_puerta", "id_empresa", "tipo", "id_trabajador", "similitud",
             "creado_en_cliente", "id_dispositivo_origen", "latitud", "longitud"]

# ── Fotos de evidencia de intentos (subir a media DESPUÉS del CSV) ────────────
# Solo intentos YA subidos por CSV (sincronizado_en NOT NULL) y no rechazados: así
# la fila ya existe en la nube y el POST /off_sync/intentos/foto la encuentra por id.
_FOTO_BATCH = 20   # las fotos pesan; pocas por ciclo
_PENDIENTES_FOTO = text("""
    SELECT id_intento, foto_bytes
    FROM intentos_acceso
    WHERE foto_bytes IS NOT NULL AND sincronizado_en IS NOT NULL AND NOT sync_rechazado
    ORDER BY fecha
    LIMIT :lim
""")
_LIMPIAR_FOTO = text("UPDATE intentos_acceso SET foto_bytes = NULL WHERE id_intento = :id")


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


def _csv_intentos(filas) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_COLS_INT)
    for f in filas:
        w.writerow([
            f.id_intento, f.id_puerta, f.id_empresa, f.tipo,
            f.id_trabajador if f.id_trabajador is not None else "",
            f.similitud if f.similitud is not None else "",
            f.creado_en_cliente.isoformat() if f.creado_en_cliente else "",
            f.id_dispositivo_origen if f.id_dispositivo_origen is not None else "",
            "", "",   # latitud, longitud (sin GPS)
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
            rech = resp.get("rechazados") or []
            # Una fila RECHAZADA no llegó: marcarla como sincronizada la perdería para
            # siempre (fue el bug que dejó 952 fichajes fuera de la nube). Se marca aparte.
            rech_ids = {str(r["id"]) for r in rech if r.get("id")}
            todos = [str(f.id_escaneo) for f in filas]
            ok_ids = [i for i in todos if i not in rech_ids]       # insertados + duplicados
            if ok_ids:
                db.execute(_MARCAR, {"ids": ok_ids})
            if rech_ids:
                db.execute(_MARCAR_RECH, {"ids": list(rech_ids)})  # no reintentar en bucle
            db.commit()
            logger.info("sync: subidos %d (insertados=%s duplicados=%s rechazados=%d)",
                        len(ok_ids), resp.get("insertados"), resp.get("duplicados"), len(rech_ids))
            if rech_ids:
                logger.warning("sync: la nube rechazó %d filas (marcadas aparte): %s",
                               len(rech_ids), rech[:5])
            return {"subidos": len(ok_ids), "insertados": resp.get("insertados"),
                    "duplicados": resp.get("duplicados"), "rechazados": len(rech_ids)}
        finally:
            db.close()

    def subir_intentos_pendientes(self) -> dict:
        """Sube UN lote de intentos fallidos pendientes. Marca insertados+duplicados como
        sincronizados y los rechazados APARTE (sync_rechazado) para no reintentarlos en
        bucle. Lanza si no hay red."""
        db = SessionLocal()
        try:
            filas = db.execute(_PENDIENTES_INT, {"lim": settings.KIOSK_SYNC_BATCH}).all()
            if not filas:
                return {"pendientes": 0}
            resp = cloud_client.subir_intentos(_csv_intentos(filas))   # lanza si no hay internet
            rech = resp.get("rechazados") or []
            rech_ids = {str(r["id"]) for r in rech if r.get("id")}
            todos = [str(f.id_intento) for f in filas]
            ok_ids = [i for i in todos if i not in rech_ids]           # insertados + duplicados
            if ok_ids:
                db.execute(_MARCAR_INT_OK, {"ids": ok_ids})
            if rech_ids:
                db.execute(_MARCAR_INT_RECH, {"ids": list(rech_ids)})  # no reintentar
            db.commit()
            logger.info("sync intentos: subidos %d (insertados=%s duplicados=%s rechazados=%d)",
                        len(ok_ids), resp.get("insertados"), resp.get("duplicados"), len(rech_ids))
            if rech_ids:
                logger.warning("sync intentos: la nube rechazó %d (marcados aparte): %s",
                               len(rech_ids), rech[:5])
            return {"subidos": len(ok_ids), "insertados": resp.get("insertados"),
                    "duplicados": resp.get("duplicados"), "rechazados": len(rech_ids)}
        finally:
            db.close()

    def subir_fotos_pendientes(self) -> dict:
        """Sube las fotos de evidencia de intentos YA subidos por CSV a media (POST
        /off_sync/intentos/foto). Al subir cada una, limpia foto_bytes (NULL). Un 404
        (intento aún no ingerido en la nube) o un fallo dejan la foto para el próximo ciclo."""
        db = SessionLocal()
        subidas = 0
        try:
            filas = db.execute(_PENDIENTES_FOTO, {"lim": _FOTO_BATCH}).all()
            if not filas:
                return {"pendientes": 0}
            for f in filas:
                try:
                    cloud_client.subir_intento_foto(str(f.id_intento), bytes(f.foto_bytes))
                    db.execute(_LIMPIAR_FOTO, {"id": str(f.id_intento)})
                    db.commit()
                    subidas += 1
                except Exception as exc:
                    db.rollback()
                    logger.debug("sync foto intento %s: pendiente (%s)", f.id_intento, exc)
            if subidas:
                logger.info("sync fotos: %d fotos de intento subidas.", subidas)
            return {"subidas": subidas}
        finally:
            db.close()

    def correr_loop(self, stop: threading.Event) -> None:
        """Loop en background: cada KIOSK_SYNC_INTERVAL_SEG intenta subir las colas
        (asistencias, intentos y sus fotos). Si no hay internet, falla silencioso y
        reintenta al siguiente ciclo (nada se pierde)."""
        logger.info("sync: loop iniciado (cada %.0fs, lote %d).",
                    settings.KIOSK_SYNC_INTERVAL_SEG, settings.KIOSK_SYNC_BATCH)
        while not stop.is_set():
            try:
                r = self.subir_pendientes()
                if r.get("subidos"):
                    logger.info("sync: %s", r)
            except Exception as exc:
                logger.debug("sync: sin subir asistencias (¿sin internet?): %s", exc)
            try:
                ri = self.subir_intentos_pendientes()
                if ri.get("subidos"):
                    logger.info("sync intentos: %s", ri)
            except Exception as exc:
                logger.debug("sync: sin subir intentos (¿sin internet?): %s", exc)
            try:
                rf = self.subir_fotos_pendientes()
                if rf.get("subidas"):
                    logger.info("sync fotos: %s", rf)
            except Exception as exc:
                logger.debug("sync: sin subir fotos (¿sin internet?): %s", exc)
            stop.wait(settings.KIOSK_SYNC_INTERVAL_SEG)
        logger.info("sync: loop detenido.")


sync_service = SyncService()
