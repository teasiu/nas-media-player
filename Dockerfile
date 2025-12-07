FROM python:3.9-slim
LABEL maintainer="神雕<teasiu@qq.com>"
LABEL version="1.0"
LABEL description="NAS Media Player 多架构Python版Docker镜像"

ENV APP_DIR=/opt/nas-media-player \
    VIDEO_DIR=/mnt \
    PORT=8800 \
    LOG_FILE=/opt/nas-media-player/nas-media-player.log \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p ${APP_DIR}/static
RUN mkdir -p ${VIDEO_DIR}

RUN chmod 777 ${APP_DIR} && \
    chmod 777 ${VIDEO_DIR} && \
    chmod 777 ${APP_DIR}/static

RUN touch ${LOG_FILE} && chmod 666 ${LOG_FILE}

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl procps && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ${APP_DIR}/
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r ${APP_DIR}/requirements.txt

COPY nas-media-player.py ${APP_DIR}/
COPY index.html zhinan.html ${APP_DIR}/static/

EXPOSE ${PORT}

RUN echo '#!/bin/sh' > /entrypoint.sh && \
    echo 'cd ${APP_DIR}' >> /entrypoint.sh && \
    echo 'echo "NAS Media Player 启动中... 端口：${PORT}"' >> /entrypoint.sh && \
    echo 'exec uvicorn --host 0.0.0.0 --port ${PORT} nas-media-player:app >> ${LOG_FILE} 2>&1' >> /entrypoint.sh && \
    chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

