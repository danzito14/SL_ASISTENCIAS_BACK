# employee_monitoring/sync/mapping.py
"""
ÚNICO lugar donde una fila CRUDA de la nómina SYS21 se transforma en un trabajador
local. Combina la fila (sys21_reader) con la clasificación de área
(clasificador_areas) para derivar empresa/área/permiso. Cualquier regla de negocio
de normalización vive aquí.
"""
import logging
from dataclasses import asdict, dataclass

from src.sync.clasificador_areas import ClasificacionAreas

logger = logging.getLogger(__name__)


@dataclass
class TrabajadorMapeado:
    id_emp: str
    origen_nomina: str
    nombre: str
    apellido: str
    id_area: int
    id_empresa: int | None
    permiso_escaneo: str
    nivel_acceso_interno: str | None
    estado: str

    def as_trabajador_dict(self) -> dict:
        """Dict listo para el upsert de trabajadores (claves = columnas de la tabla)."""
        return asdict(self)


def _combinar_apellidos(paterno: str | None, materno: str | None) -> str:
    return " ".join(p.strip() for p in (paterno, materno) if p and p.strip())


def mapear_fila(
    fila: dict,
    clasificacion: ClasificacionAreas,
) -> tuple[TrabajadorMapeado | None, str | None]:
    """
    Transforma una fila canónica (sys21_reader) en un TrabajadorMapeado.

    Returns:
        (mapeado, None) si se pudo mapear; (None, motivo) si no (ej. 'area_invalida').
    """
    area = clasificacion.clasificar(
        fila["_origen"], fila.get("area_codigo"), fila.get("area_nombre"), fila.get("empresa_origen")
    )
    if area is None or area.id_area is None:
        return None, "area_invalida"

    # Regla del repo: los de 'campo' NO tienen acceso a zonas internas → nivel NULL.
    permiso = area.permiso_escaneo
    nivel = None if permiso == "campo" else area.nivel_acceso_interno

    # El reader ya filtra a ACTIVOS en el WHERE; los que desaparecen del resultado
    # se inactivan en la fase de 'desaparecidos'. Por eso todo lo mapeado es activo.
    mapeado = TrabajadorMapeado(
        id_emp=str(fila["id_emp"]).strip(),
        origen_nomina=fila["_origen"],
        nombre=(fila.get("nombre") or "").strip(),
        apellido=_combinar_apellidos(fila.get("apellido_paterno"), fila.get("apellido_materno")),
        id_area=area.id_area,
        id_empresa=area.id_empresa,
        permiso_escaneo=permiso,
        nivel_acceso_interno=nivel,
        estado="activo",
    )
    return mapeado, None
