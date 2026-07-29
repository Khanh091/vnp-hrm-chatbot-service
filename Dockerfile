FROM python:3.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./
COPY docker/entrypoint.sh /usr/local/bin/chatbot-entrypoint

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && chmod +x /usr/local/bin/chatbot-entrypoint \
    && useradd --create-home --uid 10001 chatbot \
    && chown -R chatbot:chatbot /app

USER chatbot

EXPOSE 8000

ENTRYPOINT ["chatbot-entrypoint"]
