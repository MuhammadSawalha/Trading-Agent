from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.app import create_app
from src.chat.grounding import build_context

@patch("src.chat.grounding.read_agent_output")
def test_build_context_includes_all_agent_outputs_for_symbol(mock_read):
    mock_read.return_value = {"label": "Bullish, moderate confidence"}
    context = build_context(["AAPL"])
    assert "AAPL" in context
    assert "Bullish, moderate confidence" in context

@patch("src.routers.chat._invoke_chat_llm")
@patch("src.routers.chat.build_context")
def test_chat_endpoint_returns_answer(mock_context, mock_llm):
    mock_context.return_value = "AAPL: Bullish, moderate confidence"
    mock_llm.return_value = "AAPL looks bullish based on the latest analysis."
    client = TestClient(create_app())
    response = client.post("/chat", json={"question": "How does AAPL look?", "symbols": ["AAPL"]})
    assert response.status_code == 200
    assert "bullish" in response.json()["answer"].lower()

@patch("src.routers.chat._invoke_chat_llm")
@patch("src.routers.chat.build_context")
def test_chat_rejects_more_symbols_than_the_watchlist_maximum(mock_context, mock_llm):
    # /chat is unauthenticated and build_context does len(symbols) x 8
    # sequential blocking reads, so an unbounded symbol list is a
    # resource-exhaustion lever.
    client = TestClient(create_app())
    response = client.post(
        "/chat", json={"question": "How do these look?", "symbols": [f"SYM{i}" for i in range(31)]}
    )
    assert response.status_code == 422
    mock_context.assert_not_called()
    mock_llm.assert_not_called()

@patch("src.routers.chat._invoke_chat_llm")
@patch("src.routers.chat.build_context")
def test_chat_rejects_over_length_question(mock_context, mock_llm):
    client = TestClient(create_app())
    response = client.post("/chat", json={"question": "x" * 2001, "symbols": ["AAPL"]})
    assert response.status_code == 422
    mock_llm.assert_not_called()

@patch("src.routers.chat._invoke_chat_llm")
@patch("src.routers.chat.build_context")
def test_chat_accepts_a_request_at_the_limits(mock_context, mock_llm):
    # Boundary check: exactly at the caps must still be accepted, so the
    # limits reject only genuine overruns.
    mock_context.return_value = "context"
    mock_llm.return_value = "an answer"
    client = TestClient(create_app())
    response = client.post(
        "/chat", json={"question": "x" * 2000, "symbols": [f"SYM{i}" for i in range(30)]}
    )
    assert response.status_code == 200

@patch("src.routers.chat.call_own_tool")
@patch("src.routers.chat._invoke_chat_llm")
@patch("src.routers.chat.build_context")
def test_chat_endpoint_degrades_gracefully_when_process_history_call_fails(
    mock_context, mock_llm, mock_call_own_tool
):
    mock_context.return_value = "AAPL: Bullish, moderate confidence"
    mock_llm.return_value = "AAPL looks bullish based on the latest analysis."
    mock_call_own_tool.side_effect = RuntimeError("MCP server unreachable")
    client = TestClient(create_app())
    response = client.post(
        "/chat", json={"question": "When was AAPL last updated?", "symbols": ["AAPL"]}
    )
    assert response.status_code == 200
    assert "bullish" in response.json()["answer"].lower()
    mock_llm.assert_called_once()
