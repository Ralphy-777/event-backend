#!/usr/bin/env bash
set -o errexit

PORT_VALUE="${PORT:-10000}"

exec daphne -b 0.0.0.0 -p "${PORT_VALUE}" backend.asgi:application
