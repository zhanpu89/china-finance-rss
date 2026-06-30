FROM docker.1ms.run/python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y chromium --no-install-recommends && rm -rf /var/lib/apt/lists/*

COPY requirements.txt server.py ./
RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8053
EXPOSE 8053

CMD ["python", "server.py"]
