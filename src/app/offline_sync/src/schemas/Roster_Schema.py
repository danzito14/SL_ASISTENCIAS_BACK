# offline_sync/schemas/Roster_Schema.py
from pydantic import BaseModel, Field


class RosterTrabajador(BaseModel):
    id_trabajador: int             # PK interna: el APK la usa para ligar asistencias (FK). NO se muestra.
    id_emp: str | None = None      # número de empleado SYS21: esto es lo que se MUESTRA en el front.
    origen_nomina: str | None = None  # distingue mismo id_emp entre nóminas (agricola / agricola_com / apk)
    nombre: str
    apellido: str
    permiso_escaneo: str
    id_area: int | None = None
    # Vector 512-D (buffalo_l) para el match coseno local en el dispositivo.
    embedding: list[float]
    calidad: float | None = None
    modelo_ia: str | None = None


class RosterArea(BaseModel):
    id_area: int
    nombre_area: str
    tipo_area: str | None = None
    # Polígono del área (GeoJSON) para que el APK precalcule dentro_de_area.
    poligono_geojson: str | None = None


class RosterPuerta(BaseModel):
    id_puerta: int
    nombre_puerta: str
    tipo_puerta: str
    id_area: int | None = None


class RosterResponse(BaseModel):
    empresa: int
    tipo: str
    # Huella del roster: si cambia, el APK vuelve a descargar; si no, se ahorra la bajada.
    roster_version: str = Field(..., description="Hash del conjunto; el APK lo compara para saber si cambió.")
    total_trabajadores: int
    trabajadores: list[RosterTrabajador]
    areas: list[RosterArea]
    puertas: list[RosterPuerta]
