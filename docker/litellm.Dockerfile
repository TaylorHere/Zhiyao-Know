ARG PYTHON_BASE_IMAGE=docker.m.daocloud.io/python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com

ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}
ENV PIP_NO_CACHE_DIR=1

RUN python -m pip install -U pip && \
    pip install "litellm[proxy]" tiktoken && \
    python -c "import tiktoken"

EXPOSE 8010

ENTRYPOINT ["litellm"]
CMD ["--config", "/app/config.yaml", "--port", "8010"]
