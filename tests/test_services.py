from unittest.mock import Mock

import pytest

from s23.domain import Alert, DeliveryRequest, Status
from s23.services import AlertService, Dispatcher, Scheduler, TransientDeliveryError
from s23.store import Conflict

NOW = 1_800_000_000_000


def test_duplicate_reading_does_not_create_duplicate_alerts(store, reading):
    service = AlertService(store, lambda: NOW)
    first = service.create(reading)
    assert service.create(reading) == first
    assert len(store.events(10)) == 1
    with pytest.raises(ValueError, match="different"):
        service.create(reading.model_copy(update={"heart_rate": 42}))


def scheduler(store, now=NOW):
    return Scheduler(store, Mock(), Mock(), Mock(), lambda: now, 45_000, 5)


def test_only_leader_dispatches_and_publishes_outbox(store, reading):
    AlertService(store, lambda: NOW).create(reading)
    worker = scheduler(store)
    assert worker.tick(None) == 0
    worker.queue.send.assert_not_called()
    assert worker.tick(8) == 1
    worker.queue.send.assert_called_once_with(DeliveryRequest(alert_id=reading.event_id, version=1))
    worker.broker.publish.assert_called_once()
    assert store.events(10) == []
    assert store.get(reading.event_id).status == Status.IN_FLIGHT


def test_queue_send_failure_leaves_a_recoverable_lease(store, reading):
    AlertService(store, lambda: NOW).create(reading)
    worker = scheduler(store)
    worker.queue.send.side_effect = RuntimeError("simulated queue outage")
    with pytest.raises(RuntimeError, match="outage"):
        worker.tick(8)
    recovery = scheduler(store, NOW + 45_000)
    assert recovery.tick(9) == 1
    assert store.get(reading.event_id).dispatches == 2


def test_outbox_publish_failure_is_not_silently_deleted(store, reading):
    AlertService(store, lambda: NOW).create(reading)
    worker = scheduler(store)
    worker.broker.publish.side_effect = RuntimeError("simulated Kafka outage")
    with pytest.raises(RuntimeError):
        worker.tick(1)
    assert len(store.events(10)) == 1


def test_transient_notification_retries_then_deduplicates(store, reading):
    AlertService(store, lambda: NOW).create(reading)
    scheduler(store).tick(1)
    request = DeliveryRequest(alert_id=reading.event_id, version=1)
    dispatcher = Dispatcher(store, lambda: NOW + 10, 60_000, True)
    with pytest.raises(TransientDeliveryError):
        dispatcher.deliver(request, 1)
    assert dispatcher.deliver(request, 2) == "delivered"
    assert dispatcher.deliver(request, 3) == "duplicate"
    assert store.get(reading.event_id).status == Status.DELIVERED
    inbox = store.notifications(10)
    assert len(inbox) == 1
    assert inbox[0]["alert_id"] == reading.event_id
    assert inbox[0]["recipient"] == "demo-operator"


def test_old_queue_message_cannot_deliver_a_new_claim(store, reading):
    AlertService(store, lambda: NOW).create(reading)
    scheduler(store).tick(1)
    scheduler(store, NOW + 45_000).tick(2)
    dispatcher = Dispatcher(store, lambda: NOW + 45_010, 60_000, False)
    assert dispatcher.deliver(DeliveryRequest(alert_id=reading.event_id, version=1), 1) == "stale"
    assert (
        dispatcher.deliver(DeliveryRequest(alert_id=reading.event_id, version=2), 1) == "delivered"
    )


def test_acknowledgement_stops_escalation_and_retries(store, reading):
    service = AlertService(store, lambda: NOW + 30)
    service.create(reading)
    scheduler(store, NOW + 30).tick(1)
    Dispatcher(store, lambda: NOW + 40, 60_000, False).deliver(
        DeliveryRequest(alert_id=reading.event_id, version=1), 1
    )
    acked = service.ack(reading.event_id)
    assert acked.status == Status.ACKNOWLEDGED
    assert service.ack(reading.event_id) == acked
    assert store.due(NOW + 100_000, 10) == []


def test_overdue_alert_is_escalated_by_acknowledgement_service(store, reading):
    service = AlertService(store, lambda: NOW)
    service.create(reading)
    scheduler(store).tick(1)
    Dispatcher(store, lambda: NOW, 60_000, False).deliver(
        DeliveryRequest(alert_id=reading.event_id, version=1), 1
    )
    worker = scheduler(store, NOW + 60_000)
    worker.tick(1)
    worker.acknowledger.escalate.assert_called_once_with(reading.event_id)
    escalated = AlertService(store, lambda: NOW + 60_000).escalate(reading.event_id)
    assert escalated.status == Status.ESCALATED


def test_dispatch_limit_marks_failed_instead_of_retrying_forever(store, reading):
    alert = Alert.from_reading(reading, NOW).model_copy(update={"dispatches": 5})
    store.save(alert, None)
    worker = scheduler(store)
    assert worker.tick(1) == 0
    assert store.get(reading.event_id).status == Status.FAILED
    worker.queue.send.assert_not_called()


def test_missing_alert_and_stale_leader_are_explicit(store, reading):
    with pytest.raises(LookupError):
        AlertService(store, lambda: NOW).ack("missing")
    store.activate_fence(10)
    assert scheduler(store).tick(9) == 0
    dispatcher = Dispatcher(store, lambda: NOW, 60_000, False)
    with pytest.raises(LookupError):
        dispatcher.deliver(DeliveryRequest(alert_id="missing", version=1), 1)


def test_compare_and_swap_conflict_during_delivery_is_a_safe_stale_result(store, reading):
    AlertService(store, lambda: NOW).create(reading)
    scheduler(store).tick(1)
    dispatcher = Dispatcher(store, lambda: NOW, 60_000, False)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(store, "save", Mock(side_effect=Conflict("new owner")))
        assert (
            dispatcher.deliver(DeliveryRequest(alert_id=reading.event_id, version=1), 1) == "stale"
        )
