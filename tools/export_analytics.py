import argparse
import re
from pathlib import Path

from .common import ROOT, run

ARTIFACTS = {
    "clinical-analytics.jar": "/opt/flink/usrlib/clinical-analytics.jar",
    "runtime/flink-metrics-prometheus.jar": "/opt/flink/lib/flink-metrics-prometheus.jar",
    "runtime/flink-s3-fs-hadoop.jar": ("/opt/flink/plugins/s3-fs-hadoop/flink-s3-fs-hadoop.jar"),
}


def extract(root: Path, image: str) -> None:
    if not image or image.startswith("-"):
        raise ValueError("Supply the local Flink image built from analytics/Dockerfile")
    container = run(["docker", "create", image], capture=True).strip()
    if not re.fullmatch(r"[a-f0-9]{12,64}", container):
        raise RuntimeError("Docker did not return a valid temporary container ID")
    try:
        for relative, source in ARTIFACTS.items():
            destination = root / "analytics" / "target" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            run(["docker", "cp", f"{container}:{source}", str(destination)])
            if not destination.is_file() or destination.stat().st_size == 0:
                raise RuntimeError(f"Docker did not export a nonempty {relative}")
    finally:
        run(["docker", "rm", container])
    print("Exported all three verified-build JARs. This command does not contact AWS.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Flink JARs from a local Docker build")
    parser.add_argument("--image", default="s23-analytics:build")
    args = parser.parse_args()
    extract(ROOT, args.image)


if __name__ == "__main__":
    main()
