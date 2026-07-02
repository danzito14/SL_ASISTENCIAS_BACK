# offline_sync/schemas/Ingesta_Schema.py
from pydantic import BaseModel


class FilaRechazada(BaseModel):
    linea: int              # número de línea en el CSV (1 = encabezado; los datos arrancan en 2)
    id: str | None = None   # PK de la fila (id_asistencia/id_intento) para que el front NO mapee por línea
    motivo: str


class IngestaResponse(BaseModel):
    recibidos: int    # filas de datos leídas del CSV
    insertados: int   # filas nuevas que entraron
    duplicados: int   # filas ya existentes (ON CONFLICT DO NOTHING) — idempotencia
    rechazados: list[FilaRechazada] = []
