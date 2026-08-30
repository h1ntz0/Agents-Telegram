FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/
COPY config/ config/
COPY scripts/ scripts/

RUN pip install --upgrade pip && \
    pip install .

RUN mkdir -p data && chmod 755 data

EXPOSE 8080

CMD ["python", "-m", "src", "start"]
