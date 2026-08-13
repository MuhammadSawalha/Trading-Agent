# tradingview-mcp-server (https://github.com/atilaahmettaner/tradingview-mcp) speaks MCP over
# stdio only -- it has no HTTP mode of its own. mcp-proxy wraps it as a subprocess and exposes
# an SSE endpoint that our services' streamable_http/sse-based MultiServerMCPClient can reach
# over the docker network, the same way any other HTTP dependency is reached.
FROM python:3.12-slim
# mcp-proxy 0.12.0's open-ended `mcp>=1.17.0` dependency resolves to the latest mcp package by
# default, but mcp 2.0.0 removed/moved `request_ctx` that mcp-proxy's own code still imports --
# an upstream incompatibility, not a real API choice. Pin mcp to 1.29.0 (the same version this
# repo's own services already build against) to avoid it.
RUN pip install --no-cache-dir uv mcp-proxy "mcp==1.29.0"
EXPOSE 8080
CMD ["mcp-proxy", "--port=8080", "--host=0.0.0.0", "--", "uvx", "--from", "tradingview-mcp-server", "tradingview-mcp"]
