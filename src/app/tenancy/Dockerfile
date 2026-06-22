# Microservicio tenancy — imagen LIVIANA (web + DB + geo). shapely/geoalchemy2/
# psycopg2-binary son wheels (shapely trae GEOS), no requieren build tools.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "60"]
