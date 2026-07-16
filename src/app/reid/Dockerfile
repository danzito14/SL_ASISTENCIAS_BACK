# POC de seguimiento por apariencia (Re-ID). Base OFICIAL de Ultralytics: ya trae
# PyTorch + CUDA + OpenCV + YOLO listos para GPU (evita compilar torch). Correr con
# --gpus all. Es un POC (se rehará/optimizará después).
FROM ultralytics/ultralytics:latest

WORKDIR /app
# 'lap' = tracker BoT-SORT; torchreid = OSNet (Re-ID de apariencia); tensorboard/gdown = deps.
RUN pip install --no-cache-dir "lap>=0.5.12" torchreid gdown tensorboard
# Hornear los pesos: YOLOv8-pose (personas+keypoints) y OSNet-AIN MSMT17 (Re-ID entrenado,
# domain-generalizable) → arranque instantáneo, sin descargas en runtime.
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n-pose.pt')" && \
    python -c "from pathlib import Path; import gdown; from torchreid import reid_model_factory as f; \
gdown.download(f.get_model_url(Path('osnet_ain_x1_0_msmt17.pt')), '/app/osnet_ain_x1_0_msmt17.pt', quiet=False)"
COPY seguimiento.py supervisor.py ./

# Sin display (headless): escribe frames anotados + recortes de referencia a /salida.
ENV MPLBACKEND=Agg
# Supervisor multi-cámara: lee /salida/reid_config.json (grupos_dvr + camaras) y lanza un
# worker seguimiento.py por cámara. Para una sola cámara por env, correr seguimiento.py.
CMD ["python", "supervisor.py"]
