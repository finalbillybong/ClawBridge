#!/usr/bin/with-contenv bashio

bashio::log.info "Starting ClawBridge..."
bashio::log.info "SUPERVISOR_TOKEN length: ${#SUPERVISOR_TOKEN}"

exec python3 /app/server.py
