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
    table = _dynamo_resource().Table("ProcessHistory")
    items = []
    kwargs = {"KeyConditionExpression": boto3.dynamodb.conditions.Key("symbol").eq(symbol)}
    while True:
        response = table.query(**kwargs)
        items.extend(response["Items"])
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    items = sorted(items, key=lambda i: i["sk"])
    if since is not None:
        since_utc = _to_utc(since).isoformat()
        items = [i for i in items if i["timestamp"] >= since_utc]
    return items

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
