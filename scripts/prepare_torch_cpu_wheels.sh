#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHEEL_DIR="${ROOT_DIR}/.wheels"

mkdir -p "${WHEEL_DIR}"

docker run --rm \
  -v "${WHEEL_DIR}:/wheels" \
  python:3.12-slim \
  bash -lc "python -m pip install -U pip && \
    pip download --dest /wheels \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.8.0 torchvision==0.23.0"

echo "CPU wheels downloaded to: ${WHEEL_DIR}"
