import httpx


class ProviderClient:
    def __init__(self, base_url: str, api_key: str, api_key_param: str):
        self._api_key = api_key
        self._api_key_param = api_key_param
        self._client = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def get(self, path: str, params: dict | None = None) -> dict:
        query = dict(params or {})
        query[self._api_key_param] = self._api_key
        response = await self._client.get(path, params=query)
        response.raise_for_status()
        return response.json()
