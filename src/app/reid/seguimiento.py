# POC seguimiento (Fase 2): detecta PERSONAS con YOLOv8-POSE, exige que estén DE FRENTE
# (keypoints faciales: nariz + ojos visibles) y con tamaño suficiente, les asigna un ID
# anónimo (persona-N) y usa una GALERÍA DE APARIENCIA (firma de ropa/cuerpo) para que la
# MISMA persona conserve su ID al salir y volver a entrar (persistencia). Sin identidad.
#
#  - "de frente": YOLOv8-pose da nariz/ojos; si se ven con confianza → mira a la cámara.
#                 De espaldas → sin keypoints faciales → NO se registra.
#  - "tamaño": ignora cajas más bajas que REID_MIN_ALTO (lejanas / tras el vidrio).
#  - "persistencia": firma de apariencia (ResNet50; POC — cambiable a OSNet) + coseno.
#      Detección nueva parecida a una ya vista (>= REID_SIM_UMBRAL) → MISMO ID.
#      Umbral conservador: ante la duda, ID nuevo (no confundir a una persona con otra).
#
# Env: REID_FUENTE, REID_OUT, REID_CONF, REID_DEVICE(0/cpu), REID_MIN_ALTO,
#      REID_SIM_UMBRAL, REID_KP_CONF
import csv
import glob
import http.server
import json
import os
import shutil
import socketserver
import threading
import time
import urllib.request
from datetime import datetime, timezone

import cv2
import numpy as np
import torch
from torchreid.reid.utils import FeatureExtractor
from ultralytics import YOLO

# RTSP sobre TCP por defecto: este Hikvision/DVR entrega H.265 (HEVC) y por UDP pierde
# paquetes → frames corruptos ('PPS id out of range', 'vps_base_layer... not set') o el
# stream ni abre (cam por DVR). TCP lo estabiliza. Debe quedar en el entorno ANTES de que
# OpenCV/ffmpeg abran el stream. Override con REID_FFMPEG_OPTS si hiciera falta.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = os.getenv("REID_FFMPEG_OPTS", "rtsp_transport;tcp")

FUENTE = os.getenv("REID_FUENTE",
                   "rtsp://admin:gembel2015*t@192.168.12.245:554/Streaming/Channels/101")
OUT = os.getenv("REID_OUT", "/salida")
CONF = float(os.getenv("REID_CONF", "0.4"))
DEVICE = os.getenv("REID_DEVICE", "0")
WEB_PORT = int(os.getenv("REID_WEB_PORT", "8600"))   # vista en vivo (MJPEG) por red
CLUSTER_INTERVAL = float(os.getenv("REID_CLUSTER_INTERVAL_SEG", "180"))  # auto-cluster cada X seg
CLUSTER_UMBRAL = float(os.getenv("REID_CLUSTER_UMBRAL", "0.72"))         # coseno para agrupar
MIN_ALTO = int(os.getenv("REID_MIN_ALTO", "180"))          # px: ignora cajas más bajas
SIM_UMBRAL = float(os.getenv("REID_SIM_UMBRAL", "0.75"))   # coseno OSNet-AIN para re-emparejar
KP_CONF = float(os.getenv("REID_KP_CONF", "0.35"))         # confianza mínima de ojos para "de frente"

# ── Galería COMPARTIDA (cross-cámara) ──────────────────────────────────────────
# Si hay endpoint configurado, la identidad de apariencia (persona-N) es GLOBAL: se
# resuelve en vigilancia (pgvector) → la misma persona conserva su id entre cámaras.
# Sin endpoint, el motor cae a la galería LOCAL en memoria (POC standalone, id por cámara).
CAMARA_ID = os.getenv("REID_CAMARA_ID", "0")
_CONFIG_URL = os.getenv("REID_CONFIG_URL", "").strip()
AVIST_URL = os.getenv("REID_AVISTAMIENTO_URL", "").strip() or (
    _CONFIG_URL.replace("/reid/config", "/reid/avistamiento") if _CONFIG_URL else "")
REID_TOKEN = os.getenv("REID_INTERNAL_TOKEN", "").strip()
REMOTO = bool(AVIST_URL)

os.makedirs(f"{OUT}/ref", exist_ok=True)
LOG = f"{OUT}/avistamientos.csv"
if not os.path.exists(LOG):
    try:
        with open(LOG, "w", newline="") as f:
            csv.writer(f).writerow(["hora", "persona", "evento", "sim", "x1", "y1", "x2", "y2"])
    except Exception:
        pass


def ahora() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def log(persona, evento, sim="", box=("", "", "", "")) -> None:
    try:
        with open(LOG, "a", newline="") as f:
            csv.writer(f).writerow([ahora(), persona, evento, sim, *box])
    except Exception as exc:
        print(f"WARN: log ({exc})", flush=True)


def guardar_jpg(ruta, img) -> None:
    try:
        cv2.imwrite(ruta, img)
    except Exception as exc:
        print(f"WARN: jpg {ruta} ({exc})", flush=True)


# ── ROI: polígono del PISO por donde camina la gente (por cámara) ──────────────
# Detecciones cuyos PIES caen FUERA del piso = reflejo en vidrio/pared → se ignoran.
# REID_ROI="x1,y1;x2,y2;..." (>=3 puntos). Vacío = sin ROI (acepta todo).
def _parse_roi(s: str):
    pts = []
    for par in (s or "").split(";"):
        par = par.strip()
        if "," in par:
            x, y = par.split(",")
            pts.append([int(x), int(y)])
    return np.array(pts, dtype=np.int32) if len(pts) >= 3 else None


ROI = _parse_roi(os.getenv("REID_ROI", ""))


def _en_roi(x1, y1, x2, y2) -> bool:
    if ROI is None:
        return True
    return cv2.pointPolygonTest(ROI, (float((x1 + x2) / 2), float(y2)), False) >= 0


# ── Vista en vivo por web (MJPEG) — verla desde cualquier dispositivo de la red ────
_WEB = {"jpg": None}
_WEB_LOCK = threading.Lock()


def _publicar_web(vis) -> None:
    ok, buf = cv2.imencode(".jpg", vis)
    if ok:
        with _WEB_LOCK:
            _WEB["jpg"] = buf.tobytes()


class _WebHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    with _WEB_LOCK:
                        jpg = _WEB["jpg"]
                    if jpg:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                         b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n"
                                         + jpg + b"\r\n")
                    time.sleep(0.15)   # ~6-7 fps al navegador
            except Exception:
                pass
        else:
            html = (b"<html><head><title>Seguimiento (reid)</title></head>"
                    b"<body style='margin:0;background:#111;text-align:center'>"
                    b"<img src='/stream' style='max-width:100%;height:auto'></body></html>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html)

    def log_message(self, *a):
        pass


class _WebServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _correr_web(port: int) -> None:
    try:
        _WebServer(("0.0.0.0", port), _WebHandler).serve_forever()
    except Exception as exc:
        print(f"WARN: no se pudo abrir la vista web en :{port} ({exc})", flush=True)


# ── Auto-cluster periódico: consolida las fotos de referencia en PERSONAS ──────
# Agrupa por apariencia (OSNet, union-find) las persona-N que son la MISMA persona
# (frente/espalda/reflejo) → carpetas /salida/personas/grupo-NN. Corre en un hilo en
# CPU (no pelea con la GPU del tracking) cada REID_CLUSTER_INTERVAL_SEG.
def _consolidar(ex_cpu) -> None:
    files = sorted(glob.glob(f"{OUT}/ref/persona-*.jpg"))
    n = len(files)
    if n < 2:
        return
    F = ex_cpu(files).cpu().numpy()
    F = F / (np.linalg.norm(F, axis=1, keepdims=True) + 1e-9)
    S = F @ F.T
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if S[i, j] >= CLUSTER_UMBRAL:
                parent[find(i)] = find(j)
    grupos = {}
    for i in range(n):
        grupos.setdefault(find(i), []).append(i)

    shutil.rmtree(f"{OUT}/personas", ignore_errors=True)
    for gi, (_, idxs) in enumerate(sorted(grupos.items(), key=lambda kv: -len(kv[1])), 1):
        dst = f"{OUT}/personas/grupo-{gi:02d}"
        os.makedirs(dst, exist_ok=True)
        for k in idxs:
            try:
                shutil.copy(files[k], os.path.join(dst, os.path.basename(files[k])))
            except Exception:
                pass
    print(f"[{ahora()}] auto-cluster: {n} fotos → {len(grupos)} personas (umbral {CLUSTER_UMBRAL})", flush=True)


def _correr_cluster() -> None:
    ex_cpu = FeatureExtractor(model_name="osnet_ain_x1_0",
                              model_path="/app/osnet_ain_x1_0_msmt17.pt", device="cpu")
    while True:
        time.sleep(CLUSTER_INTERVAL)
        try:
            _consolidar(ex_cpu)
        except Exception as exc:
            print(f"WARN auto-cluster: {exc}", flush=True)


# ── Modelos ───────────────────────────────────────────────────────────────────
print(f"seguimiento POC F2: fuente={FUENTE} min_alto={MIN_ALTO} umbral={SIM_UMBRAL}", flush=True)
model = YOLO("yolov8n-pose.pt")                             # personas + keypoints [GPU]
_dev = "cuda" if (DEVICE != "cpu" and torch.cuda.is_available()) else "cpu"

# Extractor de apariencia = OSNet-AIN entrenado en Re-ID (MSMT17), domain-generalizable.
# Es lo que SÍ separa misma-persona de distintas (ResNet/OSNet-ImageNet no podían).
_ext = FeatureExtractor(model_name="osnet_ain_x1_0",
                        model_path="/app/osnet_ain_x1_0_msmt17.pt", device=_dev)
print(f"modelos listos; apariencia OSNet-AIN en {_dev}", flush=True)
threading.Thread(target=_correr_web, args=(WEB_PORT,), daemon=True).start()
print(f"vista en vivo web en http://<IP-de-la-maquina>:{WEB_PORT}/", flush=True)
threading.Thread(target=_correr_cluster, daemon=True).start()
print(f"auto-cluster cada {CLUSTER_INTERVAL:.0f}s (umbral {CLUSTER_UMBRAL})", flush=True)

KP_NOSE, KP_LEYE, KP_REYE = 0, 1, 2   # índices COCO de nariz/ojo izq/ojo der


def es_frontal(kpts) -> bool:
    """De frente = nariz clara + AMBOS ojos visibles (de espaldas no hay keypoints faciales)."""
    return (kpts[KP_NOSE][2] >= 0.5 and kpts[KP_LEYE][2] >= KP_CONF and kpts[KP_REYE][2] >= KP_CONF)


def firma(crop_bgr) -> np.ndarray:
    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
    f = _ext([rgb]).cpu().numpy()[0]      # OSNet-AIN → vector de apariencia
    n = np.linalg.norm(f)
    return f / n if n > 0 else f


def emparejar(emb) -> tuple[int | None, float]:
    best_pid, best_sim = None, -1.0
    for pid, g in galeria.items():
        s = float(np.dot(emb, g["emb"]))
        if s > best_sim:
            best_pid, best_sim = pid, s
    return best_pid, best_sim


def emparejar_local(emb) -> tuple[int, str, float]:
    """Galería LOCAL en memoria (por cámara). Devuelve (pid, evento, sim)."""
    global next_pid
    pid_m, sim = emparejar(emb)
    if pid_m is not None and sim >= SIM_UMBRAL:
        g = galeria[pid_m]                       # REAPARECE: promedio corrido de la firma
        g["emb"] = g["emb"] * g["n"] + emb
        g["emb"] /= (np.linalg.norm(g["emb"]) or 1.0)
        g["n"] += 1
        return pid_m, "reaparece", sim
    pid = next_pid                               # NUEVA
    next_pid += 1
    galeria[pid] = {"emb": emb, "n": 1}
    return pid, "nueva", sim


def resolver_persona(emb, box) -> tuple[int | None, str | None, float | None]:
    """Galería COMPARTIDA: POST a vigilancia → id de persona GLOBAL (mismo entre cámaras).
    Devuelve (pid, evento, sim) o (None, None, None) si la red falla (para caer a local)."""
    try:
        body = json.dumps({
            "id_camara": int(CAMARA_ID),
            "embedding": [float(x) for x in emb],
            "bbox": ",".join(str(int(v)) for v in box),
            "umbral": SIM_UMBRAL,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if REID_TOKEN:
            headers["X-Reid-Token"] = REID_TOKEN
        req = urllib.request.Request(AVIST_URL, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
        return int(d["id_persona"]), d.get("evento", "reaparece"), float(d.get("similitud", 0.0))
    except Exception as exc:
        print(f"WARN: reid remoto falló ({exc}); uso galería local.", flush=True)
        return None, None, None


# ── Estado ────────────────────────────────────────────────────────────────────
galeria: dict[int, dict] = {}     # pid -> {"emb": vector normalizado, "n": veces visto}
track2pid: dict[int, int] = {}    # track_id -> pid de la galería (persistencia)
next_pid = 1
n_frames = 0

# ── Captura robusta ────────────────────────────────────────────────────────────
# Abrimos el RTSP nosotros (no vía model.track(source=...)): LoadStreams de Ultralytics
# es impaciente con el PRIMER frame y aborta con DVRs que tardan en dar keyframe. Aquí
# reintentamos hasta leer un frame y, si el stream se cae, RECONECTAMOS (no crashea).
def abrir_captura():
    """Abre FUENTE y espera el primer frame decodificable. Reintenta indefinidamente."""
    while True:
        cap = cv2.VideoCapture(FUENTE, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # menos latencia (frames recientes)
        except Exception:
            pass
        if cap.isOpened():
            for _ in range(80):                   # ~8s esperando keyframe (DVR lento)
                ok, f0 = cap.read()
                if ok and f0 is not None:
                    print(f"[{ahora()}] stream OK cam={CAMARA_ID} ({f0.shape[1]}x{f0.shape[0]})", flush=True)
                    return cap, f0
                time.sleep(0.1)
        cap.release()
        print(f"[{ahora()}] stream cam={CAMARA_ID} no disponible; reintento en 3s.", flush=True)
        time.sleep(3)


# ── Loop ──────────────────────────────────────────────────────────────────────
cap, frame = abrir_captura()
while True:
    n_frames += 1
    r = model.track(frame, persist=True, classes=[0], conf=CONF, device=DEVICE, verbose=False)[0]
    etiquetas = []
    b, kp = r.boxes, r.keypoints
    if b is not None and b.id is not None and kp is not None:
        ids = b.id.int().tolist()
        cajas = b.xyxy.int().tolist()
        kdata = kp.data.cpu().numpy()   # [N,17,3] = (x,y,conf)
        for i, (tid, (x1, y1, x2, y2)) in enumerate(zip(ids, cajas)):
            if (y2 - y1) < MIN_ALTO:                 # (1) filtro de tamaño
                continue
            if not _en_roi(x1, y1, x2, y2):          # (1b) pies fuera del piso = reflejo → ignora
                continue
            if tid in track2pid:                     # ya identificado en este track
                etiquetas.append((x1, y1, x2, y2, f"persona-{track2pid[tid]}", True))
                continue
            if not es_frontal(kdata[i]):             # (2) solo de FRENTE
                etiquetas.append((x1, y1, x2, y2, "de espaldas", False))
                continue
            crop = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
            if crop.size == 0:
                continue
            emb = firma(crop)                        # (3) firma de apariencia (512-D)
            if REMOTO:                               # galería COMPARTIDA → id GLOBAL entre cámaras
                pid, evento, sim = resolver_persona(emb, (x1, y1, x2, y2))
                if pid is None:                      # sin red → cae a local (no pierde el track)
                    pid, evento, sim = emparejar_local(emb)
            else:                                    # POC standalone: galería local en memoria
                pid, evento, sim = emparejar_local(emb)
            if evento == "nueva":                    # registra la vestimenta (recorte de referencia)
                guardar_jpg(f"{OUT}/ref/persona-{pid:03d}.jpg", crop)
            log(f"persona-{pid}", evento, f"{sim:.2f}", (x1, y1, x2, y2))
            print(f"[{ahora()}] persona-{pid} {evento.upper()} (sim {sim:.2f}) cam={CAMARA_ID}", flush=True)
            track2pid[tid] = pid
            etiquetas.append((x1, y1, x2, y2, f"persona-{pid}", True))

    if n_frames % 3 == 0:                            # anota → vista web (~7fps al navegador)
        vis = frame.copy()
        if ROI is not None:                          # zona de piso (azul) para verificar el ROI
            cv2.polylines(vis, [ROI], True, (255, 180, 0), 2)
        for x1, y1, x2, y2, lab, ok in etiquetas:
            color = (0, 200, 0) if ok else (0, 140, 255)
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
            cv2.putText(vis, lab, (x1, max(12, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        _publicar_web(vis)
        if n_frames % 15 == 0:                        # a disco cada 15 (I/O del bind-mount lento)
            guardar_jpg(f"{OUT}/live.jpg", vis)
    if n_frames % 60 == 0:
        print(f"[{ahora()}] frames={n_frames}  cam={CAMARA_ID}", flush=True)

    # Siguiente frame; si el stream se cae, reconecta (con reintento interno).
    ok, frame = cap.read()
    if not ok or frame is None:
        for _ in range(10):
            time.sleep(0.1)
            ok, frame = cap.read()
            if ok and frame is not None:
                break
        if not ok or frame is None:
            print(f"[{ahora()}] stream cam={CAMARA_ID} cayó; reconectando.", flush=True)
            cap.release()
            cap, frame = abrir_captura()
