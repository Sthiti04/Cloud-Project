import argparse
import secrets
from pathlib import Path

from .common import ROOT


def initialise(root: Path) -> None:
    path = root / ".env"
    if path.exists():
        raise FileExistsError(".env already exists; keep it or remove that specific file yourself")
    values = {
        "DEMO_API_KEY": secrets.token_urlsafe(32),
        "DEMO_DB_PASSWORD": secrets.token_urlsafe(24),
        "DEMO_GRAFANA_PASSWORD": secrets.token_urlsafe(24),
        "FAIL_FIRST_DELIVERY": "false",
    }
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    path.chmod(0o600)
    print("Created ignored .env. Never upload it. These are local-only random demo credentials.")


def main() -> None:
    argparse.ArgumentParser(
        description="Generate local-only secrets; does not call AWS"
    ).parse_args()
    initialise(ROOT)


if __name__ == "__main__":
    main()
