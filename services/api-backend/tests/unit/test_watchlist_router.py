import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from src.app import create_app

@patch("src.routers.watchlist.add_to_watchlist")
@patch("src.routers.watchlist.call_own_tool", new_callable=AsyncMock)
def test_add_validates_symbol_before_adding(mock_call_tool, mock_add):
    mock_call_tool.return_value = {"name": "Apple Inc"}
    client = TestClient(create_app())
    response = client.post("/watchlist/AAPL")
    assert response.status_code == 201
    mock_add.assert_called_once_with("AAPL")

@patch("src.routers.watchlist.add_to_watchlist")
@patch("src.routers.watchlist.call_own_tool", new_callable=AsyncMock)
def test_add_rejects_invalid_symbol(mock_call_tool, mock_add):
    mock_call_tool.return_value = {}  # empty response = invalid symbol, per spec §3
    client = TestClient(create_app())
    response = client.post("/watchlist/BADSYMBOL")
    assert response.status_code == 422
    mock_add.assert_not_called()

@patch("src.routers.watchlist.remove_from_watchlist")
def test_remove(mock_remove):
    client = TestClient(create_app())
    response = client.delete("/watchlist/AAPL")
    assert response.status_code == 204
    mock_remove.assert_called_once_with("AAPL")

@patch("src.routers.watchlist.read_watchlist")
def test_list(mock_read):
    mock_read.return_value = ["AAPL", "MSFT"]
    client = TestClient(create_app())
    response = client.get("/watchlist")
    assert response.json() == ["AAPL", "MSFT"]
