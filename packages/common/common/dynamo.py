import json
import os
import uuid
from datetime import datetime, timezone

import boto3

_OFFLOAD_THRESHOLD_BYTES = 300_000

def _to_utc(dt: datetime) -> datetime:
    """Normalize a datetime to an aware, UTC datetime.

    Naive datetimes are treated as already being UTC (rather than local time,
    which is what `.timestamp()`/`.isoformat()` would otherwise silently
    assume). Aware datetimes are converted to UTC so stored/queried
    timestamps are always directly comparable as strings or as datetimes.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _dynamo_resource():
    kwargs = {"region_name": os.environ.get("AWS_REGION", "us-east-1")}
    if endpoint := os.environ.get("DYNAMODB_ENDPOINT"):
        kwargs["endpoint_url"] = endpoint
    return boto3.resource("dynamodb", **kwargs)

def _s3_client():
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))

def ensure_tables_for_test() -> None:
    """Test-only helper: creates all three tables against the current (mocked) DynamoDB."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "services", "mcp-server"))
    from src.dynamo_schema import TABLE_DEFINITIONS
    client = boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    for definition in TABLE_DEFINITIONS.values():
        client.create_table(**definition)

def write_tool_result(pk: str, payload: dict, ttl_seconds: int) -> None:
    table = _dynamo_resource().Table("ToolResults")
    expires_at = int(datetime.now(timezone.utc).timestamp()) + ttl_seconds
    serialized = json.dumps(payload)
    if len(serialized.encode()) > _OFFLOAD_THRESHOLD_BYTES:
        bucket = os.environ["TOOL_PAYLOADS_BUCKET"]
        key = f"{pk}/{uuid.uuid4()}.json"
        _s3_client().put_object(Bucket=bucket, Key=key, Body=serialized.encode())
        table.put_item(Item={"pk": pk, "s3_bucket": bucket, "s3_key": key, "expires_at": expires_at})
    else:
        table.put_item(Item={"pk": pk, "payload": serialized, "expires_at": expires_at})

def read_tool_result(pk: str) -> dict | None:
    table = _dynamo_resource().Table("ToolResults")
    item = table.get_item(Key={"pk": pk}).get("Item")
    if item is None:
        return None
    if "s3_key" in item:
        obj = _s3_client().get_object(Bucket=item["s3_bucket"], Key=item["s3_key"])
        return json.loads(obj["Body"].read())
    return json.loads(item["payload"])

def write_agent_output(symbol: str, agent_name: str, payload: dict) -> None:
    table = _dynamo_resource().Table("AgentOutputs")
    table.put_item(Item={
        "symbol": symbol, "agent_name": agent_name,
        "payload": json.dumps(payload),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

def read_agent_output(symbol: str, agent_name: str) -> dict | None:
    table = _dynamo_resource().Table("AgentOutputs")
    item = table.get_item(Key={"symbol": symbol, "agent_name": agent_name}).get("Item")
    return json.loads(item["payload"]) if item else None

def append_process_history(symbol: str, agent: str, reason: str, status: str, timestamp: datetime) -> None:
    timestamp = _to_utc(timestamp)
    table = _dynamo_resource().Table("ProcessHistory")
    sk = f"{timestamp.isoformat()}#{agent}"
    table.put_item(Item={
        "symbol": symbol, "sk": sk, "agent": agent,
        "reason": reason, "status": status, "timestamp": timestamp.isoformat(),
    })

def query_process_history(symbol: str, since: datetime | None = None) -> list[dict]:
    # ProcessHistory is an append-only audit log, so a symbol's history grows without
    # bound. DynamoDB returns at most 1MB per query page and signals more data with
    # LastEvaluatedKey; without draining every page this returns only the *oldest*
    # 1MB, silently freezing every "last updated" consumer on stale data forever.
    #
    # `since`, when given, is applied as a range condition on `sk` rather than as a
    # client-side filter after the fact: `sk` is written as
    # f"{timestamp.isoformat()}#{agent}" (see append_process_history above), and a bare
    # ISO-8601 timestamp string is a strict prefix of any `sk` sharing that timestamp, so
    # Key("sk").gte(since.isoformat()) is a correct inclusive lower bound. This lets
    # DynamoDB itself skip everything older instead of fetching it and discarding it here.
    table = _dynamo_resource().Table("ProcessHistory")
    key_condition = boto3.dynamodb.conditions.Key("symbol").eq(symbol)
    if since is not None:
        since_iso = _to_utc(since).isoformat()
        key_condition = key_condition & boto3.dynamodb.conditions.Key("sk").gte(since_iso)
    items = []
    kwargs = {"KeyConditionExpression": key_condition}
    while True:
        response = table.query(**kwargs)
        items.extend(response["Items"])
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return sorted(items, key=lambda i: i["sk"])

def get_latest_process_history_entry(symbol: str) -> dict | None:
    # Cheap, bounded alternative to query_process_history for callers that only need
    # the single newest entry (e.g. a "last updated" display) rather than the full
    # history. ScanIndexForward=False returns items in descending `sk` order, and since
    # `sk` is timestamp-prefixed (see append_process_history), the first item is the
    # newest -- so Limit=1 reads exactly one item instead of draining the whole table.
    table = _dynamo_resource().Table("ProcessHistory")
    response = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("symbol").eq(symbol),
        ScanIndexForward=False,
        Limit=1,
    )
    items = response["Items"]
    return items[0] if items else None

_FETCH_ATTEMPT_TTL_SECONDS = 7 * 86400  # generous fixed window, independent of any tool's own cadence

def record_fetch_attempt(pk: str, timestamp: datetime) -> None:
    """Records that a *successful* live call was made for `pk`, independent of whether the
    fetched value actually changed. This is deliberately separate from write_tool_result,
    which only writes on a diff — cadence enforcement (Task 16's _is_due) needs "when did we
    last try" even when the value has been stable for a while and nothing gets rewritten."""
    timestamp = _to_utc(timestamp)
    table = _dynamo_resource().Table("ToolResults")
    expires_at = int(timestamp.timestamp()) + _FETCH_ATTEMPT_TTL_SECONDS
    table.put_item(Item={"pk": f"{pk}#LAST_ATTEMPT", "attempted_at": timestamp.isoformat(), "expires_at": expires_at})

def get_last_fetch_attempt(pk: str) -> datetime | None:
    table = _dynamo_resource().Table("ToolResults")
    item = table.get_item(Key={"pk": f"{pk}#LAST_ATTEMPT"}).get("Item")
    return datetime.fromisoformat(item["attempted_at"]) if item else None

_WATCHLIST_PK = "WATCHLIST#CONFIG"
_WATCHLIST_MAX_SIZE = 30
_WATCHLIST_TTL_SECONDS = 10 * 365 * 24 * 3600  # effectively permanent

class WatchlistFullError(Exception):
    pass

def read_watchlist() -> list[str]:
    result = read_tool_result(_WATCHLIST_PK)
    return result["symbols"] if result else []

def add_to_watchlist(symbol: str) -> None:
    symbols = read_watchlist()
    if symbol in symbols:
        return
    if len(symbols) >= _WATCHLIST_MAX_SIZE:
        raise WatchlistFullError(f"watchlist is at its {_WATCHLIST_MAX_SIZE}-symbol maximum")
    write_tool_result(_WATCHLIST_PK, {"symbols": symbols + [symbol]}, ttl_seconds=_WATCHLIST_TTL_SECONDS)

def remove_from_watchlist(symbol: str) -> None:
    symbols = [s for s in read_watchlist() if s != symbol]
    write_tool_result(_WATCHLIST_PK, {"symbols": symbols}, ttl_seconds=_WATCHLIST_TTL_SECONDS)
    delete_symbol_data(symbol)

def delete_symbol_data(symbol: str) -> None:
    """Purges every trace of a symbol's derived/cached state -- ToolResults (raw fetches AND
    the LAST_ATTEMPT cadence markers, both keyed f"{symbol}#..."), AgentOutputs, and
    ProcessHistory -- so re-adding the symbol later is a genuine cold start instead of
    resuming mid-stream on leftover data from before it was removed."""
    _delete_tool_results_for_symbol(symbol)
    _delete_agent_outputs_for_symbol(symbol)
    _delete_process_history_for_symbol(symbol)

def _delete_tool_results_for_symbol(symbol: str) -> None:
    # ToolResults' only key is `pk`, with no symbol attribute to Query on, so finding every
    # f"{symbol}#..." row (all per-symbol fetches plus their LAST_ATTEMPT markers) means
    # scanning the whole table. Fine at this table's scale (one row per watchlist symbol per
    # tool, capped at 30 symbols) -- a GSI would be overkill for a purge that only runs on
    # removal, not on any hot path.
    table = _dynamo_resource().Table("ToolResults")
    prefix = f"{symbol}#"
    scan_kwargs = {
        "FilterExpression": boto3.dynamodb.conditions.Attr("pk").begins_with(prefix),
        "ProjectionExpression": "pk",
    }
    with table.batch_writer() as batch:
        while True:
            response = table.scan(**scan_kwargs)
            for item in response["Items"]:
                batch.delete_item(Key={"pk": item["pk"]})
            if "LastEvaluatedKey" not in response:
                break
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

def _delete_agent_outputs_for_symbol(symbol: str) -> None:
    table = _dynamo_resource().Table("AgentOutputs")
    response = table.query(KeyConditionExpression=boto3.dynamodb.conditions.Key("symbol").eq(symbol))
    with table.batch_writer() as batch:
        for item in response["Items"]:
            batch.delete_item(Key={"symbol": item["symbol"], "agent_name": item["agent_name"]})

def _delete_process_history_for_symbol(symbol: str) -> None:
    table = _dynamo_resource().Table("ProcessHistory")
    with table.batch_writer() as batch:
        for entry in query_process_history(symbol):
            batch.delete_item(Key={"symbol": entry["symbol"], "sk": entry["sk"]})
