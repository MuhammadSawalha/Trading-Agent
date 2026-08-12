from unittest.mock import patch
from fastapi.testclient import TestClient
from src.app import create_app

@patch("src.routers.stream.query_process_history")
def test_symbol_stream_emits_new_process_history_entries(mock_history):
    mock_history.side_effect = [
        [],  # first poll: nothing yet
        [{"agent": "Fundamentals", "status": "started",
          "sk": "2026-01-05T12:00:00+00:00#Fundamentals",
          "timestamp": "2026-01-05T12:00:00+00:00"}],
    ]
    client = TestClient(create_app())
    with client.stream("GET", "/symbols/AAPL/stream?_test_max_polls=2") as response:
        events = [line for line in response.iter_lines() if line.startswith("data:")]
    assert any("Fundamentals" in e for e in events)

@patch("src.routers.stream.query_process_history")
def test_symbol_stream_tags_each_event_with_its_sort_key_as_sse_id(mock_history):
    # An `id:` field makes the stream resumable-in-principle: clients replay
    # from it via the standard Last-Event-ID header.
    mock_history.side_effect = [
        [{"agent": "Risk", "status": "finished",
          "sk": "2026-01-05T12:00:00+00:00#Risk",
          "timestamp": "2026-01-05T12:00:00+00:00"}],
    ]
    client = TestClient(create_app())
    with client.stream("GET", "/symbols/AAPL/stream?_test_max_polls=1") as response:
        lines = list(response.iter_lines())
    assert "id: 2026-01-05T12:00:00+00:00#Risk" in lines

@patch("src.routers.stream.query_process_history")
def test_symbol_stream_emits_keepalive_when_no_new_entries(mock_history):
    # An idle stream must still send bytes, or a proxy with an idle-connection
    # timeout will drop the connection between pipeline runs.
    mock_history.return_value = []
    client = TestClient(create_app())
    with client.stream("GET", "/symbols/AAPL/stream?_test_max_polls=1") as response:
        lines = list(response.iter_lines())
    assert ": keepalive" in lines
    assert not any(line.startswith("data:") for line in lines)

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

@patch("src.routers.stream.read_tool_result")
@patch("src.routers.stream.read_watchlist")
def test_news_stream_emits_keepalive_when_no_new_articles(mock_watchlist, mock_read_tool_result):
    mock_watchlist.return_value = ["AAPL"]
    mock_read_tool_result.return_value = {"data": []}
    client = TestClient(create_app())
    with client.stream("GET", "/stream/news?_test_max_polls=1") as response:
        lines = list(response.iter_lines())
    assert ": keepalive" in lines
    assert not any(line.startswith("data:") for line in lines)

@patch("src.routers.stream.read_tool_result")
@patch("src.routers.stream.read_watchlist")
def test_news_stream_does_not_re_emit_already_seen_articles(mock_watchlist, mock_read_tool_result):
    # Dedup state must survive the move of a poll cycle into a worker thread.
    mock_watchlist.return_value = ["AAPL"]
    mock_read_tool_result.return_value = {
        "data": [{"uuid": "abc-123", "title": "Apple announces X"}]
    }
    client = TestClient(create_app())
    with client.stream("GET", "/stream/news?_test_max_polls=3") as response:
        events = [line for line in response.iter_lines() if line.startswith("data:")]
    assert len(events) == 1
