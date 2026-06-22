# reports/schemas/incidencia.py — solo el tipo que usa el router de reportes.
from typing import Literal


# Valores permitidos por el ENUM tipo_incidencia de la tabla.
TipoIncidencia = Literal[
    "salida_sin_registro",
    "entrada_sin_registro",
    "falta",
    "retardo",
    "fuera_de_area",
    "acceso_otra_empresa",
    "area_incorrecta",
]
EstadoIncidencia = Literal["pendiente", "revisada", "justificada"]
