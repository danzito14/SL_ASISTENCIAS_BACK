# employee_monitoring/sources/sys21_engines.py
"""
Engines SQLAlchemy de SOLO LECTURA hacia la nómina SYS21 (MSSQL), una por origen
(ASL_Nomina = 'agricola', ASL_Nomina_COM = 'agricola_com'). No se mapea ORM: son
tablas externas que se leen con Core/text() (ver sys21_reader.py).

Los engines se crean perezosamente (la primera vez que se piden) para que la app
arranque aunque SYS21 esté caído o el driver ODBC falte en un entorno de prueba.
"""
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.core.config import settings

logger = logging.getLogger(__name__)

# Cache de engines por origen (no usar Date/random; estado puro de proceso).
_engines: dict[str, Engine] = {}


def get_engine(origen: str) -> Engine:
    """Devuelve (creando si hace falta) el engine read-only del origen indicado."""
    if origen in _engines:
        return _engines[origen]

    url = settings.sys21_urls.get(origen)
    if not url:
        raise RuntimeError(f"SYS21: no hay URL configurada para el origen '{origen}'.")

    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        pool_recycle=1800,      # MSSQL cierra conexiones ociosas; recicla antes
        echo=settings.DEBUG,
    )
    _engines[origen] = engine
    return engine


def get_engines() -> dict[str, Engine]:
    """Engines de todos los orígenes configurados (mapa origen → Engine)."""
    return {origen: get_engine(origen) for origen in settings.sys21_urls}


def probar_conexiones() -> dict[str, bool]:
    """
    Hace 'SELECT 1' contra cada origen configurado. No es fatal: se usa en el
    lifespan para loguear OK/degradado por origen. Devuelve {origen: ok}.
    """
    resultado: dict[str, bool] = {}
    for origen in settings.sys21_urls:
        try:
            with get_engine(origen).connect() as conn:
                conn.execute(text("SELECT 1"))
            resultado[origen] = True
        except Exception as exc:  # noqa: BLE001 — diagnóstico, no debe tumbar la app
            logger.warning("SYS21[%s]: sin conexión: %s", origen, exc)
            resultado[origen] = False
    return resultado
