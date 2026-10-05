# employee_monitoring/sources/sys21_reader.py
"""
Lectura de empleados ACTIVOS desde la nómina SYS21 (MSSQL), solo lectura y por
streaming. Cada origen tiene su propia vista, nombres de columna y filtros, así que
hay una consulta por origen en CONSULTAS, cada una aliaseada al conjunto CANÓNICO
de abajo para que mapping.py reciba siempre las mismas claves.

Orígenes:
  - 'agricola'      → ASL_Nomina.dbo.ViewBI_Empleados (+ JOIN ViewBI_Puestos)
                      filtro: inactivo = 0 y SIN fantasmas (trabajó en ViewBI en
                      las últimas SYNC_FANTASMA_SEMANAS, o fecha_ingreso dentro de
                      los últimos SYNC_NUEVO_INGRESO_DIAS)
  - 'agricola_com'  → ASL_Nomina_COM.dbo.ViewBI_Com_Empleados
                      filtro: estatus = 1   (activos; en COM no hay filtro de fantasmas)

Como ambas consultas filtran a ACTIVOS en el WHERE, toda fila devuelta es vigente;
los que desaparecen del resultado se inactivan por la fase de 'desaparecidos'.
"""
import logging
from collections.abc import Iterator

from sqlalchemy import text

from src.core.config import settings
from src.sources.sys21_engines import get_engine

logger = logging.getLogger(__name__)

# Conjunto CANÓNICO que cada consulta debe producir (vía alias):
#   id_emp           identificador del empleado en la nómina (clave de negocio)
#   nombre           nombre(s)
#   apellido_paterno apellido paterno
#   apellido_materno apellido materno (puede venir NULL)
#   empresa_origen   empresa según la propia nómina (informativa; la id_empresa
#                    AUTORITATIVA la deriva la clasificación de área local)
#   area_codigo      código del área/puesto/departamento (para clasificar)
#   area_nombre      nombre del área/puesto/departamento (para clasificar/mostrar)
#   puesto           nombre del puesto (informativo)
CANONICAS = (
    "id_emp", "nombre", "apellido_paterno", "apellido_materno",
    "empresa_origen", "area_codigo", "area_nombre", "puesto",
)

CONSULTAS: dict[str, str] = {
    # ── ASL_Nomina (agrícola) ────────────────────────────────────────────────
    # El "área" para clasificar es el PUESTO (id_puesto → ViewBI_Puestos.nombre).
    "agricola": text("""
        SELECT
            e.id_empleado        AS id_emp,
            e.nombre             AS nombre,
            e.apellido_paterno   AS apellido_paterno,
            e.apellido_materno   AS apellido_materno,
            e.id_empresa         AS empresa_origen,
            e.id_puesto          AS area_codigo,
            p.nombre             AS area_nombre,
            p.nombre             AS puesto
        FROM dbo.ViewBI_Empleados e
        LEFT JOIN dbo.ViewBI_Puestos p ON p.id = e.id_puesto
        WHERE e.inactivo = 0
          -- Sin fantasmas: trabajó en las últimas N semanas, o es de nuevo ingreso.
          AND (
                e.fecha_ingreso >= DATEADD(DAY, -:dias_nuevo_ingreso, CAST(GETDATE() AS DATE))
             OR EXISTS (
                    SELECT 1
                    FROM dbo.ViewBI v
                    WHERE v.id_empleado = e.id_empleado
                      AND v.Fecha >= DATEADD(WEEK, -:semanas_fantasma, CAST(GETDATE() AS DATE))
                )
          )
    """),
    # ── ASL_Nomina_COM (comercializadora) ────────────────────────────────────
    # AREA y NOMBRE_PUESTO vienen como texto; 'empresa' es numérico (como en agrícola).
    # Activo = estatus = 1 (columna agregada a la vista en oct-2026; más estricta que
    # fecha_baja IS NULL: deja fuera a los que no tienen baja pero ya no están).
    "agricola_com": text("""
        SELECT
            e.Numero             AS id_emp,
            e.Nombre             AS nombre,
            e.APELLIDO_PATERNO   AS apellido_paterno,
            e.APELLIDO_MATERNO   AS apellido_materno,
            e.empresa            AS empresa_origen,
            e.AREA               AS area_codigo,
            e.AREA               AS area_nombre,
            e.NOMBRE_PUESTO      AS puesto
        FROM dbo.ViewBI_Com_Empleados e
        WHERE e.estatus = 1
    """),
}


def _parametros(origen: str) -> dict:
    """Parámetros enlazados de la consulta de cada origen (solo agrícola filtra fantasmas)."""
    if origen == "agricola":
        return {
            "semanas_fantasma": settings.SYNC_FANTASMA_SEMANAS,
            "dias_nuevo_ingreso": settings.SYNC_NUEVO_INGRESO_DIAS,
        }
    return {}


def leer_empleados(origen: str) -> Iterator[dict]:
    """
    Itera (streaming) los empleados ACTIVOS de un origen. Cada item es un dict con
    las claves CANÓNICAS + '_origen'. id_emp se normaliza a str (la columna local es
    VARCHAR) y se descartan filas sin id_emp.
    """
    if origen not in CONSULTAS:
        raise RuntimeError(f"SYS21: no hay consulta definida para el origen '{origen}'.")

    engine = get_engine(origen)
    with engine.connect().execution_options(stream_results=True, yield_per=1000) as conn:
        for fila in conn.execute(CONSULTAS[origen], _parametros(origen)).mappings():
            id_emp = fila.get("id_emp")
            if id_emp is None or str(id_emp).strip() == "":
                continue
            registro = {clave: fila.get(clave) for clave in CANONICAS}
            registro["id_emp"] = str(id_emp).strip()
            registro["_origen"] = origen
            yield registro
