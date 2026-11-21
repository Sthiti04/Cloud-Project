import argparse
import json
import time
import uuid
from typing import Any

import requests

from .common import ROOT, deployment, environment, run


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, response: requests.Response):
        super().__init__(f"{method} {path}: HTTP {response.status_code}: {response.text[:1000]}")
        self.status = response.status_code


class Client:
    def __init__(self, aws: bool):
        self.session = requests.Session()
        if aws:
            metadata = deployment()
            self.url = metadata["public_url"]
            self.session.verify = str(ROOT / "artifacts" / "demo-ca.pem")
            secret = json.loads(
                run(
                    [
                        "aws",
                        "secretsmanager",
                        "get-secret-value",
                        "--secret-id",
                        metadata["environment"]["API_SECRET_ARN"],
                        "--region",
                        metadata["region"],
                        "--query",
                        "SecretString",
                        "--output",
                        "text",
                    ],
                    capture=True,
                )
            )
            key = secret["api_key"]
        else:
            self.url = "http://127.0.0.1:8080"
            key = environment(ROOT / ".env")["DEMO_API_KEY"]
        self.session.headers["X-API-Key"] = key
        # Polls can outlive server keep-alive; avoid reusing idle sockets.
        self.session.headers["Connection"] = "close"

    def call(self, method: str, path: str, body: Any = None) -> Any:
        response = self.session.request(method, self.url + path, json=body, timeout=15)
        if not response.ok:
            raise ApiError(method, path, response)
        return response.json()


def tick(client: Client) -> None:
    client.call(
        "POST",
        "/readings",
        {
            "event_id": f"tick-{uuid.uuid4().hex}",
            "device_id": "device-2",
            "patient_id": "patient-2",
            "heart_rate": 72,
            "observed_at": int(time.time() * 1000),
        },
    )


def smoke(client: Client, timeout: int) -> dict[str, Any]:
    run_id = f"smoke-{uuid.uuid4().hex[:12]}"
    started = int(time.time() * 1000)
    generated = client.call(
        "POST",
        "/simulate",
        {
            "run_id": run_id,
            "seed": 7,
            "count": 12,
            "start_at": started,
        },
    )
    if generated != {"generated": 12}:
        raise AssertionError(f"Unexpected simulation result: {generated}")
    deadline = time.monotonic() + timeout
    acknowledged: str | None = None
    while time.monotonic() < deadline:
        tick(client)
        alerts = []
        for index in (0, 3, 6, 9):
            try:
                alerts.append(client.call("GET", f"/alerts/{run_id}-{index}"))
            except ApiError as error:
                if error.status != 404:
                    raise
                print(f"Waiting for rule engine to create {run_id}-{index}")
        sent = [item for item in alerts if item["status"] == "DELIVERED"]
        if acknowledged is None and sent:
            acknowledged = sent[0]["alert_id"]
            ack = client.call("POST", f"/alerts/{acknowledged}/acknowledge")
            if ack["status"] != "ACKNOWLEDGED":
                raise AssertionError("Acknowledgement did not persist")
        results = client.call("GET", "/analytics")
        inbox = [
            item
            for item in client.call("GET", "/notifications?limit=100")
            if item["alert_id"].startswith(run_id)
        ]
        matching = [
            item
            for item in results
            if (
                isinstance(item.get("window_end"), int)
                and item.get("window_start", started + 1) <= started < item["window_end"]
            )
        ]
        required_fields = {
            "device_id",
            "window_start",
            "window_end",
            "reading_count",
            "created_count",
            "delivery_count",
            "ack_count",
            "escalation_count",
            "failed_count",
            "average_heart_rate",
            "average_ack_delay_ms",
        }
        recent = [item for item in results if item.get("window_end", 0) > started]
        analytics_ok = (
            bool(matching)
            and all(required_fields.issubset(item) for item in recent)
            and sum(item["reading_count"] for item in matching) >= 12
            and sum(item["delivery_count"] for item in recent) >= 4
            and sum(item["ack_count"] for item in recent) >= 1
            and sum(item["escalation_count"] for item in recent) >= 1
        )
        if (
            len(alerts) == 4
            and acknowledged is not None
            and any(item["status"] == "ESCALATED" for item in alerts)
            and len(inbox) == 4
            and analytics_ok
        ):
            report = {
                "verified": True,
                "run_id": run_id,
                "generated": 12,
                "alert_count": len(alerts),
                "acknowledged": acknowledged,
                "alerts": alerts,
                "notifications": inbox,
                "windows": matching,
            }
            print(json.dumps(report, indent=2))
            return report
        print("Waiting for notification, acknowledgement/escalation, and event-time windows...")
        time.sleep(5)
    raise TimeoutError(
        "Smoke test did not satisfy all checks. Inspect services, Lambda, Kafka, Flink, and logs."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic-only demo; no infrastructure creation")
    parser.add_argument("--aws", action="store_true", help="Use saved AWS metadata and pinned CA")
    parser.add_argument("action", choices=["simulate", "status", "ack", "tick", "smoke"])
    parser.add_argument("alert_id", nargs="?")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    client = Client(args.aws)
    if args.action == "smoke":
        report = smoke(client, args.timeout)
        path = ROOT / "evidence"
        path.mkdir(exist_ok=True)
        (path / f"smoke-{'aws' if args.aws else 'local'}.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
    elif args.action == "simulate":
        print(
            client.call(
                "POST",
                "/simulate",
                {
                    "run_id": f"demo-{uuid.uuid4().hex[:12]}",
                    "seed": 7,
                    "count": 12,
                    "start_at": int(time.time() * 1000),
                },
            )
        )
    elif args.action == "status":
        print(
            json.dumps(
                {
                    "alerts": client.call("GET", "/alerts"),
                    "notifications": client.call("GET", "/notifications"),
                    "analytics": client.call("GET", "/analytics"),
                },
                indent=2,
            )
        )
    elif args.action == "tick":
        tick(client)
        print("Sent one normal reading to advance event time.")
    else:
        if not args.alert_id:
            parser.error("ack requires an alert ID")
        print(json.dumps(client.call("POST", f"/alerts/{args.alert_id}/acknowledge"), indent=2))


if __name__ == "__main__":
    main()
