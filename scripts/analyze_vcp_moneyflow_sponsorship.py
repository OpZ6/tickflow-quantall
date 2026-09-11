#!/usr/bin/env python3
"""Audit causal active-order sponsorship around broad VCP breakouts."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
QUANTS_DB = Path("D:/quantall/apps/quants/data/warehouse/ppgu_unified.duckdb")
INPUTS = (
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2017-2020-v1/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-v4/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2024-2026-v1/discovery-candidates.parquet",
)
OUTPUT = ROOT / "data/research/vcp/analysis/moneyflow-sponsorship-2017-2026-v1.json"
DETAIL = ROOT / "data/research/vcp/analysis/moneyflow-sponsorship-2017-2026-v1.parquet"
FEATURES = (
    "final_leg_net_ratio",
    "final_leg_positive_day_share",
    "signal_day_net_ratio",
)


def _pairwise_probability(values: pd.Series, labels: pd.Series) -> float | None:
    frame = pd.DataFrame({"value": values, "label": labels}).dropna()
    positive = frame.loc[frame["label"].astype(bool), "value"].to_numpy(float)
    negative = frame.loc[~frame["label"].astype(bool), "value"].to_numpy(float)
    if not len(positive) or not len(negative):
        return None
    comparisons = positive[:, None] - negative[None, :]
    return float((np.sum(comparisons > 0) + 0.5 * np.sum(comparisons == 0)) / comparisons.size)


def _spearman(values: pd.Series, outcomes: pd.Series) -> float | None:
    frame = pd.DataFrame({"value": values, "outcome": outcomes}).dropna()
    if len(frame) < 3 or frame["value"].nunique() < 2 or frame["outcome"].nunique() < 2:
        return None
    return float(frame["value"].rank().corr(frame["outcome"].rank()))


def _quintiles(frame: pd.DataFrame, feature: str) -> list[dict]:
    usable = frame.dropna(subset=[feature, "true_breakout_10_7_20", "return_40d"]).copy()
    usable["year_rank"] = usable.groupby("year")[feature].rank(method="average", pct=True)
    usable["quintile"] = np.minimum(np.ceil(usable["year_rank"] * 5), 5).astype(int)
    return [
        {
            "quintile": int(quintile),
            "n": len(group),
            "feature_median": float(group[feature].median()),
            "true_breakout_rate": float(group["true_breakout_10_7_20"].mean()),
            "return_40d_median": float(group["return_40d"].median()),
        }
        for quintile, group in usable.groupby("quintile", sort=True)
    ]


def _feature_summary(frame: pd.DataFrame, feature: str) -> dict:
    annual = []
    for year, group in frame.groupby("year", sort=True):
        probability = _pairwise_probability(group[feature], group["true_breakout_10_7_20"])
        if probability is not None:
            annual.append(
                {
                    "year": int(year),
                    "n": int(group[feature].notna().sum()),
                    "pairwise_probability": probability,
                }
            )
    quintiles = _quintiles(frame, feature)
    top_bottom = (
        quintiles[-1]["true_breakout_rate"] - quintiles[0]["true_breakout_rate"]
        if len(quintiles) == 5
        else None
    )
    pairwise = _pairwise_probability(frame[feature], frame["true_breakout_10_7_20"])
    spearman = _spearman(frame[feature], frame["return_40d"])
    years_positive = sum(row["pairwise_probability"] > 0.5 for row in annual)
    gates = {
        "overall_direction_positive": pairwise is not None and pairwise > 0.5,
        "at_least_7_of_10_years_positive": years_positive >= 7,
        "top_minus_bottom_breakout_rate_at_least_0_05": (
            top_bottom is not None and top_bottom >= 0.05
        ),
        "continuous_return_direction_positive": spearman is not None and spearman > 0,
    }
    return {
        "n": int(frame[feature].notna().sum()),
        "pairwise_probability": pairwise,
        "spearman_return_40d": spearman,
        "years_above_0_5": years_positive,
        "years_below_0_5": sum(row["pairwise_probability"] < 0.5 for row in annual),
        "annual": annual,
        "quintiles": quintiles,
        "top_minus_bottom_breakout_rate": top_bottom,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
    }


def main() -> int:
    candidates = (
        pl.concat([pl.read_parquet(path) for path in INPUTS], how="diagonal_relaxed")
        .sort(["signal_date", "symbol", "scale", "pivot_date"])
        .unique(["symbol", "scale", "pivot_date"], keep="first", maintain_order=True)
        .select(
            "symbol",
            "signal_date",
            "scale",
            "pivot_date",
            "true_breakout_10_7_20",
            "return_40d",
            "mfe_40d",
        )
        .with_columns(
            pl.col("signal_date").str.to_date(strict=True),
            pl.col("pivot_date").str.to_date(strict=True),
        )
        .to_pandas()
    )
    connection = duckdb.connect(str(QUANTS_DB), read_only=True)
    connection.register("vcp_candidates", candidates)
    try:
        data = connection.execute(
            """
            WITH flow AS (
                SELECT
                    ts_code,
                    trade_date,
                    net_mf_amount,
                    COALESCE(buy_sm_amount, 0) + COALESCE(sell_sm_amount, 0)
                    + COALESCE(buy_md_amount, 0) + COALESCE(sell_md_amount, 0)
                    + COALESCE(buy_lg_amount, 0) + COALESCE(sell_lg_amount, 0)
                    + COALESCE(buy_elg_amount, 0) + COALESCE(sell_elg_amount, 0)
                    AS component_amount,
                    source_name
                FROM dwd_moneyflow
            )
            SELECT
                c.*,
                SUM(CASE WHEN f.trade_date < c.signal_date THEN f.net_mf_amount END)
                    / NULLIF(SUM(CASE WHEN f.trade_date < c.signal_date THEN f.component_amount END), 0)
                    AS final_leg_net_ratio,
                AVG(CASE WHEN f.trade_date < c.signal_date
                         THEN CASE WHEN f.net_mf_amount > 0 THEN 1.0 ELSE 0.0 END END)
                    AS final_leg_positive_day_share,
                MAX(CASE WHEN f.trade_date = c.signal_date
                         THEN f.net_mf_amount / NULLIF(f.component_amount, 0) END)
                    AS signal_day_net_ratio,
                COUNT(CASE WHEN f.trade_date < c.signal_date THEN 1 END)::BIGINT
                    AS final_leg_covered_sessions,
                MAX(CASE WHEN f.trade_date = c.signal_date THEN 1 ELSE 0 END)::INTEGER
                    AS signal_day_covered,
                STRING_AGG(DISTINCT f.source_name, ',' ORDER BY f.source_name) AS flow_sources
            FROM vcp_candidates AS c
            LEFT JOIN flow AS f
              ON f.ts_code = c.symbol
             AND f.trade_date BETWEEN c.pivot_date AND c.signal_date
            GROUP BY ALL
            ORDER BY c.signal_date, c.symbol, c.scale, c.pivot_date
            """
        ).fetch_df()
    finally:
        connection.close()
    data["year"] = pd.to_datetime(data["signal_date"]).dt.year
    data["true_breakout_10_7_20"] = data["true_breakout_10_7_20"].astype("boolean")
    summaries = {feature: _feature_summary(data, feature) for feature in FEATURES}
    result = {
        "analysis": "moneyflow-sponsorship-2017-2026-v1",
        "unique_setups": len(data),
        "date_range": [
            pd.to_datetime(data["signal_date"]).min().date().isoformat(),
            pd.to_datetime(data["signal_date"]).max().date().isoformat(),
        ],
        "signal_day_coverage": float(data["signal_day_covered"].mean()),
        "final_leg_any_coverage": float((data["final_leg_covered_sessions"] > 0).mean()),
        "final_leg_covered_sessions_median": float(data["final_leg_covered_sessions"].median()),
        "features": summaries,
        "any_feature_passed_all_gates": any(
            summary["all_gates_passed"] for summary in summaries.values()
        ),
        "guardrails": {
            "warehouse_access": "read_only",
            "strategy_changed": False,
            "threshold_selected": False,
            "score_created": False,
            "portfolio_backtest_run": False,
            "future_columns_used_only_as_labels": [
                "true_breakout_10_7_20",
                "return_40d",
                "mfe_40d",
            ],
        },
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pl.from_pandas(data).write_parquet(DETAIL)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
