import pytest
import respx
import httpx
from src.clients.base import ProviderClient

@pytest.mark.asyncio
@respx.mock
async def test_get_injects_api_key_as_query_param():
    route = respx.get("https://example.com/thing").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = ProviderClient(base_url="https://example.com", api_key="secret123", api_key_param="token")
    result = await client.get("/thing", {"symbol": "AAPL"})
    assert result == {"ok": True}
    assert route.calls.last.request.url.params["token"] == "secret123"
    assert route.calls.last.request.url.params["symbol"] == "AAPL"

@pytest.mark.asyncio
@respx.mock
async def test_get_raises_on_http_error():
    respx.get("https://example.com/bad").mock(return_value=httpx.Response(500))
    client = ProviderClient(base_url="https://example.com", api_key="k", api_key_param="token")
    with pytest.raises(httpx.HTTPStatusError):
        await client.get("/bad")

@pytest.mark.asyncio
@respx.mock
async def test_get_error_does_not_leak_api_key():
    respx.get("https://example.com/bad").mock(return_value=httpx.Response(401))
    client = ProviderClient(
        base_url="https://example.com", api_key="SUPERSECRETKEY123", api_key_param="token"
    )
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.get("/bad")
    assert "SUPERSECRETKEY123" not in str(exc_info.value)
