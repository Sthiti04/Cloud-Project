import os
import subprocess

from s23.observability import log
from s23.resources import Resources
from s23.settings import Settings


def main() -> None:
    runtime = Resources(Settings.from_env("patient-simulator"))
    env = {
        **os.environ,
        "API_KEY": runtime.api_key.get(),
        "BASE_URL": runtime.settings.ingestion_url,
    }
    log(
        "load_test_started",
        rate=env.get("LOAD_RATE", "90"),
        duration=env.get("LOAD_DURATION", "10m"),
        target="internal-vital-ingestion",
    )
    subprocess.run(["k6", "run", "/app/load/k6.js"], env=env, check=True)
    log("load_test_completed")


if __name__ == "__main__":
    main()
