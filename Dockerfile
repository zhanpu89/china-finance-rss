FROM docker.1ms.run/python:3.12-slim

WORKDIR /app

RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    apt-get update && apt-get install -y chromium --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt server.py ./
RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8053
EXPOSE 8053

CMD ["python", "server.py"]
