import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.repository
SERVICES = {
    "patient-simulator",
    "device-registry",
    "vital-ingestion",
    "alert-rule-engine",
    "alert-queue-manager",
    "acknowledgement-service",
}
GUIDES = [
    "00-project-explained.md",
    "01-start-here.md",
    "02-requirements-and-evidence.md",
    "03-design.md",
    "04-local-walkthrough.md",
    "05-aws-deployment.md",
    "06-demonstration-and-observability.md",
    "07-troubleshooting.md",
    "08-cleanup-and-cost.md",
    "09-viva-and-ai-help.md",
    "10-validation-status.md",
    "11-components-and-viva.md",
]


@pytest.fixture(scope="module")
def workflow():
    return yaml.load(
        (ROOT / ".github" / "workflows" / "validate.yml").read_text(),
        Loader=yaml.BaseLoader,
    )


def render_chart(chart, api_versions=()):
    command = [
        os.environ.get("HELM", "helm"),
        "template",
        "s23",
        str(ROOT / "deploy" / chart),
        "--namespace",
        "s23" if chart == "app" else "argocd",
        "-f",
        str(ROOT / "tests" / "helm-values.yaml"),
        "--set",
        "loadTest.enabled=true",
    ]
    for api_version in api_versions:
        command.extend(["--api-versions", api_version])
    output = subprocess.check_output(command, text=True)
    return [item for item in yaml.safe_load_all(output) if item is not None]


@pytest.fixture(scope="module")
def rendered():
    return {chart: render_chart(chart) for chart in ("app", "platform")}


def resources(rendered, chart, kind):
    return {item["metadata"]["name"]: item for item in rendered[chart] if item["kind"] == kind}


def sync_wave(resource):
    return int(resource["metadata"].get("annotations", {}).get("argocd.argoproj.io/sync-wave", 0))


def test_exact_six_stateless_roles_and_only_one_public_service(rendered):
    deployments = resources(rendered, "app", "Deployment")
    assert set(deployments) == SERVICES
    for name, deployment in deployments.items():
        pod = deployment["spec"]["template"]["spec"]
        assert pod["serviceAccountName"] == name
        assert "@sha256:" in pod["containers"][0]["image"]
        assert pod["securityContext"]["runAsNonRoot"]
        assert pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"]
        assert re.fullmatch(
            "[a-f0-9]{64}",
            deployment["spec"]["template"]["metadata"]["annotations"]["checksum/environment"],
        )
    services = resources(rendered, "app", "Service")
    assert {name for name, item in services.items() if item["spec"].get("type") == "NodePort"} == {
        "vital-ingestion"
    }
    assert not any(item["spec"].get("type") == "LoadBalancer" for item in services.values())
    ports = services["device-registry"]["spec"]["ports"]
    assert any(port["port"] == 50051 for port in ports)
    env = resources(rendered, "app", "ConfigMap")["s23-environment"]["data"]
    assert env["APP_MODE"] == "aws" and "AWS_ENDPOINT_URL" not in env
    assert not {"DEMO_API_KEY", "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD"}.intersection(env)


def test_two_cpu_hpas_and_gitops_do_not_fight_autoscaling(rendered):
    hpas = resources(rendered, "app", "HorizontalPodAutoscaler")
    assert set(hpas) == {"vital-ingestion", "device-registry"}
    deployments = resources(rendered, "app", "Deployment")
    for name, item in hpas.items():
        assert item["spec"]["minReplicas"] == 1 and item["spec"]["maxReplicas"] >= 2
        assert item["spec"]["scaleTargetRef"]["name"] == name
        assert item["spec"]["metrics"][0]["resource"]["name"] == "cpu"
        assert "replicas" not in deployments[name]["spec"]
        cpu = deployments[name]["spec"]["template"]["spec"]["containers"][0]["resources"]
        assert cpu["requests"]["cpu"] == "10m"
    apps = resources(rendered, "platform", "Application")
    app = apps["s23-application"]["spec"]
    assert {item["name"] for item in app["ignoreDifferences"]} == set(hpas)
    assert "RespectIgnoreDifferences=true" in app["syncPolicy"]["syncOptions"]


def test_gitops_creates_hpas_after_their_target_deployments(rendered):
    deployments = resources(rendered, "app", "Deployment")
    for hpa in resources(rendered, "app", "HorizontalPodAutoscaler").values():
        target = deployments[hpa["spec"]["scaleTargetRef"]["name"]]
        assert sync_wave(hpa) > sync_wave(target), (
            "An HPA must not block Argo from creating the Deployment it needs to become healthy"
        )


def test_gitops_starts_load_after_the_autoscalers(rendered):
    hpas = resources(rendered, "app", "HorizontalPodAutoscaler").values()
    load_jobs = [
        job
        for name, job in resources(rendered, "app", "Job").items()
        if name.startswith("load-test-")
    ]
    assert load_jobs
    for job in load_jobs:
        assert sync_wave(job) > max(sync_wave(hpa) for hpa in hpas), (
            "A load Job must not block the services and autoscalers it exercises"
        )


def test_gitops_waits_for_initialization_before_starting_services(rendered):
    jobs = resources(rendered, "app", "Job")
    prerequisites = [
        jobs["schema-init"],
        jobs["topic-bootstrap"],
        resources(rendered, "app", "StatefulSet")["zookeeper"],
    ]
    for deployment in resources(rendered, "app", "Deployment").values():
        assert all(
            sync_wave(prerequisite) < sync_wave(deployment) for prerequisite in prerequisites
        )
    for name in ("schema-init", "topic-bootstrap"):
        assert jobs[name]["metadata"]["annotations"]["argocd.argoproj.io/hook"] == "Sync"


@pytest.mark.parametrize("api_available", [False, True], ids=["fresh-cluster", "existing-cluster"])
def test_cloudwatch_monitor_is_not_omitted_before_crd_installation(rendered, api_available):
    platform = (
        render_chart("platform", ["monitoring.coreos.com/v1/ServiceMonitor"])
        if api_available
        else rendered["platform"]
    )
    chart = {"platform": platform}
    monitor = resources(chart, "platform", "ServiceMonitor")["cloudwatch-exporter"]
    installer = resources(chart, "platform", "Application")["s23-monitoring"]
    assert sync_wave(monitor) > sync_wave(installer)
    assert (
        monitor["metadata"]["annotations"]["argocd.argoproj.io/sync-options"]
        == "SkipDryRunOnMissingResource=true"
    )
    service = resources(chart, "platform", "Service")["cloudwatch-exporter"]
    assert (
        monitor["spec"]["selector"]["matchLabels"].items() <= service["metadata"]["labels"].items()
    )
    assert monitor["spec"]["endpoints"][0]["port"] in {
        port["name"] for port in service["spec"]["ports"]
    }


def test_logging_runs_fluent_bit_with_the_mounted_configuration(rendered):
    pod = resources(rendered, "platform", "DaemonSet")["fluent-bit"]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert container["command"] == ["/fluent-bit/bin/fluent-bit"]
    assert container["args"][0] == "-c"
    config_mount = next(mount for mount in container["volumeMounts"] if mount["name"] == "config")
    config_volume = next(volume for volume in pod["volumes"] if volume["name"] == "config")
    config = resources(rendered, "platform", "ConfigMap")[config_volume["configMap"]["name"]]
    config_file = container["args"][1].removeprefix(config_mount["mountPath"] + "/")
    assert config_file in config["data"]
    account = resources(rendered, "platform", "ServiceAccount")[pod["serviceAccountName"]]
    assert account["metadata"]["annotations"]["eks.amazonaws.com/role-arn"].startswith(
        "arn:aws:iam::"
    )


def test_zookeeper_has_real_persistence_and_quorum_startup_contracts(rendered):
    stateful = resources(rendered, "app", "StatefulSet")["zookeeper"]["spec"]
    assert stateful["replicas"] == 3
    assert stateful["podManagementPolicy"] == "Parallel"
    assert len(resources(rendered, "app", "PersistentVolume")) == 3
    assert len(resources(rendered, "app", "PersistentVolumeClaim")) == 3
    headless = resources(rendered, "app", "Service")["zookeeper"]["spec"]
    assert headless["publishNotReadyAddresses"] is True
    assert headless["clusterIP"] == "None"


def test_gitops_orders_monitoring_before_application_and_load_is_opt_in(rendered):
    apps = resources(rendered, "platform", "Application")
    assert set(apps) == {"s23-monitoring", "s23-metrics-server", "s23-application"}
    assert (
        int(apps["s23-monitoring"]["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]) < 0
    )
    assert apps["s23-application"]["spec"]["source"]["path"] == "deploy/app"
    assert "ServerSideApply=true" in apps["s23-monitoring"]["spec"]["syncPolicy"]["syncOptions"]
    assert any(name.startswith("load-test-") for name in resources(rendered, "app", "Job"))
    assert (
        yaml.safe_load((ROOT / "deploy" / "app" / "values.yaml").read_text())["loadTest"]["enabled"]
        is False
    )
    dashboard = json.loads((ROOT / "deploy" / "app" / "dashboards" / "s23.json").read_text())
    assert len(dashboard["panels"]) >= 6


def test_runtime_command_and_message_timeouts_match_managed_flink_and_lambda():
    streaming = (ROOT / "infra" / "aws" / "streaming.tf").read_text()
    assert "flink run-application -t yarn-application" in streaming
    assert 'applications  = ["Hadoop", "Flink"]' in streaming
    lambda_code = (ROOT / "infra" / "aws" / "lambda.tf").read_text()
    storage = (ROOT / "infra" / "aws" / "storage.tf").read_text()
    timeout = int(re.search(r"timeout\s*=\s*(\d+)", lambda_code)[1])
    visibility = int(re.search(r"visibility_timeout_seconds\s*=\s*(\d+)", storage)[1])
    lease = int(re.search(r'DISPATCH_LEASE_MS\s*=\s*"(\d+)"', lambda_code)[1])
    assert visibility >= timeout * 6
    assert lease > visibility * 1000
    assert "ReportBatchItemFailures" in lambda_code


def test_all_requested_guides_and_truthful_assignment_record_exist():
    for name in GUIDES:
        path = ROOT / "docs" / name
        assert path.is_file(), f"Missing beginner guide: {name}"
        assert len(path.read_text(encoding="utf-8")) >= 500
    text = (ROOT / "task_divison.txt").read_text(encoding="utf-8")
    assert "Sthiti Swain" in text and "2025H1030055P" in text
    assert "UNASSIGNED" in text and "approval" in text.lower()
    assert not (ROOT / "task_division.txt").exists()


def test_relative_markdown_links_resolve_to_delivered_files():
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = target.strip("<>")
            if "://" in target or target.startswith("#"):
                continue
            file = unquote(target.split("#", 1)[0])
            assert (path.parent / file).exists(), f"Broken link in {path.name}: {target}"


def test_macos_guides_use_zsh_and_keep_local_builds_native():
    guides = [(ROOT / "docs" / name).read_text(encoding="utf-8") for name in GUIDES]
    assert not any("```powershell" in guide for guide in guides)
    local = (ROOT / "docs" / "04-local-walkthrough.md").read_text(encoding="utf-8")
    assert "setopt INTERACTIVE_COMMENTS" in local
    assert "brew install git python@3.12 helm@3" in local
    assert 'export PATH="$(brew --prefix helm@3)/bin:$PATH"' in local
    assert "unset DOCKER_DEFAULT_PLATFORM" in local
    assert "```zsh" in local
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    assert all("platform" not in service for service in compose["services"].values())
    for name in ("Dockerfile", "analytics/Dockerfile"):
        assert "FROM --platform=" not in (ROOT / name).read_text()
    aws = (ROOT / "docs" / "05-aws-deployment.md").read_text(encoding="utf-8")
    builds = re.findall(r"docker buildx build ([^\n]+)", aws)
    assert len(builds) == 2
    assert all("--platform linux/amd64 --provenance=false --sbom=false" in line for line in builds)


@pytest.mark.parametrize("valid", [True, False], ids=["valid-secret", "invalid-base64"])
def test_documented_password_decoding_is_portable_and_rejects_invalid_input(valid):
    for name in ("05-aws-deployment.md", "06-demonstration-and-observability.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        commands = re.findall(r'python -c "(import base64;[^"]+)"', text)
        assert len(commands) == 1, f"{name} must use portable, validated password decoding"
        result = subprocess.run(
            [sys.executable, "-c", commands[0]],
            input=base64.b64encode(b"synthetic-not-a-secret").decode() if valid else "!!!",
            text=True,
            capture_output=True,
            check=False,
        )
        if valid:
            assert result.returncode == 0, result.stderr
            assert result.stdout == "synthetic-not-a-secret\n"
        else:
            assert result.returncode != 0
            assert not result.stdout
            assert "Error" in result.stderr


@pytest.mark.parametrize(
    ("series", "expected"),
    [
        ([("healthy", "202", 60)], {"healthy": 0}),
        (
            [("healthy", "202", 60), ("failing", "202", 54), ("failing", "500", 6)],
            {"healthy": 0, "failing": 0.1},
        ),
        ([("idle", "202", 0)], {"idle": 0}),
    ],
)
def test_dashboard_error_fraction_handles_missing_error_series(tmp_path, series, expected):
    dashboard = json.loads((ROOT / "deploy" / "app" / "dashboards" / "s23.json").read_text())
    panel = next(item for item in dashboard["panels"] if item["title"] == "HTTP error fraction")
    rules = {
        "evaluation_interval": "1m",
        "tests": [
            {
                "interval": "1m",
                "input_series": [
                    {
                        "series": (
                            f's23_http_requests_total{{service="{service}",status="{status}"}}'
                        ),
                        "values": f"0+{increment}x4",
                    }
                    for service, status, increment in series
                ],
                "promql_expr_test": [
                    {
                        "expr": panel["targets"][0]["expr"],
                        "eval_time": "4m",
                        "exp_samples": [
                            {"labels": f'{{service="{service}"}}', "value": value}
                            for service, value in expected.items()
                        ],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "metrics.yml"
    path.write_text(yaml.safe_dump(rules), encoding="utf-8")
    # The Prometheus image runs as nobody; these fixtures contain only synthetic series.
    tmp_path.chmod(0o755)
    path.chmod(0o644)
    command = (
        [os.environ["PROMTOOL"], "test", "rules", str(path)]
        if os.environ.get("PROMTOOL")
        else [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--entrypoint=/bin/promtool",
            "--mount",
            f"type=bind,source={tmp_path},target=/tests,readonly",
            "prom/prometheus:v3.7.3",
            "test",
            "rules",
            "/tests/metrics.yml",
        ]
    )
    subprocess.run(command, check=True)


def test_compose_is_synthetic_and_exposes_only_loopback_ports():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    services = compose["services"]
    for name in SERVICES | {"notification-dispatcher", "bootstrap"}:
        environment = services[name]["environment"]
        assert environment["APP_MODE"] == "local"
        assert environment["AWS_ENDPOINT_URL"] == "http://aws-mock:5000"
        assert environment["AWS_ACCESS_KEY_ID"] == "testing"
        assert environment["AWS_SECRET_ACCESS_KEY"] == "testing"
    for service in services.values():
        assert all(port.startswith("127.0.0.1:") for port in service.get("ports", []))
    assert services["flink-submit"]["restart"] == "no"
    assert services["bootstrap"]["restart"] == "no"
    assert services["alert-queue-manager"]["deploy"]["replicas"] == 2


@pytest.mark.parametrize(
    ("bootstrap_exit", "flink_exit", "missing", "wait_error", "expected"),
    [
        (0, 0, "", 0, 0),
        (7, 0, "", 0, 1),
        (0, 7, "", 0, 1),
        (0, 0, "bootstrap", 0, 1),
        (0, 0, "", 23, 23),
    ],
    ids=["already-exited", "bootstrap-failed", "flink-failed", "missing-container", "docker-error"],
)
def test_ci_waits_for_one_shot_container_ids_and_checks_exit_codes(
    workflow, bootstrap_exit, flink_exit, missing, wait_error, expected
):
    step = next(
        step
        for step in workflow["jobs"]["integration"]["steps"]
        if step.get("name") == "Wait for API and RUNNING Flink, then verify one-shot exits"
    )
    one_shot_check = step["run"].split("\ndone\n", 1)[1]
    fake_docker = r"""
docker() {
  if [[ "$1 $2" == "compose ps" ]]; then
    service="${@: -1}"
    [[ "$service" == "$MISSING_SERVICE" ]] || printf '%s-id\n' "$service"
  elif [[ "$1 $2" == "compose wait" ]]; then
    printf 'no containers for project "s23-demo"\n' >&2
    return 1
  elif [[ "$1" == "wait" ]]; then
    printf 'WAIT:%s\n' "$2" >&2
    if [[ "$WAIT_ERROR" != 0 ]]; then
      printf 'fake Docker wait failed\n' >&2
      return "$WAIT_ERROR"
    fi
    case "$2" in
      bootstrap-id) printf '%s\n' "$BOOTSTRAP_EXIT" ;;
      flink-submit-id) printf '%s\n' "$FLINK_EXIT" ;;
      *) return 99 ;;
    esac
  else
    printf 'Unexpected Docker command\n' >&2
    return 99
  fi
}
"""
    result = subprocess.run(
        [os.environ.get("BASH", "bash"), "--noprofile", "--norc", "-e", "-o", "pipefail", "-s"],
        input=(fake_docker + one_shot_check).encode(),
        capture_output=True,
        timeout=10,
        check=False,
        env={
            **os.environ,
            "BOOTSTRAP_EXIT": str(bootstrap_exit),
            "FLINK_EXIT": str(flink_exit),
            "MISSING_SERVICE": missing,
            "WAIT_ERROR": str(wait_error),
        },
    )
    error = result.stderr.decode()
    assert result.returncode == expected, error
    if missing:
        assert f"Missing one-shot container: {missing}" in error
    else:
        assert "WAIT:bootstrap-id" in error
        if not bootstrap_exit and not wait_error:
            assert "WAIT:flink-submit-id" in error
    if bootstrap_exit or flink_exit:
        service = "bootstrap" if bootstrap_exit else "flink-submit"
        assert f"{service} exited with code 7" in error
    if wait_error:
        assert "fake Docker wait failed" in error


def test_ci_validates_without_deploying_or_using_cloud_credentials(workflow):
    assert workflow["permissions"] == {"contents": "read"}
    assert {"push", "pull_request", "workflow_dispatch"} <= workflow["on"].keys()
    assert set(workflow["jobs"]) == {"python", "java", "infrastructure", "integration"}
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    assert not any("configure-aws-credentials" in step.get("uses", "") for step in steps)
    scripts = "\n".join(step.get("run", "") for step in steps)
    assert not re.search(
        r"terraform[^\n]*\b(apply|destroy)\b|kubectl\s+(apply|create|scale)\b|docker\s+push\b",
        scripts,
    )
    assert "tools.demo smoke" in scripts and "--aws" not in scripts
    assert "percent_covered" in scripts
    assert "-m repository" in scripts
    assert 'subprocess.run(["zsh", "-f", "-n"]' in scripts
    terraform_tests = (ROOT / "infra" / "aws" / "tests" / "guard.tftest.hcl").read_text()
    assert set(re.findall(r'mock_provider\s+"([^"]+)"', terraform_tests)) == {
        "aws",
        "tls",
        "random",
    }


def test_ci_defaults_to_fast_checks_with_full_validation_opt_in(workflow):
    option = workflow["on"]["workflow_dispatch"]["inputs"]["full_validation"]
    assert option["type"] == "boolean"
    assert option["default"] == "false"
    full_only = "${{ github.event_name == 'workflow_dispatch' && inputs.full_validation }}"
    full_report = (
        "${{ always() && github.event_name == 'workflow_dispatch' && inputs.full_validation }}"
    )
    for name in ("python", "java"):
        job = workflow["jobs"][name]
        assert "if" not in job and "needs" not in job
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/upload-artifact@"):
                assert step["if"] in {full_only, full_report}
    for name in ("infrastructure", "integration"):
        assert workflow["jobs"][name]["if"] == full_only
    assert workflow["jobs"]["infrastructure"]["needs"] == "java"
    assert workflow["jobs"]["integration"]["needs"] == ["python", "infrastructure"]
    python_scripts = "\n".join(step.get("run", "") for step in workflow["jobs"]["python"]["steps"])
    assert 'pytest -m "not repository" --cov' in python_scripts
    assert 'pytest -m repository -k "not dashboard_error_fraction"' in python_scripts
    assert any(
        step.get("uses") == "azure/setup-helm@v4" for step in workflow["jobs"]["python"]["steps"]
    )
    assert not re.search(r"\bdocker\b|\bterraform\b|\bhelm\b", python_scripts)
    for job in workflow["jobs"].values():
        assert not job.get("continue-on-error")
        assert all(not step.get("continue-on-error") for step in job["steps"])
