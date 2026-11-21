import json
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from s23.adapters import ApiKey, HttpAcknowledger, HttpClient, UpstreamRejected
from s23.broker import KafkaBus
from s23.resources import Resources
from s23.settings import Settings, boolean, required


def test_settings_require_explicit_mode_and_validate(local_settings, monkeypatch):
    assert Settings.from_env("vital-ingestion").service == "vital-ingestion"
    monkeypatch.delenv("DEMO_API_KEY")
    with pytest.raises(ValueError, match="DEMO_API_KEY"):
        Settings.from_env("patient-simulator")
    monkeypatch.setenv("APP_MODE", "aws")
    with pytest.raises(ValueError, match="API_SECRET_ARN"):
        Settings.from_env("vital-ingestion")
    monkeypatch.setenv("API_SECRET_ARN", "arn:demo")
    assert Settings.from_env("vital-ingestion").mode == "aws"
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://moto")
    with pytest.raises(ValueError, match="mock"):
        Settings.from_env()
    monkeypatch.setenv("APP_MODE", "wrong")
    with pytest.raises(ValueError, match="APP_MODE"):
        Settings.from_env()
    with pytest.raises(ValueError, match="Unknown service"):
        Settings.from_env("wrong")


def test_configuration_helpers_and_timeout_guards(local_settings, monkeypatch):
    monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
    with pytest.raises(ValueError, match="DOES_NOT_EXIST"):
        required("DOES_NOT_EXIST")
    assert boolean("DOES_NOT_EXIST") is False
    monkeypatch.setenv("FLAG", "true")
    assert boolean("FLAG")
    monkeypatch.setenv("FLAG", "yes")
    with pytest.raises(ValueError):
        boolean("FLAG")
    with pytest.raises(ValueError, match="timeouts"):
        replace(local_settings, ack_timeout_ms=0)
    with pytest.raises(ValueError, match="MAX_DISPATCHES"):
        replace(local_settings, max_dispatches=0)


def test_api_secret_is_validated_and_cached(aws):
    client = aws.client("secretsmanager")
    arn = client.create_secret(
        Name="demo-key", SecretString=json.dumps({"api_key": "synthetic-only-valid-test-key"})
    )["ARN"]
    key = ApiKey(client, arn, "")
    with patch.object(client, "get_secret_value", wraps=client.get_secret_value) as get:
        assert key.get() == key.get()
        assert get.call_count == 1
    with pytest.raises(ValueError):
        ApiKey(client, "", "short").get()


def test_resources_construct_only_needed_adapters_and_cache_them(local_settings, aws):
    session = Mock()
    session.resource.side_effect = lambda name, **kwargs: aws.resource(name)
    session.client.side_effect = lambda name, **kwargs: aws.client(name)
    with (
        patch("s23.resources.boto3.Session", return_value=session),
        patch("s23.resources.KafkaBus.from_settings", return_value=Mock()),
        patch("s23.resources.grpc.insecure_channel", return_value=Mock()),
        patch("s23.resources.KazooClient", return_value=Mock()),
        patch("s23.resources.time", return_value=1_800_000_000),
    ):
        runtime = Resources(local_settings)
        assert runtime.clock() == 1_800_000_000_000
        for name in (
            "store",
            "queue",
            "archive",
            "api_key",
            "broker",
            "registry",
            "device_client",
            "http",
            "alerts",
            "dispatcher",
            "election",
            "scheduler",
        ):
            assert getattr(runtime, name) is getattr(runtime, name)


def test_kafka_factories_configure_manual_commits(local_settings):
    with (
        patch("s23.broker.Producer", return_value=Mock()) as producer,
        patch("s23.broker.Consumer", return_value=Mock()) as consumer,
    ):
        bus = KafkaBus.from_settings(local_settings)
        assert producer.call_args.args[0]["enable.idempotence"] is True
        bus.consumer("test", "vitals")
        assert consumer.call_args.args[0]["enable.auto.commit"] is False
        consumer.return_value.subscribe.assert_called_once_with(["vitals"])


def test_upstream_client_errors_are_not_mislabeled_as_outages():
    import requests

    session = Mock()
    response = session.request.return_value
    response.status_code = 409
    response.raise_for_status.side_effect = requests.HTTPError("conflict")
    with pytest.raises(UpstreamRejected) as error:
        HttpClient(session).call("POST", "http://ack")
    assert error.value.status == 409
    ack = HttpAcknowledger(Mock(), "http://ack")
    ack.http.call.side_effect = UpstreamRejected(409)
    ack.escalate("a")
    ack.http.call.side_effect = UpstreamRejected(404)
    with pytest.raises(UpstreamRejected):
        ack.escalate("a")
