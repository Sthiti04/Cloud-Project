import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        env={**os.environ, "AWS_PAGER": ""},
    )
    return result.stdout if capture else ""


def environment(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def deployment() -> dict[str, Any]:
    path = ROOT / "artifacts" / "deployment.json"
    if not path.exists():
        raise FileNotFoundError("Run python -m tools.configure_aws after the foundation apply")
    return json.loads(path.read_text(encoding="utf-8"))
