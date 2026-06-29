# employee_monitoring/sync/Sync_Service.py
"""
Orquestador de la sincronización nómina SYS21 → PostgreSQL.

Por cada origen (nómina):
  1. resetea visto=False y carga el estado previo (hashes/foto) y el mapa id_trabajador.
  2. lee la nómina (streaming) → mapea → calcula hash_datos → detecta nuevos/modificados.
  3. upsert bulk de trabajadores (ON CONFLICT id_emp,origen) + upsert de sync_estado.
  4. fase de fotos (salvo solo_datos): por SFTP detecta foto nueva/cambiada, valida
     localmente, extrae embedding vía recognition (en paralelo) y crea/reemplaza el
     embedding. Lo que no pasa va a fotos_pendientes con su motivo (no aborta el lote).
  5. baja lógica de desaparecidos (visto=False).

Tolerante a fallos: una foto que falla solo va a fotos_pendientes; un origen caído se
marca como fallido pero no impide procesar el otro. Commit por lote (idempotente).
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models.Embedding_Model import Embedding
from src.models.FotoPendiente_Model import FotoPendiente
from src.models.SyncEstado_Model import SyncEstado
from src.services.Bulk_Service import bulk_service
from src.services.Embedding_Service import embedding_service
from src.services.Recognition_Service import recognition_service
from src.sources import sys21_reader
from src.sources.foto_sftp_client import FotoSFTPClient
from src.sync import hashing, mapping
from src.sync.clasificador_areas import ClasificacionAreas
from src.sync.foto_validacion import validar_foto_local
from src.schemas.Sync_Schema import SyncOrigenResultado, SyncRunResponse

logger = logging.getLogger(__name__)


@dataclass
class _Pendiente:
    """Una foto a re-tomar lista para procesar por recognition."""
    mapeado: "mapping.TrabajadorMapeado"
    id_trabajador: int
    foto_bytes: bytes
    hash_foto: str
    mtime: int | None
    size: int | None


@dataclass
class _FotoCandidato:
    """Trabajador YA registrado, para el endpoint dedicado de fotos (/sync/fotos).
    Lo consume _procesar_fotos, que solo necesita id_emp e id_empresa."""
    id_emp: str
    id_empresa: int | None


class SyncService:

    def ejecutar_sync(
        self,
        db: Session,
        disparado_por: str = "manual",
        origenes: list[str] | None = None,
        solo_datos: bool = False,
    ) -> SyncRunResponse:
        inicio = datetime.now(timezone.utc)
        objetivos = origenes or list(settings.sys21_urls.keys())
        resumen = SyncRunResponse(disparado_por=disparado_por, solo_datos=solo_datos, inicio=inicio)

        # La clasificación de áreas se construye una vez (áreas locales activas).
        clasificacion = ClasificacionAreas.construir(db)

        for origen in objetivos:
            r = SyncOrigenResultado(origen=origen)
            try:
                self._sincronizar_origen(db, origen, clasificacion, r, solo_datos)
            except Exception as exc:  # noqa: BLE001 — un origen no debe tumbar al otro
                db.rollback()
                r.ok = False
                r.detalle_error = str(exc)
                logger.exception("Sync[%s] falló: %s", origen, exc)
            resumen.por_origen.append(r)
            self._acumular(resumen, r)

        fin = datetime.now(timezone.utc)
        resumen.fin = fin
        resumen.duracion_seg = round((fin - inicio).total_seconds(), 2)
        resumen.mensaje = "Sincronización completada."
        logger.info(
            "Sync (%s) listo en %.1fs: %d leídos, %d nuevos, %d actualizados, "
            "%d fotos ok, %d pendientes, %d desaparecidos, %d errores.",
            disparado_por, resumen.duracion_seg, resumen.leidos, resumen.nuevos,
            resumen.actualizados, resumen.fotos_ok, resumen.fotos_pendientes,
            resumen.desaparecidos, resumen.errores,
        )
        return resumen

    # ── Endpoint dedicado: SOLO fotos de trabajadores ya registrados ──────────
    def ejecutar_fotos(
        self,
        db: Session,
        origenes: list[str] | None = None,
        limite: int | None = None,
        forzar: bool = False,
    ) -> SyncRunResponse:
        """
        Procesa SOLO las fotos de los trabajadores YA registrados (no re-lee SYS21).

        Args:
            origenes: orígenes a procesar (None = todos los configurados).
            limite:   procesar a lo más N por origen (útil para pruebas).
            forzar:   ignora el estado previo de la foto (reprocesa aunque no haya
                      cambiado mtime/size); útil para recalibrar umbrales.
        """
        inicio = datetime.now(timezone.utc)
        objetivos = origenes or list(settings.sys21_urls.keys())
        resumen = SyncRunResponse(disparado_por="fotos", solo_datos=False, inicio=inicio)

        for origen in objetivos:
            r = SyncOrigenResultado(origen=origen)
            try:
                registrados = bulk_service.cargar_registrados(db, origen, limite=limite)
                candidatos = [_FotoCandidato(id_emp=row.id_emp, id_empresa=row.id_empresa) for row in registrados]
                id_trab_map = {(row.id_emp, origen): row.id_trabajador for row in registrados}
                estado_prev = {} if forzar else bulk_service.cargar_estado(db, origen)
                r.leidos = len(candidatos)
                self._procesar_fotos(db, origen, candidatos, id_trab_map, estado_prev, r)
            except Exception as exc:  # noqa: BLE001 — un origen no debe tumbar al otro
                db.rollback()
                r.ok = False
                r.detalle_error = str(exc)
                logger.exception("Fotos[%s] falló: %s", origen, exc)
            resumen.por_origen.append(r)
            self._acumular(resumen, r)

        fin = datetime.now(timezone.utc)
        resumen.fin = fin
        resumen.duracion_seg = round((fin - inicio).total_seconds(), 2)
        resumen.mensaje = "Procesamiento de fotos completado."
        logger.info(
            "Fotos listo en %.1fs: %d candidatos, %d fotos ok, %d pendientes, %d errores.",
            resumen.duracion_seg, resumen.leidos, resumen.fotos_ok, resumen.fotos_pendientes, resumen.errores,
        )
        return resumen

    # ── Por origen ────────────────────────────────────────────────────────────
    def _sincronizar_origen(
        self,
        db: Session,
        origen: str,
        clasificacion: ClasificacionAreas,
        r: SyncOrigenResultado,
        solo_datos: bool,
    ) -> None:
        bulk_service.resetear_visto(db, origen)
        estado_prev = bulk_service.cargar_estado(db, origen)
        # Trabajadores que YA existen (id_emp poblado). Si un empleado está en
        # sync_estado pero su trabajador ya no existe (p.ej. borrado en cascada al
        # eliminar un área), hay que re-insertarlo aunque su hash no haya cambiado.
        ya_registrados = bulk_service.cargar_id_trabajadores(db, origen)
        ahora = datetime.now(timezone.utc)

        mapeados: list[mapping.TrabajadorMapeado] = []
        filas_trab: list[dict] = []      # trabajadores nuevos/modificados → upsert
        filas_sync: list[dict] = []      # sync_estado de TODOS los vistos → upsert

        for fila in sys21_reader.leer_empleados(origen):
            r.leidos += 1
            mapeado, motivo = mapping.mapear_fila(fila, clasificacion)
            if mapeado is None:
                r.errores += 1
                self._registrar_pendiente(
                    db, str(fila.get("id_emp")), origen, None, None, motivo,
                    detalle=f"area_codigo={fila.get('area_codigo')} area_nombre={fila.get('area_nombre')}",
                )
                continue

            mapeados.append(mapeado)
            clave = (mapeado.id_emp, origen)
            h = hashing.hash_datos(mapeado.as_trabajador_dict())
            prev = estado_prev.get(clave)
            if prev is None or clave not in ya_registrados:
                # Nuevo, o huérfano (en sync_estado pero sin trabajador) → re-insertar.
                r.nuevos += 1
                filas_trab.append(mapeado.as_trabajador_dict())
            elif prev["hash_datos"] != h:
                r.actualizados += 1
                filas_trab.append(mapeado.as_trabajador_dict())
            else:
                r.sin_cambio += 1

            filas_sync.append({
                "id_emp": mapeado.id_emp,
                "origen_nomina": origen,
                "id_empresa": mapeado.id_empresa,
                "hash_datos": h,
                "visto_en_ultima_corrida": True,
                "ultima_sync": ahora,
            })

        # Persistir datos (bulk) y el estado de sync de todos los vistos.
        bulk_service.upsert_trabajadores(db, filas_trab, settings.SYNC_BATCH_SIZE)
        bulk_service.upsert_sync_estado(
            db, filas_sync,
            columnas_update=("id_empresa", "hash_datos", "visto_en_ultima_corrida", "ultima_sync"),
            batch_size=settings.SYNC_BATCH_SIZE,
        )
        db.commit()

        # Fase de fotos (necesita el id_trabajador de TODOS los vistos).
        if not solo_datos:
            id_trab_map = bulk_service.cargar_id_trabajadores(db, origen)
            self._procesar_fotos(db, origen, mapeados, id_trab_map, estado_prev, r)

        # Desaparecidos → baja lógica.
        r.desaparecidos = bulk_service.soft_delete_no_vistos(db, origen)
        db.commit()

    # ── Fase de fotos ─────────────────────────────────────────────────────────
    def _procesar_fotos(
        self,
        db: Session,
        origen: str,
        mapeados: list[mapping.TrabajadorMapeado],
        id_trab_map: dict[tuple[str, str], int],
        estado_prev: dict[tuple[str, str], dict],
        r: SyncOrigenResultado,
    ) -> None:
        try:
            sftp = FotoSFTPClient()
            sftp.conectar()
        except Exception as exc:  # noqa: BLE001 — sin SFTP no hay fotos, pero los datos ya están
            logger.error("Sync[%s]: no se pudo abrir SFTP, se omiten fotos: %s", origen, exc)
            return

        try:
            for lote in _chunks(mapeados, settings.SYNC_BATCH_SIZE):
                a_reconocer: list[_Pendiente] = []

                # A) stat + descarga + validación local (serial: SFTP no es thread-safe)
                for m in lote:
                    id_trab = id_trab_map.get((m.id_emp, origen))
                    if id_trab is None:
                        continue  # debería existir tras el upsert; defensivo
                    prev = estado_prev.get((m.id_emp, origen))
                    existe, mtime, size = sftp.stat_por_id_emp(m.id_emp)

                    if not existe:
                        self._actualizar_estado_foto(db, m.id_emp, origen, "sin_foto", None, None, None)
                        self._registrar_pendiente(db, m.id_emp, origen, m.id_empresa, id_trab, "sin_foto")
                        r.fotos_pendientes += 1
                        continue

                    # Sin cambio de foto (mismo mtime/size) → no reprocesar.
                    if prev and prev["foto_mtime"] == mtime and prev["foto_size"] == size \
                            and prev["estado_foto"] in ("ok", "pendiente"):
                        continue

                    data = sftp.descargar_por_id_emp(m.id_emp)
                    ok, motivo = validar_foto_local(data)
                    if not ok:
                        h = hashing.hash_foto(data) if data else None
                        self._actualizar_estado_foto(db, m.id_emp, origen, "pendiente", h, mtime, size)
                        self._registrar_pendiente(db, m.id_emp, origen, m.id_empresa, id_trab, motivo)
                        r.fotos_pendientes += 1
                        continue

                    a_reconocer.append(_Pendiente(
                        mapeado=m, id_trabajador=id_trab, foto_bytes=data,
                        hash_foto=hashing.hash_foto(data), mtime=mtime, size=size,
                    ))

                # B) recognition en paralelo (I/O HTTP)
                resultados: dict[int, dict | None] = {}
                if a_reconocer:
                    with ThreadPoolExecutor(max_workers=settings.SYNC_RECOG_CONCURRENCY) as ex:
                        futuros = {
                            ex.submit(recognition_service.extraer, p.foto_bytes): i
                            for i, p in enumerate(a_reconocer)
                        }
                        for fut in as_completed(futuros):
                            i = futuros[fut]
                            try:
                                resultados[i] = fut.result()
                            except Exception:  # noqa: BLE001
                                resultados[i] = None

                # C) aplicar resultados (serial: escritura a BD)
                for i, p in enumerate(a_reconocer):
                    res = resultados.get(i)
                    motivo = self._evaluar_recognition(res, db, p.id_trabajador, p.mapeado.id_empresa)

                    if motivo == "recognition_no_disponible":
                        # Transitorio: NO guardamos hash → se reintenta en la próxima corrida.
                        self._registrar_pendiente(db, p.mapeado.id_emp, origen, p.mapeado.id_empresa,
                                                  p.id_trabajador, motivo)
                        r.fotos_pendientes += 1
                        continue

                    if motivo is not None:
                        # Foto mala persistente: guardamos su hash para no reprocesarla igual.
                        self._actualizar_estado_foto(db, p.mapeado.id_emp, origen, "pendiente",
                                                     p.hash_foto, p.mtime, p.size)
                        self._registrar_pendiente(db, p.mapeado.id_emp, origen, p.mapeado.id_empresa,
                                                  p.id_trabajador, motivo, detalle=self._metricas_detalle(res))
                        r.fotos_pendientes += 1
                        continue

                    cara = {"embedding": res["embedding"], "det_score": res["det_score"]}
                    self._crear_o_reemplazar_embedding(db, p.id_trabajador, cara)
                    self._resolver_pendientes(db, p.mapeado.id_emp, origen)
                    self._actualizar_estado_foto(db, p.mapeado.id_emp, origen, "ok",
                                                 p.hash_foto, p.mtime, p.size, marca_ok=True)
                    r.fotos_ok += 1

                db.commit()
        finally:
            sftp.cerrar()

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _evaluar_recognition(self, res: dict | None, db: Session, id_trab: int,
                             id_empresa: int | None) -> str | None:
        """Aplica la cadena de validación de recognition. Devuelve motivo o None si pasa."""
        if res is None:
            return "recognition_no_disponible"
        if res.get("estado") == "no_rostro":
            return "no_rostro"
        # Una sola cara (si hay 2+, recognition tomó la más grande → ambiguo).
        if settings.FOTO_EXIGIR_UNA_CARA and (res.get("num_caras") or 1) > 1:
            return "multiples_caras"
        # Cara bien detectada.
        if (res.get("det_score") or 0) < settings.FOTO_DET_SCORE_MIN:
            return "det_score_bajo"
        # Cara suficientemente grande (no lejana).
        if (res.get("face_ratio") or 0) < settings.FOTO_MIN_FACE_RATIO:
            return "cara_pequena"
        # Pose frontal. pose = [pitch, yaw, roll] (InsightFace); si no viene, se omite.
        pose = res.get("pose")
        if pose and len(pose) >= 2:
            if abs(pose[0]) > settings.FOTO_MAX_PITCH or abs(pose[1]) > settings.FOTO_MAX_YAW:
                return "pose_no_frontal"
        # Nitidez (varianza del Laplaciano).
        if (res.get("blur") or 0) < settings.FOTO_BLUR_MIN:
            return "borrosa"
        # Anti-spoofing (hoy NO exigido; activar FOTO_EXIGIR_ANTISPOOF cuando esté listo).
        if settings.FOTO_EXIGIR_ANTISPOOF:
            if not res.get("es_real"):
                return "spoofing"
            anti = res.get("antispoof")
            if anti is not None and not anti.get("es_real"):
                return "spoofing"
        # Anti-duplicado por empresa (excluye al propio trabajador para recapturas).
        dup = embedding_service.buscar_duplicado(
            res["embedding"], db, excluir_id_trabajador=id_trab, id_empresa=id_empresa
        )
        if dup is not None:
            return "duplicado"
        return None

    def _crear_o_reemplazar_embedding(self, db: Session, id_trabajador: int, cara: dict) -> None:
        """Crea el embedding del trabajador o reemplaza el vector si ya tenía uno (1:1)."""
        existente = db.query(Embedding).filter(Embedding.id_trabajador == id_trabajador).first()
        if existente is None:
            existente = Embedding(id_trabajador=id_trabajador)
            db.add(existente)
        embedding_service._aplicar_cara(existente, cara, db)

    def _actualizar_estado_foto(self, db: Session, id_emp: str, origen: str, estado_foto: str,
                                hash_foto: str | None, mtime: int | None, size: int | None,
                                marca_ok: bool = False) -> None:
        valores = {
            "estado_foto": estado_foto, "hash_foto": hash_foto,
            "foto_mtime": mtime, "foto_size": size,
        }
        if marca_ok:
            valores["ultima_sync_ok"] = datetime.now(timezone.utc)
        db.execute(
            update(SyncEstado)
            .where(SyncEstado.id_emp == id_emp, SyncEstado.origen_nomina == origen)
            .values(**valores)
        )

    @staticmethod
    def _metricas_detalle(res: dict | None) -> str | None:
        """Resumen de las señales medidas (para calibrar umbrales desde fotos_pendientes)."""
        if not res:
            return None
        return (
            f"det_score={res.get('det_score')} num_caras={res.get('num_caras')} "
            f"face_ratio={res.get('face_ratio')} blur={res.get('blur')} pose={res.get('pose')}"
        )

    def _registrar_pendiente(self, db: Session, id_emp: str, origen: str, id_empresa: int | None,
                             id_trabajador: int | None, motivo: str, detalle: str | None = None) -> None:
        """Registra/actualiza la foto pendiente abierta de un empleado (sin duplicar)."""
        abierta = (
            db.query(FotoPendiente)
            .filter(
                FotoPendiente.id_emp == id_emp,
                FotoPendiente.origen_nomina == origen,
                FotoPendiente.estado == "pendiente",
            )
            .first()
        )
        if abierta is not None:
            abierta.motivo = motivo
            abierta.detalle = detalle
            abierta.id_trabajador = id_trabajador
            abierta.id_empresa = id_empresa
            abierta.fecha = datetime.now(timezone.utc)
        else:
            db.add(FotoPendiente(
                id_emp=id_emp, origen_nomina=origen, id_trabajador=id_trabajador,
                id_empresa=id_empresa, motivo=motivo, detalle=detalle, estado="pendiente",
            ))

    def _resolver_pendientes(self, db: Session, id_emp: str, origen: str) -> None:
        """Cierra (resuelto) las fotos pendientes abiertas cuando la foto ya pasó."""
        db.execute(
            update(FotoPendiente)
            .where(
                FotoPendiente.id_emp == id_emp,
                FotoPendiente.origen_nomina == origen,
                FotoPendiente.estado == "pendiente",
            )
            .values(estado="resuelto")
        )

    @staticmethod
    def _acumular(resumen: SyncRunResponse, r: SyncOrigenResultado) -> None:
        resumen.leidos += r.leidos
        resumen.nuevos += r.nuevos
        resumen.actualizados += r.actualizados
        resumen.sin_cambio += r.sin_cambio
        resumen.fotos_ok += r.fotos_ok
        resumen.fotos_pendientes += r.fotos_pendientes
        resumen.desaparecidos += r.desaparecidos
        resumen.errores += r.errores


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


sync_service = SyncService()
