# Container image for Railway, Fly.io, a VPS or an office server.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LCN_DATABASE=/data/compliance.db PORT=8000
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m appuser && mkdir -p /data && chown appuser /data
USER appuser
VOLUME ["/data"]
EXPOSE 8000
CMD ["gunicorn", "-c", "gunicorn.conf.py", "run:app"]
