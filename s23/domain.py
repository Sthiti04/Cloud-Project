from collections.abc import Iterator
from enum import StrEnum
from random import Random
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
Millis = Annotated[int, Field(ge=946684800000, strict=True)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Reading(Model):
    event_id: Identifier
    device_id: Identifier
    patient_id: Identifier
    heart_rate: Annotated[int, Field(ge=0, le=300, strict=True)]
    observed_at: Millis

    @property
    def abnormal(self) -> bool:
        return self.heart_rate < 50 or self.heart_rate > 120


class Simulation(Model):
    run_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,72}$")]
    seed: int = 7
    count: Annotated[int, Field(ge=1, le=100)] = 12
    start_at: Millis


def simulate(run_id: str, seed: int, count: int, start_at: int) -> Iterator[Reading]:
    request = Simulation(run_id=run_id, seed=seed, count=count, start_at=start_at)
    rng = Random(request.seed)
    for index in range(request.count):
        device = index % 3 + 1
        rate = rng.choice([42, 145]) if index % 3 == 0 else rng.randint(65, 95)
        yield Reading(
            event_id=f"{request.run_id}-{index}",
            device_id=f"device-{device}",
            patient_id=f"patient-{device}",
            heart_rate=rate,
            observed_at=request.start_at,
        )


class Status(StrEnum):
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class Alert(Model):
    alert_id: Identifier
    device_id: Identifier
    patient_id: Identifier
    heart_rate: int
    created_at: Millis
    due_at: Millis
    status: Status = Status.PENDING
    version: int = 0
    dispatches: int = 0
    fence: int = 0
    delivered_at: Millis | None = None
    acknowledged_at: Millis | None = None

    @classmethod
    def from_reading(cls, reading: Reading, now: int) -> "Alert":
        if not reading.abnormal:
            raise ValueError("A normal reading does not create an alert")
        return cls(
            alert_id=reading.event_id,
            device_id=reading.device_id,
            patient_id=reading.patient_id,
            heart_rate=reading.heart_rate,
            created_at=now,
            due_at=now,
        )

    @property
    def open(self) -> bool:
        return self.status in (Status.PENDING, Status.IN_FLIGHT, Status.DELIVERED)


def claim(alert: Alert, now: int, fence: int, lease_ms: int) -> Alert:
    if alert.status not in (Status.PENDING, Status.IN_FLIGHT) or alert.due_at > now:
        raise ValueError("Alert is not due for dispatch")
    return alert.model_copy(
        update={
            "status": Status.IN_FLIGHT,
            "version": alert.version + 1,
            "dispatches": alert.dispatches + 1,
            "fence": fence,
            "due_at": now + lease_ms,
        }
    )


def delivered(alert: Alert, now: int, ack_ms: int) -> Alert:
    if alert.status != Status.IN_FLIGHT:
        raise ValueError("Only an in-flight alert can be delivered")
    return alert.model_copy(
        update={
            "status": Status.DELIVERED,
            "version": alert.version + 1,
            "delivered_at": now,
            "due_at": now + ack_ms,
        }
    )


def acknowledge(alert: Alert, now: int) -> Alert:
    if alert.status == Status.ACKNOWLEDGED:
        return alert
    if alert.status not in (Status.DELIVERED, Status.ESCALATED):
        raise ValueError("Only a delivered or escalated alert can be acknowledged")
    return alert.model_copy(
        update={
            "status": Status.ACKNOWLEDGED,
            "version": alert.version + 1,
            "acknowledged_at": now,
        }
    )


def escalate(alert: Alert, now: int) -> Alert:
    if alert.status != Status.DELIVERED:
        raise ValueError("Only a delivered alert can be escalated")
    if alert.due_at > now:
        raise ValueError("Alert is not overdue")
    return alert.model_copy(update={"status": Status.ESCALATED, "version": alert.version + 1})


EventKind = Literal["reading", "created", "delivered", "acknowledged", "escalated", "failed"]


class ClinicalEvent(Model):
    event_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_:-]{1,100}$")]
    kind: EventKind
    device_id: Identifier
    occurred_at: Millis
    heart_rate: Annotated[int, Field(ge=0, le=300, strict=True)] | None = None
    latency_ms: Annotated[int, Field(ge=0, le=2147483647, strict=True)] | None = None

    @classmethod
    def for_reading(cls, reading: Reading) -> "ClinicalEvent":
        return cls(
            event_id=f"reading:{reading.event_id}",
            kind="reading",
            device_id=reading.device_id,
            occurred_at=reading.observed_at,
            heart_rate=reading.heart_rate,
        )

    @classmethod
    def for_alert(cls, kind: EventKind, alert: Alert, now: int) -> "ClinicalEvent":
        latency = None
        if kind == "acknowledged" and alert.delivered_at is not None:
            latency = max(0, now - alert.delivered_at)
        elif kind == "delivered":
            latency = max(0, now - alert.created_at)
        return cls(
            event_id=f"{kind}:{alert.alert_id}:{alert.version}",
            kind=kind,
            device_id=alert.device_id,
            occurred_at=now,
            latency_ms=latency,
        )


class DeliveryRequest(Model):
    alert_id: Identifier
    version: Annotated[int, Field(ge=1)]
