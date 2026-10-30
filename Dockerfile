# Etiqueta libre dentro de 3.14: al reconstruir se recogen los parches de Python y de Debian.
# Pasar a otra versión menor se decide y se prueba a mano.
FROM python:3.14-slim

LABEL org.opencontainers.image.source="https://github.com/angoru/parking"
LABEL org.opencontainers.image.licenses="0BSD"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PARKING_DB=/data/parking.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 parking \
    && useradd --uid 10001 --gid parking --no-create-home parking \
    && install -d -o 10001 -g 10001 /data

COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 VERSION ./VERSION
COPY --chown=10001:10001 LICENSE ./LICENSE

USER 10001:10001
VOLUME /data
EXPOSE 8000
# Solo debe llegar a este puerto el proxy con HTTPS (compose.yaml lo publica en 127.0.0.1): se fía
# de sus cabeceras X-Forwarded-* para conocer la IP real (límites por IP) y que la conexión es HTTPS.
# Un único proceso: los límites de intentos se guardan en memoria.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
