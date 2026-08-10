import os
from .base import ProviderClient

def finnhub_client() -> ProviderClient:
    return ProviderClient(
        base_url="https://finnhub.io/api/v1",
        api_key=os.environ["FINNHUB_API_KEY"],
        api_key_param="token",
    )
