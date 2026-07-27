# Microservicio recognition — imagen PESADA (InsightFace + OpenCV + ONNX).
FROM python:3.12-slim

# build-essential/cmake: compilar insightface; libgl/libglib: OpenCV; libgomp1: onnxruntime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# buffalo_l (~300 MB): por DEFAULT se hornea → imagen autónoma (nube/dev, sin cambios).
# Para el instalador de escritorio se publica con --build-arg BAKE_MODEL=false → imagen
# LIGERA; el modelo se descarga en la instalación a un volumen montado en /root/.insightface.
ARG BAKE_MODEL=true
RUN if [ "$BAKE_MODEL" = "true" ]; then \
        python -c "from insightface.app import FaceAnalysis; FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']).prepare(ctx_id=0, det_size=(640, 640))"; \
    fi

EXPOSE 8000

# Cada worker carga su PROPIA copia del modelo (~1 GB RAM). En VPS chico deja -w 1.
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "120"]
