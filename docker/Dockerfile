# PetOps 应用镜像（FastAPI + LangGraph 决策中枢，单进程）。
# 无本地模型 / 无 GPU：LLM 走云端 API，视觉走第三方 API。
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# 使用国内 PyPI 镜像（阿里云）：默认 pypi.org 在国内网络下载大体积 wheel
# （如 cryptography）时经常连接中断（IncompleteRead），与 Docker Hub 拉取镜像
# 需配 daocloud 加速器是同一类问题。同时加大重试次数 / 超时兜底网络抖动。
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ \
    && pip config set global.retries 10 \
    && pip config set global.timeout 120

# 先装依赖（利用构建缓存）：仅复制包元数据与源码后安装。
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

# 入口脚本：等待数据库就绪 → 跑迁移 → 启动 uvicorn。
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
