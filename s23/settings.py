import os
from dataclasses import dataclass
from typing import Literal

Service = Literal[
    "patient-simulator",
    "device-registry",
    "vital-ingestion",
    "alert-rule-engine",
    "alert-queue-manager",
    "acknowledgement-service",
    "notification-dispatcher",
]
SERVICES: tuple[str, ...] = (
    "patient-simulator",
    "device-registry",
    "vital-ingestion",
    "alert-rule-engine",
    "alert-queue-manager",
    "acknowledgement-service",
    "notification-dispatcher",
)


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def boolean(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, str(default)).lower()
    if value not in ("true", "false"):
        raise ValueError(f"{name} must be true or false")
    return value == "true"


@dataclass(frozen=True)
class Settings:
    service: str
    mode: str
    region: str
    aws_endpoint: str | None
    brokers: str
    table: str
    queue_url: str
    bucket: str
    zk_hosts: str
    api_key: str
    api_secret_arn: str
    database_host: str
    database_name: str
    database_user: str
    database_password: str
    database_secret_arn: str
    registry_grpc: str
    ingestion_url: str
    simulator_url: str
    manager_url: str
    acknowledgement_url: str
    ack_timeout_ms: int
    dispatch_lease_ms: int
    max_dispatches: int
    fail_first_delivery: bool

    def __post_init__(self) -> None:
        if self.mode == "aws" and self.aws_endpoint:
            raise ValueError("AWS mode must not point at a local mock AWS endpoint")
        if self.ack_timeout_ms < 1000 or self.dispatch_lease_ms < 1000:
            raise ValueError("Acknowledgement and dispatch timeouts must be at least 1000ms")
        if not 1 <= self.max_dispatches <= 20:
            raise ValueError("MAX_DISPATCHES must be between 1 and 20")

    @classmethod
    def from_env(cls, service: str | None = None) -> "Settings":
        service = service or required("SERVICE")
        if service not in SERVICES:
            raise ValueError(f"Unknown service: {service}")
        mode = required("APP_MODE")
        if mode not in ("local", "aws"):
            raise ValueError("APP_MODE must be local or aws")
        api_key = os.environ.get("DEMO_API_KEY", "")
        api_secret = os.environ.get("API_SECRET_ARN", "")
        if service in ("vital-ingestion", "patient-simulator"):
            if mode == "local" and not api_key:
                raise ValueError("DEMO_API_KEY is required locally")
            if mode == "aws" and not api_secret:
                raise ValueError("API_SECRET_ARN is required on AWS")
        return cls(
            service=service,
            mode=mode,
            region=required("AWS_REGION"),
            aws_endpoint=os.environ.get("AWS_ENDPOINT_URL") or None,
            brokers=required("KAFKA_BROKERS"),
            table=required("ALERT_TABLE"),
            queue_url=required("SQS_QUEUE_URL"),
            bucket=required("ARCHIVE_BUCKET"),
            zk_hosts=required("ZOOKEEPER_HOSTS"),
            api_key=api_key,
            api_secret_arn=api_secret,
            database_host=required("DB_HOST"),
            database_name=os.environ.get("DB_NAME", "registry"),
            database_user=os.environ.get("DB_USER", "s23_registry"),
            database_password=os.environ.get("DB_PASSWORD", ""),
            database_secret_arn=os.environ.get("DB_SECRET_ARN", ""),
            registry_grpc=os.environ.get("REGISTRY_GRPC", "device-registry:50051"),
            ingestion_url=os.environ.get("INGESTION_URL", "http://vital-ingestion:8080"),
            simulator_url=os.environ.get("SIMULATOR_URL", "http://patient-simulator:8080"),
            manager_url=os.environ.get("MANAGER_URL", "http://alert-queue-manager:8080"),
            acknowledgement_url=os.environ.get(
                "ACKNOWLEDGEMENT_URL", "http://acknowledgement-service:8080"
            ),
            ack_timeout_ms=int(os.environ.get("ACK_TIMEOUT_MS", "60000")),
            dispatch_lease_ms=int(os.environ.get("DISPATCH_LEASE_MS", "45000")),
            max_dispatches=int(os.environ.get("MAX_DISPATCHES", "5")),
            fail_first_delivery=boolean("FAIL_FIRST_DELIVERY"),
        )
