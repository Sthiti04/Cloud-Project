import json
import logging
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

LOGGER = logging.getLogger("s23")


def log(event: str, **fields: Any) -> None:
    LOGGER.info(json.dumps({"event": event, **fields}, separators=(",", ":"), default=str))


class Metrics:
    def __init__(self, service: str):
        self.registry = CollectorRegistry()
        labels = ["service"]
        self.requests = Counter(
            "s23_http_requests_total",
            "HTTP requests",
            labels + ["method", "route", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "s23_http_request_duration_seconds",
            "HTTP latency",
            labels + ["route"],
            registry=self.registry,
        )
        self.rpc_requests = Counter(
            "s23_grpc_requests_total",
            "gRPC requests",
            labels + ["method", "status"],
            registry=self.registry,
        )
        self.rpc_latency = Histogram(
            "s23_grpc_request_duration_seconds",
            "gRPC latency",
            labels + ["method"],
            registry=self.registry,
        )
        self.events = Counter(
            "s23_events_total",
            "Successfully processed events",
            labels + ["kind"],
            registry=self.registry,
        )
        self.failures = Counter(
            "s23_failures_total",
            "Processing failures",
            labels + ["kind"],
            registry=self.registry,
        )
        self.leader = Gauge(
            "s23_queue_leader",
            "1 if this queue manager owns the election",
            labels,
            registry=self.registry,
        )
        self.service = service

    def processed(self, kind: str) -> None:
        self.events.labels(self.service, kind).inc()
