FROM pgvector/pgvector:pg17

RUN apt-get update && apt-get install -y \
    postgresql-17-postgis-3 \
    postgresql-17-postgis-3-scripts \
    postgresql-17-cron \
 && rm -rf /var/lib/apt/lists/*