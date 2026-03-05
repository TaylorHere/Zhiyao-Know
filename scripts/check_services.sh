#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

COMPOSE_FILES="docker-compose.yml"
BASE_URL="http://127.0.0.1"
ADMIN_USER=""
ADMIN_PASS=""

usage() {
  cat <<'EOF'
Usage:
  bash scripts/check_services.sh [--compose-files "a.yml,b.yml"] [--base-url http://127.0.0.1] [--admin-user xxx] [--admin-pass xxx]

Examples:
  bash scripts/check_services.sh
  bash scripts/check_services.sh --compose-files "docker-compose.yml,docker-compose.remote.full.yml"
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --compose-files)
      COMPOSE_FILES="${2:?missing compose files}"
      shift 2
      ;;
    --base-url)
      BASE_URL="${2:?missing base url}"
      shift 2
      ;;
    --admin-user)
      ADMIN_USER="${2:?missing admin user}"
      shift 2
      ;;
    --admin-pass)
      ADMIN_PASS="${2:?missing admin pass}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

IFS=',' read -r -a compose_file_arr <<< "${COMPOSE_FILES}"
compose_args=()
for f in "${compose_file_arr[@]}"; do
  ff="$(echo "${f}" | xargs)"
  [[ -n "${ff}" ]] || continue
  compose_args+=(-f "${ff}")
done

if [[ ${#compose_args[@]} -eq 0 ]]; then
  echo "No compose files provided."
  exit 1
fi

pass_count=0
fail_count=0
skip_count=0

ok() {
  pass_count=$((pass_count + 1))
  echo "[PASS] $*"
}

fail() {
  fail_count=$((fail_count + 1))
  echo "[FAIL] $*"
}

skip() {
  skip_count=$((skip_count + 1))
  echo "[SKIP] $*"
}

check_service_state() {
  local svc="$1"
  local cid
  cid="$(docker compose "${compose_args[@]}" ps -q "${svc}" 2>/dev/null || true)"
  if [[ -z "${cid}" ]]; then
    fail "service=${svc} 未创建容器"
    return
  fi

  local state health
  state="$(docker inspect -f '{{.State.Status}}' "${cid}")"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${cid}")"

  if [[ "${state}" != "running" ]]; then
    fail "service=${svc} state=${state} health=${health}"
    return
  fi

  if [[ "${health}" == "unhealthy" ]]; then
    fail "service=${svc} state=${state} health=${health}"
    return
  fi

  ok "service=${svc} state=${state} health=${health}"
}

check_http_status() {
  local name="$1"
  local url="$2"
  local expected="$3"
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "${url}" || true)"
  if [[ "${code}" == "${expected}" ]]; then
    ok "${name} -> ${url} status=${code}"
  else
    fail "${name} -> ${url} status=${code} expected=${expected}"
  fi
}

check_http_status_auth() {
  local name="$1"
  local url="$2"
  local expected="$3"
  local token="$4"
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 -H "Authorization: Bearer ${token}" "${url}" || true)"
  if [[ "${code}" == "${expected}" ]]; then
    ok "${name} -> ${url} status=${code}"
  else
    fail "${name} -> ${url} status=${code} expected=${expected}"
  fi
}

load_admin_from_env_file() {
  local env_file="${ROOT_DIR}/.env"
  if [[ ! -f "${env_file}" ]]; then
    return
  fi
  if [[ -z "${ADMIN_USER}" ]]; then
    ADMIN_USER="$(grep -E '^YUXI_SUPER_ADMIN_NAME=' "${env_file}" | head -n1 | cut -d= -f2- || true)"
  fi
  if [[ -z "${ADMIN_PASS}" ]]; then
    ADMIN_PASS="$(grep -E '^YUXI_SUPER_ADMIN_PASSWORD=' "${env_file}" | head -n1 | cut -d= -f2- || true)"
  fi
}

echo "== Docker Compose Services =="
docker compose "${compose_args[@]}" ps || true
echo

echo "== Service State Checks =="
for svc in web api crawler crawler-worker postgres milvus graph minio etcd crawler-redis; do
  check_service_state "${svc}"
done
echo

echo "== HTTP Checks =="
check_http_status "nginx-api-health" "${BASE_URL}/api/system/health" "200"
check_http_status "nginx-crawler-health" "${BASE_URL}/crawler-api/health" "200"
check_http_status "api-health-direct" "http://127.0.0.1:5050/api/system/health" "200"
check_http_status "crawler-health-direct" "http://127.0.0.1:18060/api/v1/health" "200"
check_http_status "auth-guard" "${BASE_URL}/api/knowledge/databases?page=1&page_size=1" "401"
echo

load_admin_from_env_file
echo "== Authenticated API Checks =="
if [[ -z "${ADMIN_USER}" || -z "${ADMIN_PASS}" ]]; then
  skip "未提供管理员账号，跳过鉴权接口检查（可用 --admin-user/--admin-pass 或在 .env 配置 YUXI_SUPER_ADMIN_*）"
else
  login_json="$(curl -sS --max-time 15 -X POST "${BASE_URL}/api/auth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=${ADMIN_USER}" \
    --data-urlencode "password=${ADMIN_PASS}" || true)"
  token="$(printf '%s' "${login_json}" | python3 -c 'import json,sys; 
try:
 d=json.load(sys.stdin); print(d.get("access_token",""))
except Exception:
 print("")
')"
  if [[ -z "${token}" ]]; then
    fail "admin 登录失败：/api/auth/token 未返回 access_token"
  else
    ok "admin 登录成功：/api/auth/token"
    check_http_status_auth "auth-me" "${BASE_URL}/api/auth/me" "200" "${token}"
    check_http_status_auth "departments-tree" "${BASE_URL}/api/departments/tree" "200" "${token}"
    check_http_status_auth "users-list" "${BASE_URL}/api/auth/users" "200" "${token}"
    check_http_status_auth "knowledge-databases" "${BASE_URL}/api/knowledge/databases" "200" "${token}"
    check_http_status_auth "crawler-tasks" "${BASE_URL}/crawler-api/tasks?page=1&size=10" "200" "${token}"
    check_http_status_auth "crawler-jobs" "${BASE_URL}/crawler-api/jobs?page=1&size=10" "200" "${token}"
    check_http_status_auth "crawler-logs" "${BASE_URL}/crawler-api/logs?page=1&size=10" "200" "${token}"
  fi
fi
echo

echo "== Summary =="
echo "PASS=${pass_count} FAIL=${fail_count} SKIP=${skip_count}"

if [[ "${fail_count}" -gt 0 ]]; then
  exit 1
fi
