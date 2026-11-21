import json
import subprocess
from unittest.mock import Mock, patch

import pytest
import yaml

from tools import common, configure_aws, demo, setup_local, verify_hpa


@pytest.fixture(autouse=True)
def demo_clock_and_identifiers(monkeypatch):
    monkeypatch.setattr(demo.time, "time", lambda: 1_800_000_000)
    monkeypatch.setattr(demo.uuid, "uuid4", lambda: Mock(hex="abcdef123456"))


@pytest.fixture
def metadata(tmp_path):
    for chart in ("app", "platform"):
        (tmp_path / "deploy" / chart).mkdir(parents=True)
    return {
        "project": "s23-demo",
        "region": "ap-south-1",
        "app_repository": "example/app",
        "environment": {"APP_MODE": "aws"},
        "role_arns": {},
        "log_groups": ["logs"],
        "lambda_function": "dispatcher",
        "certificate_pem": "public-demo-certificate",
        "zookeeper_volumes": [{"id": f"vol-{i}", "zone": "ap-south-1a"} for i in range(3)],
    }


def snapshot(replicas):
    hpas = {
        "items": [
            {
                "metadata": {"name": name},
                "status": {
                    "currentReplicas": replicas,
                    "desiredReplicas": replicas,
                },
            }
            for name in verify_hpa.CRITICAL
        ]
    }
    deployments = {
        "items": [
            {
                "metadata": {"name": name},
                "status": {
                    "availableReplicas": replicas,
                },
            }
            for name in verify_hpa.CRITICAL
        ]
    }
    return hpas, deployments


def test_hpa_proof_requires_a_baseline_then_scaleout(tmp_path):
    responses = [json.dumps(item) for size in (2, 1, 2) for item in snapshot(size)]
    with (
        patch("tools.verify_hpa.run", side_effect=responses),
        patch("tools.verify_hpa.time.monotonic", side_effect=[0, 0, 1, 2]),
        patch("tools.verify_hpa.time.sleep"),
        patch("tools.verify_hpa.ROOT", tmp_path),
        patch("sys.argv", ["verify_hpa", "--timeout", "10"]),
    ):
        verify_hpa.main()
    report = json.loads((tmp_path / "evidence" / "hpa.json").read_text())
    assert report["verified"] is True
    assert len(report["snapshots"]) == 3
    assert report["baseline_seen"] is True


def test_already_scaled_hpas_are_not_false_success(tmp_path):
    responses = [json.dumps(item) for item in snapshot(2)]
    with (
        patch("tools.verify_hpa.run", side_effect=responses),
        patch("tools.verify_hpa.time.monotonic", side_effect=[0, 0, 11]),
        patch("tools.verify_hpa.ROOT", tmp_path),
        patch("tools.verify_hpa.time.sleep"),
        patch("sys.argv", ["verify_hpa", "--timeout", "10"]),
    ):
        with pytest.raises(TimeoutError):
            verify_hpa.main()
    assert not json.loads((tmp_path / "evidence" / "hpa.json").read_text())["verified"]


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(1, ["kubectl", "get", "hpa"]),
        json.JSONDecodeError("Malformed snapshot", "invalid", 0),
    ],
)
def test_interrupted_hpa_observation_replaces_stale_success(tmp_path, failure):
    path = tmp_path / "evidence" / "hpa.json"
    path.parent.mkdir()
    path.write_text('{"verified": true}', encoding="utf-8")
    responses = [json.dumps(item) for item in snapshot(1)] + [failure]
    with (
        patch("tools.verify_hpa.run", side_effect=responses),
        patch("tools.verify_hpa.time.monotonic", side_effect=[0, 0, 1]),
        patch("tools.verify_hpa.time.sleep"),
        patch("tools.verify_hpa.ROOT", tmp_path),
        patch("sys.argv", ["verify_hpa", "--timeout", "10"]),
    ):
        with pytest.raises(type(failure)):
            verify_hpa.main()
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["verified"] is False
    assert report["baseline_seen"] is True
    assert report["observed"] == []
    assert len(report["snapshots"]) == 1


def test_local_setup_is_private_and_never_overwrites_existing_secrets(tmp_path):
    with patch("tools.setup_local.secrets.token_urlsafe", return_value="synthetic-random"):
        setup_local.initialise(tmp_path)
    assert common.environment(tmp_path / ".env")["FAIL_FIRST_DELIVERY"] == "false"
    with pytest.raises(FileExistsError):
        setup_local.initialise(tmp_path)
    with patch("tools.setup_local.ROOT", tmp_path), patch("sys.argv", ["setup_local"]):
        with pytest.raises(FileExistsError):
            setup_local.main()


def test_configuration_updates_preserve_nested_customizations(tmp_path, metadata):
    existing = tmp_path / "deploy" / "app" / "values-aws.yaml"
    existing.write_text("zookeeper:\n  image: custom-image\n", encoding="utf-8")
    image = f"example/app@sha256:{'0' * 64}"
    configure_aws.configure(tmp_path, metadata, image)
    assert yaml.safe_load(existing.read_text())["zookeeper"]["image"] == "custom-image"
    with pytest.raises(ValueError):
        configure_aws.configure(tmp_path, metadata, "example/app:latest")
    metadata["environment"]["AWS_SESSION_TOKEN"] = "must-not-be-committed"
    with pytest.raises(ValueError, match="secret"):
        configure_aws.configure(tmp_path, metadata, image)


def test_common_commands_and_missing_metadata_report_errors(tmp_path):
    with patch("tools.common.subprocess.run", return_value=Mock(stdout="result")) as run:
        assert common.run(["read-only"], capture=True) == "result"
        assert common.run(["read-only"]) == ""
        assert run.call_args.kwargs["check"] is True
    with patch("tools.common.ROOT", tmp_path):
        with pytest.raises(FileNotFoundError):
            common.deployment()
        (tmp_path / "artifacts").mkdir()
        (tmp_path / "artifacts" / "deployment.json").write_text('{"region":"ap-south-1"}')
        assert common.deployment()["region"] == "ap-south-1"


def test_demo_client_uses_pinned_ca_and_validates_http_failures(tmp_path):
    with (
        patch("tools.demo.requests.Session", return_value=Mock(headers={})) as factory,
        patch("tools.demo.ROOT", tmp_path),
        patch("tools.demo.environment", return_value={"DEMO_API_KEY": "synthetic"}),
    ):
        client = demo.Client(False)
        assert client.url == "http://127.0.0.1:8080"
        assert client.session.headers["X-API-Key"] == "synthetic"
        assert client.session.headers["Connection"] == "close"
        client.session.request.return_value.ok = False
        client.session.request.return_value.status_code = 503
        client.session.request.return_value.text = "dependency unavailable"
        with pytest.raises(demo.ApiError):
            client.call("GET", "/alerts")
        client.session.request.return_value.ok = True
        client.session.request.return_value.json.return_value = {"ok": True}
        assert client.call("GET", "/alerts") == {"ok": True}
        metadata = {
            "public_url": "https://demo",
            "region": "ap-south-1",
            "environment": {"API_SECRET_ARN": "arn:fake"},
        }
        with (
            patch("tools.demo.deployment", return_value=metadata),
            patch("tools.demo.run", return_value='{"api_key":"synthetic"}'),
        ):
            aws_client = demo.Client(True)
            assert aws_client.session.verify == str(tmp_path / "artifacts" / "demo-ca.pem")
            assert aws_client.session.headers["Connection"] == "close"
        assert factory.call_count == 2


def test_demo_client_surfaces_connection_errors_without_retrying_mutating_requests():
    with (
        patch("tools.demo.requests.Session", return_value=Mock(headers={})),
        patch("tools.demo.environment", return_value={"DEMO_API_KEY": "synthetic"}),
    ):
        client = demo.Client(False)
    error = demo.requests.ConnectionError("Remote end closed connection")
    client.session.request.side_effect = error
    with pytest.raises(demo.requests.ConnectionError, match="Remote end closed"):
        client.call("POST", "/readings", {"event_id": "synthetic-tick"})
    client.session.request.assert_called_once_with(
        "POST",
        "http://127.0.0.1:8080/readings",
        json={"event_id": "synthetic-tick"},
        timeout=15,
    )


def test_configure_cli_and_reject_invalid_yaml_before_partial_writes(tmp_path, metadata):
    with (
        patch("tools.configure_aws.ROOT", tmp_path),
        patch("tools.configure_aws.run", return_value=json.dumps(metadata)),
        patch("sys.argv", ["configure_aws", "--image", f"example/app@sha256:{'0' * 64}"]),
    ):
        configure_aws.main()
    path = tmp_path / "deploy" / "platform" / "values-aws.yaml"
    path.write_text("[1]")
    app = tmp_path / "deploy" / "app" / "values-aws.yaml"
    before = app.read_text()
    with pytest.raises(ValueError, match="mapping"):
        configure_aws.configure(tmp_path, metadata, f"example/app@sha256:{'1' * 64}")
    assert app.read_text() == before
    path.write_text("project: demo")
    app.write_text("zookeeper: [1]")
    with pytest.raises(ValueError, match="mapping"):
        configure_aws.configure(tmp_path, metadata, f"example/app@sha256:{'0' * 64}")
    metadata["environment"] = []
    with pytest.raises(ValueError, match="map"):
        configure_aws.configure(tmp_path, metadata, f"example/app@sha256:{'0' * 64}")


def test_smoke_waits_for_its_exact_alerts_then_checks_inbox_and_window_shape():
    client = Mock()
    run_id = "smoke-abcdef123456"
    polls = 0
    window = {
        "device_id": "device-1",
        "window_start": 1_800_000_000_000,
        "window_end": 1_800_000_060_000,
        "reading_count": 12,
        "created_count": 4,
        "delivery_count": 4,
        "ack_count": 1,
        "escalation_count": 1,
        "failed_count": 0,
        "average_heart_rate": 80,
        "average_ack_delay_ms": 2000,
    }

    def call(method, path, body=None):
        nonlocal polls
        if path == "/simulate":
            return {"generated": 12}
        if path == "/readings":
            polls += 1
            return {"accepted": "tick"}
        if method == "POST":
            return {"status": "ACKNOWLEDGED"}
        if path.startswith("/alerts/"):
            if polls == 1:
                response = Mock(status_code=404, text="not yet created")
                raise demo.ApiError(method, path, response)
            return {
                "alert_id": path.rsplit("/", 1)[-1],
                "status": "DELIVERED" if path.endswith("-0") else "ESCALATED",
            }
        if path == "/analytics":
            return [window] if polls > 1 else []
        return [{"alert_id": f"{run_id}-{i}"} for i in (0, 3, 6, 9)]

    client.call.side_effect = call
    with (
        patch("tools.demo.uuid.uuid4", return_value=Mock(hex="abcdef123456")),
        patch("tools.demo.time.time", return_value=1_800_000_000),
        patch("tools.demo.time.monotonic", side_effect=[0, 0, 1]),
        patch("tools.demo.time.sleep"),
    ):
        report = demo.smoke(client, 300)
    assert report["verified"] is True
    assert report["alert_count"] == 4
    assert len(report["notifications"]) == 4
    assert report["windows"][0]["reading_count"] == 12
    assert polls == 2


def test_smoke_rejects_bad_generator_result_and_does_not_fake_timeout_success():
    client = Mock()
    client.call.return_value = {"generated": 11}
    with pytest.raises(AssertionError):
        demo.smoke(client, 10)
    client.call.return_value = {"generated": 12}
    with patch("tools.demo.time.monotonic", side_effect=[0, 11]):
        with pytest.raises(TimeoutError):
            demo.smoke(client, 10)


@pytest.mark.parametrize("action", ["simulate", "status", "tick", "ack", "smoke"])
def test_demo_cli_actions_and_evidence_are_local_and_explicit(tmp_path, action):
    args = ["demo", action] + (["test-alert"] if action == "ack" else [])
    client = Mock()
    client.call.return_value = {"ok": True}
    with (
        patch("tools.demo.Client", return_value=client),
        patch("tools.demo.ROOT", tmp_path),
        patch("tools.demo.smoke", return_value={"verified": True}),
        patch("sys.argv", args),
    ):
        demo.main()
    if action == "smoke":
        assert json.loads((tmp_path / "evidence" / "smoke-local.json").read_text())["verified"]


def test_demo_ack_requires_an_id():
    with patch("tools.demo.Client", return_value=Mock()), patch("sys.argv", ["demo", "ack"]):
        with pytest.raises(SystemExit):
            demo.main()
