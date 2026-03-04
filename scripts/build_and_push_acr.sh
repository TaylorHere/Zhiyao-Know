#!/usr/bin/env bash
set -euo pipefail

# 用法:
# bash scripts/build_and_push_acr.sh [version] [crawler_version]
# 示例:
# bash scripts/build_and_push_acr.sh 0.5.dev 0.1.dev

VERSION="${1:-0.5.dev}"
CRAWLER_VERSION="${2:-0.1.dev}"
PLATFORM="${PLATFORM:-linux/amd64}"
ACR_REPO="${ACR_REPO:-registry.cn-beijing.aliyuncs.com/wyhy/mirrors}"

API_LOCAL_TAG="yuxi-api:${VERSION}"
WEB_LOCAL_TAG="yuxi-web:${VERSION}"
CRAWLER_LOCAL_TAG="yuxi-crawler:${CRAWLER_VERSION}"

API_REMOTE_TAG="${ACR_REPO}:yuxi-api-${VERSION}"
WEB_REMOTE_TAG="${ACR_REPO}:yuxi-web-${VERSION}"
CRAWLER_REMOTE_TAG="${ACR_REPO}:yuxi-crawler-${CRAWLER_VERSION}"

echo "==> Build ${PLATFORM} images"
docker buildx build --platform "${PLATFORM}" -f docker/api.Dockerfile -t "${API_LOCAL_TAG}" --load .
docker buildx build --platform "${PLATFORM}" -f docker/web.Dockerfile --target production -t "${WEB_LOCAL_TAG}" --load .
docker buildx build --platform "${PLATFORM}" -f docker/crawler.Dockerfile -t "${CRAWLER_LOCAL_TAG}" --load .

echo "==> Tag images for ACR: ${ACR_REPO}"
docker tag "${API_LOCAL_TAG}" "${API_REMOTE_TAG}"
docker tag "${WEB_LOCAL_TAG}" "${WEB_REMOTE_TAG}"
docker tag "${CRAWLER_LOCAL_TAG}" "${CRAWLER_REMOTE_TAG}"

echo "==> Push images"
docker push "${API_REMOTE_TAG}"
docker push "${WEB_REMOTE_TAG}"
docker push "${CRAWLER_REMOTE_TAG}"

echo "==> Done"
echo "${API_REMOTE_TAG}"
echo "${WEB_REMOTE_TAG}"
echo "${CRAWLER_REMOTE_TAG}"
