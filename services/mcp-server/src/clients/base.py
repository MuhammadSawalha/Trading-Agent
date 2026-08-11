import logging

import httpx

# FastMCP's __init__ calls configure_logging(), which sets the root logger
# to INFO. At that level httpx logs each outgoing request URL, including the
# query string -- and ProviderClient.get() puts the provider API key in the
# query string. Suppress httpx's own request-logging so API keys never land
# in plaintext logs. Set here at import time (rather than only inside
# create_app()) so it's active regardless of how a FastMCP/httpx client gets
# constructed -- e.g. test fixtures that build FastMCP("test") directly.
logging.getLogger("httpx").setLevel(logging.WARNING)


class ProviderClient:
    def __init__(self, base_url: str, api_key: str, api_key_param: str):
        self._api_key = api_key
        self._api_key_param = api_key_param
        self._client = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def get(self, path: str, params: dict | None = None) -> dict:
        query = dict(params or {})
        query[self._api_key_param] = self._api_key
        response = await self._client.get(path, params=query)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            safe_url = exc.request.url.copy_remove_param(self._api_key_param)
            raise httpx.HTTPStatusError(
                f"HTTP {exc.response.status_code} for url '{safe_url}'",
                request=exc.request,
                response=exc.response,
            ) from None
        return response.json()
