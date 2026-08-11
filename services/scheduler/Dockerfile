# services/scheduler/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY packages/common /packages/common
COPY services/scheduler/pyproject.toml services/scheduler/pyproject.toml
COPY services/scheduler/src services/scheduler/src
WORKDIR /app/services/scheduler
RUN pip install --no-cache-dir .
EXPOSE 8002
CMD ["python", "-m", "src.main"]
