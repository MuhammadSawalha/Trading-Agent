import json
import boto3
import pytest
from moto import mock_aws
from datetime import datetime, timezone
from common.dynamo import (
    read_tool_result, write_tool_result,
    read_agent_output, write_agent_output,
    append_process_history, query_process_history,
    record_fetch_attempt, get_last_fetch_attempt,
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

def test_oversized_payload_offloaded_to_s3(aws, monkeypatch):
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    big_payload = {"filing_text": "x" * 400_000}  # exceeds 300KB threshold
    write_tool_result("AAPL#EdgarFiling", big_payload, ttl_seconds=3600)
    result = read_tool_result("AAPL#EdgarFiling")
    assert result == big_payload  # transparently resolved on read

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
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)
    append_process_history("AAPL", "Risk", reason="scheduled", status="finished", timestamp=t1)
    append_process_history("AAPL", "Risk", reason="scheduled", status="finished", timestamp=t2)
    entries = query_process_history("AAPL", since=datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc))
    assert len(entries) == 1
    assert entries[0]["timestamp"] == t2.isoformat()

def test_last_fetch_attempt_is_none_before_any_attempt(aws):
    assert get_last_fetch_attempt("AAPL#finnhub_company_profile") is None

def test_record_and_read_back_last_fetch_attempt(aws):
    t = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    record_fetch_attempt("AAPL#finnhub_company_profile", t)
    assert get_last_fetch_attempt("AAPL#finnhub_company_profile") == t

def test_recording_an_attempt_does_not_disturb_the_actual_tool_result(aws, monkeypatch):
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    write_tool_result("AAPL#Quote", {"price": 150}, ttl_seconds=3600)
    record_fetch_attempt("AAPL#Quote", datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    assert read_tool_result("AAPL#Quote") == {"price": 150}
