"""Data-source adapters used by the independent TickFlow pipeline.

Adapters are isolated from the deterministic calculation layer. Their output
is persisted as source data and never interpreted as editorial or LLM text.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from .io import read_json
from .schemas import SourceResult, SourceSpec
from .source_manager import SourceManager, collect_from_descriptor

_BUILTIN_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        "tushare",
        True,
        "tushare",
        "market",
        min_records=1,
        display_name="Tushare Pro",
        collector_type="provider",
        credentials_ref="TUSHARE_TOKEN",
        dependency_modules=("tushare",),
        timeout_seconds=60,
        rate_limit_rpm=180,
    ),
    SourceSpec("akshare", False, "legacy:akshare_scraper", "market", display_name="AKShare", timeout_seconds=90),
    SourceSpec("ths_hot", False, "legacy:ths_hot_scraper", "theme", display_name="同花顺热点", timeout_seconds=60),
    SourceSpec("zhangtingke", False, "legacy:zhangtingke_scraper", "limit", display_name="涨停客", timeout_seconds=60),
    SourceSpec("zhangtingjun", False, "legacy:zhangtingjun_scraper", "limit", display_name="涨停君", timeout_seconds=90),
    SourceSpec(
        "pywencai",
        True,
        "legacy:pywencai_scraper",
        "limit",
        min_records=1,
        display_name="同花顺问财",
        dependency_modules=("pywencai",),
        timeout_seconds=90,
    ),
    SourceSpec("duanxianxia", False, "legacy:duanxianxia_scraper", "limit", display_name="短线侠", timeout_seconds=90),
    SourceSpec("deepq", False, "legacy:deepq_scraper", "theme", display_name="DeepQ", timeout_seconds=60),
    SourceSpec("legulegu", False, "legacy:legulegu_scraper", "market", display_name="乐咕乐股", timeout_seconds=180),
    SourceSpec(
        "quicktiny",
        False,
        "legacy:quicktiny_scraper",
        "limit",
        display_name="QuickTiny",
        credentials_ref="QUICKTINY_LOGIN_STATE",
        collector_type="browser",
        timeout_seconds=120,
    ),
    SourceSpec(
        "dabanke",
        False,
        "legacy:dabanke_scraper",
        "limit",
        display_name="打板客",
        credentials_ref="DABANKE_LOGIN_STATE",
        collector_type="browser",
        timeout_seconds=120,
    ),
    SourceSpec(
        "sector_fund_flow_s4",
        False,
        "legacy:sector_fund_flow_s4_scraper",
        "fund_flow",
        display_name="S4 行业资金流",
        collector_type="browser",
        timeout_seconds=120,
    ),
)


def _collect_tushare(trade_date: str, output_dir: Path | None = None) -> dict[str, Any]:
    """Fetch Tushare market, breadth, calendar and liquidity facts."""
    module = importlib.import_module("app.quantx_data.legacy_scrapers.tushare_scraper")
    path = module.run(trade_date, str(output_dir or Path(".")))
    payload = read_json(Path(path), {})
    if not isinstance(payload, dict):
        raise RuntimeError("tushare returned a non-object payload")
    return payload


def _collect_legacy(module_name: str, trade_date: str, output_dir: Path, source: str) -> dict[str, Any]:
    module = importlib.import_module(f"app.quantx_data.legacy_scrapers.{module_name}")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = module.run(trade_date, str(output_dir))
    payload = read_json(Path(path), {})
    if not isinstance(payload, dict):
        raise RuntimeError(f"{source} returned a non-object payload")
    return payload


def _collector_for(spec: SourceSpec):
    def collect(trade_date: str, output_dir: Path) -> dict[str, Any]:
        return collect_from_descriptor(spec.collector, spec.name, trade_date, output_dir)

    return collect


SOURCE_MANAGER = SourceManager()
for _spec in _BUILTIN_SPECS:
    SOURCE_MANAGER.register(_spec, _collector_for(_spec))

SOURCE_SPECS = SOURCE_MANAGER.specs
SPEC_BY_NAME = SOURCE_MANAGER.spec_by_name


def collect_source(
    spec: SourceSpec,
    trade_date: str,
    date_dir: Path,
    *,
    read_dir: Path | None = None,
    force: bool = False,
    allow_network: bool = True,
) -> SourceResult:
    return SOURCE_MANAGER.collect(
        spec.name,
        trade_date,
        date_dir,
        read_dir=read_dir,
        force=force,
        allow_network=allow_network,
    )


def source_specs(names: list[str] | None = None) -> list[SourceSpec]:
    return SOURCE_MANAGER.select(names)
