# services/api-backend/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY packages/common /app/packages/common
COPY services/api-backend/pyproject.toml services/api-backend/pyproject.toml
COPY services/api-backend/src services/api-backend/src
WORKDIR /app/services/api-backend
RUN pip install --no-cache-dir . uvicorn
EXPOSE 8080
CMD ["uvicorn", "src.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
