FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt server.py ./
RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8053
EXPOSE 8053

CMD ["python", "server.py"]
