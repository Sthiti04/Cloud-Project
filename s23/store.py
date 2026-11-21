import json
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from s23.domain import Alert, ClinicalEvent


class Conflict(RuntimeError):
    """An expected version or leadership term no longer owns the state."""


def _decimal(value: Any) -> int | float:
    if not isinstance(value, Decimal):
        raise TypeError(f"Cannot serialize {type(value).__name__}")
    return int(value) if value == value.to_integral_value() else float(value)


def _alert(item: dict[str, Any]) -> Alert:
    return Alert.model_validate_json(
        json.dumps(
            {key: value for key, value in item.items() if key not in ("pk", "work")},
            default=_decimal,
        )
    )


def _transaction_error(error: ClientError) -> None:
    code = error.response["Error"]["Code"]
    reasons = error.response.get("CancellationReasons", [])
    if code == "ConditionalCheckFailedException" or (
        code == "TransactionCanceledException"
        and any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons)
    ):
        raise Conflict("State or leadership changed; reload before retrying") from error
    raise error


class DynamoStore:
    def __init__(self, table: Any):
        self.table = table
        self.client = table.meta.client

    def get(self, alert_id: str) -> Alert | None:
        item = self.table.get_item(Key={"pk": f"alert#{alert_id}"}, ConsistentRead=True).get("Item")
        if item is None:
            return None
        return _alert(item)

    def save(
        self,
        alert: Alert,
        expected_version: int | None,
        *,
        fence: int | None = None,
        event: ClinicalEvent | None = None,
    ) -> None:
        value = {
            **alert.model_dump(mode="json"),
            "pk": f"alert#{alert.alert_id}",
            "work": "OPEN" if alert.open else "CLOSED",
        }
        put: dict[str, Any] = {"TableName": self.table.name, "Item": value}
        if expected_version is None:
            put["ConditionExpression"] = "attribute_not_exists(pk)"
        else:
            put.update(
                {
                    "ConditionExpression": "#v = :v",
                    "ExpressionAttributeNames": {"#v": "version"},
                    "ExpressionAttributeValues": {":v": expected_version},
                }
            )
        actions: list[dict[str, Any]] = [{"Put": put}]
        if event is not None:
            actions.append(
                {
                    "Put": {
                        "TableName": self.table.name,
                        "Item": {
                            "pk": f"event#{event.event_id}",
                            "work": "EVENT",
                            "due_at": event.occurred_at,
                            "payload": event.model_dump(mode="json"),
                        },
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                }
            )
            if event.kind == "delivered":
                actions.append(
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": {
                                "pk": f"notification#{event.event_id}",
                                "work": "INBOX",
                                "due_at": event.occurred_at,
                                "payload": {
                                    "notification_id": event.event_id,
                                    "alert_id": alert.alert_id,
                                    "device_id": alert.device_id,
                                    "delivered_at": event.occurred_at,
                                    "recipient": "demo-operator",
                                    "message": (
                                        f"Demo threshold alert: simulated {alert.device_id} "
                                        f"reported heart_rate={alert.heart_rate}. "
                                        "Not medical advice."
                                    ),
                                },
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    }
                )
        if fence is not None:
            actions.append(
                {
                    "ConditionCheck": {
                        "TableName": self.table.name,
                        "Key": {"pk": "fence"},
                        "ConditionExpression": "#f = :f",
                        "ExpressionAttributeNames": {"#f": "fence"},
                        "ExpressionAttributeValues": {":f": fence},
                    }
                }
            )
        try:
            self.client.transact_write_items(TransactItems=actions)
        except ClientError as error:
            _transaction_error(error)

    def activate_fence(self, token: int) -> None:
        try:
            self.table.update_item(
                Key={"pk": "fence"},
                UpdateExpression="SET #f = :f",
                ConditionExpression="attribute_not_exists(#f) OR #f <= :f",
                ExpressionAttributeNames={"#f": "fence"},
                ExpressionAttributeValues={":f": token},
            )
        except ClientError as error:
            _transaction_error(error)

    def _query(self, work: str, limit: int, now: int | None = None) -> list[dict[str, Any]]:
        condition = Key("work").eq(work)
        if now is not None:
            condition &= Key("due_at").lte(now)
        return self.table.query(
            IndexName="work-index",
            KeyConditionExpression=condition,
            Limit=limit,
        )["Items"]

    def due(self, now: int, limit: int) -> list[Alert]:
        return [_alert(item) for item in self._query("OPEN", limit, now)]

    def list_alerts(self, limit: int) -> list[Alert]:
        items = self._query("OPEN", limit) + self._query("CLOSED", limit)
        return sorted(
            (_alert(item) for item in items),
            key=lambda alert: alert.created_at,
            reverse=True,
        )[:limit]

    def events(self, limit: int) -> list[ClinicalEvent]:
        return [
            ClinicalEvent.model_validate_json(json.dumps(item["payload"], default=_decimal))
            for item in self._query("EVENT", limit)
        ]

    def delete_event(self, event_id: str) -> None:
        self.table.delete_item(Key={"pk": f"event#{event_id}"})

    def put_result(self, result: dict[str, Any]) -> None:
        if not isinstance(result.get("device_id"), str) or not isinstance(
            result.get("window_end"), int
        ):
            raise ValueError("Analytics result requires device_id and integer window_end")
        payload = json.loads(json.dumps(result), parse_float=Decimal)
        self.table.put_item(
            Item={
                "pk": f"result#{result['device_id']}#{result['window_end']}",
                "work": "RESULT",
                "due_at": result["window_end"],
                "payload": payload,
            }
        )

    def results(self, limit: int) -> list[dict[str, Any]]:
        return [
            json.loads(json.dumps(item["payload"], default=_decimal))
            for item in self.table.query(
                IndexName="work-index",
                KeyConditionExpression=Key("work").eq("RESULT"),
                ScanIndexForward=False,
                Limit=limit,
            )["Items"]
        ]

    def notifications(self, limit: int) -> list[dict[str, Any]]:
        return [
            json.loads(json.dumps(item["payload"], default=_decimal))
            for item in self.table.query(
                IndexName="work-index",
                KeyConditionExpression=Key("work").eq("INBOX"),
                ScanIndexForward=False,
                Limit=limit,
            )["Items"]
        ]
