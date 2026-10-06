FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f

WORKDIR /app

COPY pyproject.toml README.md ./
COPY skrypka_bot ./skrypka_bot
# hadolint ignore=DL3013
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

VOLUME /app/data

CMD ["skrypka-bot"]
