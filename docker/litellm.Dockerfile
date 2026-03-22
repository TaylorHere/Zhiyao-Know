ARG PYTHON_BASE_IMAGE=docker.m.daocloud.io/python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com

ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}
ENV PIP_NO_CACHE_DIR=1
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken_cache

COPY docker/tiktoken/encodings/o200k_base.tiktoken /tmp/o200k_base.tiktoken

RUN python -m pip install -U pip && \
    pip install "litellm[proxy]" tiktoken prometheus_client && \
    mkdir -p "${TIKTOKEN_CACHE_DIR}" && \
    cp /tmp/o200k_base.tiktoken "${TIKTOKEN_CACHE_DIR}/fb374d419588a4632f3f557e76b4b70aebbca790" && \
    python - <<'PY'
import tiktoken
import tiktoken.load as load

_read_file = load.read_file

def _forbid_remote(blobpath: str) -> bytes:
    if blobpath.startswith("http://") or blobpath.startswith("https://"):
        raise RuntimeError(f"unexpected remote read: {blobpath}")
    return _read_file(blobpath)

load.read_file = _forbid_remote
tiktoken.get_encoding("o200k_base")
PY

EXPOSE 8010

ENTRYPOINT ["litellm"]
CMD ["--config", "/app/config.yaml", "--port", "8010"]
