# Telegram Agent Platform -- container image.
#
# The agent is Telegram long-polling only: it never opens a listening socket, so
# this image declares no EXPOSE. All state lives in /app/data -- bind-mount it.
#
#   docker compose run --rm setup     # guided first-run configuration
#   docker compose up -d              # long-polling agent, running as non-root
#
# Manual build:  docker build -t telegram-agent:latest .

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ca-certificates is the only OS package the runtime needs: every call the agent
# makes (Telegram Bot API, model providers, GitHub) is HTTPS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Project metadata and sources. pyproject.toml declares readme = "README.md", so
# the README has to be copied before `pip install .` or the build fails.
COPY pyproject.toml README.md ./
COPY src/ src/
COPY config/ config/

RUN pip install --upgrade pip \
    && pip install .

# Launcher scripts are kept in the image so `docker compose exec telegram-agent
# scripts/doctor` works the same way it does on a host.
COPY scripts/ scripts/

# Non-root runtime user. The uid is fixed at 1000 so a host bind mount of
# ./data can be made writable with `sudo chown -R 1000:1000 ./data` on Linux.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data \
    && chown -R app:app /app

USER app

CMD ["python", "-m", "src", "start"]
