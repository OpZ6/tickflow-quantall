from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.market_facts.registry import validate_registry_contracts

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "scaffold_market_fact.py"


def test_market_fact_registry_contracts_are_self_consistent() -> None:
    assert validate_registry_contracts() == []


def test_market_fact_scaffold_generates_contract_builder_and_test(tmp_path: Path) -> None:
    output = tmp_path / "northbound_flow_daily"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "northbound_flow_daily",
            "--source",
            "tushare",
            "--description",
            "Daily northbound capital flow",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in output.iterdir()) == [
        "README.md",
        "builder.py",
        "registry_snippet.py",
        "test_northbound_flow_daily.py",
    ]
    assert "NORTHBOUND_FLOW_DAILY" in (output / "registry_snippet.py").read_text(
        encoding="utf-8"
    )
    assert "REPLACE_WITH_EXPLICIT_UNIT" in (
        output / "registry_snippet.py"
    ).read_text(encoding="utf-8")


def test_market_fact_scaffold_refuses_to_overwrite_nonempty_directory(
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("user data", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "demo_daily",
            "--source",
            "demo",
            "--description",
            "demo",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert (output / "keep.txt").read_text(encoding="utf-8") == "user data"
