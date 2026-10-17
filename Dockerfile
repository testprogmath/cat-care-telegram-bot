FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY pyproject.toml README.md ./
COPY skrypka_bot ./skrypka_bot
RUN pip install --no-cache-dir --no-deps -e .

VOLUME /app/data

CMD ["skrypka-bot"]
