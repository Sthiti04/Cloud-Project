import json
from threading import Event
from typing import Any

from confluent_kafka import KafkaException

from s23.domain import Reading
from s23.observability import log
from s23.resources import Resources
from s23.services import RESULTS_TOPIC, VITALS_TOPIC


def _poll(consumer: Any) -> Any:
    message = consumer.poll(1)
    if message is not None and message.error():
        raise KafkaException(message.error())
    return message


def rules(resources: Resources, stop: Event) -> None:
    consumer = resources.broker.consumer("alert-rules", VITALS_TOPIC)
    try:
        while not stop.is_set():
            message = _poll(consumer)
            if message is None:
                continue
            reading = Reading.model_validate_json(message.value())
            if reading.abnormal:
                resources.http.call(
                    "POST",
                    f"{resources.settings.manager_url}/alerts",
                    body=reading.model_dump(mode="json"),
                )
            consumer.commit(message=message, asynchronous=False)
            resources.metrics.processed("reading")
    finally:
        consumer.close()


def results(resources: Resources, stop: Event) -> None:
    consumer = resources.broker.consumer("clinical-results-store", RESULTS_TOPIC)
    try:
        while not stop.is_set():
            message = _poll(consumer)
            if message is None:
                continue
            result = json.loads(message.value())
            resources.store.put_result(result)
            consumer.commit(message=message, asynchronous=False)
            resources.metrics.processed("window-result")
            log(
                "analytics_result_stored",
                device_id=result["device_id"],
                window_end=result["window_end"],
            )
    finally:
        consumer.close()


def schedule(resources: Resources, stop: Event) -> None:
    resources.election.start()
    previous: int | None = None
    try:
        while not stop.is_set():
            term = resources.election.term()
            resources.metrics.leader.labels(resources.settings.service).set(int(term is not None))
            if term != previous:
                log("queue_leadership", leader=term is not None, term=term)
                previous = term
            count = resources.scheduler.tick(term)
            if count:
                resources.metrics.events.labels(resources.settings.service, "dispatch").inc(count)
            stop.wait(2)
    finally:
        resources.election.close()


WORKERS = {
    "alert-rule-engine": rules,
    "alert-queue-manager": schedule,
    "acknowledgement-service": results,
}
