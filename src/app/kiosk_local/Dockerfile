# Backend LOCAL del kiosko de escritorio. Imagen LIGERA (sin IA: el reconocimiento lo
# hace el contenedor 'recognition' aparte). Baja el roster de la nube → postgres local.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# 1 worker: un kiosko local sirve a UN front; con 1 worker hay UN solo loop de auto-sync
# (con 2 workers correrían 2 loops → subidas redundantes, aunque idempotentes).
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "1", "-b", "0.0.0.0:8000", "--timeout", "120"]
