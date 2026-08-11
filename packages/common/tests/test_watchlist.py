import boto3
import pytest
from moto import mock_aws
from common.dynamo import read_watchlist, add_to_watchlist, remove_from_watchlist, WatchlistFullError, ensure_tables_for_test

@pytest.fixture
def aws():
    with mock_aws():
        ensure_tables_for_test()
        yield

def test_empty_watchlist_by_default(aws):
    assert read_watchlist() == []

def test_add_and_read_back(aws):
    add_to_watchlist("AAPL")
    add_to_watchlist("MSFT")
    assert read_watchlist() == ["AAPL", "MSFT"]

def test_add_duplicate_is_a_no_op(aws):
    add_to_watchlist("AAPL")
    add_to_watchlist("AAPL")
    assert read_watchlist() == ["AAPL"]

def test_remove(aws):
    add_to_watchlist("AAPL")
    add_to_watchlist("MSFT")
    remove_from_watchlist("AAPL")
    assert read_watchlist() == ["MSFT"]

def test_add_raises_when_watchlist_full(aws):
    for i in range(30):
        add_to_watchlist(f"SYM{i}")
    with pytest.raises(WatchlistFullError):
        add_to_watchlist("ONE_TOO_MANY")
