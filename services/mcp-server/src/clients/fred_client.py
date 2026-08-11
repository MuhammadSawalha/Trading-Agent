import os
from .base import ProviderClient

def fred_client() -> ProviderClient:
    return ProviderClient(
        base_url="https://api.stlouisfed.org/fred",
        api_key=os.environ["FRED_API_KEY"],
        api_key_param="api_key",
    )
