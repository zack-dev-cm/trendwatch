FROM python:3.11-slim

# 1. system deps
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# 2. python deps
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. copy code
COPY app ./app
RUN mkdir -p /data

# 4. non-root user (Cloud Run best practice)
RUN useradd -m svc && chown svc:svc /data
USER svc

ENV PYTHONUNBUFFERED=1
ENV DATA_PATH=/data/trendwatch.parquet

CMD ["python", "-m", "app.server"]
