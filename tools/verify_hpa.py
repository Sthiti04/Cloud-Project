import argparse
import json
import time
from typing import Any

from .common import ROOT, run

CRITICAL = {"vital-ingestion", "device-registry"}


def replica_counts(
    hpas: dict[str, Any],
    deployments: dict[str, Any],
) -> dict[str, tuple[int, int, int]]:
    ready = {
        item["metadata"]["name"]: item.get("status", {}).get("availableReplicas", 0)
        for item in deployments["items"]
    }
    return {
        item["metadata"]["name"]: (
            item.get("status", {}).get("currentReplicas", 0),
            item.get("status", {}).get("desiredReplicas", 0),
            ready.get(item["metadata"]["name"], 0),
        )
        for item in hpas["items"]
        if item["metadata"]["name"] in CRITICAL
    }


def scaled(hpas: dict[str, Any], deployments: dict[str, Any]) -> set[str]:
    return {
        name
        for name, counts in replica_counts(hpas, deployments).items()
        if all(value >= 2 for value in counts)
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only HPA evidence; start load through GitOps"
    )
    parser.add_argument("--timeout", type=int, default=720)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    observed: set[str] = set()
    baseline_seen = False
    verified = False
    snapshots = []
    deadline = time.monotonic() + args.timeout
    try:
        while time.monotonic() < deadline:
            hpas = json.loads(
                run(["kubectl", "get", "hpa", "-n", "s23", "-o", "json"], capture=True)
            )
            deployments = json.loads(
                run(["kubectl", "get", "deployments", "-n", "s23", "-o", "json"], capture=True)
            )
            if not baseline_seen:
                baseline_seen = all(
                    replica_counts(hpas, deployments).get(name) == (1, 1, 1) for name in CRITICAL
                )
                if baseline_seen:
                    print("Recorded both HPAs at one ready replica. Start the GitOps load Job now.")
            else:
                observed |= scaled(hpas, deployments)
            snapshots.append({"time": int(time.time()), "hpas": hpas, "deployments": deployments})
            print(f"Observed >=2 ready replicas under HPA control: {sorted(observed)}")
            if observed == CRITICAL:
                break
            time.sleep(10)
        verified = observed == CRITICAL
    finally:
        path = ROOT / "evidence"
        path.mkdir(exist_ok=True)
        (path / "hpa.json").write_text(
            json.dumps(
                {
                    "verified": verified,
                    "baseline_seen": baseline_seen,
                    "observed": sorted(observed),
                    "snapshots": snapshots,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    if not verified:
        raise TimeoutError(
            "Both required HPAs did not demonstrate scale-out. Do not claim success."
        )
    print("Saved evidence/hpa.json. Also save the successful k6 Job logs.")


if __name__ == "__main__":
    main()
