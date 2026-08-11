from pathlib import Path
import yaml

# Final review Finding 1: docker-compose.yaml's scheduler service must set the exact env var
# names build_mcp_client() (src/mcp_clients.py) reads via os.environ[...] -- OWN_MCP_SERVER_URL,
# TRADINGVIEW_MCP_URL, STOCK_SCANNER_MCP_URL -- not the unused MCP_SERVER_URL name that no
# Python in this repo reads. Verified live: running the scheduler entrypoint under the old env
# raised KeyError: 'OWN_MCP_SERVER_URL'.
_COMPOSE_PATH = Path(__file__).resolve().parents[4] / "docker-compose.yaml"


def _scheduler_service() -> dict:
    with open(_COMPOSE_PATH) as f:
        compose = yaml.safe_load(f)
    return compose["services"]["scheduler"]


def test_scheduler_service_sets_own_mcp_server_url_matching_the_mcp_servers_mount_path():
    # FastMCP's default streamable_http_path is "/mcp" (services/mcp-server/src/server.py's
    # create_app() never overrides it), so the URL the scheduler dials must include that path
    # -- a bare host:port would 404 every tool call.
    env = _scheduler_service()["environment"]
    assert env["OWN_MCP_SERVER_URL"] == "http://mcp-server:8001/mcp"


def test_scheduler_service_no_longer_sets_the_unused_mcp_server_url_var():
    env = _scheduler_service()["environment"]
    assert "MCP_SERVER_URL" not in env


def test_scheduler_service_sets_third_party_mcp_urls_from_env_file():
    # tradingview/stock_scanner are third-party MCP servers with no service defined in this
    # compose file -- their endpoints must come from the .env-provided vars, not be hardcoded.
    env = _scheduler_service()["environment"]
    assert env["TRADINGVIEW_MCP_URL"] == "${TRADINGVIEW_MCP_URL:-}"
    assert env["STOCK_SCANNER_MCP_URL"] == "${STOCK_SCANNER_MCP_URL:-}"
