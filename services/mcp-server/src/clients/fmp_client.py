import os
from .base import ProviderClient

def fmp_client() -> ProviderClient:
    return ProviderClient(
        base_url="https://financialmodelingprep.com/stable",
        api_key=os.environ["FMP_API_KEY"],
        api_key_param="apikey",
    )
