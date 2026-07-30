# offline_sync/services/Roster_Service.py
"""
Construye el roster que el APK baja para reconocer OFFLINE.

REGLA DEL ROSTER (acotada por empresa del usuario kiosko + 'tipo' del dispositivo):
  - Trabajadores activos de la empresa cuya ÁREA asignada es del `tipo`
    (area_trabajo.tipo_area), CON embedding activo (sin él no se puede reconocer).
  - MÁS permiso_escaneo='super' (los pocos admins que fichan en cualquier lado).
  - Si ROSTER_INCLUIR_GENERAL=true, MÁS permiso_escaneo='general' (a futuro, cuando
    se afinen los permisos por área). Hoy default False = OPCIÓN A (estricto).

Devuelve también las áreas del tipo (con su polígono GeoJSON para que el APK
precalcule dentro_de_area) y las puertas de fichaje de ese tipo.
"""
import hashlib
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.config import settings
from src.schemas.Candidatos_Schema import CandidatosResponse, CandidatoTrabajador
from src.schemas.Roster_Schema import (RosterArea, RosterDispositivo, RosterPuerta,
                                       RosterResponse, RosterTrabajador)

logger = logging.getLogger(__name__)

_SQL_TRABAJADORES = text("""
    SELECT t.id_trabajador, t.id_emp, t.origen_nomina, t.nombre, t.apellido,
           t.permiso_escaneo, t.id_area,
           e.vector_embedding::text AS emb, e.calidad_embedding, e.modelo_ia,
           GREATEST(t.fecha_actualizacion, e.fecha_captura) AS actualizado
    FROM trabajadores t
    JOIN area_trabajo a ON a.id_area = t.id_area
    JOIN embeddings   e ON e.id_trabajador = t.id_trabajador AND e.estado = 'activo'
    WHERE t.id_empresa = :empresa
      AND t.estado = 'activo'
      AND ( a.tipo_area = ANY(:tipos)
            OR t.permiso_escaneo = 'super'
            OR (CAST(:incluir_general AS boolean) AND t.permiso_escaneo = 'general') )
    ORDER BY t.id_trabajador
""")

_SQL_AREAS = text("""
    SELECT id_area, nombre_area, tipo_area, ST_AsGeoJSON(ubicacion) AS poligono
    FROM area_trabajo
    WHERE id_empresa = :empresa AND tipo_area = ANY(:tipos) AND estado = 'activo'
    ORDER BY id_area
""")

_SQL_PUERTAS = text("""
    SELECT p.id_puerta, p.nombre_puerta, p.tipo_puerta, p.id_area
    FROM puertas_acceso p
    JOIN area_trabajo a ON a.id_area = p.id_area
    WHERE p.id_empresa = :empresa AND p.funcion_puerta = 'asistencia'
      AND a.tipo_area = ANY(:tipos) AND p.estado = 'activo'
    ORDER BY p.id_puerta
""")

# Dispositivos (terminales/estaciones) de la empresa. LEFT JOIN + 'id_area IS NULL' a
# propósito: una PC de kiosko suele no estar atada a un área concreta, y si se filtrara
# solo por tipo de área se quedaría fuera justo la que ficha. Sin este catálogo en local,
# el escaneo con id_dispositivo fallaba por la FK.
_SQL_DISPOSITIVOS = text("""
    SELECT d.id_dispositivo, d.nombre_dispositivo, d.tipo_dispositivo::text AS tipo_dispositivo,
           d.id_area
    FROM dispositivos d
    LEFT JOIN area_trabajo a ON a.id_area = d.id_area
    WHERE d.id_empresa = :empresa AND d.estado = 'activo'
      AND (d.id_area IS NULL OR a.tipo_area = ANY(:tipos))
    ORDER BY d.id_dispositivo
""")

# Trabajadores activos SIN rostro (sin embedding activo): candidatos a enrolar.
# Scopeado por empresa y, si se indica, por tipo de área (campo/oficina/empaque).
_SQL_CANDIDATOS = text("""
    SELECT t.id_trabajador, t.nombre, t.apellido, t.id_area, a.tipo_area,
           t.permiso_escaneo, t.id_emp, t.origen_nomina
    FROM trabajadores t
    JOIN area_trabajo a ON a.id_area = t.id_area
    LEFT JOIN embeddings e ON e.id_trabajador = t.id_trabajador AND e.estado = 'activo'
    WHERE t.id_empresa = :empresa
      AND t.estado = 'activo'
      AND e.id_embedding IS NULL
      AND (:tipo IS NULL OR a.tipo_area = :tipo)
      AND (:nombre IS NULL OR t.nombre ILIKE :patron OR t.apellido ILIKE :patron)
    ORDER BY t.nombre, t.apellido
    LIMIT :limite
""")


def _parse_vec(s: str | None) -> list[float]:
    """'[0.1,0.2,...]' (pgvector::text) → list[float]."""
    if not s:
        return []
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    if not s:
        return []
    return [float(x) for x in s.split(",")]


class RosterService:

    def construir_roster(self, db: Session, empresa: int, tipo: str) -> RosterResponse:
        # 'mixto' baja oficina + empaque juntos (lugares con entrada compartida).
        tipos = ["oficina", "empaque"] if tipo == "mixto" else [tipo]
        params = {"empresa": empresa, "tipos": tipos,
                  "incluir_general": settings.ROSTER_INCLUIR_GENERAL}

        filas = db.execute(_SQL_TRABAJADORES, params).all()
        trabajadores = [
            RosterTrabajador(
                id_trabajador=f.id_trabajador, id_emp=f.id_emp, origen_nomina=f.origen_nomina,
                nombre=f.nombre, apellido=f.apellido,
                permiso_escaneo=f.permiso_escaneo, id_area=f.id_area,
                embedding=_parse_vec(f.emb),
                calidad=float(f.calidad_embedding) if f.calidad_embedding is not None else None,
                modelo_ia=f.modelo_ia,
            )
            for f in filas
        ]

        areas = [
            RosterArea(id_area=a.id_area, nombre_area=a.nombre_area,
                       tipo_area=a.tipo_area, poligono_geojson=a.poligono)
            for a in db.execute(_SQL_AREAS, {"empresa": empresa, "tipos": tipos}).all()
        ]
        puertas = [
            RosterPuerta(id_puerta=p.id_puerta, nombre_puerta=p.nombre_puerta,
                         tipo_puerta=p.tipo_puerta, id_area=p.id_area)
            for p in db.execute(_SQL_PUERTAS, {"empresa": empresa, "tipos": tipos}).all()
        ]

        dispositivos = [
            RosterDispositivo(id_dispositivo=d.id_dispositivo,
                              nombre_dispositivo=d.nombre_dispositivo,
                              tipo_dispositivo=d.tipo_dispositivo, id_area=d.id_area)
            for d in db.execute(_SQL_DISPOSITIVOS, {"empresa": empresa, "tipos": tipos}).all()
        ]

        version = self._version(empresa, tipo, filas)
        logger.info("Roster empresa=%s tipo=%s → %d trabajadores, %d áreas, %d puertas, "
                    "%d dispositivos (v=%s).",
                    empresa, tipo, len(trabajadores), len(areas), len(puertas),
                    len(dispositivos), version)
        return RosterResponse(
            empresa=empresa, tipo=tipo, roster_version=version,
            total_trabajadores=len(trabajadores), trabajadores=trabajadores,
            areas=areas, puertas=puertas, dispositivos=dispositivos,
        )

    def _version(self, empresa: int, tipo: str, filas) -> str:
        """Huella estable del roster: (#trabajadores, máxima fecha de cambio)."""
        n = len(filas)
        maxts = max((f.actualizado for f in filas if f.actualizado is not None), default=None)
        base = f"{empresa}:{tipo}:{n}:{maxts.isoformat() if maxts else '0'}"
        return hashlib.sha256(base.encode()).hexdigest()[:16]

    def listar_candidatos(self, db: Session, empresa: int, tipo: str | None = None,
                          nombre: str | None = None, limite: int = 200) -> CandidatosResponse:
        """Trabajadores activos SIN rostro (para que el operador elija a quién enrolar)."""
        filas = db.execute(_SQL_CANDIDATOS, {
            "empresa": empresa, "tipo": tipo, "nombre": nombre,
            "patron": f"%{nombre}%" if nombre else None, "limite": limite,
        }).all()
        candidatos = [
            CandidatoTrabajador(
                id_trabajador=f.id_trabajador, nombre=f.nombre, apellido=f.apellido,
                id_area=f.id_area, tipo_area=f.tipo_area, permiso_escaneo=f.permiso_escaneo,
                id_emp=f.id_emp, origen_nomina=f.origen_nomina,
            )
            for f in filas
        ]
        return CandidatosResponse(empresa=empresa, tipo=tipo, total=len(candidatos),
                                  candidatos=candidatos)


roster_service = RosterService()
