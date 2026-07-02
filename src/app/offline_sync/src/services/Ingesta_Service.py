# offline_sync/services/Ingesta_Service.py
"""
Ingesta por lotes (CSV) de lo que el APK capturó offline.

ASISTENCIAS  → se ingieren como ESCANEOS (la fuente de verdad) y luego se corre
el MISMO pipeline que el online:
    escaneos → validar_escaneos_lote(desde) → consolidar_asistencia_dia(dia, NULL, TRUE)
Ese pipeline DERIVA entrada/salida (1er scan=entrada, último=salida) e incidencias
en el SERVIDOR, con la zona horaria de la empresa. El `tipo_registro` del CSV se
IGNORA (el kiosko no sabe si es entrada o salida). Es idempotente (PK UUIDv7 del
dispositivo + ON CONFLICT DO NOTHING) y reconcilia lotes tardíos/desordenados
(consolidar re-ajusta entrada/salida y retracta 'entrada_sin_registro').

INTENTOS rechazados → van directos a intentos_acceso (no requieren derivación).

dentro_de_area: el APK lo precalcula; validar_escaneos_lote lo RE-AUDITA con
PostGIS. Sin fix GPS (lat/lon nulos) NO se penaliza: se conserva el valor cliente.

Cada fila va en su propio SAVEPOINT: una fila inválida se rechaza y se reporta
(con su PK) sin abortar el resto del lote.
"""
import csv
import io
import logging
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.auth import Principal, es_admin
from src.core.config import settings
from src.schemas.Ingesta_Schema import FilaRechazada, IngestaResponse

logger = logging.getLogger(__name__)

TIPOS_REGISTRO = {"entrada", "salida"}
TIPOS_INTENTO = {"spoofing", "desconocido", "otra_empresa"}

# Las asistencias offline entran como ESCANEOS. estado 'exitoso' → los toma el
# pipeline. tipo_registro es solo un placeholder (columna NOT NULL); se DERIVA.
_SQL_ESCANEO = text("""
    INSERT INTO escaneos (
        id_escaneo, id_trabajador, id_puerta, id_empresa, tipo_registro,
        fecha_hora, confianza_biometrica, estado_registro, dentro_de_area,
        id_dispositivo_origen, ubicacion, creado_en_cliente
    ) VALUES (
        :id, :id_trabajador, :id_puerta, :id_empresa, CAST(:tipo_registro AS tipo_registro),
        COALESCE(:creado_en_cliente, NOW()), :confianza, 'exitoso', :dentro_cliente,
        :id_dispositivo_origen,
        CASE WHEN :lon IS NULL OR :lat IS NULL THEN NULL
             ELSE ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography END,
        :creado_en_cliente
    )
    ON CONFLICT (id_escaneo) DO NOTHING
    RETURNING id_escaneo
""")

# Días (por empresa/TZ) presentes en el lote → para consolidar cada uno.
_SQL_DIAS_LOTE = text("""
    SELECT DISTINCT (timezone(em.zona_horaria, now())::date
         - timezone(em.zona_horaria, COALESCE(e.creado_en_cliente, e.fecha_hora))::date) AS d
    FROM escaneos e
    JOIN empresas em ON em.id_empresa = e.id_empresa
    WHERE e.id_escaneo = ANY(CAST(:ids AS uuid[]))
""")

_SQL_INTENTO = text("""
    INSERT INTO intentos_acceso (
        id_intento, id_puerta, id_empresa, tipo, id_trabajador, similitud,
        ubicacion, id_dispositivo_origen, creado_en_cliente, fecha
    ) VALUES (
        :id_intento, :id_puerta, :id_empresa, CAST(:tipo AS tipo_intento), :id_trabajador, :similitud,
        CASE WHEN :lon IS NULL OR :lat IS NULL THEN NULL
             ELSE ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography END,
        :id_dispositivo_origen, :creado_en_cliente, COALESCE(:creado_en_cliente, NOW())
    )
    ON CONFLICT (id_intento) DO NOTHING
    RETURNING id_intento
""")


# ── Conversores tolerantes (celda CSV → tipo Python o None) ───────────────────
def _i(v):
    return int(v) if v not in (None, "") else None


def _f(v):
    return float(v) if v not in (None, "") else None


def _b(v):
    if v in (None, ""):
        return None
    return str(v).strip().lower() in ("1", "true", "t", "si", "sí", "yes", "y")


def _dt(v):
    if v in (None, ""):
        return None
    return datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))


def _uuid(v):
    return uuid.UUID(str(v).strip())


def _motivo(exc: Exception) -> str:
    return str(getattr(exc, "orig", exc)).splitlines()[0][:200]


def _pk_crudo(fila: dict) -> str | None:
    """PK que trae la fila del CSV (para reportarla en rechazados)."""
    return fila.get("id_asistencia") or fila.get("id_intento")


class IngestaService:

    # ── ASISTENCIAS: escaneos + pipeline (derivación entrada/salida) ───────────
    def ingerir_asistencias(self, db: Session, contenido: str, principal: Principal) -> IngestaResponse:
        lector = csv.DictReader(io.StringIO(contenido))
        insertados = duplicados = recibidos = 0
        rechazados: list[FilaRechazada] = []
        # Marca temporal (reloj de la BD) para acotar validar_escaneos_lote al lote.
        desde = db.execute(text("SELECT now()")).scalar()
        ids_lote: list[str] = []

        for i, fila in enumerate(lector, start=2):  # línea 1 = encabezado
            recibidos += 1
            if recibidos > settings.INGESTA_MAX_FILAS:
                rechazados.append(FilaRechazada(linea=i, id=_pk_crudo(fila), motivo="limite_filas_excedido"))
                break
            try:
                params = self._parse_asistencia(fila, principal)
            except ValueError as e:
                rechazados.append(FilaRechazada(linea=i, id=fila.get("id_asistencia"), motivo=str(e)))
                continue
            try:
                with db.begin_nested():
                    r = db.execute(_SQL_ESCANEO, params).first()
                ids_lote.append(str(params["id"]))  # insertados y duplicados: re-derivar el día
                if r:
                    insertados += 1
                else:
                    duplicados += 1
            except Exception as exc:
                logger.warning("Ingesta escaneo línea %d rechazada: %s", i, exc)
                rechazados.append(FilaRechazada(linea=i, id=str(params.get("id")), motivo=_motivo(exc)))
        db.commit()

        # Pipeline de derivación (validar 3 capas + consolidar por día del lote).
        # Si falla, los escaneos ya quedaron: la próxima subida re-deriva (idempotente).
        if ids_lote:
            self._derivar_asistencia(db, desde, ids_lote)

        return IngestaResponse(recibidos=recibidos, insertados=insertados,
                               duplicados=duplicados, rechazados=rechazados)

    def _derivar_asistencia(self, db: Session, desde, ids_lote: list[str]) -> None:
        try:
            db.execute(text("SELECT validar_escaneos_lote(:desde)"), {"desde": desde})
            dias = db.execute(_SQL_DIAS_LOTE, {"ids": ids_lote}).scalars().all()
            for d in dias:
                db.execute(text("SELECT consolidar_asistencia_dia(:d, NULL, TRUE)"), {"d": int(d)})
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("No se pudo derivar la asistencia del lote offline: %s", exc)

    def _parse_asistencia(self, fila: dict, principal: Principal) -> dict:
        id_emp = _i(fila.get("id_empresa"))
        self._empresa_ok(id_emp, principal)
        # tipo_registro se DERIVA en el server; el del CSV es solo placeholder de la
        # columna NOT NULL de escaneos. Si viene inválido/ausente, se usa 'entrada'.
        tipo = (fila.get("tipo_registro") or "").strip().lower()
        if tipo not in TIPOS_REGISTRO:
            tipo = "entrada"
        try:
            p = {
                "id": _uuid(fila.get("id_asistencia")),
                "id_trabajador": _i(fila.get("id_trabajador")),
                "id_puerta": _i(fila.get("id_puerta")),
                "id_empresa": id_emp,
                "tipo_registro": tipo,
                "creado_en_cliente": _dt(fila.get("creado_en_cliente")),
                "confianza": _f(fila.get("confianza_biometrica")),
                "dentro_cliente": _b(fila.get("dentro_de_area")),
                "id_dispositivo_origen": _i(fila.get("id_dispositivo_origen")),
                "lat": _f(fila.get("latitud")),
                "lon": _f(fila.get("longitud")),
            }
        except (TypeError, ValueError) as e:
            raise ValueError(f"fila_invalida: {e}")
        if p["id_trabajador"] is None or p["id_puerta"] is None or p["creado_en_cliente"] is None:
            raise ValueError("campos_obligatorios_faltantes")
        return p

    # ── INTENTOS: directos a intentos_acceso (sin derivación) ──────────────────
    def ingerir_intentos(self, db: Session, contenido: str, principal: Principal) -> IngestaResponse:
        lector = csv.DictReader(io.StringIO(contenido))
        insertados = duplicados = recibidos = 0
        rechazados: list[FilaRechazada] = []
        for i, fila in enumerate(lector, start=2):
            recibidos += 1
            if recibidos > settings.INGESTA_MAX_FILAS:
                rechazados.append(FilaRechazada(linea=i, id=fila.get("id_intento"), motivo="limite_filas_excedido"))
                break
            try:
                params = self._parse_intento(fila, principal)
            except ValueError as e:
                rechazados.append(FilaRechazada(linea=i, id=fila.get("id_intento"), motivo=str(e)))
                continue
            try:
                with db.begin_nested():
                    r = db.execute(_SQL_INTENTO, params).first()
                if r:
                    insertados += 1
                else:
                    duplicados += 1
            except Exception as exc:
                logger.warning("Ingesta intento línea %d rechazada: %s", i, exc)
                rechazados.append(FilaRechazada(linea=i, id=str(params.get("id_intento")), motivo=_motivo(exc)))
        db.commit()
        return IngestaResponse(recibidos=recibidos, insertados=insertados,
                               duplicados=duplicados, rechazados=rechazados)

    def _empresa_ok(self, id_empresa, principal: Principal) -> None:
        if id_empresa is None:
            raise ValueError("id_empresa_requerido")
        if not es_admin(principal) and id_empresa != principal.empresa:
            raise ValueError("empresa_no_permitida")

    def _parse_intento(self, fila: dict, principal: Principal) -> dict:
        id_emp = _i(fila.get("id_empresa"))
        self._empresa_ok(id_emp, principal)
        tipo = (fila.get("tipo") or "").strip().lower()
        if tipo not in TIPOS_INTENTO:
            raise ValueError("tipo_intento_invalido")
        try:
            p = {
                "id_intento": _uuid(fila.get("id_intento")),
                "id_puerta": _i(fila.get("id_puerta")),
                "id_empresa": id_emp,
                "tipo": tipo,
                "id_trabajador": _i(fila.get("id_trabajador")),  # solo en 'otra_empresa'
                "similitud": _f(fila.get("similitud")),
                "creado_en_cliente": _dt(fila.get("creado_en_cliente")),
                "id_dispositivo_origen": _i(fila.get("id_dispositivo_origen")),
                "lat": _f(fila.get("latitud")),
                "lon": _f(fila.get("longitud")),
            }
        except (TypeError, ValueError) as e:
            raise ValueError(f"fila_invalida: {e}")
        if p["id_puerta"] is None:
            raise ValueError("campos_obligatorios_faltantes")
        return p


ingesta_service = IngestaService()
