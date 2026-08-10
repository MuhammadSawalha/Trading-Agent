from src.dynamo_schema import TABLE_DEFINITIONS

def test_tool_results_key_schema():
    t = TABLE_DEFINITIONS["ToolResults"]
    assert t["KeySchema"] == [{"AttributeName": "pk", "KeyType": "HASH"}]

def test_agent_outputs_key_schema():
    t = TABLE_DEFINITIONS["AgentOutputs"]
    assert t["KeySchema"] == [
        {"AttributeName": "symbol", "KeyType": "HASH"},
        {"AttributeName": "agent_name", "KeyType": "RANGE"},
    ]

def test_process_history_key_schema():
    t = TABLE_DEFINITIONS["ProcessHistory"]
    assert t["KeySchema"] == [
        {"AttributeName": "symbol", "KeyType": "HASH"},
        {"AttributeName": "sk", "KeyType": "RANGE"},
    ]

def test_all_tables_use_pay_per_request():
    for name, t in TABLE_DEFINITIONS.items():
        assert t["BillingMode"] == "PAY_PER_REQUEST", name
