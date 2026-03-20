# 生产部署指南

本指南介绍了如何在生产环境中部署 Yuxi-Know。

## 前置要求

- **Docker Engine** (v24.0+)
- **Docker Compose** (v2.20+)
- **NVIDIA Container Toolkit** (如果在生产环境使用 GPU 服务)

注意事项：

1. 生产环境和开发环境最好是两台独立的机器，不然会存在端口和资源的冲突问题。
2. 虽然名为“生产环境”，但实际上只是做了一些基本的配置而已，真要上线业务，需要根据实际情况进行调整。
3. 前端有个**调试面板**，长按侧边栏触发，生产环境不建议开启。

## 部署步骤

### 1. 配置环境变量

为了避免与开发环境的冲突，建议在生产环境中使用 `.env.prod` 文件。请确保你已经从模板创建了该文件并填写了必要的密钥。

```bash
cp .env.template .env.prod
```

编辑 `.env.prod` 文件，设置强密码并配置必要的 API 密钥：

- `NEO4J_PASSWORD`: 修改默认密码
- `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`: 修改默认密钥
- `SILICONFLOW_API_KEY` 等模型密钥

如果你使用本地 vLLM 模型套件（聊天 / Embedding / Rerank），也可以在 `docker-compose.prod.yml` 的 `api.environment` 中通过以下变量覆盖端点：

- `VLLM_CHAT_BASE_URL`（默认：`http://host.docker.internal:8000/v1`）
- `VLLM_CHAT_MODEL`（默认：`Qwen2.5-72B-Instruct-AWQ`）
- `VLLM_EMBED_BASE_URL`（默认：`http://host.docker.internal:8001/v1/embeddings`）
- `VLLM_EMBED_MODEL`（默认：`Qwen3-Embedding-0.6B`）
- `VLLM_RERANK_BASE_URL`（默认：`http://host.docker.internal:8002/v1/rerank`）
- `VLLM_RERANK_MODEL`（默认：`qwen3-rerank`）

### 2. 启动服务

使用 `docker-compose.prod.yml` 文件启动生产环境：

```bash
# 仅启动核心服务 (CPU 模式)
docker compose -f docker-compose.prod.yml up -d --build

# 启动所有服务 (包含 GPU OCR 服务)
docker compose -f docker-compose.prod.yml --profile all up -d --build
```

### 3. 验证部署

- **Web 访问**: `http://localhost` (直接通过 80 端口访问，无需 :5173)
- **API 健康检查**: `curl http://localhost/api/system/health`

## 维护与更新

### 更新代码并重新部署

```bash
# 拉取最新代码
git pull

# 重新构建并启动
docker compose -f docker-compose.prod.yml up -d --build
```

### 查看日志

```bash
# 查看 API 日志
docker logs -f api-prod

# 查看 Nginx 访问日志
docker logs -f web-prod
```

## 离线交付部署（内网）

如果目标环境无法访问外网，使用离线包部署：

```bash
# 在源机器打包
bash scripts/offline_bundle.sh export \
  --bundle-name yuxi-offline-e2e \
  --compose-files "docker-compose.remote.full.yml" \
  --with-env yes

# 在目标机器导入并启动
bash scripts/offline_bundle.sh import \
  --bundle ./yuxi-offline-e2e.tar.gz \
  --compose-files "docker-compose.remote.full.yml" \
  --up yes
```

详细步骤和交付清单见：

- `docs/离线交付部署说明.md`

## Ubuntu 22.04 + 双 L20 + vLLM 专用部署

如果是从 Ubuntu 22.04 LTS 裸机开始，并需要按如下方式部署：

- Qwen2.5-72B-Instruct-AWQ（vLLM，GPU 双卡）
- 或 Qwen3.5-35B-A3B-FP8（vLLM，GPU 双卡）
- Qwen3-Embedding-0.6B（vLLM，CPU）
- Qwen3-Reranker-0.6B（vLLM，CPU）
- PaddleOCR（CPU，仅整套 compose）

请参考专用 Step by Step 文档：

- `docs/ubuntu22.04-l20-vllm-step-by-step.md`

对应编排文件（最新）：

- `docker-compose.remote.l20.qwen25.vllm.yml`（整套，含 OCR）
- `docker-compose.model-suite.l20.qwen25.vllm.yml`（模型套件，不含 OCR）
- `docker-compose.remote.l20.qwen35.vllm.yml`（整套，含 OCR）
- `docker-compose.model-suite.l20.qwen35.vllm.yml`（模型套件，不含 OCR）
