#!/usr/bin/env bash
set -euo pipefail

URL="${LITELLM_QUERY_URL:-http://127.0.0.1:8010/queue/chat/completions}"
MODEL="${LITELLM_MODEL:-Qwen3.5-35B-A3B-FP8}"
QUERY="${LITELLM_QUERY_TEXT:-你好，请用一句话介绍你自己。}"
API_KEY="${LITELLM_API_KEY:-no_api_key}"
MAX_TOKENS="${LITELLM_MAX_TOKENS:-256}"
TEMPERATURE="${LITELLM_TEMPERATURE:-0.7}"

usage() {
  cat <<EOF
用法:
  bash scripts/test_litellm_query.sh [选项]

选项:
  --url <url>                 请求地址（默认: ${URL}）
  --model <model>             模型名（默认: ${MODEL}）
  --query <text>              提问内容
  --api-key <key>             API Key（默认: ${API_KEY}）
  --max-tokens <number>       最大输出 token（默认: ${MAX_TOKENS}）
  --temperature <number>      采样温度（默认: ${TEMPERATURE}）
  -h, --help                  显示帮助

环境变量:
  LITELLM_QUERY_URL
  LITELLM_MODEL
  LITELLM_QUERY_TEXT
  LITELLM_API_KEY
  LITELLM_MAX_TOKENS
  LITELLM_TEMPERATURE
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      URL="${2:?缺少参数}"
      shift 2
      ;;
    --model)
      MODEL="${2:?缺少参数}"
      shift 2
      ;;
    --query)
      QUERY="${2:?缺少参数}"
      shift 2
      ;;
    --api-key)
      API_KEY="${2:?缺少参数}"
      shift 2
      ;;
    --max-tokens)
      MAX_TOKENS="${2:?缺少参数}"
      shift 2
      ;;
    --temperature)
      TEMPERATURE="${2:?缺少参数}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1"
      usage
      exit 1
      ;;
  esac
done

payload="$(MODEL="${MODEL}" QUERY="${QUERY}" MAX_TOKENS="${MAX_TOKENS}" TEMPERATURE="${TEMPERATURE}" python3 -c 'import json, os; print(json.dumps({
    "model": os.environ["MODEL"],
    "messages": [{"role": "user", "content": os.environ["QUERY"]}],
    "max_tokens": int(os.environ["MAX_TOKENS"]),
    "temperature": float(os.environ["TEMPERATURE"]),
    "stream": False
}, ensure_ascii=False))')"

response_file="$(mktemp)"
trap 'rm -f "${response_file}"' EXIT

http_code="$(curl -sS -o "${response_file}" -w "%{http_code}" \
  -X POST "${URL}" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_KEY}" \
  --data "${payload}")"

echo "请求地址: ${URL}"
echo "模型: ${MODEL}"
echo "HTTP 状态码: ${http_code}"

if [[ "${http_code}" != "200" ]]; then
  echo "请求失败，响应如下:"
  cat "${response_file}"
  exit 1
fi

python3 - <<'PY' "${response_file}"
import json
import pathlib
import sys

response_path = pathlib.Path(sys.argv[1])
data = json.loads(response_path.read_text())
choices = data.get("choices", [])

if choices:
    message = choices[0].get("message", {}).get("content")
    if message:
        print("\n模型回复:")
        print(message)

print("\n完整响应:")
print(json.dumps(data, ensure_ascii=False, indent=2))
PY
