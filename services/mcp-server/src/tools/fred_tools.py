from datetime import date, timedelta
from mcp.server.fastmcp import FastMCP
from ..clients.fred_client import fred_client

# Unbounded FRED series calls return full history back to each series' inception (CPI to
# 1947, unemployment to 1948, etc.) -- tens to hundreds of KB per series that gets fed
# straight into the macro_options specialist prompt. Two years of history is enough for a
# macro-trend read and keeps every series (even the daily ones) small.
_DEFAULT_LOOKBACK = timedelta(days=730)

_SERIES_TOOLS = {
    "fred_federal_funds_rate": ("DFF", "Effective federal funds rate, daily."),
    "fred_10y_treasury_yield": ("DGS10", "10-year Treasury constant maturity yield, daily."),
    "fred_2y_treasury_yield": ("DGS2", "2-year Treasury constant maturity yield, daily."),
    "fred_cpi": ("CPIAUCSL", "Consumer Price Index for All Urban Consumers, monthly."),
    "fred_unemployment_rate": ("UNRATE", "US unemployment rate, monthly."),
    "fred_nonfarm_payrolls": ("PAYEMS", "Total nonfarm payroll employment, monthly."),
    "fred_real_gdp": ("GDPC1", "Real Gross Domestic Product, quarterly."),
    "fred_vix": ("VIXCLS", "CBOE Volatility Index, daily."),
    "fred_consumer_sentiment": ("UMCSENT", "University of Michigan Consumer Sentiment Index, monthly."),
}

def register_fred_tools(app: FastMCP) -> None:
    client = fred_client()

    def make_series_tool(series_id: str):
        async def tool(observation_start: str | None = None, observation_end: str | None = None) -> dict:
            params = {"series_id": series_id, "file_type": "json"}
            params["observation_start"] = observation_start or str(date.today() - _DEFAULT_LOOKBACK)
            if observation_end:
                params["observation_end"] = observation_end
            return await client.get("/series/observations", params)
        return tool

    for tool_name, (series_id, description) in _SERIES_TOOLS.items():
        fn = make_series_tool(series_id)
        fn.__name__ = tool_name
        fn.__doc__ = description
        app.add_tool(fn, name=tool_name, description=description)

    @app.tool()
    async def fred_series_search(search_text: str) -> dict:
        """Search FRED for series matching free-text terms (e.g. 'unemployment')."""
        return await client.get("/series/search", {"search_text": search_text, "file_type": "json"})

    @app.tool()
    async def fred_release_calendar(realtime_start: str, realtime_end: str) -> dict:
        """Upcoming FRED data release dates within a date range (YYYY-MM-DD)."""
        return await client.get("/releases/dates", {
            "realtime_start": realtime_start, "realtime_end": realtime_end, "file_type": "json",
        })
