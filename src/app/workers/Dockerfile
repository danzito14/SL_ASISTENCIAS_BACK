# Microservicio workers — imagen LIVIANA (web + DB + pgvector). El reconocimiento
# facial lo hace 'recognition' (workers solo le manda la foto y guarda el embedding).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "60"]
