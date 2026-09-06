"""Measure a VCP research run against the same dataset's A-share equal-weight market.

The benchmark is built causally from adjusted daily closes for every available
stock on each date.  It avoids a separate index vendor and therefore remains
reproducible inside the isolated VCP dataset.
"""
from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]


def _max_drawdown(values: np.ndarray) -> float:
    peaks = np.maximum.accumulate(values)
    return float(np.min(values / peaks - 1.0)) if len(values) else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    protocol = json.loads((run_dir / "protocol.json").read_text(encoding="utf-8"))
    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    curve = pl.DataFrame(result["equity_curve"]).select(
        pl.col("date").str.to_date(), pl.col("value").cast(pl.Float64)
    ).sort("date")
    start = curve["date"].min()
    end = curve["date"].max()
    if start is None or end is None:
        raise RuntimeError("run has no equity curve")

    data_dir = ROOT / "data" / protocol["data_directory"]
    daily_glob = str(data_dir / "kline_daily_enriched" / "date=*" / "part.parquet")
    panel = (
        pl.scan_parquet(daily_glob, hive_partitioning=True)
        .filter(
            (pl.col("date") >= pl.lit(start - timedelta(days=30)))
            & (pl.col("date") <= pl.lit(end))
        )
        .select("symbol", "date", "close")
        .filter(pl.col("close").is_finite() & (pl.col("close") > 0))
        .collect()
        .sort(["symbol", "date"])
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1.0)
            .alias("stock_return")
        )
        .filter(
            (pl.col("date") >= start)
            & pl.col("stock_return").is_finite()
            & (pl.col("stock_return") > -0.5)
            & (pl.col("stock_return") < 0.5)
        )
    )
    benchmark = (
        panel.group_by("date")
        .agg(
            pl.col("stock_return").mean().alias("market_return"),
            pl.len().alias("market_constituents"),
        )
        .sort("date")
    )
    aligned = (
        curve.with_columns(
            (pl.col("value") / pl.col("value").shift(1) - 1.0).alias("strategy_return")
        )
        .join(benchmark, on="date", how="inner")
        .drop_nulls(["strategy_return", "market_return"])
    )
    if aligned.height < 20:
        raise RuntimeError("insufficient aligned market observations")
    strategy_returns = aligned["strategy_return"].to_numpy()
    market_returns = aligned["market_return"].to_numpy()
    market_curve = np.cumprod(1.0 + market_returns)
    strategy_total = float(curve["value"][-1] / curve["value"][0] - 1.0)
    market_total = float(market_curve[-1] - 1.0)
    years = aligned.height / 252.0
    covariance = float(np.cov(strategy_returns, market_returns, ddof=1)[0, 1])
    market_variance = float(np.var(market_returns, ddof=1))
    beta = covariance / market_variance if market_variance > 0 else None
    correlation = float(np.corrcoef(strategy_returns, market_returns)[0, 1])
    alpha_daily = (
        float(np.mean(strategy_returns - beta * market_returns))
        if beta is not None
        else None
    )
    report = {
        "run_id": result.get("run_id"),
        "phase": status.get("phase"),
        "period": [str(start), str(end)],
        "aligned_trading_days": aligned.height,
        "benchmark": "A-share equal-weight adjusted-close daily return",
        "benchmark_source": str(data_dir.relative_to(ROOT)),
        "average_daily_constituents": float(aligned["market_constituents"].mean()),
        "strategy_total_return": strategy_total,
        "market_total_return": market_total,
        "geometric_excess_return": (1.0 + strategy_total) / (1.0 + market_total) - 1.0,
        "strategy_annualized_return": (1.0 + strategy_total) ** (1.0 / years) - 1.0,
        "market_annualized_return": (1.0 + market_total) ** (1.0 / years) - 1.0,
        "market_max_drawdown": _max_drawdown(market_curve),
        "beta": beta,
        "daily_return_correlation": correlation,
        "annualized_regression_alpha": alpha_daily * 252.0 if alpha_daily is not None else None,
        "method": (
            "Cross-sectional mean of each available stock's adjusted-close return; "
            "strategy and benchmark daily returns aligned on identical trading dates."
        ),
    }
    output = run_dir / "market-relative.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
