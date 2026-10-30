"""源级降级策略回归测试。

`validate_sources` 曾经对 `partial/degraded/used_fallback` 无条件判定整轮降级,
忽略了 SourceSpec.degrades_when_missing — 于是 QuickTiny 这类「登录态一过期就
拿不到数据」的尽力而为源, 会把每日 run 永久钉在 degraded 上。
"""
from __future__ import annotations

from app.quantx_data.quality import validate_sources
from app.quantx_data.schemas import RunStatus, SourceResult, SourceSpec


def _spec(name: str = "demo", **kwargs) -> SourceSpec:
    return SourceSpec(name, False, "test:collector", "limit", **kwargs)


def test_best_effort_partial_source_does_not_degrade_run() -> None:
    """尽力而为的源返回残缺数据: 记 warning, 但整轮仍算 complete。"""
    specs = [_spec("quicktiny", degrades_when_missing=False)]
    results = {
        "quicktiny": SourceResult(
            name="quicktiny",
            status="partial",
            error="QuickTiny 登录态已失效, 接口返回 401",
        )
    }

    status, errors, warnings = validate_sources(specs, results)

    assert status == RunStatus.COMPLETE
    assert errors == []
    # 原因仍要留痕, 不能因为「不降级」就静默吞掉
    assert warnings and "401" in warnings[0]


def test_default_partial_source_still_degrades_run() -> None:
    """未声明为尽力而为的源, 行为不变: partial 仍让整轮降级。"""
    specs = [_spec("core_src")]
    results = {"core_src": SourceResult(name="core_src", status="partial")}

    status, _errors, warnings = validate_sources(specs, results)

    assert status == RunStatus.DEGRADED
    assert warnings == ["core_src: degraded source payload"]


def test_best_effort_partial_alongside_degrading_source_stays_degraded() -> None:
    """尽力而为的源不能「稀释」其它源造成的降级。"""
    specs = [
        _spec("quicktiny", degrades_when_missing=False),
        _spec("core_src"),
    ]
    results = {
        "quicktiny": SourceResult(name="quicktiny", status="partial", error="401"),
        "core_src": SourceResult(name="core_src", status="partial"),
    }

    status, _errors, _warnings = validate_sources(specs, results)

    assert status == RunStatus.DEGRADED
