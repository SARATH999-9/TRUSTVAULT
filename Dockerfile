FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m app && mkdir -p /data/storage && chown -R app /app /data
USER app
ENV STORAGE_DIR=/data/storage
EXPOSE 8000
CMD ["./start.sh"]
