# recognition/core/runtime_config.py
# Overrides de umbrales EN CALIENTE, leídos de parametros_sistema (clave 'reco.<NOMBRE>').
# Motivo: recognition corre con -w 2 (2 workers, memoria separada), así que un endpoint
# "en memoria" sería inconsistente. La BD es el store compartido: los 2 workers leen la
# MISMA tabla → consistente, y sobrevive reinicios. Caché con TTL para no pegarle a la BD
# en cada request (el costo real es la inferencia, no el SELECT). Si el toggle está OFF o
# la clave no existe / la BD falla, cae al DEFAULT (el valor de env). Prod = OFF → env puro.
import logging
import threading
import time

from sqlalchemy import text

from src.core.config import settings
from src.core.pgdb import engine

logger = logging.getLogger(__name__)

_PREFIJO = "reco."


class RuntimeConfig:
    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._ts: float = 0.0
        self._lock = threading.Lock()

    def _refrescar(self) -> None:
        try:
            with engine.connect() as conn:
                filas = conn.execute(
                    text("SELECT clave, valor FROM parametros_sistema WHERE clave LIKE :p"),
                    {"p": _PREFIJO + "%"},
                ).all()
            self._cache = {c[len(_PREFIJO):]: v for c, v in filas}
        except Exception as exc:  # sin permiso (svc_recognition) o BD caída → defaults
            logger.debug("runtime_config: no se pudo leer parametros_sistema: %s", exc)
            self._cache = {}
        self._ts = time.monotonic()

    def _raw(self, clave: str, forzar: bool = False) -> str | None:
        if not settings.CONFIG_RUNTIME_ACTIVO:
            return None
        if forzar or (time.monotonic() - self._ts) > settings.CONFIG_RUNTIME_TTL:
            with self._lock:
                if forzar or (time.monotonic() - self._ts) > settings.CONFIG_RUNTIME_TTL:
                    self._refrescar()
        return self._cache.get(clave)

    def flt(self, clave: str, default: float) -> float:
        v = self._raw(clave)
        try:
            return float(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def intt(self, clave: str, default: int) -> int:
        v = self._raw(clave)
        try:
            return int(float(v)) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def boolt(self, clave: str, default: bool) -> bool:
        v = self._raw(clave)
        if v in (None, ""):
            return default
        return str(v).strip().lower() in ("1", "true", "t", "si", "sí", "yes", "y")

    def efectivos(self) -> dict:
        """Valores EFECTIVOS (override de BD o default de env). Lee fresco (bypassa caché)
        para que el front vea el cambio al instante tras un POST. Para mostrar/depurar."""
        self._raw("_", forzar=True)  # fuerza un refresh del cache si el toggle está ON
        return {
            "CONFIG_RUNTIME_ACTIVO":         settings.CONFIG_RUNTIME_ACTIVO,
            "CALIDAD_GATE_ACTIVO":           self.boolt("CALIDAD_GATE_ACTIVO", settings.CALIDAD_GATE_ACTIVO),
            "CALIDAD_DET_SCORE_MIN":         self.flt("CALIDAD_DET_SCORE_MIN", settings.CALIDAD_DET_SCORE_MIN),
            "CALIDAD_FACE_RATIO_MIN":        self.flt("CALIDAD_FACE_RATIO_MIN", settings.CALIDAD_FACE_RATIO_MIN),
            "CALIDAD_BLUR_MIN":              self.flt("CALIDAD_BLUR_MIN", settings.CALIDAD_BLUR_MIN),
            "CALIDAD_BORDE_MARGEN":          self.flt("CALIDAD_BORDE_MARGEN", settings.CALIDAD_BORDE_MARGEN),
            "ANTISPOOFING_ACTIVO":           self.boolt("ANTISPOOFING_ACTIVO", settings.ANTISPOOFING_ACTIVO),
            "ANTISPOOF_UMBRAL":              self.flt("ANTISPOOF_UMBRAL", settings.ANTISPOOF_UMBRAL),
            "SIMILITUD_UMBRAL":              self.flt("SIMILITUD_UMBRAL", settings.SIMILITUD_UMBRAL),
            "SIMILITUD_UMBRAL_ACOTADO":      self.flt("SIMILITUD_UMBRAL_ACOTADO", settings.SIMILITUD_UMBRAL_ACOTADO),
            "SPOOFING_UMBRAL":               self.flt("SPOOFING_UMBRAL", settings.SPOOFING_UMBRAL),
            "LIVENESS_MIN_FRAMES_CON_ROSTRO": self.intt("LIVENESS_MIN_FRAMES_CON_ROSTRO", settings.LIVENESS_MIN_FRAMES_CON_ROSTRO),
            "LIVENESS_MISMA_PERSONA_UMBRAL": self.flt("LIVENESS_MISMA_PERSONA_UMBRAL", settings.LIVENESS_MISMA_PERSONA_UMBRAL),
            "LIVENESS_MOVIMIENTO_MIN":       self.flt("LIVENESS_MOVIMIENTO_MIN", settings.LIVENESS_MOVIMIENTO_MIN),
        }


cfg = RuntimeConfig()
