import pytest

from s23.domain import ClinicalEvent, claim
from s23.store import Conflict

NOW = 1_800_000_000_000


def test_create_is_atomic_with_outbox_and_conflicts_are_explicit(store, alert):
    event = ClinicalEvent.for_alert("created", alert, NOW)
    store.save(alert, None, event=event)
    assert store.get(alert.alert_id) == alert
    assert store.events(10) == [event]
    with pytest.raises(Conflict):
        store.save(alert, None, event=event)
    store.delete_event(event.event_id)
    assert store.events(10) == []
    assert store.get("missing") is None


def test_due_query_and_version_compare_and_swap(store, alert):
    store.save(alert, None)
    assert store.due(NOW - 1, 10) == []
    assert store.due(NOW, 10) == [alert]
    updated = claim(alert, NOW, 4, 30_000)
    store.save(updated, 0)
    assert store.get(alert.alert_id) == updated
    with pytest.raises(Conflict):
        store.save(updated, 0)
    assert len(store.list_alerts(10)) == 1


def test_fencing_blocks_an_old_leader_atomically(store, alert):
    store.save(alert, None)
    store.activate_fence(4)
    store.save(claim(alert, NOW, 4, 30_000), 0, fence=4)
    store.activate_fence(5)
    current = store.get(alert.alert_id)
    with pytest.raises(Conflict):
        store.save(claim(current, NOW + 30_000, 4, 30_000), 1, fence=4)
    with pytest.raises(Conflict):
        store.activate_fence(3)
    store.activate_fence(5)


def test_results_preserve_numeric_aggregates(store):
    result = {"device_id": "device-1", "window_end": NOW, "average_heart_rate": 72.5}
    store.put_result(result)
    assert store.results(10) == [result]
