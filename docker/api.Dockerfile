# 使用轻量级Python基础镜像
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7.2 /uv /uvx /bin/
COPY --from=node:20-slim /usr/local/bin /usr/local/bin
COPY --from=node:20-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node:20-slim /usr/local/include /usr/local/include
COPY --from=node:20-slim /usr/local/share /usr/local/share

# 设置工作目录
WORKDIR /app

# 环境变量设置
ENV TZ=Asia/Shanghai \
    UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_COMPILE_BYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

RUN npm install -g npm@latest && npm cache clean --force
ARG INSTALL_LIBREOFFICE=true

# 设置代理和时区，更换镜像源，安装系统依赖 - 合并为一个RUN减少层数
RUN set -ex \
    # (A) 设置时区
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    # (B) 替换阿里源 (针对 Debian Bookworm 的新版格式)
    && sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|security.debian.org/debian-security|mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    # (C) 安装必要的系统库
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 update \
    && apt-get install -y --no-install-recommends --fix-missing \
    curl \
    ffmpeg \
    libsm6 \
    libxext6 \
    && if [ "${INSTALL_LIBREOFFICE}" = "true" ]; then \
        apt-get install -y --no-install-recommends --fix-missing \
        libreoffice-writer \
        libreoffice-core; \
       fi \
    # (D) 清理垃圾，减小体积
    && apt-get clean \
    && rm -rf /var/cache/apt/archives/* \
    && rm -rf /var/lib/apt/lists/*


# 复制项目配置文件
COPY ../pyproject.toml /app/pyproject.toml
COPY ../.python-version /app/.python-version
COPY ../uv.lock /app/uv.lock
COPY ../.wheels /tmp/wheels

# 统一使用阿里源
RUN sed -i 's|https://pypi.tuna.tsinghua.edu.cn|https://mirrors.aliyun.com/pypi|g' /app/uv.lock

# 方法一：优先使用仓库内预下载的 CPU wheel，避免构建时反复拉取 torch 大包
RUN set -ex \
    && if ls /tmp/wheels/torch-*.whl /tmp/wheels/torchvision-*.whl >/dev/null 2>&1; then \
        pip install --no-cache-dir --no-index --find-links=/tmp/wheels torch torchvision; \
    else \
        echo "No local torch cpu wheels found in /tmp/wheels, fallback to online indexes."; \
    fi

# 安装其余依赖；torch/torchvision 若已离线安装，这里会复用已安装版本
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen \
    --index-url https://mirrors.aliyun.com/pypi/simple \
    --extra-index-url https://download.pytorch.org/whl/cpu

RUN python -m pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple tiktoken

RUN rm -rf /tmp/wheels

# 激活虚拟环境并添加到PATH
ENV PATH="/app/.venv/bin:$PATH"
RUN echo 'export PATH="/app/.venv/bin:$PATH"' >> /root/.bashrc

# 复制代码到容器中
COPY ../src /app/src
COPY ../server /app/server
COPY ../scripts /app/scripts
