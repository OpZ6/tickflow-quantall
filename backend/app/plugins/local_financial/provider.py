from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date

import polars as pl

from app.plugins.tushare.provider import TushareProvider


@dataclass
class _Config:
    name: str = "local_financial"
    display_name: str = "本地财务（AkShare + Tushare）"
    datasets: dict = field(default_factory=lambda: {"financial": None})
    builtin: bool = True


class LocalFinancialProvider:
    name = "local_financial"
    builtin = True

    def __init__(self) -> None:
        self.config = _Config()
        self._detail = TushareProvider()

    def close(self) -> None:
        self._detail.close()

    def financial_mode(self) -> str:
        if os.environ.get("TUSHARE_TOKEN", "").strip():
            return "standard_on_demand"
        return "overview_only"

    def get_financials(
        self, table: str, symbols: list[str], latest_only: bool = True
    ) -> pl.DataFrame:
        if not os.environ.get("TUSHARE_TOKEN", "").strip():
            raise RuntimeError("详细财报需要设置 TUSHARE_TOKEN；全市场概览仍可独立更新")
        return self._detail.get_financials(table, symbols, latest_only=latest_only)

    def get_financial_overview(self, report_period: date | None = None) -> pl.DataFrame:
        import akshare as ak

        period = report_period or _latest_report_period(date.today())
        raw = ak.stock_yjbb_em(date=period.strftime("%Y%m%d"))
        return _normalize_market_frame(
            raw,
            period,
            {
                "eps": 3,
                "revenue": 4,
                "revenue_yoy": 5,
                "net_profit": 7,
                "net_profit_yoy": 8,
                "roe": 11,
                "gross_margin": 13,
                "announce_date": 15,
            },
            min_columns=16,
            quality_level="snapshot",
        )

    def get_financial_market_table(
        self, table: str, report_period: date
    ) -> pl.DataFrame:
        """Fetch one report period for the entire A-share market.

        These Eastmoney datasets are compact core statements. Rich hundreds-field
        statements remain an on-demand Tushare concern.
        """
        import akshare as ak

        period = report_period.strftime("%Y%m%d")
        if table == "metrics":
            raw = ak.stock_yjbb_em(date=period)
            return _normalize_market_frame(
                raw,
                report_period,
                {
                    "eps_basic": 3,
                    "revenue": 4,
                    "revenue_yoy": 5,
                    "net_income": 7,
                    "net_income_yoy": 8,
                    "roe": 11,
                    "ocfps": 12,
                    "gross_margin": 13,
                    "announce_date": 15,
                },
                min_columns=16,
            )
        if table == "income":
            raw = ak.stock_lrb_em(date=period)
            return _normalize_market_frame(
                raw,
                report_period,
                {
                    "net_income": 3,
                    "net_income_yoy": 4,
                    "revenue": 5,
                    "revenue_yoy": 6,
                    "operating_cost": 7,
                    "selling_expense": 8,
                    "admin_expense": 9,
                    "financial_expense": 10,
                    "total_operating_expense": 11,
                    "operating_profit": 12,
                    "total_profit": 13,
                    "announce_date": 14,
                },
                min_columns=15,
            )
        if table == "balance_sheet":
            frames = [ak.stock_zcfz_em(date=period)]
            bj = getattr(ak, "stock_zcfz_bj_em", None)
            if callable(bj):
                frames.append(bj(date=period))
            normalized = [
                _normalize_market_frame(
                    raw,
                    report_period,
                    {
                        "cash_and_equivalents": 3,
                        "accounts_receivable": 4,
                        "inventory": 5,
                        "total_assets": 6,
                        "total_assets_yoy": 7,
                        "accounts_payable": 8,
                        "total_liabilities": 9,
                        "advance_receipts": 10,
                        "total_liabilities_yoy": 11,
                        "debt_to_asset_ratio": 12,
                        "total_equity": 13,
                        "announce_date": 14,
                    },
                    min_columns=15,
                )
                for raw in frames
            ]
            valid = [frame for frame in normalized if not frame.is_empty()]
            return (
                pl.concat(valid, how="diagonal_relaxed").unique("symbol", keep="last")
                if valid
                else pl.DataFrame()
            )
        if table == "cash_flow":
            raw = ak.stock_xjll_em(date=period)
            return _normalize_market_frame(
                raw,
                report_period,
                {
                    "net_cash_change": 3,
                    "net_cash_change_yoy": 4,
                    "net_operating_cash_flow": 5,
                    "operating_cash_ratio": 6,
                    "net_investing_cash_flow": 7,
                    "investing_cash_ratio": 8,
                    "net_financing_cash_flow": 9,
                    "financing_cash_ratio": 10,
                    "announce_date": 11,
                },
                min_columns=12,
            )
        raise ValueError(f"不支持全市场历史财务表: {table}")

    def test_dataset(self, dataset: str, symbols: list[str] | None = None) -> dict:
        if dataset != "financial":
            raise ValueError(dataset)
        return {
            "provider": self.name,
            "dataset": dataset,
            "mode": self.financial_mode(),
            "rows": 0,
            "preview": [],
        }


def _latest_report_period(today: date) -> date:
    candidates = [
        date(today.year, 9, 30),
        date(today.year, 6, 30),
        date(today.year, 3, 31),
        date(today.year - 1, 12, 31),
    ]
    return next(period for period in candidates if period < today)


def _normalize_market_frame(
    raw,
    report_period: date,
    fields: dict[str, int],
    *,
    min_columns: int,
    quality_level: str = "core_statement",
) -> pl.DataFrame:
    """Normalize AkShare's full-market positional tables across Windows locales."""
    if raw is None or raw.empty or raw.shape[1] < min_columns:
        return pl.DataFrame()
    import pandas as pd

    selected = {
        "code": raw.iloc[:, 1].astype(str).to_numpy(),
        "name": raw.iloc[:, 2].to_numpy(),
    }
    selected.update({name: raw.iloc[:, index].to_numpy() for name, index in fields.items()})
    df = pl.from_pandas(pd.DataFrame(selected))
    code = pl.col("code").cast(pl.Utf8).str.zfill(6)
    df = df.with_columns(
        code,
        pl.when(code.str.contains(r"^(4|8|92)"))
        .then(code + pl.lit(".BJ"))
        .when(code.str.contains(r"^[569]"))
        .then(code + pl.lit(".SH"))
        .otherwise(code + pl.lit(".SZ"))
        .alias("symbol"),
        pl.lit(report_period).alias("period_end"),
        pl.lit(date.today()).alias("observed_at"),
        pl.lit("akshare_eastmoney").alias("source"),
        pl.lit(quality_level).alias("quality_level"),
    )
    if "announce_date" in df.columns:
        df = df.with_columns(pl.col("announce_date").cast(pl.Date, strict=False))
    numeric = [
        column
        for column in fields
        if column != "announce_date" and column in df.columns
    ]
    if numeric:
        df = df.with_columns(
            [pl.col(column).cast(pl.Float64, strict=False) for column in numeric]
        )
    return df.filter(pl.col("symbol").is_not_null()).unique("symbol", keep="last")
