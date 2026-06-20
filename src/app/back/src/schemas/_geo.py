# app/schemas/_geo.py
"""
Tipos de apoyo para columnas geográficas de PostGIS (GeoAlchemy2).

PostGIS devuelve las columnas `geography` como un `WKBElement` (binario). Para
las respuestas de la API lo convertimos a texto WKT (ej: 'POINT (-99.13 19.43)').
En la entrada aceptamos texto WKT/EWKT tal cual, que PostGIS sabe interpretar.
"""
from typing import Annotated, Any

from pydantic import BeforeValidator


def _to_wkt(valor: Any) -> Any:
    """Convierte un WKBElement de PostGIS a texto WKT; deja pasar str/None."""
    if valor is None or isinstance(valor, str):
        return valor

    # WKBElement (geoalchemy2) -> shapely -> WKT
    try:
        from geoalchemy2.shape import to_shape

        return to_shape(valor).wkt
    except Exception:
        return str(valor)


# Campo geográfico: en la respuesta sale como WKT (str); en la entrada acepta WKT/EWKT.
GeografiaWKT = Annotated[str | None, BeforeValidator(_to_wkt)]


# ── Constructores: datos del cliente -> geometría PostGIS (geography 4326) ─────

def punto_desde_latlon(latitud: float | None, longitud: float | None):
    """
    Construye un geography(POINT,4326) a partir de latitud y longitud.
    Devuelve None si falta alguna de las dos.
    """
    if latitud is None or longitud is None:
        return None

    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    # En PostGIS/WKT el orden es (X Y) = (longitud latitud).
    return from_shape(Point(longitud, latitud), srid=4326)


def poligono_desde_coords(coordenadas: list[tuple[float, float]] | None):
    """
    Construye un geography(POLYGON,4326) a partir de una lista de coordenadas
    [longitud, latitud]. El anillo se cierra automáticamente. Devuelve None si
    no llegan coordenadas.

    Lanza ValueError si hay menos de 3 puntos (un polígono necesita al menos 3).
    """
    if not coordenadas:
        return None
    if len(coordenadas) < 3:
        raise ValueError("Un polígono necesita al menos 3 coordenadas [longitud, latitud].")

    from geoalchemy2.shape import from_shape
    from shapely.geometry import Polygon

    # shapely espera (x, y) = (longitud, latitud) y cierra el anillo solo.
    puntos = [(float(lon), float(lat)) for lon, lat in coordenadas]
    return from_shape(Polygon(puntos), srid=4326)
