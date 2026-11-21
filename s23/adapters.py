import json
from typing import Any

import requests
from botocore.exceptions import ClientError

from s23.domain import DeliveryRequest
from s23.observability import log


class UpstreamRejected(RuntimeError):
    def __init__(self, status: int):
        super().__init__("The responsible service rejected the request")
        self.status = status


class SqsQueue:
    def __init__(self, client: Any, url: str):
        self.client = client
        self.url = url

    def send(self, request: DeliveryRequest) -> None:
        self.client.send_message(QueueUrl=self.url, MessageBody=request.model_dump_json())

    def receive(self) -> list[dict[str, Any]]:
        return self.client.receive_message(
            QueueUrl=self.url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=2,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        ).get("Messages", [])

    def delete(self, receipt: str) -> None:
        self.client.delete_message(QueueUrl=self.url, ReceiptHandle=receipt)


class Archive:
    def __init__(self, client: Any, bucket: str):
        self.client = client
        self.bucket = bucket

    def put(self, event_id: str, payload: str) -> None:
        key = f"readings/{event_id}.json"
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload.encode(),
                ContentType="application/json",
                IfNoneMatch="*",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "PreconditionFailed":
                raise
            existing = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
            try:
                same = existing.read().decode() == payload
            finally:
                existing.close()
            if not same:
                raise ValueError("Reading ID was reused with different data") from None
            log("raw_reading_duplicate", event_id=event_id)


class HttpClient:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()

    def call(
        self,
        method: str,
        url: str,
        *,
        body: Any = None,
        api_key: str | None = None,
    ) -> Any:
        headers = {"X-API-Key": api_key} if api_key else {}
        response = self.session.request(method, url, json=body, headers=headers, timeout=10)
        try:
            response.raise_for_status()
        except requests.HTTPError:
            if 400 <= response.status_code < 500:
                raise UpstreamRejected(response.status_code) from None
            raise
        return response.json()


class HttpAcknowledger:
    def __init__(self, http: HttpClient, base_url: str):
        self.http = http
        self.base_url = base_url

    def escalate(self, alert_id: str) -> None:
        try:
            self.http.call("POST", f"{self.base_url}/alerts/{alert_id}/escalate")
        except UpstreamRejected as error:
            if error.status != 409:
                raise
            log("escalation_concurrent_update", alert_id=alert_id)


class ApiKey:
    def __init__(self, client: Any, secret_arn: str, local_key: str):
        self.client = client
        self.secret_arn = secret_arn
        self.local_key = local_key
        self._value: str | None = None

    def get(self) -> str:
        if self._value is None:
            if self.secret_arn:
                secret = json.loads(
                    self.client.get_secret_value(SecretId=self.secret_arn)["SecretString"]
                )
                value = secret.get("api_key")
            else:
                value = self.local_key
            if not isinstance(value, str) or len(value) < 16:
                raise ValueError("Demo API key must contain at least 16 characters")
            self._value = value
        return self._value
