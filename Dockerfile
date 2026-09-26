FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY skrypka_bot ./skrypka_bot
RUN pip install --no-cache-dir .

VOLUME /app/data

CMD ["skrypka-bot"]
