# Ubuntu 22.04 LTS（裸机）双 L20 + vLLM 部署指引（Step by Step）

本文档用于从 **Ubuntu 22.04 LTS Live** 全新系统开始，部署本项目。

当前支持两套 LLM 版本（其余组件一致）：

- `Qwen2.5-72B-Instruct-AWQ`
- `Qwen3.5-35B-A3B-FP8`

---

## 0.1 编排文件选择（最新）

| 场景 | 编排文件 | 是否包含 OCR |
|---|---|---|
| Qwen2.5 整套拉起 | `docker-compose.l20.qwen25.vllm.yml` | 是（`paddlex`） |
| Qwen2.5 仅模型套件 | `docker-compose.model-suite.l20.qwen25.vllm.yml` | 否 |
| Qwen3.5 整套拉起 | `docker-compose.l20.qwen35.vllm.yml` | 是（`paddlex`） |
| Qwen3.5 仅模型套件 | `docker-compose.model-suite.l20.qwen35.vllm.yml` | 否 |

以上四个文件均内置 `litellm-gateway`（LiteLLM），作为业务与模型服务之间的 **Token 感知网关**，默认端口 `8010`。

---

## 0. 目标机器建议规格

- GPU：NVIDIA L20 x 2
- CPU：32 vCPU 及以上（embedding/rerank/OCR 在 CPU）
- 内存：128 GB 及以上
- 磁盘：1 TB 及以上（模型 + 镜像 + 数据）
- 系统：Ubuntu 22.04 LTS

---

## 1. 初始化系统

### 1.1 更新系统与基础工具

```bash
sudo apt update
sudo apt -y upgrade
sudo apt install -y curl wget git vim ca-certificates gnupg lsb-release software-properties-common
```

### 1.2 设置时区（可选）

```bash
sudo timedatectl set-timezone Asia/Shanghai
timedatectl
```

---

## 2. 安装 NVIDIA 驱动

### 2.1 查看推荐驱动

```bash
ubuntu-drivers devices
```

### 2.2 安装驱动（示例）

> 以 `ubuntu-drivers devices` 推荐版本为准。L20 常见可用版本为 550+。

```bash
sudo apt install -y nvidia-driver-550-server
sudo reboot
```

### 2.3 验证 GPU

```bash
nvidia-smi
```

预期看到 2 张 L20。

---

## 3. 安装 Docker Engine + Compose Plugin

### 3.1 添加 Docker 官方源

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

### 3.2 安装 Docker

```bash
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 3.3 非 root 使用 docker（可选）

```bash
sudo usermod -aG docker $USER
newgrp docker
docker version
docker compose version
```

### 3.4 配置 Docker 国内镜像加速（强烈建议）

编辑 `/etc/docker/daemon.json`：

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.cn"
  ]
}
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker
docker info | rg "Registry Mirrors" -n -A 4
```

> 如你们企业有内网 Harbor/制品库镜像，请优先替换为企业镜像地址。

### 3.5 调整 nofile（避免 `os error 24`）

当出现 `No file descriptors available (os error 24)` 或 `Too many open files` 时，按以下步骤提升系统与容器的文件句柄上限。

#### 3.5.1 提升 Docker 服务进程限制（关键）

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/override.conf >/dev/null <<'EOF'
[Service]
LimitNOFILE=1048576
EOF
```

#### 3.5.2 给容器设置默认 nofile

> 如果 `/etc/docker/daemon.json` 已存在，请把 `default-ulimits` 合并进去，不要覆盖掉已有配置（如 `registry-mirrors`）。

可直接改成如下结构（保留你现有的镜像加速配置）：

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.cn"
  ],
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Soft": 1048576,
      "Hard": 1048576
    }
  }
}
```

#### 3.5.3 重载并重启 Docker

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

#### 3.5.4 验证是否生效

```bash
docker info | rg -i "Default Ulimits|nofile"
docker run --rm alpine sh -c 'ulimit -n'
```

> 若你只想对单个服务生效，也可在 `docker-compose*.yml` 的服务下增加：
>
> ```yaml
> ulimits:
>   nofile:
>     soft: 262144
>     hard: 262144
> ```

---

## 4. 安装 NVIDIA Container Toolkit（让容器可用 GPU）

```bash
(curl -fsSL https://mirrors.tuna.tsinghua.edu.cn/github-raw/NVIDIA/libnvidia-container/gh-pages/gpgkey \
  || curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey) | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

((curl -fsSL https://mirrors.tuna.tsinghua.edu.cn/github-raw/NVIDIA/libnvidia-container/gh-pages/stable/deb/nvidia-container-toolkit.list \
  || curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list) | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g') | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null

sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### 4.1 验证容器内 GPU

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

---

## 5. 获取项目代码

```bash
sudo mkdir -p /opt/yuxi-know
sudo chown -R $USER:$USER /opt/yuxi-know
cd /opt/yuxi-know

git clone https://github.com/TaylorHere/Zhiyao-Know.git
cd Zhiyao-Know
```

---

## 6. 准备模型目录（本地模型）

### 6.1 目录约定

本部署默认使用 `${MODEL_DIR:-./models}`，建议明确指定绝对路径，例如：

```bash
mkdir -p /opt/yuxi-know/Zhiyao-Know/models/Qwen
```

### 6.2 安装 ModelScope（方案一，国内推荐）

```bash
sudo apt install -y python3-pip
python3 -m pip install -U modelscope
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 6.3 登录并下载模型（按选择下载）

```bash
# 如需登录（私有模型或更高配额）
# modelscope login --token <your_modelscope_token>

# Qwen2.5（AWQ）方案
modelscope download --model "Qwen/Qwen2.5-72B-Instruct-AWQ" \
  --local_dir /opt/yuxi-know/Zhiyao-Know/models/Qwen/Qwen2.5-72B-Instruct-AWQ

# Qwen3.5（FP8）方案（若使用 qwen35 compose，请下载）
modelscope download --model "Qwen/Qwen3.5-35B-A3B-FP8" \
  --local_dir /opt/yuxi-know/Zhiyao-Know/models/Qwen/Qwen3.5-35B-A3B-FP8

# 公共 embedding/rerank
modelscope download --model "Qwen/Qwen3-Embedding-0.6B" \
  --local_dir /opt/yuxi-know/Zhiyao-Know/models/Qwen/Qwen3-Embedding-0.6B

modelscope download --model "BAAI/bge-reranker-v2-m3" \
  --local_dir /opt/yuxi-know/Zhiyao-Know/models/BAAI/bge-reranker-v2-m3
```

---

## 7. 配置环境变量

### 7.1 复制模板

```bash
cd /opt/yuxi-know/Zhiyao-Know
cp .env.template .env
```

### 7.2 编辑 `.env`

至少确认以下配置（按需调整）：

```env
MODEL_DIR=/opt/yuxi-know/Zhiyao-Know/models
SAVE_DIR=./saves

# 可选：用于文件 URL 回显
HOST_IP=<你的服务器IP>

# 建议修改默认密码
NEO4J_PASSWORD=<strong_password>
POSTGRES_PASSWORD=<strong_password>

# Docker 镜像源（如需覆盖）
VLLM_OPENAI_IMAGE=docker.m.daocloud.io/vllm/vllm-openai:latest
VLLM_OPENAI_CPU_IMAGE=docker.m.daocloud.io/vllm/vllm-openai-cpu:latest

# LiteLLM 本地构建参数（国内 PyPI 源）
PYTHON_BASE_IMAGE=docker.m.daocloud.io/python:3.11-slim
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
```

---

## 8. 启动服务（使用双 L20 + vLLM 编排）

```bash
mkdir docker/volumes/prometheus/
sudo chown -R 65534:65534 docker/volumes/prometheus/

cd /opt/yuxi-know/Zhiyao-Know
FILE=docker-compose.l20.qwen25.vllm.yml
# 可替换为：
# docker-compose.model-suite.l20.qwen25.vllm.yml
# docker-compose.l20.qwen35.vllm.yml
# docker-compose.model-suite.l20.qwen35.vllm.yml

docker compose -f "$FILE" up -d
```

查看状态：

```bash
docker compose -f "$FILE" ps
```

---

## 9. 健康检查与验收

### 9.1 核心业务服务（仅整套 compose）

```bash
curl -sS http://127.0.0.1/api/system/health
curl -sS http://127.0.0.1/crawler-api/v1/health
```

> 如果使用的是 `model-suite` 文件，这两项不会存在，属于正常情况。

### 9.2 vLLM 服务

```bash
# Token 感知网关（业务侧建议使用）
curl -sS http://127.0.0.1:8010/health/readiness

# 直连后端模型服务（运维排障用）
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8002/health
```

### 9.3 PaddleOCR 服务（仅整套 compose）

```bash
curl -sS http://127.0.0.1:8080/health
```

> 如果使用的是 `model-suite` 文件，默认不包含 OCR 服务。

### 9.4 检查 GPU 占用（LLM 是否在跑）

```bash
nvidia-smi
# Qwen2.5
docker logs -f vllm-qwen25-72b-awq

# Qwen3.5
docker logs -f vllm-qwen35-35b-a3b-fp8
```

---

## 10. 推荐的系统模型配置（可选）

当前项目默认内置了常见云模型配置。若你希望系统默认优先走本地 vLLM 聊天模型，建议在系统设置中新增一个自定义供应商：

- Provider ID：`vllm-l20`
- base_url：`http://vllm-qwen25-72b-awq:8000/v1`（若使用 qwen35，可改为 `http://vllm-qwen35-35b-a3b-fp8:8000/v1`）
- env：`NO_API_KEY`
- models：`["Qwen2.5-72B-Instruct-AWQ"]`

然后将默认模型设置为：

`vllm-l20/Qwen2.5-72B-Instruct-AWQ`（若使用 qwen35，可改为 `vllm-l20/Qwen3.5-35B-A3B-FP8`）

> 说明：embedding/rerank 的模型选择可按你们业务策略进一步在系统配置中统一固定。

---

## 11. 常见问题排查

### 11.1 `docker: command not found`

- Docker 未安装或未加入 PATH  
- 执行第 3 节安装步骤后重新登录 shell

### 11.2 容器起不来，提示 GPU 相关错误

- 检查 `nvidia-smi` 正常
- 检查 `docker run --rm --gpus all ... nvidia-smi` 正常
- 检查 `/etc/docker/daemon.json` 已写入 nvidia runtime（`nvidia-ctk runtime configure`）

### 11.3 vLLM OOM / 启动慢

- 适当降低 `--gpu-memory-utilization`（例如 0.90 -> 0.85）
- 降低 `--max-model-len`
- 首次启动会有权重加载时间，耐心等待健康检查

### 11.4 模型目录挂载错误

- 确认 `.env` 中 `MODEL_DIR` 为绝对路径
- 确认目录下包含：
  - `Qwen/Qwen2.5-72B-Instruct-AWQ`
  - `Qwen/Qwen3.5-35B-A3B-FP8`（如果使用 qwen35）
  - `Qwen/Qwen3-Embedding-0.6B`
  - `BAAI/bge-reranker-v2-m3`

### 11.5 根分区满了，但 `lsblk` 看起来磁盘很大

典型现象：

- `lsblk` 显示磁盘 / LVM 分区很大（如 800G+）
- 但 `df -h /` 仍然 100%

原因通常是：**LVM 逻辑卷扩了，但文件系统没有扩**，或扩容时命令路径写错。

先确认根分区设备与文件系统：

```bash
findmnt -no SOURCE,FSTYPE /
df -hT /
sudo lvs
sudo vgs
```

> 常见命令拼写错误：应使用 `df -h`，不是 `dsk -h`。

#### 11.5.1 一步扩容（推荐）

```bash
sudo lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
df -h /
```

说明：

- `-r` 会尝试自动扩展文件系统
- 设备路径建议用 `/dev/ubuntu-vg/ubuntu-lv`
- 也可用 `/dev/mapper/ubuntu--vg-ubuntu--lv`

#### 11.5.2 `lsblk` 已变大，但 `df -h` 仍没变

这表示需要手动扩文件系统：

```bash
findmnt -no FSTYPE /
```

- 若为 `ext4`：

```bash
sudo resize2fs /dev/ubuntu-vg/ubuntu-lv
```

- 若为 `xfs`：

```bash
sudo xfs_growfs /
```

然后再次检查：

```bash
df -h /
```

#### 11.5.3 仍然显示空间不足

检查是否有“已删除但仍被进程占用”的大文件：

```bash
sudo lsof +L1
```

如果有，重启对应进程/容器后空间会释放。

若文件系统是 ext4，也可适当降低保留块（谨慎）：

```bash
sudo tune2fs -m 1 /dev/ubuntu-vg/ubuntu-lv
```

---

## 12. 常用运维命令

```bash
# 查看所有服务日志
docker compose -f "$FILE" logs -f

# 仅看 vLLM 服务日志（按实际模型）
docker compose -f "$FILE" logs -f vllm-qwen25-72b-awq
docker compose -f "$FILE" logs -f vllm-qwen35-35b-a3b-fp8
docker compose -f "$FILE" logs -f litellm-gateway

# 重启
docker compose -f "$FILE" restart

# 停止
docker compose -f "$FILE" down
```

## 13. Token 限流参数调优（LiteLLM）

默认限流配置在以下文件中：

- `docker/litellm.qwen25.yaml`
- `docker/litellm.qwen35.yaml`

每个模型都有独立的 `rpm` / `tpm` 配置（在 `litellm_params` 下）。

当前默认值（基于双 L20 的稳态配置）：

- **Qwen2.5-72B-Instruct-AWQ**：`rpm=36`，`tpm=90000`
- **Qwen3.5-35B-A3B-FP8**：`rpm=72`，`tpm=180000`

如果并发较高且出现 LLM OOM，可先适当降低：

- Chat 模型的 `tpm`（建议先下调 20%~40%）
- Chat 模型的 `rpm`（建议先下调 20%~40%）

## 14. vLLM 并发参数默认值（双 L20 推荐）

当前 compose 已内置以下默认参数：

- **Qwen2.5-72B-Instruct-AWQ**
  - `--gpu-memory-utilization 0.86`
  - `--max-model-len 16384`
  - `--max-num-seqs 8`
  - `--max-num-batched-tokens 16384`

- **Qwen3.5-35B-A3B-FP8**
  - `--gpu-memory-utilization 0.90`
  - `--max-model-len 24576`
  - `--max-num-seqs 12`
  - `--max-num-batched-tokens 24576`

## 15. Prometheus 可观测性（低内存配置）

当前编排已内置 Prometheus（端口 `9090`），用于统一采集系统指标：

- Prometheus：`http://127.0.0.1:9090`
- API 指标：`http://127.0.0.1:5050/metrics`
- Crawler 指标：`http://127.0.0.1:18060/metrics`
- LiteLLM 指标：`http://127.0.0.1:8010/metrics`
- vLLM 指标：`http://127.0.0.1:8000/metrics`、`http://127.0.0.1:8001/metrics`、`http://127.0.0.1:8002/metrics`
- 基础设施指标：Redis、Postgres、Neo4j、Milvus、etcd、MinIO

默认低内存参数：

- `scrape_interval=30s`
- `retention.time=24h`
- `retention.size=512MB`
- `wal-compression` 开启
- `query.max-concurrency=4`
- `query.max-samples=200000`
- 丢弃 histogram bucket 时序，减少高基数占用

