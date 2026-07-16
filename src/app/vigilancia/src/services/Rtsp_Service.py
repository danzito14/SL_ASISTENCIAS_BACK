# vigilancia/services/Rtsp_Service.py
# Un frame JPEG de un stream RTSP (para preview de canales de DVR en el front). El DVR NO
# da snapshot ISAPI de canales IP (400) → hay que sacar el frame por RTSP y codificarlo.
# cv2 (headless) con su ffmpeg. Import PEREZOSO (solo este endpoint carga cv2).
import os
import time

# RTSP sobre TCP: el H.265/H.264 del DVR por UDP se corrompe. Debe fijarse antes de abrir.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402 — después de fijar la opción de ffmpeg


def frame_jpeg(url: str, tries: int = 60, descartar: int = 12, calidad: int = 80) -> bytes | None:
    """Abre el RTSP y devuelve un frame ya SINCRONIZADO como JPEG. Descarta los primeros
    `descartar` frames: al abrir a mitad de stream, los primeros suelen venir corruptos
    (P-frames sin su keyframe → artefactos verdes/bloques) hasta que llega un IDR.
    None si no logró leer (canal caído, credencial/canal equivocado, codec ilegible)."""
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    frame = None
    leidos = 0
    for _ in range(tries):
        ok, f = cap.read()
        if ok and f is not None:
            frame = f
            leidos += 1
            if leidos > descartar:   # ya pasó el arranque corrupto → frame limpio
                break
        else:
            time.sleep(0.05)
    cap.release()
    if frame is None:
        return None
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, calidad])
    return buf.tobytes() if ok else None
