from concurrent.futures import Future
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from s23.adapters import UpstreamRejected
from s23.app import create_app
from s23.domain import ClinicalEvent
from s23.observability import Metrics
from s23.store import Conflict

NOW = 1_800_000_000_000


@pytest.fixture
def runtime():
    resources = Mock()
    resources.clock.return_value = NOW
    resources.api_key.get.return_value = "local-test-key-with-32-characters"
    resources.device_client.get.return_value = {"patient_id": "patient-1", "active": True}
    resources.metrics = Metrics("vital-ingestion")
    return resources


@pytest.fixture
def settings():
    return SimpleNamespace(
        service="vital-ingestion",
        manager_url="http://manager",
        simulator_url="http://simulator",
        acknowledgement_url="http://ack",
    )


def test_public_health_is_open_but_readings_require_key(settings, runtime, reading):
    with TestClient(create_app(settings, runtime)) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/").json()["synthetic_only"] is True
        assert client.post("/readings", json=reading.model_dump()).status_code == 401
        runtime.broker.publish.assert_not_called()


def test_reading_uses_grpc_archive_and_both_kafka_topics(settings, runtime, reading):
    with TestClient(create_app(settings, runtime)) as client:
        response = client.post(
            "/readings", json=reading.model_dump(), headers={"X-API-Key": runtime.api_key.get()}
        )
        assert response.status_code == 202
        runtime.device_client.get.assert_called_once_with("device-1")
        runtime.archive.put.assert_called_once()
        assert runtime.broker.publish.call_count == 2
        args = runtime.broker.publish.call_args_list[1].args
        assert args[0] == "clinical-events"
        assert ClinicalEvent.model_validate_json(args[1]).kind == "reading"
        metrics = client.get("/metrics").text
        assert "s23_http_requests_total" in metrics


@pytest.mark.parametrize(
    "patient,active,timestamp",
    [
        ("other", True, NOW),
        ("patient-1", False, NOW),
        ("patient-1", True, NOW + 60_001),
        ("patient-1", True, NOW - 300_001),
    ],
)
def test_invalid_device_or_timestamp_is_not_published(
    settings, runtime, reading, patient, active, timestamp
):
    runtime.device_client.get.return_value = {"patient_id": patient, "active": active}
    with TestClient(create_app(settings, runtime)) as client:
        response = client.post(
            "/readings",
            json={**reading.model_dump(), "observed_at": timestamp},
            headers={"X-API-Key": runtime.api_key.get()},
        )
        assert response.status_code == 422
        runtime.broker.publish.assert_not_called()


def test_invalid_schema_returns_422_without_logging_input(settings, runtime):
    with TestClient(create_app(settings, runtime)) as client:
        response = client.post(
            "/readings",
            json={"password": "do-not-log"},
            headers={"X-API-Key": runtime.api_key.get()},
        )
        assert response.status_code == 422


def test_gateway_routes_to_the_responsible_services(settings, runtime):
    runtime.http.call.return_value = {"ok": True}
    headers = {"X-API-Key": runtime.api_key.get()}
    with TestClient(create_app(settings, runtime)) as client:
        assert client.get("/alerts", headers=headers).status_code == 200
        assert client.post("/alerts/r/acknowledge", headers=headers).status_code == 200
        assert client.get("/analytics", headers=headers).status_code == 200
        assert client.get("/notifications", headers=headers).status_code == 200
        assert client.get("/alerts/r", headers=headers).status_code == 200
        assert (
            client.post(
                "/simulate",
                headers=headers,
                json={
                    "run_id": "run-a",
                    "start_at": NOW,
                    "count": 6,
                },
            ).status_code
            == 200
        )
        assert runtime.http.call.call_args_list[-1].args == ("POST", "http://simulator/simulate")


@pytest.mark.parametrize(
    "error,status",
    [
        (LookupError("missing"), 404),
        (ValueError("invalid state"), 409),
        (Conflict("concurrent change"), 409),
        (UpstreamRejected(404), 404),
        (RuntimeError("dependency offline"), 503),
    ],
)
def test_gateway_preserves_expected_errors(settings, runtime, error, status):
    runtime.http.call.side_effect = error
    with TestClient(create_app(settings, runtime)) as client:
        assert (
            client.get(
                "/alerts",
                headers={
                    "X-API-Key": runtime.api_key.get(),
                },
            ).status_code
            == status
        )


@pytest.mark.parametrize(
    "service",
    [
        "patient-simulator",
        "device-registry",
        "alert-queue-manager",
        "acknowledgement-service",
    ],
)
def test_role_specific_apis_delegate_to_their_own_adapters(
    service, local_settings, runtime, reading
):
    config = replace(local_settings, service=service)
    runtime.registry.list.return_value = [{"device_id": "device-1"}]
    runtime.registry.get.return_value = {"device_id": "device-1"}
    runtime.alerts.create.return_value = {"alert_id": reading.event_id}
    runtime.alerts.get.return_value = {"alert_id": reading.event_id}
    runtime.alerts.ack.return_value = {"status": "ACKNOWLEDGED"}
    runtime.alerts.escalate.return_value = {"status": "ESCALATED"}
    runtime.store.list_alerts.return_value = []
    runtime.store.results.return_value = []
    runtime.store.notifications.return_value = []
    runtime.election.term.return_value = 1
    with (
        patch("s23.app.WORKERS", {}),
        patch("s23.app.start_server", return_value=Mock()),
        TestClient(create_app(config, runtime)) as client,
    ):
        if service == "patient-simulator":
            assert client.post(
                "/simulate",
                json={
                    "run_id": "test-run",
                    "start_at": NOW,
                    "count": 3,
                },
            ).json() == {"generated": 3}
            assert runtime.http.call.call_count == 3
        elif service == "device-registry":
            assert client.get("/devices").status_code == 200
            assert client.get("/devices/device-1").status_code == 200
            assert client.put(
                "/devices/device-1",
                json={
                    "patient_id": "patient-1",
                    "active": False,
                },
            ).json() == {"updated": "device-1"}
            runtime.registry.put.assert_called_once_with("device-1", "patient-1", False)
        elif service == "alert-queue-manager":
            assert client.post("/alerts", json=reading.model_dump()).status_code == 201
            assert client.get("/alerts").status_code == 200
            assert client.get("/alerts/reading-1").status_code == 200
            assert client.get("/leader").json() == {"leader": True, "term": 1}
        else:
            assert client.post("/alerts/reading-1/acknowledge").status_code == 200
            assert client.post("/alerts/reading-1/escalate").status_code == 200
            assert client.get("/analytics").json() == []
            assert client.get("/notifications").json() == []


@pytest.mark.parametrize("failed", [False, True])
def test_finished_or_failed_worker_makes_readiness_fail(local_settings, runtime, failed):
    future = Future()
    if failed:
        future.set_exception(RuntimeError("worker test"))
    else:
        future.set_result(None)
    executor = Mock()
    executor.submit.return_value = future
    with (
        patch("s23.app.ThreadPoolExecutor", return_value=executor),
        patch("s23.app.WORKERS", {"alert-rule-engine": Mock()}),
        TestClient(create_app(replace(local_settings, service="alert-rule-engine"), runtime)) as c,
    ):
        assert c.get("/health/ready").status_code == 503
        assert runtime.metrics.failures.labels("vital-ingestion", "worker")._value.get() == 0
        assert runtime.metrics.failures.labels("alert-rule-engine", "worker")._value.get() == int(
            failed
        )
