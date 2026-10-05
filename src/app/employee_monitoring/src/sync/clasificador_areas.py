# employee_monitoring/sync/clasificador_areas.py
"""
Clasificación de empleados → área local + permiso, según su departamento/puesto.

Modelo: cada empresa tiene 3 áreas locales (area_trabajo) marcadas con
`tipo_area` ∈ {'oficina', 'empaque', 'campo'}. Cada departamento (COM) o puesto
(agrícola) de la nómina se mapea a uno de esos 3 grupos; de ahí salen el área
local (por (id_empresa, tipo_area)), el permiso_escaneo y el nivel_acceso_interno.

Reglas: tabla `reglas_clasificacion` (se administran por API en /emp_sync/reglas y
se releen en cada corrida). Por origen:
  - COM (agricola_com): por DEPARTAMENTO (columna AREA, texto).
  - Agrícola (agricola): por PUESTO (ViewBI_Puestos).
Cada regla puede reemplazar el permiso_escaneo / nivel_acceso_interno del grupo.
  - empresa_origen de la nómina = id_empresa local (mismo número).
  - Si la empresa existe pero no tiene el área de ese tipo, se CREA (ver _crear_area).
    Si la empresa no existe en local, el empleado se rechaza (empresa_no_registrada).
"""
import logging
import unicodedata
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo
from src.models.ReglaClasificacion_Model import ReglaClasificacion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AreaClasificada:
    id_area: int | None
    id_empresa: int | None
    permiso_escaneo: str            # 'campo' | 'administrativo' | 'general' | 'super'
    nivel_acceso_interno: str | None  # 'oficina' | 'empaque' | 'mixto' | None


# ── Permiso/nivel por grupo (área local) ──────────────────────────────────────
# (permiso_escaneo, nivel_acceso_interno). 'campo' fuerza nivel NULL (sin acceso interno).
PERMISO_POR_GRUPO: dict[str, tuple[str, str | None]] = {
    "oficina": ("general", "mixto"),
    "empaque": ("general", "empaque"),
    "campo":   ("campo", None),
}
GRUPOS = tuple(PERMISO_POR_GRUPO)


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin acentos, espacios colapsados (para empatar nombres robustos)."""
    if not texto:
        return ""
    desc = unicodedata.normalize("NFKD", str(texto))
    sin_acentos = "".join(c for c in desc if not unicodedata.combining(c))
    return " ".join(sin_acentos.strip().lower().split())


# ── Motivos de rechazo de la clasificación (van a fotos_pendientes.motivo) ─────
MOTIVO_SIN_REGLA = "area_invalida"                     # puesto/departamento sin regla
MOTIVO_EMPRESA_NO_REGISTRADA = "empresa_no_registrada"  # la empresa no existe/está inactiva en local
MOTIVO_AREA_NO_DISPONIBLE = "area_no_disponible"        # el área estándar existe pero inactiva/de otro tipo

# Áreas que el sync crea solo cuando la empresa no tiene la de ese tipo. Mismo
# patrón de nombres que las áreas dadas de alta a mano.
NOMBRE_AREA_POR_TIPO = {
    "campo":   "Campo {empresa}",
    "empaque": "Empaque {empresa}",
    "oficina": "Oficinas Administrativas de {empresa}",
}
HORA_ENTRADA_AREA_NUEVA = "08:30"


@dataclass(frozen=True)
class _AreaLocal:
    id_area: int
    id_empresa: int


@dataclass(frozen=True)
class _Regla:
    grupo: str
    permiso_escaneo: str | None       # None = default del grupo
    nivel_acceso_interno: str | None  # None = default del grupo


class ClasificacionAreas:
    """
    Índice de áreas locales por (id_empresa, tipo_area) + empresas locales activas.

    Si un empleado tiene regla pero su empresa no tiene el área de ese tipo, la crea
    (INSERT en area_trabajo, dentro de la transacción del sync). Construir UNA por
    origen: si el origen hace rollback, las áreas creadas se descartan con él.
    """

    def __init__(self, db: Session, areas: dict[tuple[int, str], _AreaLocal],
                 empresas: dict[int, str], reglas: dict[tuple[str, str], _Regla]) -> None:
        self._db = db
        self._idx = areas
        self._empresas = empresas
        self._reglas = reglas
        self._no_disponibles: set[tuple[int, str]] = set()
        self.areas_creadas: list[str] = []

    @classmethod
    def construir(cls, db: Session) -> "ClasificacionAreas":
        """Carga las reglas, las áreas ACTIVAS con tipo_area y las empresas ACTIVAS (menos la admin)."""
        reglas = {
            (r.origen_nomina, r.clave): _Regla(r.grupo, r.permiso_escaneo, r.nivel_acceso_interno)
            for r in db.query(ReglaClasificacion).all()
        }
        areas = (
            db.query(AreaTrabajo)
            .filter(AreaTrabajo.estado == "activo", AreaTrabajo.tipo_area.isnot(None))
            .all()
        )
        idx = {(a.id_empresa, normalizar(a.tipo_area)): _AreaLocal(a.id_area, a.id_empresa)
               for a in areas}
        empresas = {
            f.id_empresa: f.nombre_empresa
            for f in db.execute(text(
                "SELECT id_empresa, nombre_empresa FROM empresas WHERE estado = 'activo'"
            ))
            if f.id_empresa != settings.EMPRESA_ADMIN
        }
        logger.info("Clasificador: %d reglas, %d áreas locales (empresa, tipo) y %d empresas.",
                    len(reglas), len(idx), len(empresas))
        return cls(db, idx, empresas, reglas)

    def clasificar(
        self,
        origen: str,
        area_codigo: str | None,
        area_nombre: str | None,
        empresa_origen,
    ) -> tuple[AreaClasificada | None, str | None]:
        """
        Resuelve el área local + permiso. Devuelve (clasificada, None) o (None, motivo):
          - MOTIVO_SIN_REGLA:             el departamento/puesto no tiene regla.
          - MOTIVO_EMPRESA_NO_REGISTRADA: la empresa no existe (o está inactiva) en local.
          - MOTIVO_AREA_NO_DISPONIBLE:    faltaba el área y no se pudo crear.
        """
        regla = self._reglas.get((origen, normalizar(area_nombre)))
        if regla is None:
            return None, MOTIVO_SIN_REGLA
        grupo = regla.grupo

        try:
            id_empresa = int(empresa_origen)
        except (TypeError, ValueError):
            return None, MOTIVO_EMPRESA_NO_REGISTRADA
        if id_empresa not in self._empresas:
            return None, MOTIVO_EMPRESA_NO_REGISTRADA

        area_local = self._idx.get((id_empresa, grupo)) or self._crear_area(id_empresa, grupo)
        if area_local is None:
            return None, MOTIVO_AREA_NO_DISPONIBLE

        permiso, nivel = PERMISO_POR_GRUPO[grupo]
        permiso = regla.permiso_escaneo or permiso
        nivel = regla.nivel_acceso_interno or nivel

        return AreaClasificada(
            id_area=area_local.id_area,
            id_empresa=area_local.id_empresa,
            permiso_escaneo=permiso,
            nivel_acceso_interno=nivel,
        ), None

    def _crear_area(self, id_empresa: int, grupo: str) -> _AreaLocal | None:
        """
        Crea el área estándar (empresa, tipo). ON CONFLICT sobre (id_empresa,
        nombre_area) evita duplicarla si otro sync la creó a la vez. Si ya existía
        con ese nombre pero inactiva o de otro tipo, NO se toca (la administra
        tenancy) y se devuelve None.
        """
        if (id_empresa, grupo) in self._no_disponibles:
            return None
        nombre = NOMBRE_AREA_POR_TIPO[grupo].format(empresa=self._empresas[id_empresa])[:100]
        id_area = self._db.execute(text("""
            INSERT INTO area_trabajo (nombre_area, id_empresa, tipo_area, hora_entrada)
            VALUES (:nombre, :id_empresa, :tipo, CAST(:hora AS TIME))
            ON CONFLICT (id_empresa, nombre_area) DO NOTHING
            RETURNING id_area
        """), {"nombre": nombre, "id_empresa": id_empresa, "tipo": grupo,
               "hora": HORA_ENTRADA_AREA_NUEVA}).scalar()

        if id_area is None:
            existente = self._db.execute(text("""
                SELECT id_area, tipo_area, estado FROM area_trabajo
                WHERE id_empresa = :id_empresa AND nombre_area = :nombre
            """), {"id_empresa": id_empresa, "nombre": nombre}).first()
            if existente is None or existente.estado != "activo" \
                    or normalizar(existente.tipo_area) != grupo:
                logger.warning("Clasificador: no se pudo usar/crear el área '%s' (empresa %s).",
                               nombre, id_empresa)
                self._no_disponibles.add((id_empresa, grupo))
                return None
            id_area = existente.id_area
        else:
            self.areas_creadas.append(f"{id_empresa}: {nombre}")
            logger.info("Clasificador: área creada '%s' (empresa %s, id_area %s).",
                        nombre, id_empresa, id_area)

        area = _AreaLocal(id_area, id_empresa)
        self._idx[(id_empresa, grupo)] = area
        return area
