# -----------------------------
# NAS Media Player Dockerfile
# -----------------------------
FROM python:3.9-slim

LABEL maintainer="神雕<teasiu@qq.com>"
LABEL version="1.2"
LABEL description="NAS Media Player 多架构Python版Docker镜像"

# -----------------------------
# 环境变量
# -----------------------------
ENV APP_DIR=/opt/nas-media-player \
    VIDEO_DIR=/mnt \
    PORT=8800 \
    LOG_FILE=/opt/nas-media-player/nas-media-player.log \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# -----------------------------
# 创建目录
# -----------------------------
RUN mkdir -p ${APP_DIR}/static \
    && mkdir -p ${VIDEO_DIR} \
    && chmod 777 ${APP_DIR} ${VIDEO_DIR} ${APP_DIR}/static

# -----------------------------
# 日志文件
# -----------------------------
RUN touch ${LOG_FILE} && chmod 666 ${LOG_FILE}

# -----------------------------
# 安装依赖工具
# -----------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl procps \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# 复制 requirements 并安装
# -----------------------------
COPY requirements.txt ${APP_DIR}/
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r ${APP_DIR}/requirements.txt

# -----------------------------
# 复制程序和静态文件
# -----------------------------
COPY nas-media-player.py ${APP_DIR}/
COPY index.html zhinan.html ${APP_DIR}/static/

# -----------------------------
# 暴露端口
# -----------------------------
EXPOSE ${PORT}

# -----------------------------
# EntryPoint：直接运行 Python
# -----------------------------
RUN echo '#!/bin/sh' > /entrypoint.sh && \
    echo 'cd ${APP_DIR}' >> /entrypoint.sh && \
    echo 'echo "NAS Media Player 启动中... 端口：${PORT}"' >> /entrypoint.sh && \
    echo 'exec python3 nas-media-player.py >> ${LOG_FILE} 2>&1' >> /entrypoint.sh && \
    chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

