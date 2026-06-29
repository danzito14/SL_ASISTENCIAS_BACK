# Microservicio media — imagen MÍNIMA (solo almacena/sirve archivos; sin BD ni IA).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Carpeta de almacenamiento (se monta como volumen en docker-compose).
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "60"]
