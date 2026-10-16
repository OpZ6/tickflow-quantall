from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from app.services.financial_sync import get_financial_df


def analyze_stock(data_dir: Path, symbol: str, as_of: date) -> dict[str, Any]:
    tables = {
        name: _as_of(get_financial_df(data_dir, name), symbol, as_of)
        for name in ("metrics", "income", "balance_sheet", "cash_flow")
    }
    metrics = _latest(tables["metrics"])
    income = _latest(tables["income"])
    cash = _latest(tables["cash_flow"])
    balance = _latest(tables["balance_sheet"])
    revenue_yoy = _num(metrics, "revenue_yoy")
    profit_yoy = _num(metrics, "net_income_yoy")
    roe = _num(metrics, "roe")
    margin = _num(metrics, "gross_margin")
    eps = _num(metrics, "eps_basic")
    components = {
        "revenue_growth": _bounded(revenue_yoy, 0, 40, 25),
        "profit_growth": _bounded(profit_yoy, 0, 50, 30),
        "roe": _bounded(roe, 0, 20, 20),
        "gross_margin": _bounded(margin, 0, 40, 15),
        "positive_eps": 10.0 if eps is not None and eps > 0 else 0.0,
    }
    ocf = _num(cash, "net_operating_cash_flow")
    net_income = _num(income, "net_income")
    debt_ratio = _num(metrics, "debt_to_asset_ratio")
    if debt_ratio is None:
        assets, liabilities = _num(balance, "total_assets"), _num(balance, "total_liabilities")
        debt_ratio = liabilities / assets * 100 if assets and liabilities is not None else None
    periods = sorted(
        {
            str(row.get("period_end"))
            for frame in tables.values()
            for row in frame.to_dicts()
            if row.get("period_end")
        }
    )
    quality_flag = (
        all(v is not None for v in (revenue_yoy, profit_yoy, roe, margin, eps))
        and revenue_yoy >= 15
        and profit_yoy >= 15
        and roe >= 8
        and margin >= 15
        and eps > 0
    )
    return {
        "symbol": symbol, "as_of": as_of.isoformat(), "model": "finance_quality_v1",
        "score": {
            "total": round(sum(components.values()), 1),
            "components": components,
            "quality_flag": quality_flag,
        },
        "cards": {
            "growth": {"revenue_yoy": revenue_yoy, "net_income_yoy": profit_yoy},
            "profitability": {"roe": roe, "gross_margin": margin},
            "cash_quality": {
                "operating_cash_flow": ocf,
                "net_income": net_income,
                "cash_to_profit": (
                    ocf / net_income if ocf is not None and net_income else None
                ),
            },
            "solvency": {"debt_to_asset_ratio": debt_ratio},
        },
        "coverage": {"periods": len(periods), "latest_period": periods[-1] if periods else None},
        "warnings": [] if periods else ["尚无该股票的本地详细财报，请先更新该股"],
    }


def _as_of(df: pl.DataFrame, symbol: str, as_of: date) -> pl.DataFrame:
    if df.is_empty() or "symbol" not in df.columns:
        return pl.DataFrame()
    out = df.filter(pl.col("symbol") == symbol)
    if "announce_date" in out.columns:
        out = out.filter(pl.col("announce_date").is_null() | (pl.col("announce_date") <= as_of))
    return out


def _latest(df: pl.DataFrame) -> dict:
    if df.is_empty():
        return {}
    return df.sort("period_end").tail(1).to_dicts()[0]


def _num(row: dict, key: str) -> float | None:
    value = row.get(key)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _bounded(value: float | None, low: float, high: float, weight: float) -> float:
    if value is None:
        return 0.0
    return round((min(max(value, low), high) - low) / (high - low) * weight, 2)
