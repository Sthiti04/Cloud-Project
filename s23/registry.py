import json
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any

import boto3
import grpc
import psycopg
from google.protobuf import json_format, struct_pb2, wrappers_pb2
from psycopg import sql

from s23.observability import Metrics, log
from s23.settings import Settings

METHOD = "/s23.DeviceRegistry/GetDevice"


def connection(settings: Settings, *, admin: bool = False) -> Any:
    options: dict[str, Any] = {
        "host": settings.database_host,
        "dbname": settings.database_name,
        "user": settings.database_user,
        "password": settings.database_password,
        "connect_timeout": 10,
    }
    if settings.mode == "aws":
        options.update(sslmode="verify-full", sslrootcert="/app/certs/rds.pem")
        if admin:
            secret = boto3.client("secretsmanager", region_name=settings.region).get_secret_value(
                SecretId=settings.database_secret_arn
            )
            credentials = json.loads(secret["SecretString"])
            options.update(user=credentials["username"], password=credentials["password"])
        else:
            options["password"] = boto3.client(
                "rds", region_name=settings.region
            ).generate_db_auth_token(
                DBHostname=settings.database_host,
                Port=5432,
                DBUsername=settings.database_user,
                Region=settings.region,
            )
    return psycopg.connect(**options)


def initialise(settings: Settings) -> None:
    with connection(settings, admin=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS devices ("
            "device_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, active BOOLEAN NOT NULL)"
        )
        if settings.mode == "aws":
            exists = conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (settings.database_user,)
            ).fetchone()
            if not exists:
                conn.execute(
                    sql.SQL("CREATE USER {} WITH LOGIN").format(
                        sql.Identifier(settings.database_user)
                    )
                )
            conn.execute(
                sql.SQL("GRANT rds_iam TO {}").format(sql.Identifier(settings.database_user))
            )
            conn.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE ON devices TO {}").format(
                    sql.Identifier(settings.database_user)
                )
            )
        for index in range(1, 4):
            conn.execute(
                "INSERT INTO devices VALUES (%s, %s, TRUE) ON CONFLICT (device_id) DO NOTHING",
                (f"device-{index}", f"patient-{index}"),
            )
    log("registry_initialised", synthetic_devices=3)


class Registry:
    def __init__(self, settings: Settings):
        self.settings = settings

    def get(self, device_id: str) -> dict[str, Any]:
        with connection(self.settings) as conn:
            row = conn.execute(
                "SELECT device_id, patient_id, active FROM devices WHERE device_id = %s",
                (device_id,),
            ).fetchone()
        if row is None:
            raise LookupError("Unknown synthetic device")
        return {"device_id": row[0], "patient_id": row[1], "active": row[2]}

    def list(self) -> list[dict[str, Any]]:
        with connection(self.settings) as conn:
            rows = conn.execute(
                "SELECT device_id, patient_id, active FROM devices ORDER BY device_id LIMIT 100"
            ).fetchall()
        return [{"device_id": r[0], "patient_id": r[1], "active": r[2]} for r in rows]

    def put(self, device_id: str, patient_id: str, active: bool) -> None:
        with connection(self.settings) as conn:
            conn.execute(
                "INSERT INTO devices VALUES (%s, %s, %s) ON CONFLICT (device_id) "
                "DO UPDATE SET patient_id = EXCLUDED.patient_id, active = EXCLUDED.active",
                (device_id, patient_id, active),
            )
        log("synthetic_device_updated", device_id=device_id)


class DeviceClient:
    def __init__(self, channel: Any):
        self.channel = channel
        self.lookup = channel.unary_unary(
            METHOD,
            request_serializer=wrappers_pb2.StringValue.SerializeToString,
            response_deserializer=struct_pb2.Struct.FromString,
        )

    def get(self, device_id: str) -> dict[str, Any]:
        try:
            response = self.lookup(wrappers_pb2.StringValue(value=device_id), timeout=5)
        except grpc.RpcError as error:
            if error.code() == grpc.StatusCode.NOT_FOUND:
                raise LookupError("Unknown synthetic device") from error
            raise
        return json_format.MessageToDict(response)

    def close(self) -> None:
        self.channel.close()


def start_server(registry: Registry, metrics: Metrics | None = None) -> Any:
    def lookup(request: Any, context: Any) -> Any:
        started = perf_counter()
        status = "500"
        try:
            device = registry.get(request.value)
            status = "200"
        except LookupError:
            status = "404"
            context.abort(grpc.StatusCode.NOT_FOUND, "Unknown synthetic device")
        except psycopg.Error as error:
            status = "503"
            log("registry_database_error", error_type=type(error).__name__)
            context.abort(grpc.StatusCode.UNAVAILABLE, "Device registry unavailable")
        finally:
            if metrics is not None:
                metrics.rpc_requests.labels(metrics.service, "GetDevice", status).inc()
                metrics.rpc_latency.labels(metrics.service, "GetDevice").observe(
                    perf_counter() - started
                )
        response = struct_pb2.Struct()
        response.update(device)
        return response

    server = grpc.server(ThreadPoolExecutor(max_workers=4))
    server.add_generic_rpc_handlers(
        (
            grpc.method_handlers_generic_handler(
                "s23.DeviceRegistry",
                {
                    "GetDevice": grpc.unary_unary_rpc_method_handler(
                        lookup,
                        request_deserializer=wrappers_pb2.StringValue.FromString,
                        response_serializer=struct_pb2.Struct.SerializeToString,
                    )
                },
            ),
        )
    )
    if not server.add_insecure_port("[::]:50051"):
        raise RuntimeError("Could not bind the internal registry gRPC port")
    server.start()
    log("grpc_server_started", port=50051)
    return server
