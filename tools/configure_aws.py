import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

from .common import ROOT, run


def configure(
    root: Path,
    metadata: dict[str, Any],
    image: str,
    repo: str = "git@github.com:Sthiti04/CC-Project.git",
    branch: str = "main",
) -> None:
    expected = metadata["app_repository"]
    if not image.startswith(f"{expected}@sha256:") or not re.fullmatch(
        r".+@sha256:[a-f0-9]{64}", image
    ):
        raise ValueError("Use this deployment's service ECR repository and its sha256 image digest")
    environment = metadata["environment"]
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in environment.items()
    ):
        raise ValueError("Terraform environment output must map names to string values")
    forbidden = {
        "DEMO_API_KEY",
        "DB_PASSWORD",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    }
    if forbidden.intersection(environment):
        raise ValueError("Never generate Git-tracked configuration containing secret values")
    volumes = metadata["zookeeper_volumes"]
    if (
        not isinstance(volumes, list)
        or len(volumes) != 3
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("zone"), str)
            for item in volumes
        )
    ):
        raise ValueError("Three Terraform-created ZooKeeper EBS volumes are required")
    pending = []
    for relative, updates in {
        "deploy/app/values-aws.yaml": {
            "project": metadata["project"],
            "image": image,
            "environment": environment,
            "roleArns": metadata["role_arns"],
            "zookeeper": {"volumes": metadata["zookeeper_volumes"]},
        },
        "deploy/platform/values-aws.yaml": {
            "repoURL": repo,
            "branch": branch,
            "project": metadata["project"],
            "region": metadata["region"],
            "logGroup": metadata["log_groups"][0],
            "functionName": metadata["lambda_function"],
            "roleArns": metadata["role_arns"],
        },
    }.items():
        path = root / relative
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        if existing is None:
            existing = {}
        if not isinstance(existing, dict):
            raise ValueError(f"{relative} must contain a YAML mapping")
        for key, value in updates.items():
            if isinstance(value, dict):
                previous = existing.get(key, {})
                if not isinstance(previous, dict):
                    raise ValueError(f"{relative}: {key} must be a mapping")
                if key == "environment" and forbidden.intersection(previous):
                    raise ValueError("Remove secret values from existing Git-tracked environment")
                existing[key] = {**previous, **value}
            else:
                existing[key] = value
        pending.append((path, yaml.safe_dump(existing, sort_keys=False)))
    for path, content in pending:
        path.write_text(content, encoding="utf-8")
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "deployment.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (artifacts / "demo-ca.pem").write_text(metadata["certificate_pem"], encoding="ascii")
    print("Generated two non-secret values-aws.yaml files: commit those so Argo CD can read them.")
    print("Saved local deployment metadata and public demo certificate under ignored artifacts/.")
    print("No AWS resources were created by this command.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Service image URI including @sha256:digest")
    parser.add_argument("--repo", default="git@github.com:Sthiti04/CC-Project.git")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    metadata = json.loads(
        run(
            ["terraform", f"-chdir={ROOT / 'infra' / 'aws'}", "output", "-json", "deployment"],
            capture=True,
        )
    )
    configure(ROOT, metadata, args.image, args.repo, args.branch)


if __name__ == "__main__":
    main()
