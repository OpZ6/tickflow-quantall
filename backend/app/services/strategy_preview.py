"""On-demand, read-only strategy signal previews for one stock chart."""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any

import numpy as np
import polars as pl

from app.chart_layers.models import AnnotationEvidence, AnnotationMarker, ChartAnnotationLayer
from app.strategy.engine import StrategyDataContext, StrategyEngine

_MAX_PREVIEW_STRATEGIES = 3


def _fingerprint(panel: pl.DataFrame, strategy_id: str, version: str, params: dict) -> str:
    columns = [column for column in ("date", "open", "high", "low", "close", "volume") if column in panel.columns]
    payload = {
        "strategy_id": strategy_id,
        "version": version,
        "params": params,
        "rows": panel.select(columns).to_dicts(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def _preview_fetch_start(start_date: date, required_bars: int) -> date:
    # Daily strategies need real trading bars, not calendar-day slices.  The
    # repository query is calendar bounded, so reserve a conservative three
    # calendar days per required bar to cover weekends and long holidays.
    return start_date - timedelta(days=max(120, required_bars * 3))


class StrategyPreviewService:
    """Build transient chart annotation layers without a market-wide run."""

    def __init__(self, repo: Any, engine: StrategyEngine) -> None:
        self.repo = repo
        self.engine = engine

    def preview(
        self,
        *,
        symbol: str,
        asset_type: str,
        timeframe: str,
        start_date: date,
        end_date: date,
        strategy_ids: list[str],
        params_by_strategy: dict[str, dict] | None = None,
        overrides_by_strategy: dict[str, dict] | None = None,
    ) -> dict:
        if end_date < start_date:
            raise ValueError("end_date 不能早于 start_date")
        strategy_ids = list(dict.fromkeys(item for item in strategy_ids if item))
        if not strategy_ids or len(strategy_ids) > _MAX_PREVIEW_STRATEGIES:
            raise ValueError(f"strategy_ids 需要 1—{_MAX_PREVIEW_STRATEGIES} 个")

        params_by_strategy = params_by_strategy or {}
        overrides_by_strategy = overrides_by_strategy or {}
        strategies = []
        required_bars = 1
        for strategy_id in strategy_ids:
            strategy = self.engine.get(strategy_id)
            self.engine.validate_context(
                strategy,
                StrategyDataContext(
                    asset_type=asset_type,
                    timeframe=timeframe,
                    as_of=end_date,
                ),
            )
            preview = strategy.meta.get("chart_preview") or {}
            if not isinstance(preview, dict) or not preview.get("enabled"):
                raise ValueError(f"strategy {strategy_id} 不支持个股即时预览")
            if preview.get("mode", "single_asset") != "single_asset":
                raise ValueError(f"strategy {strategy_id} 不支持个股即时预览")
            strategies.append(strategy)
            required_bars = max(
                required_bars,
                self.engine.required_history_bars(
                    [strategy_id],
                    params_map={strategy_id: params_by_strategy.get(strategy_id) or {}},
                    overrides_map={strategy_id: overrides_by_strategy.get(strategy_id) or {}},
                ),
            )

        fetch_start = _preview_fetch_start(start_date, required_bars)
        panel = self.repo.get_daily_asset(asset_type, symbol, fetch_start, end_date)
        if panel.is_empty():
            return {
                "mode": "single_asset_preview",
                "symbol": symbol,
                "asset_type": asset_type,
                "timeframe": timeframe,
                "calculation_price_basis": "qfq",
                "layers": [
                    ChartAnnotationLayer(
                        id=f"strategy.preview.{strategy.meta['id']}",
                        category="strategy",
                        title=f"{strategy.meta.get('name') or strategy.meta['id']} · 单股预览",
                        status="unavailable",
                        price_basis="qfq",
                        algorithm_version=str(strategy.meta.get("version") or "unknown"),
                        warnings=["当前股票没有覆盖所选区间的本地日K数据"],
                    ).to_dict()
                    for strategy in strategies
                ],
                "warnings": ["当前股票没有覆盖所选区间的本地日K数据"],
            }

        if "symbol" not in panel.columns or "date" not in panel.columns:
            raise ValueError("个股即时预览缺少标准 symbol/date 行情字段")
        panel = panel.filter((pl.col("symbol") == symbol) & (pl.col("date") <= end_date)).sort("date")
        if panel.is_empty():
            raise ValueError("个股即时预览没有匹配的标准行情数据")
        symbols = panel["symbol"].drop_nulls().cast(pl.Utf8).unique().to_list()
        if symbols != [symbol]:
            raise ValueError("个股即时预览只能读取所选标的")

        # The enriched daily repository is the strategy's canonical qfq input.
        # Attach stable instrument metadata only for framework-owned filters.
        instruments = self.repo.get_instruments_asset(asset_type)
        if instruments is not None and not instruments.is_empty() and "symbol" in instruments.columns:
            metadata_columns = [
                column
                for column in ("name", "total_shares", "float_shares")
                if column in instruments.columns and column not in panel.columns
            ]
            if metadata_columns:
                metadata = instruments.select(["symbol", *metadata_columns]).unique(
                    subset=["symbol"], keep="last"
                )
                panel = panel.join(metadata, on="symbol", how="left")

        latest_date = panel["date"].max()
        visible_start = start_date.isoformat()
        visible_end = min(end_date, latest_date).isoformat()
        pre_visible_bars = panel.filter(pl.col("date") < start_date).height
        layers: list[dict] = []
        warnings: list[str] = []

        for strategy in strategies:
            strategy_id = str(strategy.meta["id"])
            history = self.engine.preview_signal_history(
                strategy_id,
                StrategyDataContext(
                    asset_type=asset_type,
                    timeframe=timeframe,
                    as_of=latest_date,
                    current=panel.filter(pl.col("date") == latest_date),
                    history=panel,
                ),
                params=params_by_strategy.get(strategy_id),
                overrides=overrides_by_strategy.get(strategy_id),
            )
            layer_warnings: list[str] = []
            if pre_visible_bars < required_bars:
                layer_warnings.append(
                    f"展示区间前仅有 {pre_visible_bars} 根预热K线, 前 {required_bars} 根附近信号可能不足"
                )
            layer = self._build_layer(
                strategy=strategy,
                history=history,
                visible_start=visible_start,
                visible_end=visible_end,
                layer_warnings=layer_warnings,
                panel=panel,
            )
            layers.append(layer.to_dict())
            warnings.extend(layer_warnings)

        return {
            "mode": "single_asset_preview",
            "symbol": symbol,
            "asset_type": asset_type,
            "timeframe": timeframe,
            "calculation_price_basis": "qfq",
            "layers": layers,
            "warnings": sorted(set(warnings)),
        }

    @staticmethod
    def _build_layer(
        *,
        strategy,
        history,
        visible_start: str,
        visible_end: str,
        layer_warnings: list[str],
        panel: pl.DataFrame,
    ) -> ChartAnnotationLayer:
        strategy_id = str(strategy.meta["id"])
        version = str(strategy.meta.get("version") or "unknown")
        params_fingerprint = _fingerprint(panel, strategy_id, version, history.params)
        layer_id = f"strategy.preview.{strategy_id}"
        markers: list[AnnotationMarker] = []
        evidence: list[AnnotationEvidence] = []
        market = history.market
        signals = history.signals
        if len(market.symbols) != 1:
            raise ValueError("个股即时预览只能输出一个标的")

        def append_signal(index: int, event_type: str, signal_ids: tuple[str, ...], code: int) -> None:
            if not (0 <= code < len(signal_ids)):
                return
            day = market.timestamp_labels[index][:10]
            if day < visible_start or day > visible_end:
                return
            signal_id = signal_ids[code]
            evidence_id = f"{layer_id}:{event_type}:{day}:{params_fingerprint}"
            price = float(market.close[index, 0]) if np.isfinite(market.close[index, 0]) else None
            role = "strategy_entry" if event_type == "entry" else "strategy_exit"
            event_label = "入场" if event_type == "entry" else "离场"
            markers.append(
                AnnotationMarker(
                    id=evidence_id,
                    layer_id=layer_id,
                    date=day,
                    price=price,
                    role=role,
                    label=f"{strategy.meta.get('name') or strategy_id} · {event_label}",
                    evidence_id=evidence_id,
                    detected_at=day,
                    confirmed_at=day,
                )
            )
            metrics = [] if price is None else [{"name": "收盘价", "value": round(price, 4), "unit": "前复权价"}]
            evidence.append(
                AnnotationEvidence(
                    id=evidence_id,
                    title=f"{strategy.meta.get('name') or strategy_id} · {event_label}",
                    summary="单股即时计算的历史策略信号; 未执行全市场扫描, 也未写入策略事件库。",
                    metrics=metrics,
                    reason_codes=[signal_id],
                    warnings=list(layer_warnings),
                    metadata={
                        "strategy_id": strategy_id,
                        "strategy_version": version,
                        "event_date": day,
                        "event_type": event_type,
                        "signal_kind": "strategy_signal",
                        "provenance": "single_asset_preview",
                        "params": history.params,
                        "params_fingerprint": params_fingerprint,
                        "calculation_price_basis": "qfq",
                    },
                )
            )

        for index in range(market.shape[0]):
            if signals.entry[index, 0]:
                append_signal(
                    index,
                    "entry",
                    signals.entry_signal_ids,
                    int(signals.entry_signal_code[index, 0]),
                )
            if signals.exit[index, 0]:
                append_signal(
                    index,
                    "exit",
                    signals.exit_signal_ids,
                    int(signals.exit_signal_code[index, 0]),
                )

        return ChartAnnotationLayer(
            id=layer_id,
            category="strategy",
            title=f"{strategy.meta.get('name') or strategy_id} · 单股预览",
            status="available",
            price_basis="qfq",
            algorithm_version=version,
            input_fingerprint=params_fingerprint,
            markers=markers,
            evidence=evidence,
            warnings=layer_warnings,
        )
