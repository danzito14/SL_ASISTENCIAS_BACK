# recognition/antispoof.py
"""
Servicio anti-spoofing pasivo (foto/pantalla/hoja) con Silent-Face / MiniFASNet
sobre onnxruntime. Degradación segura: si está desactivado o no hay modelos,
`evaluar()` retorna None (no bloquea).
"""
import logging
import os
import re
import threading

import cv2
import numpy as np
import onnxruntime as ort

from src.core.config import settings
from src.core.runtime_config import cfg

logger = logging.getLogger(__name__)


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


class AntiSpoofService:

    def __init__(self, model_dir: str, umbral: float = 0.0, real_index: int = 1, div255: bool = True):
        self._model_dir = model_dir
        self._umbral = umbral
        self._real_index = real_index
        self._div255 = div255
        self._modelos: list[dict] | None = None
        self._lock = threading.Lock()

    def _cargar(self) -> list[dict]:
        if self._modelos is not None:
            return self._modelos
        with self._lock:
            if self._modelos is not None:
                return self._modelos
            modelos: list[dict] = []
            if not os.path.isdir(self._model_dir):
                logger.warning("Anti-spoofing activo pero no existe el directorio: %s", self._model_dir)
                self._modelos = modelos
                return modelos
            for nombre in sorted(os.listdir(self._model_dir)):
                if not nombre.lower().endswith(".onnx"):
                    continue
                ruta = os.path.join(self._model_dir, nombre)
                sess = ort.InferenceSession(ruta, providers=["CPUExecutionProvider"])
                inp = sess.get_inputs()[0]
                _, _, h, w = (inp.shape + [80, 80, 80, 80])[:4]
                in_h = h if isinstance(h, int) else 80
                in_w = w if isinstance(w, int) else 80
                modelos.append({
                    "session": sess, "input_name": inp.name,
                    "scale": self._scale_de_nombre(nombre), "in_h": in_h, "in_w": in_w,
                })
                logger.info("Modelo anti-spoof cargado: %s (scale=%s, %dx%d)",
                            nombre, modelos[-1]["scale"], in_w, in_h)
            if not modelos:
                logger.warning("Anti-spoofing activo pero no se encontraron .onnx en %s", self._model_dir)
            self._modelos = modelos
            return modelos

    @staticmethod
    def _scale_de_nombre(nombre: str) -> float | None:
        head = os.path.basename(nombre).split("_")[0].lower()
        if head == "org":
            return None
        m = re.match(r"^\d+(\.\d+)?$", head)
        return float(head) if m else 2.7

    def disponible(self) -> bool:
        return len(self._cargar()) > 0

    @staticmethod
    def _recortar(img: np.ndarray, bbox_xywh, scale, out_w: int, out_h: int) -> np.ndarray:
        if scale is None:
            return cv2.resize(img, (out_w, out_h))
        src_h, src_w = img.shape[:2]
        x, y, bw, bh = bbox_xywh
        s = min((src_h - 1) / bh, (src_w - 1) / bw, scale)
        new_w, new_h = bw * s, bh * s
        cx, cy = x + bw / 2.0, y + bh / 2.0
        ltx, lty = cx - new_w / 2.0, cy - new_h / 2.0
        rbx, rby = cx + new_w / 2.0, cy + new_h / 2.0
        if ltx < 0:
            rbx -= ltx; ltx = 0
        if lty < 0:
            rby -= lty; lty = 0
        if rbx > src_w - 1:
            ltx -= (rbx - (src_w - 1)); rbx = src_w - 1
        if rby > src_h - 1:
            lty -= (rby - (src_h - 1)); rby = src_h - 1
        recorte = img[int(lty):int(rby), int(ltx):int(rbx)]
        if recorte.size == 0:
            return cv2.resize(img, (out_w, out_h))
        return cv2.resize(recorte, (out_w, out_h))

    def evaluar(self, frame: np.ndarray, bbox_xyxy) -> dict | None:
        """{ es_real, label, score_real } o None si no disponible (no bloquea)."""
        modelos = self._cargar()
        if not modelos:
            return None
        x1, y1, x2, y2 = bbox_xyxy
        bbox_xywh = (float(x1), float(y1), float(x2 - x1), float(y2 - y1))
        suma = None
        for m in modelos:
            recorte = self._recortar(frame, bbox_xywh, m["scale"], m["in_w"], m["in_h"])
            blob = recorte.astype(np.float32)
            if self._div255:
                blob /= 255.0
            blob = np.transpose(blob, (2, 0, 1))[np.newaxis]
            salida = m["session"].run(None, {m["input_name"]: blob})[0][0]
            prob = _softmax(np.asarray(salida, dtype=np.float32))
            suma = prob if suma is None else suma + prob
        suma = suma / len(modelos)
        label = int(np.argmax(suma))
        idx = self._real_index if self._real_index < len(suma) else 0
        score_real = float(suma[idx])
        umbral = cfg.flt("ANTISPOOF_UMBRAL", self._umbral)   # override en caliente (o env)
        es_real = (label == idx) and (score_real >= umbral)
        logger.info("Anti-spoof: probs=%s label=%d real_idx=%d score_real=%.4f es_real=%s",
                    np.round(suma, 4).tolist(), label, idx, score_real, es_real)
        return {"es_real": es_real, "label": label, "score_real": score_real, "probs": suma.tolist()}


# Ancla el directorio de modelos a la raíz del servicio (este archivo está en recognition/src/).
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_model_dir = settings.ANTISPOOF_MODEL_DIR
if not os.path.isabs(_model_dir):
    _model_dir = os.path.join(_BASE_DIR, _model_dir)

antispoof_service = AntiSpoofService(
    model_dir=_model_dir,
    umbral=settings.ANTISPOOF_UMBRAL,
    real_index=settings.ANTISPOOF_REAL_INDEX,
    div255=settings.ANTISPOOF_DIV255,
)
