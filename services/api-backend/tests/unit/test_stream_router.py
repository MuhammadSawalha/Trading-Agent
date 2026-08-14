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

def _article(uuid: str, title: str, symbol: str = "AAPL", language: str = "en",
             name: str = "Apple Inc.", other_equities: tuple[str, ...] = ()):
    entities = [{"symbol": symbol, "name": name, "type": "equity"}]
    entities += [{"symbol": s, "name": s, "type": "equity"} for s in other_equities]
    return {"uuid": uuid, "title": title, "language": language, "entities": entities}

@patch("src.routers.stream.read_tool_result")
@patch("src.routers.stream.read_watchlist")
def test_news_stream_emits_new_articles_tagged_by_symbol(mock_watchlist, mock_read_tool_result):
    mock_watchlist.return_value = ["AAPL"]
    mock_read_tool_result.side_effect = [
        {"data": []},
        {"data": [_article("abc-123", "Apple announces X")]},
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
    mock_read_tool_result.return_value = {"data": [_article("abc-123", "Apple announces X")]}
    client = TestClient(create_app())
    with client.stream("GET", "/stream/news?_test_max_polls=3") as response:
        events = [line for line in response.iter_lines() if line.startswith("data:")]
    assert len(events) == 1

@patch("src.routers.stream.read_tool_result")
@patch("src.routers.stream.read_watchlist")
def test_news_stream_drops_non_english_articles(mock_watchlist, mock_read_tool_result):
    mock_watchlist.return_value = ["AAPL"]
    mock_read_tool_result.return_value = {
        "data": [_article("abc-123", "Apple annonce X", language="fr")]
    }
    client = TestClient(create_app())
    with client.stream("GET", "/stream/news?_test_max_polls=1") as response:
        lines = list(response.iter_lines())
    assert not any(line.startswith("data:") for line in lines)

@patch("src.routers.stream.read_tool_result")
@patch("src.routers.stream.read_watchlist")
def test_news_stream_drops_broad_roundups_that_only_mention_the_symbol_in_passing(mock_watchlist, mock_read_tool_result):
    # A "top 10 holdings" roundup that tags AAPL as one of six equities but is not
    # actually about Apple -- the company name never appears in the headline either.
    mock_watchlist.return_value = ["AAPL"]
    mock_read_tool_result.return_value = {
        "data": [_article(
            "abc-123", "Norwegian fund's top holdings surge in value",
            other_equities=("NVDA", "MSFT", "GOOGL", "AVGO"),
        )]
    }
    client = TestClient(create_app())
    with client.stream("GET", "/stream/news?_test_max_polls=1") as response:
        lines = list(response.iter_lines())
    assert not any(line.startswith("data:") for line in lines)

@patch("src.routers.stream.read_tool_result")
@patch("src.routers.stream.read_watchlist")
def test_news_stream_keeps_single_subject_articles_that_use_a_product_name(mock_watchlist, mock_read_tool_result):
    # Real headlines often lead with a product/brand instead of the legal entity name
    # ("Azure" rather than "Microsoft") -- an article tagging only that one equity should
    # still count as relevant even though "Microsoft" never appears in the title.
    mock_watchlist.return_value = ["MSFT"]
    mock_read_tool_result.return_value = {
        "data": [_article(
            "abc-123", "Azure, Foundries, and Accelerators: Grading the AI Buildout's Big Three",
            symbol="MSFT", name="Microsoft Corporation",
        )]
    }
    client = TestClient(create_app())
    with client.stream("GET", "/stream/news?_test_max_polls=1") as response:
        events = [line for line in response.iter_lines() if line.startswith("data:")]
    assert any("abc-123" in e for e in events)

@patch("src.routers.stream.read_tool_result")
@patch("src.routers.stream.read_watchlist")
def test_news_stream_matches_common_ticker_brand_alias_in_a_broad_roundup(mock_watchlist, mock_read_tool_result):
    # GOOGL's tagged entity name is "Alphabet Inc.", but headlines almost always say
    # "Google" -- the alias table must let this through even in a multi-equity roundup
    # where the entity-count shortcut alone wouldn't apply.
    mock_watchlist.return_value = ["GOOGL"]
    mock_read_tool_result.return_value = {
        "data": [_article(
            "abc-123", "Google unveils new AI model, Amazon and Meta play catch-up",
            symbol="GOOGL", name="Alphabet Inc.", other_equities=("AMZN", "META"),
        )]
    }
    client = TestClient(create_app())
    with client.stream("GET", "/stream/news?_test_max_polls=1") as response:
        events = [line for line in response.iter_lines() if line.startswith("data:")]
    assert any("abc-123" in e for e in events)
