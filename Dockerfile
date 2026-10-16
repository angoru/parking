FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/angoru/parking"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 parking \
    && useradd --uid 10001 --gid parking --no-create-home parking

COPY --chown=10001:10001 app ./app

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
