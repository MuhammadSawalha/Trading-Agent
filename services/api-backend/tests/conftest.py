import sys
from pathlib import Path

import pytest

# Add the project root to Python path so imports like 'from src.app import create_app' work
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(autouse=True)
def _own_mcp_server_url(monkeypatch):
    monkeypatch.setenv("OWN_MCP_SERVER_URL", "http://mcp-server:8001/mcp")
