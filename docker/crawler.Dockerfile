FROM python:3.12-slim

WORKDIR /app

ENV TZ=Asia/Shanghai \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources; \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 update; \
    apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 install -y --no-install-recommends curl; \
    rm -rf /var/lib/apt/lists/*

COPY crawler_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt  -i https://pypi.tuna.tsinghua.edu.cn/simple
RUN PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright \
    PLAYWRIGHT_DOWNLOAD_BASE_URL=https://registry.npmmirror.com/-/binary/playwright \
    crawl4ai-setup

COPY crawler_service /app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5060", "--reload"]
