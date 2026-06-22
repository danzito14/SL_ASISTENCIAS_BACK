# Backend FastAPI — imagen LIVIANA. El reconocimiento facial vive en el
# microservicio 'recognition' (allá van insightface/OpenCV/ONNX y el modelo).
# Aquí solo hay web + DB + clientes HTTP (psycopg2-binary/numpy/shapely son wheels,
# no requieren build-essential/cmake/libgl).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Sin modelo facial → el arranque es rápido; varios workers son baratos.
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "-b", "0.0.0.0:8000", "--timeout", "60"]
