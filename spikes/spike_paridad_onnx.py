#!/usr/bin/env python3
"""
SPIKE de paridad de embeddings (offline APK).

PREGUNTA QUE RESUELVE
  ¿Un pipeline ONNX "desde cero" —el que el APK reimplementará en ONNX Runtime
  Web/Mobile— reproduce el embedding de InsightFace buffalo_l que genera el
  servidor? Es la decisión que habilita (o mata) el reconocimiento OFFLINE: si el
  embedding hecho en el teléfono cae en el MISMO espacio vectorial que el del
  servidor, el match coseno local funciona; si no, no sirve.

QUÉ PRUEBA (lo crítico para la compatibilidad)
  1) Alineación norm_crop (umeyama -> warpAffine 112x112) reimplementada a mano.
  2) Preprocesamiento ArcFace ((RGB-127.5)/127.5, NCHW) a mano (cv2.dnn.blobFromImage).
  3) El modelo de reconocimiento w600k_r50.onnx corrido con onnxruntime "pelón".
  Compara su embedding L2-normalizado contra el normed_embedding de InsightFace.
  PASA si la paridad MÍNIMA >= 0.999 en todas las caras.

QUÉ NO PRUEBA
  La detección SCRFD: aquí se usa el detector de InsightFace solo para obtener los
  5 kps (en el APK será ML Kit / MediaPipe / SCRFD-onnx). El bloque "tol±2px"
  perturba los kps para acotar cuánto afecta usar OTRO detector (debe quedar > 0.97).

CÓMO CORRER (dentro del contenedor recognition, que ya trae todo)
  docker cp spikes/spike_paridad_onnx.py sl_recognition:/tmp/spike_paridad_onnx.py
  docker cp <carpeta_con_fotos>          sl_recognition:/tmp/fotos
  docker exec -it sl_recognition python /tmp/spike_paridad_onnx.py /tmp/fotos

  (Una cara clara por foto; sirven las mismas fotos que ya usaste para enrolar.)
"""
import glob
import os
import sys

import cv2
import numpy as np
import onnxruntime as ort
from insightface.app import FaceAnalysis

# Plantilla ArcFace de 5 puntos para 112x112 (idéntica a insightface face_align).
ARCFACE_DST = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041],
], dtype=np.float64)

UMBRAL_PARIDAD = 0.999     # el pipeline a mano debe reproducir buffalo_l casi exacto
UMBRAL_TOLERANCIA = 0.97   # con un detector distinto (kps ±2px) aún debe reconocer


def encontrar_modelo_rec() -> str:
    """Ruta a w600k_r50.onnx (modelo de reconocimiento de buffalo_l)."""
    candidatos = [
        os.path.expanduser("~/.insightface/models/buffalo_l/w600k_r50.onnx"),
        "/root/.insightface/models/buffalo_l/w600k_r50.onnx",
    ]
    for c in candidatos:
        if os.path.exists(c):
            return c
    hits = glob.glob(os.path.expanduser("~/.insightface/**/w600k_r50.onnx"), recursive=True)
    if hits:
        return hits[0]
    raise FileNotFoundError("No encuentro w600k_r50.onnx (¿buffalo_l descargado?).")


def umeyama(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Transformación de similitud (rot+escala+traslación) src->dst.
    Réplica exacta de skimage.transform._umeyama (la que usa InsightFace)."""
    num, dim = src.shape
    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    src_demean = src - src_mean
    dst_demean = dst - dst_mean
    A = dst_demean.T @ src_demean / num
    d = np.ones((dim,), dtype=np.float64)
    if np.linalg.det(A) < 0:
        d[dim - 1] = -1
    T = np.eye(dim + 1, dtype=np.float64)
    U, S, Vt = np.linalg.svd(A)
    rank = np.linalg.matrix_rank(A)
    if rank == 0:
        return np.full((dim + 1, dim + 1), np.nan)
    if rank == dim - 1:
        if np.linalg.det(U) * np.linalg.det(Vt) > 0:
            T[:dim, :dim] = U @ Vt
        else:
            s = d[dim - 1]
            d[dim - 1] = -1
            T[:dim, :dim] = U @ np.diag(d) @ Vt
            d[dim - 1] = s
    else:
        T[:dim, :dim] = U @ np.diag(d) @ Vt
    scale = 1.0 / src_demean.var(axis=0).sum() * (S @ d)
    T[:dim, dim] = dst_mean - scale * (T[:dim, :dim] @ src_mean)
    T[:dim, :dim] *= scale
    return T


def norm_crop(img: np.ndarray, kps: np.ndarray) -> np.ndarray:
    """Alinea la cara a 112x112 con los 5 kps (== insightface face_align.norm_crop)."""
    M = umeyama(np.asarray(kps, dtype=np.float64), ARCFACE_DST)
    return cv2.warpAffine(img, M[:2], (112, 112), borderValue=0.0)


def preprocess(aimg: np.ndarray) -> np.ndarray:
    """ArcFace: BGR->RGB, (x-127.5)/127.5, NCHW float32 (== blobFromImage de insightface)."""
    return cv2.dnn.blobFromImage(
        aimg, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True
    ).astype(np.float32)


def l2(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-12)


def cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(l2(a), l2(b)))


def main(carpeta: str) -> None:
    exts = ("jpg", "jpeg", "png", "JPG", "JPEG", "PNG")
    fotos = sorted({p for e in exts for p in glob.glob(os.path.join(carpeta, f"*.{e}"))})
    if not fotos:
        print(f"No hay fotos en {carpeta}")
        sys.exit(2)

    print("Cargando buffalo_l (referencia) y w600k_r50.onnx (pelón)...")
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    sess = ort.InferenceSession(encontrar_modelo_rec(), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name

    # Perturbación fija de kps (px) para simular OTRO detector en el APK.
    perturba = np.array([[1.5, -1.5], [-1.5, 1.0], [0.5, 1.5], [1.0, -0.5], [-1.0, 0.5]],
                        dtype=np.float64)

    print(f"\n{'foto':32}{'paridad':>10}{'tol±2px':>10}  estado")
    print("-" * 66)
    paridades, tolerancias = [], []
    for ruta in fotos:
        nombre = os.path.basename(ruta)
        img = cv2.imread(ruta)
        if img is None:
            print(f"{nombre:32}{'':>20}  (ilegible)")
            continue
        caras = app.get(img)
        if not caras:
            print(f"{nombre:32}{'':>20}  (sin rostro)")
            continue
        cara = max(caras, key=lambda f: f.det_score)

        # (1) Verdad de referencia del SERVIDOR.
        emb_server = cara.normed_embedding

        # (2) Pipeline "del teléfono": norm_crop + preprocess + ONNX pelón.
        emb_phone = l2(sess.run(None, {in_name: preprocess(norm_crop(img, cara.kps))})[0].flatten())
        c = cos(emb_server, emb_phone)
        paridades.append(c)

        # (3) Tolerancia a otro detector (kps ±2px).
        emb_pert = l2(sess.run(None, {in_name: preprocess(norm_crop(img, cara.kps + perturba))})[0].flatten())
        t = cos(emb_server, emb_pert)
        tolerancias.append(t)

        estado = "OK" if c >= UMBRAL_PARIDAD else "FALLA"
        print(f"{nombre:32}{c:10.5f}{t:10.5f}  {estado}")

    print("-" * 66)
    if not paridades:
        print("No se pudo evaluar ninguna foto.")
        sys.exit(2)

    par_min = float(np.min(paridades))
    tol_min = float(np.min(tolerancias))
    print(f"Paridad   : media {np.mean(paridades):.5f}  min {par_min:.5f}  ({len(paridades)} caras)")
    print(f"Tolerancia: media {np.mean(tolerancias):.5f}  min {tol_min:.5f}")
    print()

    ok_paridad = par_min >= UMBRAL_PARIDAD
    if ok_paridad:
        print("VEREDICTO: OK  El pipeline ONNX 'desde cero' reproduce buffalo_l.")
        print("           -> El reconocimiento OFFLINE en el APK es VIABLE.")
        if tol_min < UMBRAL_TOLERANCIA:
            print(f"           NOTA: la tolerancia a otro detector cayó a {tol_min:.3f}")
            print("           (<0.97). El APK debería usar un detector que dé kps precisos")
            print("           (SCRFD-onnx) o re-detectar; ML Kit/MediaPipe podrían no bastar.")
    else:
        print("VEREDICTO: FALLA  Los embeddings NO coinciden (paridad < 0.999).")
        print("           Revisar alineación/preprocesamiento ANTES de construir el APK.")
    sys.exit(0 if ok_paridad else 1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fotos")
