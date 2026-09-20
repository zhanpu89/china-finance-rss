FROM docker.1ms.run/python:3.12-slim

WORKDIR /app

ENV TZ=Asia/Shanghai

# apt 源域名开关：默认阿里云公网镜像站，各云通用；仅阿里云 ECS 构建时由
# doc/deploy/docker-compose.aliyun-2c2g.yml 的 build.args 注入内网域名
# mirrors.cloud.aliyuncs.com（不占公网流量；公网 5Mbps 实测 1519s，内网 <2min）。
# ARG 须位于引用它的 RUN 之前。
ARG APT_MIRROR=mirrors.aliyun.com

RUN sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null; \
    sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    apt-get update && apt-get install -y chromium --no-install-recommends && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tzdata \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
        libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
COPY china_finance_rss/ china_finance_rss/
RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8053 PYTHONUNBUFFERED=1 MAX_WORKERS=20
# 只写 EXPOSE 8054 是不够的：config.STREAM_HOST 默认 127.0.0.1，裸
# `docker run -p 8054:8054` 会把 SSE 端口绑到容器回环 ⇒ 宿主不可达，与 EXPOSE
# 声明的意图不符（docker-compose.yml 已显式设 STREAM_HOST=0.0.0.0，此处对齐）。
ENV STREAM_HOST=0.0.0.0
EXPOSE 8053 8054

CMD ["python", "-m", "china_finance_rss.server"]
