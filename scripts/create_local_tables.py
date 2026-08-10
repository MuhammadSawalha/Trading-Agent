import boto3
import sys
sys.path.insert(0, "services/mcp-server")
from src.dynamo_schema import TABLE_DEFINITIONS

def main():
    client = boto3.client(
        "dynamodb", endpoint_url="http://localhost:8000",
        region_name="us-east-1", aws_access_key_id="local", aws_secret_access_key="local",
    )
    existing = set(client.list_tables()["TableNames"])
    for name, definition in TABLE_DEFINITIONS.items():
        if name in existing:
            print(f"{name}: already exists, skipping")
            continue
        client.create_table(**definition)
        client.get_waiter("table_exists").wait(TableName=name)
        if name == "ToolResults":
            client.update_time_to_live(
                TableName=name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
            )
        print(f"{name}: created")

if __name__ == "__main__":
    main()
