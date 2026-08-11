import os
from .base import ProviderClient


def marketaux_client() -> ProviderClient:
    return ProviderClient(
        base_url="https://api.marketaux.com/v1",
        api_key=os.environ["MARKETAUX_API_KEY"],
        api_key_param="api_token",
    )
