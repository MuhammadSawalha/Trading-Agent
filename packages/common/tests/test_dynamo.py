import json
import boto3
import pytest
from moto import mock_aws
from datetime import datetime, timedelta, timezone
from common.dynamo import (
    read_tool_result, write_tool_result,
    read_agent_output, write_agent_output,
    append_process_history, query_process_history,
    get_latest_process_history_entry,
    record_fetch_attempt, get_last_fetch_attempt,
    read_watchlist, add_to_watchlist, remove_from_watchlist,
    ensure_tables_for_test,
)

@pytest.fixture
def aws():
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").meta  # trigger client init
        ensure_tables_for_test()
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="tool-payloads-test")
        yield

def test_small_payload_stored_inline(aws, monkeypatch):
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    write_tool_result("AAPL#Quote", {"price": 150}, ttl_seconds=3600)
    result = read_tool_result("AAPL#Quote")
    assert result == {"price": 150}

    # Symmetric coverage: prove the small payload actually went the inline
    # path (has `payload`, no `s3_key`), not just that read-back matches.
    raw_item = boto3.resource("dynamodb", region_name="us-east-1").Table("ToolResults").get_item(
        Key={"pk": "AAPL#Quote"}
    )["Item"]
    assert "payload" in raw_item
    assert "s3_key" not in raw_item

def test_oversized_payload_offloaded_to_s3(aws, monkeypatch):
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    big_payload = {"filing_text": "x" * 400_000}  # exceeds 300KB threshold
    write_tool_result("AAPL#EdgarFiling", big_payload, ttl_seconds=3600)
    result = read_tool_result("AAPL#EdgarFiling")
    assert result == big_payload  # transparently resolved on read

    # Prove the S3 path was actually taken, not just that round-trip works
    # (a round-trip alone passes even with offload disabled entirely).
    raw_item = boto3.resource("dynamodb", region_name="us-east-1").Table("ToolResults").get_item(
        Key={"pk": "AAPL#EdgarFiling"}
    )["Item"]
    assert "s3_key" in raw_item
    assert "s3_bucket" in raw_item
    assert "payload" not in raw_item

    s3_object = boto3.client("s3", region_name="us-east-1").get_object(
        Bucket=raw_item["s3_bucket"], Key=raw_item["s3_key"]
    )
    assert json.loads(s3_object["Body"].read()) == big_payload

def test_missing_tool_result_returns_none(aws, monkeypatch):
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    assert read_tool_result("MSFT#Quote") is None

def test_agent_output_roundtrip(aws):
    write_agent_output("AAPL", "Fundamentals", {"strength": "strong"})
    assert read_agent_output("AAPL", "Fundamentals") == {"strength": "strong"}
    assert read_agent_output("AAPL", "Technical") is None

def test_process_history_append_and_query_ordered(aws):
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc)
    append_process_history("AAPL", "Sentiment", reason="news_cascade", status="started", timestamp=t1)
    append_process_history("AAPL", "Sentiment", reason="news_cascade", status="finished", timestamp=t2)
    entries = query_process_history("AAPL")
    assert [e["status"] for e in entries] == ["started", "finished"]

def test_process_history_query_since_filters_older_entries(aws):
    # A mix of timestamps straddling `since`, including one exactly *at* the
    # boundary, verifies the DB-level `Key("sk").gte(...)` bound behaves like the
    # old client-side `>=` filter: strictly-older entries are dropped, and the
    # at-or-after entries (including the exact-boundary one) are kept.
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    since = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)
    append_process_history("AAPL", "Risk", reason="scheduled", status="finished", timestamp=t1)
    append_process_history("AAPL", "Risk", reason="scheduled", status="started", timestamp=since)
    append_process_history("AAPL", "Risk", reason="scheduled", status="finished", timestamp=t2)
    entries = query_process_history("AAPL", since=since)
    assert [e["timestamp"] for e in entries] == [since.isoformat(), t2.isoformat()]

def test_process_history_query_since_matches_same_instant_in_different_offset(aws):
    # Entry is stored using a UTC timestamp.
    stored = datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)
    append_process_history("AAPL", "Risk", reason="scheduled", status="finished", timestamp=stored)

    # Query using the *same instant* expressed in a different UTC offset.
    # A naive lexicographic string comparison of ISO strings would wrongly
    # drop this entry because "14:30+02:00" > "13:00+00:00" as strings even
    # though they represent the identical instant.
    since_other_offset = datetime(2026, 1, 1, 14, 30, tzinfo=timezone(timedelta(hours=2)))
    entries = query_process_history("AAPL", since=since_other_offset)
    assert len(entries) == 1
    assert entries[0]["timestamp"] == stored.isoformat()

def test_process_history_query_drains_all_pages(aws):
    # DynamoDB caps a single query response at 1MB and signals more data with
    # LastEvaluatedKey. A single un-paginated query() therefore returns only the
    # *oldest* page once a symbol's history grows past 1MB, permanently freezing
    # every "last updated" consumer on stale data. Write >1MB so the real
    # response is forced to paginate, and assert nothing is dropped.
    table = boto3.resource("dynamodb", region_name="us-east-1").Table("ProcessHistory")
    filler = "x" * 3800  # ~3.8KB/item => 300 items is ~1.1MB, comfortably >1 page
    expected_count = 300
    for i in range(expected_count):
        timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=i)
        table.put_item(Item={
            "symbol": "AAPL",
            "sk": f"{timestamp.isoformat()}#Sentiment",
            "agent": "Sentiment",
            "reason": "pipeline_run",
            "status": "finished",
            "timestamp": timestamp.isoformat(),
            "filler": filler,
        })

    entries = query_process_history("AAPL")
    assert len(entries) == expected_count

    # The newest entry must be reachable -- this is the exact read every
    # "last updated" consumer does, and the one truncation silently breaks.
    last_timestamp = (datetime(2026, 1, 1, tzinfo=timezone.utc)
                      + timedelta(minutes=expected_count - 1)).isoformat()
    assert entries[-1]["timestamp"] == last_timestamp

def test_get_latest_process_history_entry_returns_newest(aws):
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)  # written out of order
    append_process_history("AAPL", "Risk", reason="scheduled", status="finished", timestamp=t1)
    append_process_history("AAPL", "Risk", reason="scheduled", status="finished", timestamp=t2)
    append_process_history("AAPL", "Risk", reason="scheduled", status="finished", timestamp=t3)
    entry = get_latest_process_history_entry("AAPL")
    assert entry["timestamp"] == t2.isoformat()

def test_get_latest_process_history_entry_returns_none_when_empty(aws):
    assert get_latest_process_history_entry("MSFT") is None

def test_last_fetch_attempt_is_none_before_any_attempt(aws):
    assert get_last_fetch_attempt("AAPL#finnhub_company_profile") is None

def test_record_and_read_back_last_fetch_attempt(aws):
    t = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    record_fetch_attempt("AAPL#finnhub_company_profile", t)
    assert get_last_fetch_attempt("AAPL#finnhub_company_profile") == t

def test_record_fetch_attempt_with_naive_datetime_returns_aware_utc(aws):
    # A naive datetime must not be silently treated as local time (which
    # would produce a wrong expires_at and, if compared downstream against
    # an aware datetime.now(timezone.utc), raise a TypeError).
    naive = datetime(2026, 1, 1, 12, 0)  # no tzinfo
    record_fetch_attempt("AAPL#finnhub_company_profile", naive)

    result = get_last_fetch_attempt("AAPL#finnhub_company_profile")
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)
    assert result == naive.replace(tzinfo=timezone.utc)

    # Must be safely comparable against an aware "now" without raising.
    delta = datetime.now(timezone.utc) - result
    assert delta.total_seconds() > 0

def test_recording_an_attempt_does_not_disturb_the_actual_tool_result(aws, monkeypatch):
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    write_tool_result("AAPL#Quote", {"price": 150}, ttl_seconds=3600)
    record_fetch_attempt("AAPL#Quote", datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    assert read_tool_result("AAPL#Quote") == {"price": 150}

def test_removing_from_watchlist_purges_all_cached_and_derived_state(aws, monkeypatch):
    # Re-adding a symbol after removal must be a genuine cold start, not a resume on
    # leftover data -- so removal has to clear every table a symbol's data lives in.
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    add_to_watchlist("AAPL")
    write_tool_result("AAPL#finnhub_quote", {"c": 150.0}, ttl_seconds=3600)
    write_tool_result("AAPL#marketaux_news_all", {"data": []}, ttl_seconds=3600)
    record_fetch_attempt("AAPL#finnhub_quote", datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    write_agent_output("AAPL", "Manager", {"net_score": 10})
    write_agent_output("AAPL", "Fundamentals", {"claims": []})
    append_process_history("AAPL", "Manager", reason="pipeline_run", status="finished",
                            timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))

    remove_from_watchlist("AAPL")

    assert "AAPL" not in read_watchlist()
    assert read_tool_result("AAPL#finnhub_quote") is None
    assert read_tool_result("AAPL#marketaux_news_all") is None
    assert get_last_fetch_attempt("AAPL#finnhub_quote") is None
    assert read_agent_output("AAPL", "Manager") is None
    assert read_agent_output("AAPL", "Fundamentals") is None
    assert query_process_history("AAPL") == []

def test_removing_from_watchlist_does_not_disturb_other_symbols(aws, monkeypatch):
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    add_to_watchlist("AAPL")
    add_to_watchlist("MSFT")
    write_tool_result("AAPL#finnhub_quote", {"c": 150.0}, ttl_seconds=3600)
    write_tool_result("MSFT#finnhub_quote", {"c": 490.0}, ttl_seconds=3600)
    write_agent_output("MSFT", "Manager", {"net_score": 5})

    remove_from_watchlist("AAPL")

    assert read_watchlist() == ["MSFT"]
    assert read_tool_result("MSFT#finnhub_quote") == {"c": 490.0}
    assert read_agent_output("MSFT", "Manager") == {"net_score": 5}
