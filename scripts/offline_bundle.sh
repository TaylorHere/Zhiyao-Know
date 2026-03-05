#!/usr/bin/env bash
set -euo pipefail

# Offline bundle tool for Yuxi-Know.
# - export: save docker images + runtime data into a transferable bundle
# - import: load images + restore data from bundle on isolated target machine

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"

timestamp() {
  date "+%Y%m%d_%H%M%S"
}

log() {
  printf '[offline-bundle] %s\n' "$*"
}

usage() {
  cat <<'EOF'
Usage:
  scripts/offline_bundle.sh export [--bundle-name NAME] [--compose-files "a.yml,b.yml"] [--with-env yes|no]
  scripts/offline_bundle.sh import --bundle PATH [--compose-files "a.yml,b.yml"] [--up yes|no]

Examples:
  scripts/offline_bundle.sh export --bundle-name yuxi-offline-v1
  scripts/offline_bundle.sh export --compose-files "docker-compose.remote.full.yml"
  scripts/offline_bundle.sh import --bundle ./dist/yuxi-offline-v1
  scripts/offline_bundle.sh import --bundle ./dist/yuxi-offline-v1.tar.gz --up yes
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Missing required command: ${cmd}" >&2
    exit 1
  fi
}

join_by() {
  local IFS="$1"
  shift
  echo "$*"
}

read_lines_to_array() {
  local array_name="$1"
  local line=""
  eval "${array_name}=()"
  while IFS= read -r line; do
    eval "${array_name}+=(\"\${line}\")"
  done
}

parse_compose_files() {
  local raw="${1:-docker-compose.remote.full.yml}"
  IFS=',' read -r -a files <<< "${raw}"
  local out=()
  for f in "${files[@]}"; do
    local ff
    ff="$(echo "${f}" | xargs)"
    if [[ -z "${ff}" ]]; then
      continue
    fi
    if [[ ! -f "${ROOT_DIR}/${ff}" ]]; then
      echo "Compose file not found: ${ROOT_DIR}/${ff}" >&2
      exit 1
    fi
    out+=("${ff}")
  done
  if [[ "${#out[@]}" -eq 0 ]]; then
    echo "No valid compose files provided." >&2
    exit 1
  fi
  printf '%s\n' "${out[@]}"
}

try_autotag_image() {
  local target_image="$1"
  local tag_part="${target_image##*:}"
  local candidate
  candidate="$(echo "${tag_part}" | sed -E 's/^(yuxi-[a-z-]+)-([0-9].*)$/\1:\2/')"
  if [[ "${candidate}" == "${tag_part}" ]]; then
    return 1
  fi
  if docker image inspect "${candidate}" >/dev/null 2>&1; then
    log "Auto-tagging local image ${candidate} -> ${target_image}"
    docker tag "${candidate}" "${target_image}"
    return 0
  fi
  return 1
}

export_bundle() {
  local bundle_name="yuxi-offline-$(timestamp)"
  local compose_raw="docker-compose.remote.full.yml"
  local with_env="yes"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --bundle-name)
        bundle_name="${2:?missing bundle name}"; shift 2 ;;
      --compose-files)
        compose_raw="${2:?missing compose files}"; shift 2 ;;
      --with-env)
        with_env="${2:?missing with-env value}"; shift 2 ;;
      -h|--help)
        usage; exit 0 ;;
      *)
        echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
  done

  require_cmd docker
  require_cmd tar

  read_lines_to_array compose_files < <(parse_compose_files "${compose_raw}")
  local compose_args=()
  for f in "${compose_files[@]}"; do
    compose_args+=(-f "${f}")
  done

  local bundle_dir="${DIST_DIR}/${bundle_name}"
  local compose_dir="${bundle_dir}/compose"
  local manifest_dir="${bundle_dir}/manifest"
  mkdir -p "${bundle_dir}" "${compose_dir}" "${manifest_dir}"

  log "Collecting image list from compose files: $(join_by ',' "${compose_files[@]}")"
  read_lines_to_array images < <(cd "${ROOT_DIR}" && docker compose "${compose_args[@]}" config --images | sort -u)
  if [[ "${#images[@]}" -eq 0 ]]; then
    echo "No images resolved from compose config." >&2
    exit 1
  fi

  printf '%s\n' "${images[@]}" > "${manifest_dir}/images.txt"
  log "Resolved ${#images[@]} images"

  for img in "${images[@]}"; do
    if ! docker image inspect "${img}" >/dev/null 2>&1; then
      if ! try_autotag_image "${img}"; then
        echo "Image not found locally: ${img}" >&2
        echo "Please build/pull all images before export." >&2
        exit 1
      fi
    fi
  done

  log "Saving images to ${bundle_dir}/images.tar (this may take a while)"
  docker save -o "${bundle_dir}/images.tar" "${images[@]}"

  local data_items=()
  local maybe_items=(
    "crawler_data"
    "crawler_service/crawler.db"
    "docker/volumes/postgresql"
    "docker/volumes/milvus"
    "docker/volumes/neo4j"
    "saves"
  )
  for item in "${maybe_items[@]}"; do
    if [[ -e "${ROOT_DIR}/${item}" ]]; then
      data_items+=("${item}")
    fi
  done
  if [[ "${with_env}" == "yes" && -f "${ROOT_DIR}/.env" ]]; then
    data_items+=(".env")
  fi

  if [[ "${#data_items[@]}" -gt 0 ]]; then
    printf '%s\n' "${data_items[@]}" > "${manifest_dir}/data-items.txt"
    log "Packing runtime data (${#data_items[@]} items) to ${bundle_dir}/data.tar.gz"
    (cd "${ROOT_DIR}" && tar -czf "${bundle_dir}/data.tar.gz" "${data_items[@]}")
  else
    log "No runtime data found, skipping data.tar.gz"
  fi

  for f in "${compose_files[@]}"; do
    cp "${ROOT_DIR}/${f}" "${compose_dir}/"
  done

  cat > "${manifest_dir}/README.txt" <<EOF
Bundle: ${bundle_name}
Created: $(date)

Import steps on target:
1) Place this bundle under project root.
2) Run:
   scripts/offline_bundle.sh import --bundle ${bundle_dir}
EOF

  log "Creating compressed bundle archive ${DIST_DIR}/${bundle_name}.tar.gz"
  (cd "${DIST_DIR}" && tar -czf "${bundle_name}.tar.gz" "${bundle_name}")
  log "Export completed:"
  log "  Directory: ${bundle_dir}"
  log "  Archive:   ${DIST_DIR}/${bundle_name}.tar.gz"
}

import_bundle() {
  local bundle_path=""
  local compose_raw="docker-compose.remote.full.yml"
  local up_after="yes"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --bundle)
        bundle_path="${2:?missing bundle path}"; shift 2 ;;
      --compose-files)
        compose_raw="${2:?missing compose files}"; shift 2 ;;
      --up)
        up_after="${2:?missing up value}"; shift 2 ;;
      -h|--help)
        usage; exit 0 ;;
      *)
        echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
  done

  if [[ -z "${bundle_path}" ]]; then
    echo "--bundle is required for import" >&2
    exit 1
  fi

  require_cmd docker
  require_cmd tar

  local resolved_bundle="${bundle_path}"
  if [[ ! "${resolved_bundle}" = /* ]]; then
    resolved_bundle="${ROOT_DIR}/${resolved_bundle}"
  fi
  if [[ ! -e "${resolved_bundle}" ]]; then
    echo "Bundle not found: ${resolved_bundle}" >&2
    exit 1
  fi

  local work_dir=""
  if [[ -f "${resolved_bundle}" ]]; then
    case "${resolved_bundle}" in
      *.tar.gz|*.tgz)
        work_dir="$(mktemp -d)"
        log "Extracting ${resolved_bundle} to ${work_dir}"
        tar -xzf "${resolved_bundle}" -C "${work_dir}"
        ;;
      *)
        echo "Unsupported bundle file format: ${resolved_bundle}" >&2
        exit 1
        ;;
    esac
    read_lines_to_array bundle_dirs < <(find "${work_dir}" -mindepth 1 -maxdepth 1 -type d)
    if [[ "${#bundle_dirs[@]}" -ne 1 ]]; then
      echo "Invalid bundle archive layout: expected exactly one root dir." >&2
      exit 1
    fi
    resolved_bundle="${bundle_dirs[0]}"
  fi

  if [[ ! -f "${resolved_bundle}/images.tar" ]]; then
    echo "Invalid bundle: missing images.tar" >&2
    exit 1
  fi

  read_lines_to_array compose_files < <(parse_compose_files "${compose_raw}")
  local compose_args=()
  for f in "${compose_files[@]}"; do
    compose_args+=(-f "${f}")
  done

  log "Stopping stack before restore"
  (cd "${ROOT_DIR}" && docker compose "${compose_args[@]}" down || true)

  log "Loading images from ${resolved_bundle}/images.tar"
  docker load -i "${resolved_bundle}/images.tar"

  if [[ -f "${resolved_bundle}/data.tar.gz" ]]; then
    log "Restoring runtime data to ${ROOT_DIR}"
    tar -xzf "${resolved_bundle}/data.tar.gz" -C "${ROOT_DIR}"
  else
    log "No data.tar.gz found, skip data restore"
  fi

  if [[ "${up_after}" == "yes" ]]; then
    log "Starting stack"
    (cd "${ROOT_DIR}" && docker compose "${compose_args[@]}" up -d)
  fi

  log "Import completed from ${resolved_bundle}"
}

main() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 1
  fi

  local cmd="$1"
  shift
  case "${cmd}" in
    export) export_bundle "$@" ;;
    import) import_bundle "$@" ;;
    -h|--help) usage ;;
    *) echo "Unknown command: ${cmd}" >&2; usage; exit 1 ;;
  esac
}

main "$@"
