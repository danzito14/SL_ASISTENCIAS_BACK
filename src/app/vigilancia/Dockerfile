# Microservicio vigilancia — asistencia por reconocimiento facial desde cámaras/
# terminales IP. ONLINE: captura por snapshot ISAPI HTTP → recognition (HTTP) →
# escaneo → consolidación. Imagen LIGERA (sin ffmpeg/IA).
FROM python:3.12-slim

WORKDIR /app

# libglib2.0-0: única lib de sistema que necesita opencv-python-headless (trae su ffmpeg).
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# API de gestión (CRUD cámaras + eventos). El motor de CAPTURA corre como proceso
# APARTE (mismo imagen, comando `python -m src.capture.run`, Fase 4) para no
# duplicarse con los -w workers de gunicorn.
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "120"]
