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

@patch("src.routers.dashboard.read_tool_result")
@patch("src.routers.dashboard.query_process_history")
@patch("src.routers.dashboard.read_agent_output")
@patch("src.routers.dashboard.read_watchlist")
def test_watchlist_dashboard_endpoint(mock_watchlist, mock_agent_output, mock_history, mock_read_tool_result):
    mock_watchlist.return_value = ["AAPL"]
    mock_agent_output.return_value = {"net_score": 42.0, "confidence": 60.0, "label": "Bullish, moderate confidence"}
    mock_history.return_value = []
    mock_read_tool_result.return_value = {"c": 191.24, "d": 2.31, "dp": 1.22}
    client = TestClient(create_app())
    response = client.get("/dashboards/watchlist")
    row = response.json()[0]
    assert row["symbol"] == "AAPL"
    assert row["verdict"]["label"] == "Bullish, moderate confidence"
    # Spec 8.1 requires price and % change on every row.
    assert row["price"] == 191.24
    assert row["percent_change"] == 1.22
    mock_read_tool_result.assert_called_once_with("AAPL#finnhub_quote")

@patch("src.routers.dashboard.read_tool_result")
@patch("src.routers.dashboard.query_process_history")
@patch("src.routers.dashboard.read_agent_output")
@patch("src.routers.dashboard.read_watchlist")
def test_watchlist_dashboard_tolerates_an_uncached_quote(mock_watchlist, mock_agent_output, mock_history, mock_read_tool_result):
    # A symbol added moments ago has no cached quote yet; that must null out
    # two fields, not fail the whole dashboard.
    mock_watchlist.return_value = ["AAPL"]
    mock_agent_output.return_value = {}
    mock_history.return_value = []
    mock_read_tool_result.return_value = None
    client = TestClient(create_app())
    response = client.get("/dashboards/watchlist")
    assert response.status_code == 200
    row = response.json()[0]
    assert row["price"] is None
    assert row["percent_change"] is None

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
