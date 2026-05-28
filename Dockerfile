FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Ensure /data directory exists (Fly.io volume mount point)
RUN mkdir -p /data

# Install sqlite3 CLI for debugging
RUN apt-get update && apt-get install -y --no-install-recommends sqlite3 && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Ensure portfolio/local.py exists — falls back to example in clean CI environments
RUN test -f portfolio/local.py || cp portfolio/local.example.py portfolio/local.py

# Run schema tests — build fails here if any test fails
RUN python -m pytest tests/ -v

# Entrypoint starts the SQLite-backed UI + scheduler.
# Legacy file-to-SQLite migration is opt-in via RUN_SQLITE_MIGRATION=1.
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 5001

CMD ["./entrypoint.sh"]
