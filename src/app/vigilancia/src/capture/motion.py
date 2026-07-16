# vigilancia/capture/motion.py
# Gate de movimiento barato: decodifica el JPEG a gris pequeño y compara con el frame
# anterior (diferencia media). Evita mandar cuadros vacíos al scanner. NO es detección
# de rostro (eso lo hace recognition en el back): es un pre-filtro de "algo cambió".
import io

import numpy as np
from PIL import Image


class MotionGate:
    def __init__(self, umbral: float = 2.5, size: tuple[int, int] = (64, 48)) -> None:
        self.umbral = umbral
        self.size = size
        self._prev: np.ndarray | None = None

    def hay_movimiento(self, jpeg: bytes) -> bool:
        try:
            img = Image.open(io.BytesIO(jpeg)).convert("L").resize(self.size)
        except Exception:
            return True  # si no decodifica, NO filtres (deja pasar al scanner)
        arr = np.asarray(img, dtype=np.int16)
        if self._prev is None:
            self._prev = arr
            return True
        diff = float(np.mean(np.abs(arr - self._prev)))
        self._prev = arr
        return diff >= self.umbral
