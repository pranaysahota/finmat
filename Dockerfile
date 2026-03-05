FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Ensure portfolio/local.py exists — falls back to example in clean CI environments
RUN test -f portfolio/local.py || cp portfolio/local.example.py portfolio/local.py

# Run schema tests — build fails here if any test fails
RUN python -m pytest tests/ -v

# Entrypoint reconstructs portfolio/local.py from secret then starts the agent
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
