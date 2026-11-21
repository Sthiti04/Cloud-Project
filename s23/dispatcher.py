import logging
from functools import lru_cache
from time import perf_counter
from typing import Any

from botocore.exceptions import ClientError
from pydantic import ValidationError

from s23.domain import DeliveryRequest
from s23.observability import log
from s23.resources import Resources
from s23.services import TransientDeliveryError
from s23.settings import Settings

logging.basicConfig(level=logging.INFO, format="%(message)s")


@lru_cache(maxsize=1)
def resources() -> Resources:
    return Resources(Settings.from_env("notification-dispatcher"))


def handle_batch(event: dict[str, Any], runtime: Resources) -> dict[str, Any]:
    records = event.get("Records")
    if not isinstance(records, list):
        raise ValueError("Lambda requires an SQS Records array")
    failures = []
    for record in records:
        message_id = record["messageId"]
        try:
            request = DeliveryRequest.model_validate_json(record["body"])
            count = int(record.get("attributes", {}).get("ApproximateReceiveCount", "1"))
            result = runtime.dispatcher.deliver(request, count)
            log("notification_outcome", message_id=message_id, outcome=result)
        except (
            TransientDeliveryError,
            LookupError,
            ClientError,
            ValidationError,
            ValueError,
        ) as error:
            log("notification_failed", message_id=message_id, error_type=type(error).__name__)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    import json

    runtime = resources()
    start = perf_counter()
    result = handle_batch(event, runtime)
    logging.getLogger("s23").info(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": runtime.clock(),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "S23/Notifications",
                            "Dimensions": [["FunctionName"]],
                            "Metrics": [
                                {"Name": "FailedRecords", "Unit": "Count"},
                                {"Name": "DurationMs", "Unit": "Milliseconds"},
                            ],
                        }
                    ],
                },
                "FunctionName": context.function_name,
                "FailedRecords": len(result["batchItemFailures"]),
                "DurationMs": (perf_counter() - start) * 1000,
            }
        )
    )
    return result


def local_run() -> None:
    runtime = resources()
    log("local_dispatcher_started", runtime="moto-SQS-not-AWS-Lambda")
    while True:
        for message in runtime.queue.receive():
            event = {
                "Records": [
                    {
                        "messageId": message["MessageId"],
                        "body": message["Body"],
                        "attributes": message.get("Attributes", {}),
                    }
                ]
            }
            result = handle_batch(event, runtime)
            if not result["batchItemFailures"]:
                runtime.queue.delete(message["ReceiptHandle"])


if __name__ == "__main__":
    local_run()
