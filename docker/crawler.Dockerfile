FROM python:3.12-slim

WORKDIR /app

ENV TZ=Asia/Shanghai \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY crawler_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt  -i https://pypi.tuna.tsinghua.edu.cn/simple
RUN crawl4ai-setup

COPY crawler_service /app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5060", "--reload"]
