import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import psycopg
import pytest
from google.protobuf import wrappers_pb2

from s23 import bootstrap, registry
from s23.observability import Metrics


def test_registry_sql_is_parameterized_and_initialization_is_idempotent(local_settings):
    connection = MagicMock()
    conn = connection.__enter__.return_value
    with patch("s23.registry.connection", return_value=connection):
        registry.initialise(local_settings)
        assert conn.execute.call_count == 4
        adapter = registry.Registry(local_settings)
        conn.execute.return_value.fetchone.return_value = ("device-1", "patient-1", True)
        assert adapter.get("device-1")["active"]
        conn.execute.return_value.fetchall.return_value = [("device-1", "patient-1", True)]
        assert len(adapter.list()) == 1
        adapter.put("device-1", "patient-1", False)
        assert conn.execute.call_args.args[1] == ("device-1", "patient-1", False)
        conn.execute.return_value.fetchone.return_value = None
        with pytest.raises(LookupError):
            adapter.get("unknown")


def test_rds_iam_and_admin_connections_verify_tls(local_settings):
    config = replace(local_settings, mode="aws", database_secret_arn="arn:db")
    client = Mock()
    client.get_secret_value.return_value = {
        "SecretString": json.dumps({"username": "admin", "password": "synthetic-testing-only"})
    }
    client.generate_db_auth_token.return_value = "iam-token"
    with (
        patch("s23.registry.boto3.client", return_value=client),
        patch("s23.registry.psycopg.connect", return_value=Mock()) as connect,
    ):
        registry.connection(config)
        assert connect.call_args.kwargs["password"] == "iam-token"
        assert connect.call_args.kwargs["sslmode"] == "verify-full"
        registry.connection(config, admin=True)
        assert connect.call_args.kwargs["user"] == "admin"
    connection = MagicMock()
    connection.__enter__.return_value.execute.return_value.fetchone.return_value = None
    with patch("s23.registry.connection", return_value=connection):
        registry.initialise(config)
        assert connection.__enter__.return_value.execute.call_count == 8


def test_grpc_server_marshals_messages_logs_metrics_and_reports_errors():
    server = Mock()
    server.add_insecure_port.return_value = 50051
    adapter = Mock()
    adapter.get.return_value = {"device_id": "d", "patient_id": "p", "active": True}
    metrics = Metrics("device-registry")
    with patch("s23.registry.grpc.server", return_value=server):
        registry.start_server(adapter, metrics)
        handler = server.add_generic_rpc_handlers.call_args.args[0][0]
        method = handler.service(SimpleNamespace(method=registry.METHOD))
        context = Mock()
        context.abort.side_effect = RuntimeError("grpc-abort")
        assert method.unary_unary(wrappers_pb2.StringValue(value="d"), context)["active"]
        adapter.get.side_effect = LookupError("unknown")
        with pytest.raises(RuntimeError, match="grpc-abort"):
            method.unary_unary(wrappers_pb2.StringValue(value="d"), context)
        adapter.get.side_effect = psycopg.Error("offline")
        with pytest.raises(RuntimeError, match="grpc-abort"):
            method.unary_unary(wrappers_pb2.StringValue(value="d"), context)
        server.add_insecure_port.return_value = 0
        with pytest.raises(RuntimeError, match="bind"):
            registry.start_server(adapter)


def test_local_mock_bootstrap_handles_existing_resources(local_settings, aws):
    config = replace(local_settings, aws_endpoint="http://moto:5000")
    session = Mock()
    session.client.side_effect = lambda name, **kwargs: aws.client(name)
    with patch("s23.bootstrap.boto3.Session", return_value=session):
        bootstrap.local_aws(config)
        bootstrap.local_aws(config)
    with pytest.raises(ValueError):
        bootstrap.local_aws(local_settings)


def test_topic_bootstrap_and_command_routing(local_settings, monkeypatch):
    admin = Mock()
    admin.create_topics.return_value = {"vitals": Mock()}
    with patch("s23.bootstrap.AdminClient", return_value=admin):
        bootstrap.topics(local_settings)
        assert len(admin.create_topics.call_args.args[0]) == 3
        assert admin.create_topics.call_args.args[0][0].num_partitions == 6
    for action in ("local", "registry", "topics"):
        monkeypatch.setattr("sys.argv", ["bootstrap", action])
        with (
            patch("s23.bootstrap.Settings.from_env", return_value=local_settings),
            patch("s23.bootstrap.local_aws") as local,
            patch("s23.bootstrap.initialise") as init,
            patch("s23.bootstrap.topics") as topics,
        ):
            bootstrap.main()
            assert local.call_count == (action == "local")
            assert init.call_count == (action in ("local", "registry"))
            assert topics.call_count == (action in ("local", "topics"))
