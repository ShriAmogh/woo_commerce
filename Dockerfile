FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Install into a local directory (not system)
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Pre-download fastembed model into builder stage
RUN PYTHONPATH=/install/lib/python3.11/site-packages \
    python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

# ---- Final stage (clean, no build tools) ----
FROM python:3.11-slim

WORKDIR /app

# Copy only installed packages from builder
COPY --from=builder /install /usr/local
# Copy cached fastembed model
COPY --from=builder /root/.cache /root/.cache

COPY . .

EXPOSE 8000

CMD ["uvicorn", "working.endpoints.agent_api:app", "--host", "0.0.0.0", "--port", "8000"]
