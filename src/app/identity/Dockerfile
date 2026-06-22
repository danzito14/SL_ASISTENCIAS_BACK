# Microservicio identity — imagen LIGERA (sin librerías de visión/IA).
# psycopg2-binary trae wheel propio, así que no hacen falta build-essential ni libgl.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Producción: gunicorn + workers Uvicorn. identity es liviano → varios workers OK.
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "60"]
