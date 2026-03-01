FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY gitea_redmine_sync/ ./gitea_redmine_sync/
COPY static/ ./static/

RUN pip install --no-cache-dir .

RUN useradd -r -u 1001 -s /bin/false appuser
USER appuser

EXPOSE 8000

CMD ["gitea-redmine-sync"]
