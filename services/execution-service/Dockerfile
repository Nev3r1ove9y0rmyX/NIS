# execution-service —— 统一 Python 基础镜像（docs/soa-deployment.md 第 8 节）。
# 构建上下文为仓库根目录：docker build -f services/execution-service/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/_shared \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY services/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services/_shared /app/_shared
COPY services/execution-service/app /app/app
COPY services/execution-service/alembic /app/alembic
COPY services/execution-service/alembic.ini /app/alembic.ini
RUN useradd --create-home --uid 10001 nis && chown -R nis:nis /app
USER nis

EXPOSE 8005

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8005/health/live', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
