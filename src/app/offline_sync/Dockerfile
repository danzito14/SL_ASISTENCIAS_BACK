# Microservicio offline_sync — entrega el roster al APK (kiosko offline) e ingiere
# por lotes lo que capturó sin conexión (asistencias, intentos, enrolamientos).
# Imagen LIGERA: sin visión/IA ni ODBC. El embedding llega YA calculado del APK
# (buffalo_l on-device), así que aquí no corre InsightFace ni se llama a recognition.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# 2 workers gunicorn. La ingesta es idempotente (ON CONFLICT DO NOTHING) y el
# roster es de solo lectura, así que no hace falta coordinación entre workers.
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "120"]
