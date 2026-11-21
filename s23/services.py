from collections.abc import Callable

from s23.domain import (
    Alert,
    ClinicalEvent,
    DeliveryRequest,
    Reading,
    Status,
    acknowledge,
    claim,
    delivered,
    escalate,
)
from s23.observability import log
from s23.ports import Acknowledger, Broker, Queue, Store
from s23.store import Conflict

CLINICAL_TOPIC = "clinical-events"
VITALS_TOPIC = "vitals"
RESULTS_TOPIC = "clinical-results"


class AlertService:
    def __init__(self, store: Store, clock: Callable[[], int]):
        self.store = store
        self.clock = clock

    def create(self, reading: Reading) -> Alert:
        now = self.clock()
        alert = Alert.from_reading(reading, now)
        try:
            self.store.save(alert, None, event=ClinicalEvent.for_alert("created", alert, now))
        except Conflict:
            existing = self.get(reading.event_id)
            if (existing.device_id, existing.patient_id, existing.heart_rate) != (
                reading.device_id,
                reading.patient_id,
                reading.heart_rate,
            ):
                raise ValueError("Reading ID was reused with different data") from None
            log("duplicate_alert", alert_id=existing.alert_id)
            return existing
        log("alert_created", alert_id=alert.alert_id)
        return alert

    def get(self, alert_id: str) -> Alert:
        alert = self.store.get(alert_id)
        if alert is None:
            raise LookupError(f"Alert not found: {alert_id}")
        return alert

    def ack(self, alert_id: str) -> Alert:
        current = self.get(alert_id)
        now = self.clock()
        updated = acknowledge(current, now)
        if updated == current:
            log("duplicate_acknowledgement", alert_id=alert_id)
            return current
        self.store.save(
            updated, current.version, event=ClinicalEvent.for_alert("acknowledged", updated, now)
        )
        log("alert_acknowledged", alert_id=alert_id)
        return updated

    def escalate(self, alert_id: str) -> Alert:
        current = self.get(alert_id)
        if current.status in (Status.ACKNOWLEDGED, Status.ESCALATED):
            log("escalation_already_resolved", alert_id=alert_id, status=current.status)
            return current
        now = self.clock()
        updated = escalate(current, now)
        self.store.save(
            updated, current.version, event=ClinicalEvent.for_alert("escalated", updated, now)
        )
        log("alert_escalated", alert_id=alert_id)
        return updated


class Scheduler:
    def __init__(
        self,
        store: Store,
        broker: Broker,
        queue: Queue,
        acknowledger: Acknowledger,
        clock: Callable[[], int],
        lease_ms: int,
        max_dispatches: int,
    ):
        self.store = store
        self.broker = broker
        self.queue = queue
        self.acknowledger = acknowledger
        self.clock = clock
        self.lease_ms = lease_ms
        self.max_dispatches = max_dispatches

    def tick(self, term: int | None) -> int:
        if term is None:
            return 0
        try:
            self.store.activate_fence(term)
        except Conflict:
            log("stale_leader", term=term)
            return 0
        for event in self.store.events(50):
            self.broker.publish(CLINICAL_TOPIC, event.model_dump_json(), event.device_id)
            self.store.delete_event(event.event_id)
        dispatched = 0
        now = self.clock()
        for current in self.store.due(now, 50):
            if current.status == Status.DELIVERED:
                self.acknowledger.escalate(current.alert_id)
                continue
            if current.dispatches >= self.max_dispatches:
                failed = current.model_copy(
                    update={
                        "status": Status.FAILED,
                        "version": current.version + 1,
                    }
                )
                try:
                    self.store.save(
                        failed,
                        current.version,
                        fence=term,
                        event=ClinicalEvent.for_alert("failed", failed, now),
                    )
                except Conflict:
                    log("dispatch_conflict", alert_id=current.alert_id, term=term)
                else:
                    log("dispatch_exhausted", alert_id=current.alert_id)
                continue
            updated = claim(current, now, term, self.lease_ms)
            try:
                self.store.save(updated, current.version, fence=term)
            except Conflict:
                log("dispatch_conflict", alert_id=current.alert_id, term=term)
                continue
            self.queue.send(DeliveryRequest(alert_id=updated.alert_id, version=updated.version))
            log("dispatch_queued", alert_id=updated.alert_id, term=term, version=updated.version)
            dispatched += 1
        return dispatched


class TransientDeliveryError(RuntimeError):
    """Synthetic, intentionally retryable notification failure."""


class Dispatcher:
    def __init__(
        self,
        store: Store,
        clock: Callable[[], int],
        ack_timeout_ms: int,
        fail_first: bool,
    ):
        self.store = store
        self.clock = clock
        self.ack_timeout_ms = ack_timeout_ms
        self.fail_first = fail_first

    def deliver(self, request: DeliveryRequest, receive_count: int) -> str:
        current = self.store.get(request.alert_id)
        if current is None:
            raise LookupError(f"Alert not found: {request.alert_id}")
        if current.status != Status.IN_FLIGHT:
            log("delivery_duplicate", alert_id=request.alert_id, status=current.status)
            return "duplicate"
        if current.version != request.version:
            log("delivery_stale", alert_id=request.alert_id, version=request.version)
            return "stale"
        if self.fail_first and receive_count == 1 and current.dispatches == 1:
            log("delivery_transient_failure", alert_id=request.alert_id)
            raise TransientDeliveryError("Synthetic first-attempt notification failure")
        now = self.clock()
        updated = delivered(current, now, self.ack_timeout_ms)
        try:
            self.store.save(
                updated, current.version, event=ClinicalEvent.for_alert("delivered", updated, now)
            )
        except Conflict:
            log("delivery_stale", alert_id=request.alert_id, version=request.version)
            return "stale"
        log("synthetic_notification_delivered", alert_id=request.alert_id, delivery=request.version)
        return "delivered"
