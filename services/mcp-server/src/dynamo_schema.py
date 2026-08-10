TABLE_DEFINITIONS: dict[str, dict] = {
    "ToolResults": {
        "TableName": "ToolResults",
        "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST",
    },
    "AgentOutputs": {
        "TableName": "AgentOutputs",
        "KeySchema": [
            {"AttributeName": "symbol", "KeyType": "HASH"},
            {"AttributeName": "agent_name", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "symbol", "AttributeType": "S"},
            {"AttributeName": "agent_name", "AttributeType": "S"},
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    "ProcessHistory": {
        "TableName": "ProcessHistory",
        "KeySchema": [
            {"AttributeName": "symbol", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "symbol", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
}
