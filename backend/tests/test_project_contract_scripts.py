from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_project_contract_validator_passes() -> None:
    result = _run("validate_project_contracts.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROJECT_CONTRACTS_OK" in result.stdout
    assert "authoritative_docs=6" in result.stdout


def test_project_contract_validator_scans_runtime_boundaries() -> None:
    source = (REPO_ROOT / "scripts" / "validate_project_contracts.py").read_text(
        encoding="utf-8"
    )

    assert "legacy QuantX service port" in source
    assert "retired TickFlow directory" in source
    assert "business layer imports a legacy scraper directly" in source


def test_upstream_status_is_machine_readable_without_mutating_repo() -> None:
    result = _run(
        "upstream_status.py",
        "--target",
        "HEAD",
        "--json",
        "--allow-dirty",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["target"] == "HEAD"
    assert report["upstream_only_commits"] == 0
    assert report["local_only_commits"] == 0
    assert isinstance(report["dirty_entries"], list)


def test_upgrade_check_handles_utf8_git_output_on_windows() -> None:
    result = _run("upgrade_check.py", "HEAD")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Tick Stock Panel 二开升级预检" in result.stdout
    assert "Git 三方预演识别的文本冲突: 0" in result.stdout
