# Conduit pipeline API — the Python engine (ifcopenshell / numpy) behind gunicorn.
# Build context is the repo root:  docker build -f webapp/Dockerfile -t conduit-api .
FROM python:3.11-slim

WORKDIR /app

# libgomp1 is dlopened by some ifcopenshell / numpy wheels at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# the API imports the pipeline (bim/) and the machine simulator (machine/ +
# run_stick_job.py) for the shop-floor "run the machine" view
COPY bim/ ./bim/
COPY machine/ ./machine/
COPY run_stick_job.py ./run_stick_job.py
COPY webapp/ ./webapp/

ENV PORT=5050 \
    CONDUIT_OUT_DIR=/data/out \
    CONDUIT_UPLOAD_DIR=/data/uploads
RUN mkdir -p /data/out /data/uploads

EXPOSE 5050
# 2 workers, 120s timeout for large IFC parses; binds all interfaces in-container
CMD ["sh", "-c", "gunicorn -w 2 -t 120 -b 0.0.0.0:${PORT} webapp.app:app"]
