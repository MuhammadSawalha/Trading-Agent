from unittest.mock import patch
from fastapi.testclient import TestClient
from src.app import create_app

@patch("src.routers.stream.query_process_history")
def test_symbol_stream_emits_new_process_history_entries(mock_history):
    mock_history.side_effect = [
        [],  # first poll: nothing yet
        [{"agent": "Fundamentals", "status": "started", "timestamp": "2026-01-05T12:00:00+00:00"}],
    ]
    client = TestClient(create_app())
    with client.stream("GET", "/symbols/AAPL/stream?_test_max_polls=2") as response:
        events = [line for line in response.iter_lines() if line.startswith("data:")]
    assert any("Fundamentals" in e for e in events)

@patch("src.routers.stream.read_tool_result")
@patch("src.routers.stream.read_watchlist")
def test_news_stream_emits_new_articles_tagged_by_symbol(mock_watchlist, mock_read_tool_result):
    mock_watchlist.return_value = ["AAPL"]
    mock_read_tool_result.side_effect = [
        {"data": []},
        {"data": [{"uuid": "abc-123", "title": "Apple announces X"}]},
    ]
    client = TestClient(create_app())
    with client.stream("GET", "/stream/news?_test_max_polls=2") as response:
        events = [line for line in response.iter_lines() if line.startswith("data:")]
    assert any("AAPL" in e and "abc-123" in e for e in events)
