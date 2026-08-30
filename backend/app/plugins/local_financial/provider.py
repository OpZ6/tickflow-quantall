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
        if raw is None or raw.empty:
            return pl.DataFrame()
        # AkShare has changed/garbled Chinese column labels in some Windows locales;
        # its documented positional schema is stable, so select explicit Series to
        # avoid duplicate-name conversion becoming a Polars List column.
        if raw.shape[1] < 16:
            return pl.DataFrame()
        import pandas as pd
        selected = pd.DataFrame({
            "code": raw.iloc[:, 1].astype(str).to_numpy(), "name": raw.iloc[:, 2].to_numpy(),
            "eps": raw.iloc[:, 3].to_numpy(), "revenue": raw.iloc[:, 4].to_numpy(),
            "revenue_yoy": raw.iloc[:, 5].to_numpy(), "net_profit": raw.iloc[:, 7].to_numpy(),
            "net_profit_yoy": raw.iloc[:, 8].to_numpy(), "roe": raw.iloc[:, 11].to_numpy(),
            "gross_margin": raw.iloc[:, 13].to_numpy(), "announce_date": raw.iloc[:, 15].to_numpy(),
        })
        df = pl.from_pandas(selected)
        df = df.with_columns(
            pl.col("code").cast(pl.Utf8).str.zfill(6),
            pl.when(pl.col("code").cast(pl.Utf8).str.contains(r"^(4|8|92)"))
              .then(pl.col("code").cast(pl.Utf8).str.zfill(6) + pl.lit(".BJ"))
              .when(pl.col("code").cast(pl.Utf8).str.contains(r"^[569]"))
              .then(pl.col("code").cast(pl.Utf8).str.zfill(6) + pl.lit(".SH"))
              .otherwise(pl.col("code").cast(pl.Utf8).str.zfill(6) + pl.lit(".SZ")).alias("symbol"),
            pl.lit(period).alias("period_end"), pl.lit(date.today()).alias("observed_at"),
            pl.lit("akshare_eastmoney").alias("source"), pl.lit("snapshot").alias("quality_level"),
        )
        if "announce_date" in df.columns:
            df = df.with_columns(pl.col("announce_date").cast(pl.Date, strict=False))
        return df.unique("symbol", keep="last")

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
