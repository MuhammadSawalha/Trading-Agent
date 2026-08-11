# services/mcp-server/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY packages/common /app/packages/common
COPY services/mcp-server/pyproject.toml services/mcp-server/pyproject.toml
COPY services/mcp-server/src services/mcp-server/src
WORKDIR /app/services/mcp-server
RUN pip install --no-cache-dir .
EXPOSE 8001
CMD ["python", "-m", "src.server"]
