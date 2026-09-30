# employee_monitoring/sync/mapping.py
"""
ÚNICO lugar donde una fila CRUDA de la nómina SYS21 se transforma en un trabajador
local. Combina la fila (sys21_reader) con la clasificación de área
(clasificador_areas) para derivar empresa/área/permiso. Cualquier regla de negocio
de normalización vive aquí.
"""
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass

from src.sync.clasificador_areas import ClasificacionAreas

logger = logging.getLogger(__name__)

# ── Normalización de nombres / prioridad de origen (dedup de homónimos) ────────
# Sufijos romanos que marcan la re-alta de una misma persona en la nómina
# ("JUAN PEREZ", "JUAN PEREZ II"...). Se ignoran al comparar nombres. (Solo I..V.)
_ROMANOS = {"I", "II", "III", "IV", "V"}

# Prioridad de origen al resolver homónimos entre nóminas: la comercial
# (agricola_com) manda sobre la agrícola. Menor número = se CONSERVA.
ORIGEN_PRIORIDAD = {"agricola_com": 0, "agricola": 1}


def _tokens_nombre(nombre: str | None, apellido: str | None) -> list[str]:
    """Nombre+apellido → tokens EN MAYÚSCULAS, sin acentos ni signos (para comparar)."""
    completo = f"{nombre or ''} {apellido or ''}"
    completo = unicodedata.normalize("NFKD", completo)
    completo = "".join(c for c in completo if not unicodedata.combining(c))
    return re.findall(r"[A-Z]+", completo.upper())


def tiene_sufijo_romano(nombre: str | None, apellido: str | None) -> bool:
    """True si el nombre termina en un numeral romano I..V (marca de duplicado)."""
    tokens = _tokens_nombre(nombre, apellido)
    return bool(tokens) and tokens[-1] in _ROMANOS


def clave_nombre(nombre: str | None, apellido: str | None) -> str:
    """Nombre normalizado (sin acentos, en mayúsculas, sin el sufijo romano) para
    detectar homónimos entre nóminas. Cadena vacía si no hay nombre."""
    tokens = _tokens_nombre(nombre, apellido)
    while tokens and tokens[-1] in _ROMANOS:
        tokens.pop()
    return " ".join(tokens)


def origenes_de_mayor_prioridad(origen: str) -> list[str]:
    """Orígenes que ganan sobre `origen` al resolver homónimos (comercial > agrícola)."""
    mia = ORIGEN_PRIORIDAD.get(origen, 99)
    return [o for o, p in ORIGEN_PRIORIDAD.items() if p < mia]


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
        (mapeado, None) si se pudo mapear; (None, motivo) si no (ej. 'area_invalida',
        'empresa_no_registrada', 'area_no_disponible').
    """
    area, motivo = clasificacion.clasificar(
        fila["_origen"], fila.get("area_codigo"), fila.get("area_nombre"), fila.get("empresa_origen")
    )
    if area is None or area.id_area is None:
        return None, motivo or "area_invalida"

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
