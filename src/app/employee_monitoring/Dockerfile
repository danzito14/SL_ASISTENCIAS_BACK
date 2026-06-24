# Microservicio employee_monitoring — sincroniza la nómina SYS21 (MSSQL) hacia
# PostgreSQL. Necesita el ODBC Driver 18 de Microsoft para que pyodbc hable con
# SQL Server (no basta el pip; es un driver del SO). Base Debian 12 (bookworm).
FROM python:3.12-slim

WORKDIR /app

# ODBC Driver 18 for SQL Server + unixODBC (runtime y build de pyodbc).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates apt-transport-https \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list \
         | sed 's#deb \[#deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg #' \
         > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev \
    && apt-get purge -y gnupg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# 2 workers gunicorn: el scheduler usa pg_try_advisory_lock para que solo una
# instancia ejecute el sync (ver src/scheduler.py).
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "120"]
