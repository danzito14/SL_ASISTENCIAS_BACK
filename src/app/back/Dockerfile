# Backend FastAPI (FE Scanner) — imagen de producción
FROM python:3.12-slim

# Dependencias de sistema:
#   - build-essential, cmake : compilar insightface (extensiones nativas)
#   - libgl1, libglib2.0-0   : que funcione opencv-python (cv2)
#   - libgomp1               : OpenMP, lo usa onnxruntime
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias primero (mejor cacheo de capas de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código: src/, main.py y models/antispoof/ (este último SÍ se necesita)
COPY . .

# Pre-descargar el modelo facial buffalo_l (~300 MB) en tiempo de build, para que
# el contenedor sea autónomo y no dependa de la CDN de insightface en runtime.
# Coméntalo si prefieres una imagen más liviana (se descargará al primer arranque,
# necesitará internet y el primer escaneo tardará más).
RUN python -c "from insightface.app import FaceAnalysis; FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']).prepare(ctx_id=0, det_size=(640, 640))"

EXPOSE 8000

# Producción: gunicorn supervisando workers Uvicorn.
# OJO con -w: cada worker carga su PROPIA copia del modelo facial (~1 GB de RAM).
# En un VPS chico deja -w 1 o -w 2. --timeout alto porque el arranque carga el modelo.
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "120"]
