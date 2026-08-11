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
