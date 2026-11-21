import os

import boto3
import pytest
from moto import mock_aws

from s23.adapters import Archive
from s23.domain import Alert, Reading
from s23.settings import Settings
from s23.store import DynamoStore


@pytest.fixture(autouse=True)
def measurement_clock(monkeypatch):
    monkeypatch.setattr("s23.app.perf_counter", lambda: 0.0)
    monkeypatch.setattr("s23.registry.perf_counter", lambda: 0.0)


@pytest.fixture
def aws():
    values = {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "ap-south-1",
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    original = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    with mock_aws():
        yield boto3.Session(region_name="ap-south-1")
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def table(aws):
    resource = aws.resource("dynamodb")
    resource.create_table(
        TableName="alerts",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "work", "AttributeType": "S"},
            {"AttributeName": "due_at", "AttributeType": "N"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "work-index",
                "KeySchema": [
                    {"AttributeName": "work", "KeyType": "HASH"},
                    {"AttributeName": "due_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return resource.Table("alerts")


@pytest.fixture
def store(table):
    return DynamoStore(table)


@pytest.fixture
def reading():
    return Reading(
        event_id="reading-1",
        device_id="device-1",
        patient_id="patient-1",
        heart_rate=145,
        observed_at=1_800_000_000_000,
    )


@pytest.fixture
def alert(reading):
    return Alert.from_reading(reading, 1_800_000_000_000)


@pytest.fixture
def archive(aws):
    client = aws.client("s3")
    client.create_bucket(
        Bucket="synthetic-readings", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
    )
    return Archive(client, "synthetic-readings")


@pytest.fixture
def local_settings(monkeypatch):
    values = {
        "SERVICE": "device-registry",
        "APP_MODE": "local",
        "AWS_REGION": "ap-south-1",
        "KAFKA_BROKERS": "kafka:9092",
        "ALERT_TABLE": "alerts",
        "SQS_QUEUE_URL": "http://moto/q",
        "ARCHIVE_BUCKET": "synthetic-readings",
        "ZOOKEEPER_HOSTS": "zookeeper:2181",
        "DB_HOST": "postgres",
        "DEMO_API_KEY": "synthetic-test-key-with-32-characters",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    return Settings.from_env()
