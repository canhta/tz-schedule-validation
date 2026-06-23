FROM python:3.12-slim

WORKDIR /app

# Dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY verifier ./verifier

EXPOSE 8000

# Bind to all interfaces so the published container port is reachable.
# nginx on the host terminates TLS and proxies to this port.
CMD ["python", "-m", "verifier.server", "--host", "0.0.0.0", "--port", "8000"]
