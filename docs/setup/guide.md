# Setup & Deployment Guide

## Quick Start

```bash
git clone https://github.com/benn/telegram-agent.git
cd telegram-agent
./setup
./start
```

## Running as a Background Daemon

You can manage the agent as a background process:

```bash
# Start in background
nohup ./start > logs/agent.log 2>&1 &

# Inspect status
agent status

# Stop process
agent stop
```

## Docker Deployment

To run in Docker:

```bash
# Complete the setup wizard first to generate .env
./setup

# Launch container
docker compose up -d

# Check health
docker compose ps
```

## Troubleshooting with Doctor

If you encounter connection issues or permission errors:

```bash
./doctor
```
