ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install Python and dependencies
RUN \
  apk add --no-cache \
    python3 \
    py3-pip \
    py3-aiohttp \
    py3-yaml

# Copy application
COPY app /app

# Install additional Python dependencies
RUN pip3 install --no-cache-dir --break-system-packages aiohttp websockets

# Copy run script and set executable permissions
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
