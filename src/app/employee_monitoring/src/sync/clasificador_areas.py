# employee_monitoring/sync/clasificador_areas.py
"""
Clasificación de empleados → área local + permiso, según su departamento/puesto.

Modelo: cada empresa tiene 3 áreas locales (area_trabajo) marcadas con
`tipo_area` ∈ {'oficina', 'empaque', 'campo'}. Cada departamento (COM) o puesto
(agrícola) de la nómina se mapea a uno de esos 3 grupos; de ahí salen el área
local (por (id_empresa, tipo_area)), el permiso_escaneo y el nivel_acceso_interno.

Estado:
  - COM (agricola_com): mapeo por DEPARTAMENTO (columna AREA, texto) → GRUPO_POR_DEPARTAMENTO_COM.
  - Agrícola (agricola): por PUESTO (ViewBI_Puestos) → GRUPO_POR_PUESTO_AGRICOLA.
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
    "emapque": "empaque",                 # typo de 'empaque' visto en SYS21
    # Variantes vistas en SYS21 (area_invalida):
    "mango": "campo",                     # (dict tenía 'huerta de mango')
    "todo santos fijos": "campo",         # (dict tenía 'todos santos')
    "gasolina fija caco": "oficina",      # (dict tenía 'gasolina fija')
    "cat malacon": "oficina",             # provisional: en administración por el momento
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
    "auxiliar compras": "oficina",
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
    "sanquero": "campo",
    # Variantes/typos vistos en SYS21 (area_invalida): normalizados a mano.
    "supervisor campo viva organica": "campo",
    "spervisor corte-chile": "campo",     # typo en la fuente (falta la 'U')
    "caco- velador": "campo",             # variante con espacio de 'caco-velador'
    "fuguero agropotato": "campo",
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


class ClasificacionAreas:
    """
    Índice de áreas locales por (id_empresa, tipo_area) + empresas locales activas.

    Si un empleado tiene regla pero su empresa no tiene el área de ese tipo, la crea
    (INSERT en area_trabajo, dentro de la transacción del sync). Construir UNA por
    origen: si el origen hace rollback, las áreas creadas se descartan con él.
    """

    def __init__(self, db: Session, areas: dict[tuple[int, str], _AreaLocal],
                 empresas: dict[int, str]) -> None:
        self._db = db
        self._idx = areas
        self._empresas = empresas
        self._no_disponibles: set[tuple[int, str]] = set()
        self.areas_creadas: list[str] = []

    @classmethod
    def construir(cls, db: Session) -> "ClasificacionAreas":
        """Carga las áreas ACTIVAS con tipo_area y las empresas ACTIVAS (menos la admin)."""
        areas = (
            db.query(AreaTrabajo)
            .filter(AreaTrabajo.estado == "activo", AreaTrabajo.tipo_area.isnot(None))
            .all()
        )
        idx = {(a.id_empresa, _normalizar(a.tipo_area)): _AreaLocal(a.id_area, a.id_empresa)
               for a in areas}
        empresas = {
            f.id_empresa: f.nombre_empresa
            for f in db.execute(text(
                "SELECT id_empresa, nombre_empresa FROM empresas WHERE estado = 'activo'"
            ))
            if f.id_empresa != settings.EMPRESA_ADMIN
        }
        logger.info("Clasificador: %d áreas locales (empresa, tipo) y %d empresas.",
                    len(idx), len(empresas))
        return cls(db, idx, empresas)

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
        mapa = _MAPA_GRUPO_POR_ORIGEN.get(origen, {})
        clave = _normalizar(area_nombre)
        grupo = mapa.get(clave)
        if grupo is None:
            return None, MOTIVO_SIN_REGLA

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
        override = _OVERRIDE_POR_ORIGEN.get(origen, {}).get(clave, {})
        permiso = override.get("permiso_escaneo", permiso)
        nivel = override.get("nivel_acceso_interno", nivel)

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
                    or _normalizar(existente.tipo_area) != grupo:
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
