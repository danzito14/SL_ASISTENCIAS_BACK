# offline_sync/services/Ingesta_Service.py
"""
Ingesta por lotes (CSV) de lo que el APK capturó offline: asistencias e intentos
rechazados. IDEMPOTENTE: la PK es un UUIDv7 generado en el dispositivo, así que
re-subir el mismo CSV NO duplica (INSERT ... ON CONFLICT (id) DO NOTHING).

dentro_de_area: el APK lo precalcula; aquí se RE-AUDITA con PostGIS (ST_Covers del
punto contra el polígono del área de la puerta) y se guarda el valor auditado;
si no hay punto o el área no tiene polígono, se conserva el del cliente.

Cada fila va en su propio SAVEPOINT: una fila inválida (FK, enum, etc.) se rechaza
y reporta sin abortar el resto del lote.
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

_SQL_ASISTENCIA = text("""
    INSERT INTO asistencia (
        id_asistencia, id_trabajador, id_puerta, id_empresa, tipo_registro,
        fecha_hora, confianza_biometrica, estado_registro, dentro_de_area,
        id_dispositivo_origen, ubicacion, creado_en_cliente, sincronizado_en
    ) VALUES (
        :id_asistencia, :id_trabajador, :id_puerta, :id_empresa, CAST(:tipo_registro AS tipo_registro),
        :creado_en_cliente, :confianza, 'exitoso',
        CASE WHEN :lon IS NULL OR :lat IS NULL THEN :dentro_cliente
             ELSE COALESCE((
                    SELECT ST_Covers(a.ubicacion, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
                    FROM puertas_acceso p JOIN area_trabajo a ON a.id_area = p.id_area
                    WHERE p.id_puerta = :id_puerta AND a.ubicacion IS NOT NULL
                  ), :dentro_cliente)
        END,
        :id_dispositivo_origen,
        CASE WHEN :lon IS NULL OR :lat IS NULL THEN NULL
             ELSE ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography END,
        :creado_en_cliente, NOW()
    )
    ON CONFLICT (id_asistencia) DO NOTHING
    RETURNING id_asistencia
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


class IngestaService:

    def ingerir_asistencias(self, db: Session, contenido: str, principal: Principal) -> IngestaResponse:
        return self._ingerir(db, contenido, principal, self._parse_asistencia, _SQL_ASISTENCIA)

    def ingerir_intentos(self, db: Session, contenido: str, principal: Principal) -> IngestaResponse:
        return self._ingerir(db, contenido, principal, self._parse_intento, _SQL_INTENTO)

    def _ingerir(self, db, contenido, principal, parser, sql) -> IngestaResponse:
        lector = csv.DictReader(io.StringIO(contenido))
        insertados = duplicados = recibidos = 0
        rechazados: list[FilaRechazada] = []
        for i, fila in enumerate(lector, start=2):  # línea 1 = encabezado
            recibidos += 1
            if recibidos > settings.INGESTA_MAX_FILAS:
                rechazados.append(FilaRechazada(linea=i, motivo="limite_filas_excedido"))
                break
            try:
                params = parser(fila, principal)
            except ValueError as e:
                rechazados.append(FilaRechazada(linea=i, motivo=str(e)))
                continue
            try:
                with db.begin_nested():
                    r = db.execute(sql, params).first()
                if r:
                    insertados += 1
                else:
                    duplicados += 1
            except Exception as exc:
                logger.warning("Ingesta línea %d rechazada: %s", i, exc)
                rechazados.append(FilaRechazada(linea=i, motivo=_motivo(exc)))
        db.commit()
        return IngestaResponse(recibidos=recibidos, insertados=insertados,
                               duplicados=duplicados, rechazados=rechazados)

    def _empresa_ok(self, id_empresa, principal: Principal) -> None:
        if id_empresa is None:
            raise ValueError("id_empresa_requerido")
        if not es_admin(principal) and id_empresa != principal.empresa:
            raise ValueError("empresa_no_permitida")

    def _parse_asistencia(self, fila: dict, principal: Principal) -> dict:
        id_emp = _i(fila.get("id_empresa"))
        self._empresa_ok(id_emp, principal)
        tipo = (fila.get("tipo_registro") or "").strip().lower()
        if tipo not in TIPOS_REGISTRO:
            raise ValueError("tipo_registro_invalido")
        try:
            p = {
                "id_asistencia": _uuid(fila.get("id_asistencia")),
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
