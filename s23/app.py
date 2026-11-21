import hmac
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from threading import Event
from time import perf_counter
from typing import Annotated, Any

import grpc
import psycopg
import requests
from botocore.exceptions import BotoCoreError, ClientError
from confluent_kafka import KafkaException
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from s23.adapters import UpstreamRejected
from s23.domain import ClinicalEvent, Identifier, Model, Reading, Simulation, simulate
from s23.observability import log
from s23.registry import start_server
from s23.resources import Resources
from s23.services import CLINICAL_TOPIC, VITALS_TOPIC
from s23.settings import Settings
from s23.store import Conflict
from s23.workers import WORKERS

logging.basicConfig(level=logging.INFO, format="%(message)s")


class Device(Model):
    patient_id: Identifier
    active: bool = True


def create_app(settings: Settings | None = None, runtime: Resources | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    runtime = runtime or Resources(config)
    stop = Event()
    jobs: list[Future[None]] = []

    def completed(job: Future[None]) -> None:
        error = job.exception()
        if error is not None:
            runtime.metrics.failures.labels(config.service, "worker").inc()
            log("worker_failed", service=config.service, error_type=type(error).__name__)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        server = (
            start_server(runtime.registry, runtime.metrics)
            if config.service == "device-registry"
            else None
        )
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=config.service)
        try:
            if config.service in WORKERS:
                job = executor.submit(WORKERS[config.service], runtime, stop)
                job.add_done_callback(completed)
                jobs.append(job)
            log("service_started", service=config.service)
            yield
        finally:
            stop.set()
            executor.shutdown(wait=True)
            if server is not None:
                server.stop(2).wait()
            if "device_client" in runtime.__dict__:
                runtime.device_client.close()
            if "http" in runtime.__dict__:
                runtime.http.session.close()
            log("service_stopped", service=config.service)

    app = FastAPI(title=f"S23 {config.service}", lifespan=lifespan)

    @app.middleware("http")
    async def measure(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            if route not in ("/metrics", "/health/live", "/health/ready"):
                runtime.metrics.requests.labels(
                    config.service, request.method, route, str(status)
                ).inc()
                runtime.metrics.latency.labels(config.service, route).observe(
                    perf_counter() - started
                )

    @app.exception_handler(RequestValidationError)
    async def invalid_schema(_: Request, error: RequestValidationError) -> JSONResponse:
        log("invalid_request_schema", service=config.service, errors=len(error.errors()))
        return JSONResponse(status_code=422, content={"detail": "Invalid request schema"})

    @app.exception_handler(LookupError)
    async def not_found(_: Request, error: LookupError) -> JSONResponse:
        log("record_not_found", service=config.service)
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(ValueError)
    async def invalid_state(_: Request, error: ValueError) -> JSONResponse:
        log("invalid_state_transition", service=config.service)
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(Conflict)
    async def conflict(_: Request, error: Conflict) -> JSONResponse:
        log("state_conflict", service=config.service)
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(UpstreamRejected)
    async def upstream_rejected(_: Request, error: UpstreamRejected) -> JSONResponse:
        log("upstream_rejected", service=config.service, status=error.status)
        return JSONResponse(status_code=error.status, content={"detail": str(error)})

    async def dependency_failed(_: Request, error: Exception) -> JSONResponse:
        runtime.metrics.failures.labels(config.service, "dependency").inc()
        log("dependency_failed", service=config.service, error_type=type(error).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "A dependency is unavailable. Inspect centralized logs and retry.",
            },
        )

    for error_type in (
        ClientError,
        BotoCoreError,
        requests.RequestException,
        grpc.RpcError,
        psycopg.Error,
        KafkaException,
        TimeoutError,
        RuntimeError,
    ):
        app.add_exception_handler(error_type, dependency_failed)

    def auth(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if x_api_key is None or not hmac.compare_digest(
            x_api_key.encode(), runtime.api_key.get().encode()
        ):
            log("authentication_failed", service=config.service)
            raise HTTPException(status_code=401, detail="A valid X-API-Key is required")

    @app.get("/")
    def overview() -> dict[str, Any]:
        return {
            "service": config.service,
            "synthetic_only": True,
            "message": "S23 assignment demonstration; see /docs",
        }

    @app.get("/health/live")
    @app.get("/health/ready")
    def health() -> dict[str, Any]:
        if stop.is_set() or any(job.done() for job in jobs):
            raise HTTPException(status_code=503, detail="Service worker is not running")
        return {"service": config.service, "ready": True}

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(runtime.metrics.registry), media_type=CONTENT_TYPE_LATEST)

    if config.service == "patient-simulator":

        @app.post("/simulate")
        def run_simulation(request: Simulation) -> dict[str, int]:
            for reading in simulate(request.run_id, request.seed, request.count, request.start_at):
                runtime.http.call(
                    "POST",
                    f"{config.ingestion_url}/readings",
                    body=reading.model_dump(mode="json"),
                    api_key=runtime.api_key.get(),
                )
                runtime.metrics.processed("generated-reading")
            return {"generated": request.count}

    elif config.service == "device-registry":

        @app.get("/devices")
        def devices() -> list[dict[str, Any]]:
            return runtime.registry.list()

        @app.get("/devices/{device_id}")
        def device(device_id: str) -> dict[str, Any]:
            return runtime.registry.get(device_id)

        @app.put("/devices/{device_id}")
        def update_device(device_id: Identifier, device: Device) -> dict[str, str]:
            runtime.registry.put(device_id, device.patient_id, device.active)
            return {"updated": device_id}

    elif config.service == "vital-ingestion":

        @app.post("/readings", status_code=202, dependencies=[Depends(auth)])
        def ingest(reading: Reading) -> dict[str, str]:
            now = runtime.clock()
            if not now - 300_000 <= reading.observed_at <= now + 60_000:
                log("invalid_reading_timestamp", event_id=reading.event_id)
                raise HTTPException(
                    status_code=422, detail="Reading timestamp is outside demo bounds"
                )
            device = runtime.device_client.get(reading.device_id)
            if device.get("active") is not True or device.get("patient_id") != reading.patient_id:
                log("invalid_device_registration", event_id=reading.event_id)
                raise HTTPException(status_code=422, detail="Device registration does not match")
            runtime.archive.put(reading.event_id, reading.model_dump_json())
            runtime.broker.publish(VITALS_TOPIC, reading.model_dump_json(), reading.device_id)
            event = ClinicalEvent.for_reading(reading)
            runtime.broker.publish(CLINICAL_TOPIC, event.model_dump_json(), reading.device_id)
            runtime.metrics.processed("accepted-reading")
            return {"accepted": reading.event_id}

        @app.post("/simulate", dependencies=[Depends(auth)])
        def simulate_proxy(request: Simulation) -> Any:
            return runtime.http.call(
                "POST", f"{config.simulator_url}/simulate", body=request.model_dump(mode="json")
            )

        @app.get("/alerts", dependencies=[Depends(auth)])
        def alerts_proxy(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> Any:
            return runtime.http.call("GET", f"{config.manager_url}/alerts?limit={limit}")

        @app.get("/alerts/{alert_id}", dependencies=[Depends(auth)])
        def alert_proxy(alert_id: str) -> Any:
            return runtime.http.call("GET", f"{config.manager_url}/alerts/{alert_id}")

        @app.post("/alerts/{alert_id}/acknowledge", dependencies=[Depends(auth)])
        def ack_proxy(alert_id: str) -> Any:
            return runtime.http.call(
                "POST", f"{config.acknowledgement_url}/alerts/{alert_id}/acknowledge"
            )

        @app.get("/analytics", dependencies=[Depends(auth)])
        def analytics_proxy() -> Any:
            return runtime.http.call("GET", f"{config.acknowledgement_url}/analytics")

        @app.get("/notifications", dependencies=[Depends(auth)])
        def notifications_proxy(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> Any:
            return runtime.http.call(
                "GET", f"{config.acknowledgement_url}/notifications?limit={limit}"
            )

    elif config.service == "alert-queue-manager":

        @app.post("/alerts", status_code=201)
        def create_alert(reading: Reading) -> Any:
            return runtime.alerts.create(reading)

        @app.get("/alerts")
        def alerts(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> Any:
            return runtime.store.list_alerts(limit)

        @app.get("/alerts/{alert_id}")
        def alert(alert_id: str) -> Any:
            return runtime.alerts.get(alert_id)

        @app.get("/leader")
        def leader() -> dict[str, Any]:
            term = runtime.election.term()
            return {"leader": term is not None, "term": term}

    elif config.service == "acknowledgement-service":

        @app.post("/alerts/{alert_id}/acknowledge")
        def ack(alert_id: str) -> Any:
            return runtime.alerts.ack(alert_id)

        @app.post("/alerts/{alert_id}/escalate")
        def escalation(alert_id: str) -> Any:
            return runtime.alerts.escalate(alert_id)

        @app.get("/analytics")
        def analytics(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> Any:
            return runtime.store.results(limit)

        @app.get("/notifications")
        def notifications(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> Any:
            return runtime.store.notifications(limit)

    return app
