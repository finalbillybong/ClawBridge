ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install Python and dependencies
RUN apk add --no-cache python3 py3-pip py3-aiohttp py3-yaml

# Copy application
COPY app /app

# Install additional Python dependencies
RUN pip3 install --no-cache-dir --break-system-packages aiohttp[speedups] websockets

WORKDIR /app

CMD ["python3", "/app/server.py"]
