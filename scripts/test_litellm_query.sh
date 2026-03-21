#!/usr/bin/env bash
set -euo pipefail

curl -X POST "http://127.0.0.1:8010/queue/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer no_api_key" \
  -d '{
    "model": "Qwen3.5-35B-A3B-FP8",
    "messages": [{"role": "user", "content": "你好，做个自我介绍"}],
    "stream": false
  }'
