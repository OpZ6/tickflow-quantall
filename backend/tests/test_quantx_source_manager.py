from __future__ import annotations

from pathlib import Path

import pytest

from app.quantx_data.schemas import SourceSpec
from app.quantx_data.source_manager import SourceManager, classify_source_error


def _spec(name: str = "demo", **kwargs) -> SourceSpec:
    return SourceSpec(name, True, "test:collector", "market", **kwargs)


def test_source_manager_registers_and_selects_in_declared_order() -> None:
    manager = SourceManager()
    manager.register(_spec("first"), lambda _date, _root: {"rows": [1]})
    manager.register(_spec("second"), lambda _date, _root: {"rows": [2]})

    assert [spec.name for spec in manager.select()] == ["first", "second"]
    assert [spec.name for spec in manager.select(["second", "first"])] == [
        "second",
        "first",
    ]


def test_source_manager_rejects_duplicate_and_unknown_sources() -> None:
    manager = SourceManager()
    manager.register(_spec(), lambda _date, _root: {})

    with pytest.raises(ValueError, match="duplicate QuantX source"):
        manager.register(_spec(), lambda _date, _root: {})
    with pytest.raises(ValueError, match="unknown QuantX source"):
        manager.select(["missing"])


def test_source_manager_reports_dependency_failure_without_calling_collector(
    tmp_path: Path,
) -> None:
    manager = SourceManager()
    called = False

    def collect(_date: str, _root: Path) -> dict:
        nonlocal called
        called = True
        return {}

    manager.register(
        _spec(),
        collect,
        dependency_check=lambda: (False, "missing dependency: demo-sdk"),
    )

    result = manager.collect("demo", "20260828", tmp_path, force=True)

    assert called is False
    assert result.status == "error"
    assert result.error_kind == "dependency"
    assert result.attempts == 0


def test_source_manager_classifies_and_isolates_collector_failure(
    tmp_path: Path,
) -> None:
    manager = SourceManager()

    def collect(_date: str, _root: Path) -> dict:
        raise TimeoutError("upstream timed out")

    manager.register(_spec(max_retries=0), collect)

    result = manager.collect("demo", "20260828", tmp_path, force=True)

    assert result.status == "error"
    assert result.error_kind == "timeout"
    assert result.attempts == 1


def test_source_manager_enforces_process_wall_clock_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_dir = tmp_path / "modules"
    module_dir.mkdir()
    (module_dir / "slow_quantx_collector.py").write_text(
        "import time\n"
        "def run(trade_date, output_dir):\n"
        "    time.sleep(30)\n"
        "    return {'trade_date': trade_date, 'rows': [1]}\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(module_dir))
    os_module = __import__("os")
    current_pythonpath = os_module.environ.get("PYTHONPATH", "")
    monkeypatch.setenv(
        "PYTHONPATH",
        str(module_dir) + (os_module.pathsep + current_pythonpath if current_pythonpath else ""),
    )
    manager = SourceManager()
    manager.register(
        SourceSpec(
            "slow",
            True,
            "module:slow_quantx_collector",
            "market",
            timeout_seconds=0.2,
            max_retries=0,
        ),
        lambda _date, _root: {"rows": [1]},
    )

    time_module = __import__("time")
    started = time_module.monotonic()
    result = manager.collect("slow", "20260828", tmp_path, force=True)

    assert time_module.monotonic() - started < 5
    assert result.status == "error"
    assert result.error_kind == "timeout"
    assert result.attempts == 1


def test_source_description_separates_readiness_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEMO_LOGIN_STATE", raising=False)
    manager = SourceManager()
    manager.register(
        _spec(credentials_ref="DEMO_LOGIN_STATE"),
        lambda _date, _root: {"rows": [1]},
        dependency_check=lambda: (True, "ok"),
    )

    description = manager.describe("demo")

    assert description["credential_readiness"] == "missing"
    assert description["dependency_readiness"] == "ready"
    assert description["manifest_health"] == "not_evaluated"
    assert description["live_probe"] == "not_run"


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (ModuleNotFoundError("sdk"), "dependency"),
        (RuntimeError("HTTP 401 token invalid"), "authentication"),
        (RuntimeError("HTTP 429 rate limit"), "rate_limit"),
        (RuntimeError("访问接口频率超限(1次/分钟)"), "rate_limit"),
        (ConnectionError("network unavailable"), "network"),
        (ValueError("bad payload"), "parse"),
    ],
)
def test_source_error_classification(error: BaseException, kind: str) -> None:
    assert classify_source_error(error) == kind


def test_partial_payload_error_is_propagated_to_result() -> None:
    """采集器写在 payload["error"] 里的可执行结论要带到 SourceResult。

    QuickTiny 会话过期时 status 仍是 partial, 但真正需要看到的是 "401 重新登录"。
    """
    manager = SourceManager()
    manager.register(_spec("quicktiny", degrades_when_missing=False), lambda _date, _root: None)
    manager._collectors["quicktiny"] = lambda _date, _root: {
        "status": "partial",
        "error": "QuickTiny 登录态已失效, 接口返回 401",
    }

    result = manager.collect("quicktiny", "20261030", Path("."))

    assert result.status == "partial"
    assert result.error and "401" in result.error
    assert result.error_kind == "authentication"


def test_partial_payload_error_is_propagated_to_result() -> None:
    """采集器写在 payload["error"] 里的可执行结论要带到 SourceResult。

    QuickTiny 会话过期时 status 仍是 partial, 但真正需要看到的是 "401 重新登录"。
    """
    manager = SourceManager()
    manager.register(_spec("quicktiny", degrades_when_missing=False), lambda _date, _root: None)
    manager._collectors["quicktiny"] = lambda _date, _root: {
        "status": "partial",
        "error": "QuickTiny 登录态已失效, 接口返回 401",
    }

    result = manager.collect("quicktiny", "20261030", Path("."))

    assert result.status == "partial"
    assert result.error and "401" in result.error
    assert result.error_kind == "authentication"
