# stock-scanner-mcp (https://mcpservers.org/servers/yyordanov-tradu/stock-scanner-mcp) is an
# npm package that speaks MCP over stdio only. mcp-proxy (Python) wraps it as a subprocess and
# exposes an SSE endpoint our services can reach over the docker network -- hence both node
# (to run the npm package) and python (to run mcp-proxy) in this one image.
FROM node:22-slim
# mcp-proxy 0.12.0's open-ended `mcp>=1.17.0` dependency resolves to the latest mcp package by
# default, but mcp 2.0.0 removed/moved `request_ctx` that mcp-proxy's own code still imports --
# an upstream incompatibility, not a real API choice. Pin mcp to 1.29.0 (the same version this
# repo's own services already build against) to avoid it.
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip \
    && pip install --no-cache-dir --break-system-packages mcp-proxy "mcp==1.29.0" \
    && rm -rf /var/lib/apt/lists/*
EXPOSE 8080
CMD ["mcp-proxy", "--port=8080", "--host=0.0.0.0", "--", "npx", "-y", "stock-scanner-mcp"]
