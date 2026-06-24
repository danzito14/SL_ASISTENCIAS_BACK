# employee_monitoring/schemas/sync.py
from datetime import datetime

from pydantic import BaseModel


class SyncOrigenResultado(BaseModel):
    """Contadores de una corrida para un origen (nómina) concreto."""
    origen:          str
    leidos:          int = 0
    nuevos:          int = 0
    actualizados:    int = 0
    sin_cambio:      int = 0
    fotos_ok:        int = 0
    fotos_pendientes: int = 0
    desaparecidos:   int = 0
    errores:         int = 0
    ok:              bool = True          # False si el origen falló (ej. sin conexión)
    detalle_error:   str | None = None


class SyncRunResponse(BaseModel):
    """Resultado agregado de una corrida de sincronización."""
    disparado_por:   str                  # 'manual' | 'scheduler'
    solo_datos:      bool = False
    inicio:          datetime | None = None
    fin:             datetime | None = None
    duracion_seg:    float | None = None
    leidos:          int = 0
    nuevos:          int = 0
    actualizados:    int = 0
    sin_cambio:      int = 0
    fotos_ok:        int = 0
    fotos_pendientes: int = 0
    desaparecidos:   int = 0
    errores:         int = 0
    por_origen:      list[SyncOrigenResultado] = []
    mensaje:         str | None = None


class SyncRunAceptado(BaseModel):
    """Respuesta 202 cuando el sync se lanza en segundo plano."""
    aceptado:  bool = True
    mensaje:   str = "Sincronización lanzada en segundo plano. Consulta /sync/estado."


class SyncEstadoResponse(BaseModel):
    """Una fila de estado de sincronización por empleado."""
    id_sync:                 int
    id_emp:                  str
    origen_nomina:           str
    id_empresa:              int | None = None
    estado_foto:             str | None = None
    visto_en_ultima_corrida: bool
    ultima_sync:             datetime | None = None
    ultima_sync_ok:          datetime | None = None

    model_config = {"from_attributes": True}
