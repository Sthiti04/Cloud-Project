import pytest
from pydantic import ValidationError

from s23.domain import (
    Alert,
    ClinicalEvent,
    Reading,
    Status,
    acknowledge,
    claim,
    delivered,
    escalate,
    simulate,
)

NOW = 1_800_000_000_000


def test_simulation_is_reproducible_and_contains_normal_and_abnormal_readings():
    first = list(simulate("run-a", 7, 12, NOW))
    assert first == list(simulate("run-a", 7, 12, NOW))
    assert len({r.event_id for r in first}) == 12
    assert {r.device_id for r in first} == {"device-1", "device-2", "device-3"}
    assert any(r.abnormal for r in first)
    assert any(not r.abnormal for r in first)


@pytest.mark.parametrize(
    "field,value",
    [
        ("heart_rate", -1),
        ("heart_rate", 301),
        ("heart_rate", 72.5),
        ("event_id", "../secret"),
        ("device_id", ""),
        ("observed_at", 0),
    ],
)
def test_readings_reject_invalid_input(reading, field, value):
    with pytest.raises(ValidationError):
        Reading.model_validate({**reading.model_dump(), field: value})


@pytest.mark.parametrize("rate,abnormal", [(49, True), (50, False), (120, False), (121, True)])
def test_threshold_boundaries(reading, rate, abnormal):
    assert Reading.model_validate({**reading.model_dump(), "heart_rate": rate}).abnormal is abnormal


def test_alert_lifecycle_has_versions_and_ack_deadline(reading):
    alert = Alert.from_reading(reading, NOW)
    assert alert.status == Status.PENDING
    claimed = claim(alert, NOW, 9, 30_000)
    assert claimed.status == Status.IN_FLIGHT
    assert claimed.version == 1 and claimed.fence == 9 and claimed.dispatches == 1
    sent = delivered(claimed, NOW + 100, 60_000)
    assert sent.status == Status.DELIVERED and sent.due_at == NOW + 60_100
    acked = acknowledge(sent, NOW + 1_100)
    assert acked.status == Status.ACKNOWLEDGED and acked.version == 3
    assert not acked.open
    event = ClinicalEvent.for_alert("acknowledged", acked, NOW + 1_100)
    assert event.latency_ms == 1_000
    assert event.event_id == f"acknowledged:{alert.alert_id}:3"


def test_escalation_requires_an_overdue_delivered_alert(reading):
    sent = delivered(claim(Alert.from_reading(reading, NOW), NOW, 1, 30_000), NOW, 60_000)
    with pytest.raises(ValueError, match="not overdue"):
        escalate(sent, NOW + 59_999)
    escalated = escalate(sent, NOW + 60_000)
    assert escalated.status == Status.ESCALATED and not escalated.open
    assert acknowledge(escalated, NOW + 60_001).status == Status.ACKNOWLEDGED


def test_duplicate_acknowledgement_is_idempotent(reading):
    alert = acknowledge(
        delivered(claim(Alert.from_reading(reading, NOW), NOW, 1, 30_000), NOW, 60_000), NOW
    )
    assert acknowledge(alert, NOW + 10) == alert


def test_invalid_transitions_are_explicit(reading):
    pending = Alert.from_reading(reading, NOW)
    with pytest.raises(ValueError, match="delivered"):
        acknowledge(pending, NOW)
    with pytest.raises(ValueError, match="in-flight"):
        delivered(pending, NOW, 60_000)
    with pytest.raises(ValueError, match="delivered"):
        escalate(pending, NOW)
    with pytest.raises(ValueError, match="normal"):
        Alert.from_reading(reading.model_copy(update={"heart_rate": 70}), NOW)
