from pathlib import Path
from unittest.mock import patch

import pytest

from tools import export_analytics


def test_export_collects_all_three_artifacts_and_removes_only_its_container(tmp_path):
    container = "a" * 64
    commands = []

    def run(args, capture=False):
        commands.append(args)
        if capture:
            return container
        if args[1] == "cp":
            Path(args[-1]).write_bytes(b"isolated-fake-jar")
        return ""

    with (
        patch("tools.export_analytics.run", side_effect=run),
        patch("tools.export_analytics.ROOT", tmp_path),
        patch("sys.argv", ["export_analytics"]),
    ):
        export_analytics.main()
    assert len(list((tmp_path / "analytics" / "target").rglob("*.jar"))) == 3
    assert commands[-1] == ["docker", "rm", container]


def test_export_rejects_bad_image_and_cleans_up_failed_copy(tmp_path):
    with pytest.raises(ValueError):
        export_analytics.extract(tmp_path, "-invalid")
    with patch("tools.export_analytics.run", return_value="invalid"):
        with pytest.raises(RuntimeError, match="container ID"):
            export_analytics.extract(tmp_path, "image")
    with patch("tools.export_analytics.run", side_effect=["b" * 64, "", ""]) as run:
        with pytest.raises(RuntimeError, match="nonempty"):
            export_analytics.extract(tmp_path, "image")
    assert run.call_args.args[0] == ["docker", "rm", "b" * 64]
