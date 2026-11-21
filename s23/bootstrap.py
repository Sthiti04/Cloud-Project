import argparse
import logging

import boto3
from botocore.exceptions import ClientError
from confluent_kafka import KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

from s23.broker import kafka_config
from s23.observability import log
from s23.registry import initialise
from s23.services import CLINICAL_TOPIC, RESULTS_TOPIC, VITALS_TOPIC
from s23.settings import Settings


def topics(settings: Settings) -> None:
    admin = AdminClient(kafka_config(settings.brokers, settings.mode, settings.region))
    replication = 2 if settings.mode == "aws" else 1
    futures = admin.create_topics(
        [
            NewTopic(
                name,
                num_partitions=6,
                replication_factor=replication,
                config={
                    "retention.ms": "86400000",
                },
            )
            for name in (VITALS_TOPIC, CLINICAL_TOPIC, RESULTS_TOPIC)
        ],
        request_timeout=30,
    )
    for name, future in futures.items():
        try:
            future.result()
        except KafkaException as error:
            if error.args[0].name() != "TOPIC_ALREADY_EXISTS":
                raise
            log("kafka_topic_already_exists", topic=name)
        else:
            log("kafka_topic_created", topic=name)


def local_aws(settings: Settings) -> None:
    if settings.mode != "local" or not settings.aws_endpoint:
        raise ValueError("Local mock initialization requires APP_MODE=local and AWS_ENDPOINT_URL")
    session = boto3.Session(region_name=settings.region)
    dynamo = session.client("dynamodb", endpoint_url=settings.aws_endpoint)
    try:
        dynamo.create_table(
            TableName=settings.table,
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
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceInUseException":
            raise
        log("mock_table_already_exists", table=settings.table)
    sqs = session.client("sqs", endpoint_url=settings.aws_endpoint)
    sqs.create_queue(QueueName="notifications", Attributes={"VisibilityTimeout": "10"})
    s3 = session.client("s3", endpoint_url=settings.aws_endpoint)
    try:
        s3.create_bucket(
            Bucket=settings.bucket,
            CreateBucketConfiguration={"LocationConstraint": settings.region},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
            raise
        log("mock_bucket_already_exists", bucket=settings.bucket)
    log("local_aws_mock_initialised")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["topics", "registry", "local"])
    action = parser.parse_args().action
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_env("device-registry")
    if action == "local":
        local_aws(settings)
        initialise(settings)
        topics(settings)
    elif action == "registry":
        initialise(settings)
    else:
        topics(settings)


if __name__ == "__main__":
    main()
