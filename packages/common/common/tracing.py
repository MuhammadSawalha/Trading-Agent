"""Langfuse Cloud tracing helpers shared by every service that makes LLM calls.

Per the agreed design (spec §9), this integrates with Langfuse Cloud (SaaS) only --
never self-hosted. Credentials (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY) and, if ever
overridden, LANGFUSE_HOST are read implicitly by the Langfuse SDK from the process
environment; nothing in this module reads them directly. When LANGFUSE_HOST is unset the
SDK's own default is already "https://cloud.langfuse.com" (verified against the installed
SDK's source), so Cloud is the default even if the credentials env vars are absent --
in that case the SDK just logs an auth warning and traces are dropped, which is fine for
local dev / tests.

NOTE on SDK version: this targets Langfuse SDK v4 (the version that `langfuse>=2.50`
actually resolves to today), not v2. v4's `langfuse.langchain.CallbackHandler` takes no
`secret_key`/`host`/`session_id` constructor kwargs -- credentials come from the
environment automatically via the SDK's global client singleton, and per-call session
grouping is done through the LangChain `config`'s `metadata["langfuse_session_id"]` key
instead of a constructor argument. See CallbackHandler.py in the installed package for
the metadata keys read (verified: `langfuse_session_id`, also `langfuse_user_id`,
`langfuse_trace_name`, `langfuse_tags`).
"""

from langfuse.langchain import CallbackHandler


def langfuse_handler() -> CallbackHandler:
    """Build a Langfuse callback handler for a single LangChain `.invoke(...)` call.

    Cheap to construct -- it just wraps the SDK's process-wide Langfuse client singleton,
    which is what actually owns credentials/host/batching. A fresh handler per call (rather
    than a shared cached one) keeps each call site's `config` self-contained and avoids any
    surprise about handler statefulness across concurrent invocations.
    """
    return CallbackHandler()


def langfuse_config(session_id: str, tags: list[str] | None = None) -> dict:
    """Build the LangChain `config=` dict that traces a call to Langfuse Cloud.

    `session_id` groups every LLM call for one pipeline run/symbol (or chat request) under
    one Langfuse session, per the plan's intent -- pass e.g. the stock symbol for
    scheduler graph nodes, or a symbol-derived identifier for chat.
    """
    metadata = {"langfuse_session_id": session_id}
    config: dict = {"callbacks": [langfuse_handler()], "metadata": metadata}
    if tags:
        config["tags"] = tags
    return config
