# employee_monitoring/sync/clasificador_areas.py
"""
Clasificación de empleados → área local + permiso, según su departamento/puesto.

Modelo: cada empresa tiene 3 áreas locales (area_trabajo) marcadas con
`tipo_area` ∈ {'oficina', 'empaque', 'campo'}. Cada departamento (COM) o puesto
(agrícola) de la nómina se mapea a uno de esos 3 grupos; de ahí salen el área
local (por (id_empresa, tipo_area)), el permiso_escaneo y el nivel_acceso_interno.

Estado:
  - COM (agricola_com): mapeo por DEPARTAMENTO (columna AREA, texto) → GRUPO_POR_DEPARTAMENTO_COM.
  - Agrícola (agricola): por PUESTO (ViewBI_Puestos) → GRUPO_POR_PUESTO_AGRICOLA (TODO, pendiente del usuario).
  - empresa_origen de la nómina = id_empresa local (mismo número).
"""
import logging
import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo

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

# ── COM: departamento (AREA, texto) → grupo. Claves NORMALIZADAS (sin acentos). ─
GRUPO_POR_DEPARTAMENTO_COM: dict[str, str] = {
    # oficina
    "administracion": "oficina",
    "compras": "oficina",
    "rrhh y nominas": "oficina",
    "sistemas": "oficina",
    "administracion sl": "oficina",
    "servicios administrativos sl": "oficina",
    "ventas": "oficina",
    "gasolina fija": "oficina",
    "practicantes": "oficina",
    "gasolina": "oficina",
    "administracion alpine": "oficina",
    "logistica": "oficina",
    "inocuidad": "oficina",
    "seguridad e intendencia": "oficina",
    "mantenimiento y equipo de transporte": "oficina",
    # campo
    "campo abierto": "campo",
    "campo protegido": "campo",
    "campo": "campo",
    "fijos caco sinaloa": "campo",
    "fijos caco jalisco": "campo",
    "fijos produce": "campo",
    "huerta de mango": "campo",
    "todos santos": "campo",
    # empaque
    "almacen": "empaque",
    "empaque ejote": "empaque",
    "albergues": "empaque",
    "empaque chile": "empaque",
    "empaque": "empaque",
    "fijos no fijos planta sl": "empaque",
    "fijo empacadora": "empaque",
}

# Overrides puntuales por departamento (sobre el default del grupo). Clave NORMALIZADA.
OVERRIDE_POR_DEPARTAMENTO_COM: dict[str, dict] = {
    # 'Fijos no fijos planta SL' es empaque pero con acceso interno MIXTO.
    "fijos no fijos planta sl": {"nivel_acceso_interno": "mixto"},
    # TODO (afinar): "administradores" → permiso 'super' por default. Falta definir
    # qué departamentos/puestos cuentan como administradores (hoy oficina = 'general').
}

# ── Agrícola: PUESTO (ViewBI_Puestos.nombre) → grupo. Claves NORMALIZADAS. ──────
GRUPO_POR_PUESTO_AGRICOLA: dict[str, str] = {
    # oficina (administrativo)
    "administrativo": "oficina",
    "auxiliar administrativo": "oficina",
    "administracion": "oficina",
    "auxiliar-sistemas": "oficina",
    "auxiliar nominas": "oficina",
    "aux. de nomina": "oficina",
    "aux contable": "oficina",
    "auxiliar imss (prefiliar)": "oficina",
    "seguridad y salud": "oficina",
    "trabajadora social": "oficina",
    "trabajador social aux": "oficina",
    "mensajero": "oficina",
    "asesora educativa": "oficina",
    "practicante": "oficina",
    "monitoreo": "oficina",
    "aux inocuidad": "oficina",
    # empaque
    "empaque": "empaque",
    "almacen empaque": "empaque",
    "montacarguista almacen": "empaque",
    "guardia empaque": "empaque",
    "escaneador": "empaque",
    # Ambiguo (lo dejó el usuario en empaque): si su función es revisar producto
    # ANTES de empaque → empaque; si no, debería ir en campo.
    "revisador caco campo": "empaque",
    "vaciadores": "empaque",
    # campo
    "jornalero": "campo",
    "cuadrillero": "campo",
    "chofer": "campo",
    "mantenimiento": "campo",
    "produccion": "campo",
    "operador": "campo",
    "mayordomo": "campo",
    "apuntador": "campo",
    "campero": "campo",
    "malleros": "campo",
    "ninera": "campo",
    "cocinera": "campo",
    "portero": "campo",
    "campo": "campo",
    "auxiliar de corte": "campo",
    "supervisor corte-chile": "campo",
    "jardinero": "campo",
    "mantenimiento albergue": "campo",
    "mantenimiento electrico": "campo",
    "supervisor campo natoches": "campo",
    "guardia": "campo",
    "aux. mantenimiento": "campo",
    "enc de motor de riego carcamo": "campo",
    "carcamo riego": "campo",
    "caco-velador": "campo",
    "fuguero caco campo": "campo",
    "canalero": "campo",
    "enc. de sistemas de riego": "campo",
    "aplicador de herbicida": "campo",
    "aux. de riego": "campo",
    "monitoreo caco campo": "campo",
    "aplicador de fungicida": "campo",
}
OVERRIDE_POR_PUESTO_AGRICOLA: dict[str, dict] = {}

# Mapa de reglas por origen.
_MAPA_GRUPO_POR_ORIGEN = {
    "agricola_com": GRUPO_POR_DEPARTAMENTO_COM,
    "agricola": GRUPO_POR_PUESTO_AGRICOLA,
}
_OVERRIDE_POR_ORIGEN = {
    "agricola_com": OVERRIDE_POR_DEPARTAMENTO_COM,
    "agricola": OVERRIDE_POR_PUESTO_AGRICOLA,
}


def _normalizar(texto: str | None) -> str:
    """Minúsculas, sin acentos, espacios colapsados (para empatar nombres robustos)."""
    if not texto:
        return ""
    desc = unicodedata.normalize("NFKD", str(texto))
    sin_acentos = "".join(c for c in desc if not unicodedata.combining(c))
    return " ".join(sin_acentos.strip().lower().split())


class ClasificacionAreas:
    """Índice de áreas locales por (id_empresa, tipo_area). Inmutable en la corrida."""

    def __init__(self, areas_por_empresa_tipo: dict[tuple[int, str], AreaTrabajo]) -> None:
        self._idx = areas_por_empresa_tipo

    @classmethod
    def construir(cls, db: Session) -> "ClasificacionAreas":
        """Carga las áreas locales ACTIVAS con tipo_area definido y las indexa."""
        areas = (
            db.query(AreaTrabajo)
            .filter(AreaTrabajo.estado == "activo", AreaTrabajo.tipo_area.isnot(None))
            .all()
        )
        idx: dict[tuple[int, str], AreaTrabajo] = {}
        for a in areas:
            idx[(a.id_empresa, _normalizar(a.tipo_area))] = a
        logger.info("Clasificador: %d áreas locales (empresa, tipo) indexadas.", len(idx))
        return cls(idx)

    def clasificar(
        self,
        origen: str,
        area_codigo: str | None,
        area_nombre: str | None,
        empresa_origen,
    ) -> AreaClasificada | None:
        """
        Resuelve el área local + permiso. Devuelve None si no hay regla para el
        departamento/puesto, si falta la empresa, o si la empresa no tiene esa área
        local (→ el orquestador lo marca como 'area_invalida').
        """
        mapa = _MAPA_GRUPO_POR_ORIGEN.get(origen, {})
        clave = _normalizar(area_nombre)
        grupo = mapa.get(clave)
        if grupo is None:
            return None

        try:
            id_empresa = int(empresa_origen)
        except (TypeError, ValueError):
            return None

        area_local = self._idx.get((id_empresa, grupo))
        if area_local is None:
            return None

        permiso, nivel = PERMISO_POR_GRUPO[grupo]
        override = _OVERRIDE_POR_ORIGEN.get(origen, {}).get(clave, {})
        permiso = override.get("permiso_escaneo", permiso)
        nivel = override.get("nivel_acceso_interno", nivel)

        return AreaClasificada(
            id_area=area_local.id_area,
            id_empresa=area_local.id_empresa,
            permiso_escaneo=permiso,
            nivel_acceso_interno=nivel,
        )
