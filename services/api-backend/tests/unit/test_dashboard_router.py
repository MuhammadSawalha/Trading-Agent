from unittest.mock import patch
from fastapi.testclient import TestClient
from src.app import create_app

@patch("src.routers.dashboard.read_tool_result")
def test_discovery_dashboards_endpoint(mock_read):
    mock_read.side_effect = lambda pk: {"results": [f"{pk}-stock"]}
    client = TestClient(create_app())
    response = client.get("/dashboards/discovery")
    body = response.json()
    assert set(body.keys()) == {"top_gainers", "top_losers", "top_volume", "volume_breakout"}

@patch("src.routers.dashboard.query_process_history")
@patch("src.routers.dashboard.read_agent_output")
@patch("src.routers.dashboard.read_watchlist")
def test_watchlist_dashboard_endpoint(mock_watchlist, mock_agent_output, mock_history):
    mock_watchlist.return_value = ["AAPL"]
    mock_agent_output.return_value = {"net_score": 42.0, "confidence": 60.0, "label": "Bullish, moderate confidence"}
    mock_history.return_value = []
    client = TestClient(create_app())
    response = client.get("/dashboards/watchlist")
    assert response.json()[0]["symbol"] == "AAPL"
    assert response.json()[0]["verdict"]["label"] == "Bullish, moderate confidence"

@patch("src.routers.dashboard.query_process_history")
@patch("src.routers.dashboard.read_agent_output")
def test_symbol_detail_endpoint_includes_per_agent_timestamps(mock_agent_output, mock_history):
    mock_agent_output.side_effect = lambda symbol, agent: {"claims": []} if agent != "Manager" else {"label": "Bullish, moderate confidence"}
    mock_history.return_value = [{"agent": "Sentiment", "timestamp": "2026-01-05T12:00:00+00:00", "status": "finished"}]
    client = TestClient(create_app())
    response = client.get("/symbols/AAPL/detail")
    body = response.json()
    assert "fundamentals" in body["agents"]
    assert body["agents"]["Sentiment"]["last_updated"] == "2026-01-05T12:00:00+00:00"
