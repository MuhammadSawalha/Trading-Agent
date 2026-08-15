from langfuse.langchain import CallbackHandler
from common.tracing import langfuse_handler, langfuse_config

def test_langfuse_handler_constructs_a_real_callback_handler():
    # No LANGFUSE_PUBLIC_KEY/SECRET_KEY needed to construct -- the SDK just logs an auth
    # warning and disables the client, it doesn't raise. Constructing successfully with
    # zero explicit args (credentials come from the environment implicitly) is exactly
    # the behavior this factory exists to provide.
    handler = langfuse_handler()
    assert isinstance(handler, CallbackHandler)

def test_langfuse_config_groups_by_session_id():
    config = langfuse_config(session_id="AAPL")
    assert config["metadata"] == {"langfuse_session_id": "AAPL"}
    assert len(config["callbacks"]) == 1
    assert isinstance(config["callbacks"][0], CallbackHandler)
    assert "tags" not in config

def test_langfuse_config_includes_tags_when_given():
    config = langfuse_config(session_id="MSFT", tags=["Fundamentals specialist"])
    assert config["tags"] == ["Fundamentals specialist"]
    assert config["metadata"] == {"langfuse_session_id": "MSFT"}

def test_langfuse_config_omits_tags_key_when_tags_is_empty_list():
    # Falsy-but-not-None tags (e.g. an empty list threaded through from a caller) should
    # behave the same as omitting tags entirely, not add an empty tags key.
    config = langfuse_config(session_id="MSFT", tags=[])
    assert "tags" not in config

def test_each_call_builds_a_fresh_handler():
    # langfuse_config must not share mutable handler/metadata state across call sites --
    # each invocation gets its own callbacks list and metadata dict.
    config_a = langfuse_config(session_id="AAPL")
    config_b = langfuse_config(session_id="AAPL")
    assert config_a["callbacks"][0] is not config_b["callbacks"][0]
    assert config_a["metadata"] is not config_b["metadata"]
