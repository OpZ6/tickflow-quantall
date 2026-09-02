"""Tushare Pro 数据源 provider。

通过 tushare SDK 拉 A 股日K/除权/指数/财务/资金流。
归一化到项目内部 schema(normalizer.py),与 TickFlow/stock-sdk provider 同台路由。
Token 从环境变量 TUSHARE_TOKEN 读;依赖用延迟 import(函数内),未安装不阻断启动。
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import polars as pl

from app.data_providers.normalizer import (
    normalize_adj_factors,
    normalize_daily,
)
from app.tickflow.rate_limits import chunked

logger = logging.getLogger(__name__)

_DATASETS = ("daily", "adj_factor", "index", "financial", "moneyflow")
_BATCH = 80
_TIMEOUT = 30.0


@dataclass
class _TushareConfig:
    """轻量 config shim,让 custom loader 的 list_plugins/provider_has_dataset 识别本 provider。"""

    name: str = "tushare"
    display_name: str = "Tushare Pro (A 股官方行情)"
    datasets: dict = field(default_factory=lambda: dict.fromkeys(_DATASETS))
    path: None = None
    builtin: bool = True


def _yyyymmdd(dt: datetime | None) -> str | None:
    return dt.strftime("%Y%m%d") if dt else None


_DATE_COLS = ("trade_date", "end_date", "ann_date", "f_ann_date", "list_date")


def _prep_dates(raw):
    """预处理 Tushare pandas 返回: YYYYMMDD 字符串 → date 对象。

    Polars cast(pl.Date) 只认 ISO 'YYYY-MM-DD'; Tushare 用 'YYYYMMDD' 字符串,
    不预处理会被 strict=False cast 变 null。覆盖 trade_date/end_date/ann_date/list_date。
    """
    if raw is None or not hasattr(raw, "columns"):
        return raw
    if hasattr(raw, "iloc"):  # pandas DataFrame
        import pandas as pd

        raw = raw.copy()
        for col in _DATE_COLS:
            if col in raw.columns and raw[col].dtype == object:
                raw[col] = pd.to_datetime(raw[col], format="%Y%m%d", errors="coerce").dt.date
    return raw


def _get_pro():
    """创建 Tushare pro 客户端。token 从环境变量读。"""
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Tushare token 未配置:设置 TUSHARE_TOKEN 环境变量")
    import tushare as ts

    return ts.pro_api(token, timeout=_TIMEOUT)


_TUSHARE_FINANCIAL_API: dict[str, str] = {
    "income": "income",
    "balance_sheet": "balancesheet",
    "cash_flow": "cashflow",
    "metrics": "fina_indicator",
    "shares": "daily_basic",
}

_FINANCIAL_FIELDS: dict[str, dict[str, str]] = {
    "metrics": {
        "eps": "eps_basic", "dt_eps": "eps_diluted", "bps": "bps", "ocfps": "ocfps",
        "roe_waa": "roe", "roe": "roe_diluted", "roa": "roa",
        "grossprofit_margin": "gross_margin", "netprofit_margin": "net_margin",
        "debt_to_assets": "debt_to_asset_ratio", "or_yoy": "revenue_yoy",
        "netprofit_yoy": "net_income_yoy", "ocf_to_or": "operating_cash_to_revenue",
        "inv_turn": "inventory_turnover",
    },
    "income": {
        "revenue": "revenue", "oper_cost": "operating_cost", "operate_profit": "operating_profit",
        "sell_exp": "selling_expense", "admin_exp": "admin_expense", "rd_exp": "rd_expense",
        "fin_exp": "financial_expense", "non_oper_income": "non_operating_income",
        "non_oper_exp": "non_operating_expense", "total_profit": "total_profit",
        "income_tax": "income_tax", "n_income": "net_income",
        "n_income_attr_p": "net_income_attributable", "basic_eps": "basic_eps",
        "diluted_eps": "diluted_eps",
    },
    "balance_sheet": {
        "total_assets": "total_assets", "total_cur_assets": "total_current_assets",
        "total_nca": "total_noncurrent_assets", "money_cap": "cash_and_equivalents",
        "accounts_receiv": "accounts_receivable", "inventories": "inventory",
        "fix_assets": "fixed_assets", "intan_assets": "intangible_assets", "goodwill": "goodwill",
        "total_liab": "total_liabilities", "total_cur_liab": "total_current_liabilities",
        "total_ncl": "total_noncurrent_liabilities", "st_borr": "short_term_borrowing",
        "lt_borr": "long_term_borrowing", "acct_payable": "accounts_payable",
        "total_hldr_eqy_inc_min_int": "total_equity",
        "total_hldr_eqy_exc_min_int": "equity_attributable", "undistr_porfit": "retained_earnings",
        "minority_int": "minority_interest",
    },
    "cash_flow": {
        "n_cashflow_act": "net_operating_cash_flow", "n_cashflow_inv_act": "net_investing_cash_flow",
        "n_cash_flows_fnc_act": "net_financing_cash_flow", "c_pay_acq_const_fiolta": "capex",
        "n_incr_cash_cash_equ": "net_cash_change",
    },
}


def _normalize_financial(table: str, raw) -> pl.DataFrame:
    """Normalize vendor fields to Tickflow's stable financial contract."""
    df = TushareProvider._to_polars_with_symbol(_prep_dates(raw))
    if df.is_empty():
        return df
    rename: dict[str, str] = {}
    if "end_date" in df.columns:
        rename["end_date"] = "period_end"
    if "f_ann_date" in df.columns:
        rename["f_ann_date"] = "announce_date"
    elif "ann_date" in df.columns:
        rename["ann_date"] = "announce_date"
    for src, dst in _FINANCIAL_FIELDS.get(table, {}).items():
        if src in df.columns and src != dst:
            if dst in df.columns and dst not in _FINANCIAL_FIELDS.get(table, {}):
                df = df.drop(dst)
            rename[src] = dst
    if table == "shares":
        if "trade_date" in df.columns:
            rename["trade_date"] = "period_end"
        if "total_share" in df.columns:
            rename["total_share"] = "total_shares"
        if "float_share" in df.columns:
            rename["float_share"] = "float_shares"
    if rename:
        df = df.rename(rename)
    for col in ("period_end", "announce_date", "effective_date"):
        if col in df.columns and df.schema[col] == pl.Utf8:
            df = df.with_columns(
                pl.coalesce(
                    pl.col(col).str.to_date("%Y%m%d", strict=False),
                    pl.col(col).str.to_date("%Y-%m-%d", strict=False),
                ).alias(col)
            )
    if table == "shares":
        cols = [c for c in ("total_shares", "float_shares") if c in df.columns]
        if cols:
            df = df.with_columns([(pl.col(c).cast(pl.Float64, strict=False) * 10_000).alias(c) for c in cols])
        if "period_end" in df.columns:
            df = df.with_columns(pl.col("period_end").alias("effective_date"))
    df = df.with_columns(
        pl.lit("tushare").alias("source"),
        pl.lit(datetime.now().date()).alias("observed_at"),
        pl.lit("official").alias("quality_level"),
    )
    # Keep consolidated/latest revisions where the provider exposes flags.
    if "report_type" in df.columns:
        filtered = df.filter(pl.col("report_type").cast(pl.Utf8) == "1")
        if not filtered.is_empty():
            df = filtered
    if "update_flag" in df.columns:
        filtered = df.filter(pl.col("update_flag").cast(pl.Utf8) == "1")
        if not filtered.is_empty():
            df = filtered
    key = "period_end" if "period_end" in df.columns else None
    if key:
        order = ["symbol", key] + (["announce_date"] if "announce_date" in df.columns else [])
        df = df.sort(order, nulls_last=True).unique(["symbol", key], keep="last")
    if table == "shares" and {"total_shares", "float_shares"} <= set(df.columns):
        df = (
            df.sort(["symbol", "period_end"])
            .with_columns(
                (
                    (pl.col("total_shares") != pl.col("total_shares").shift(1).over("symbol"))
                    | (pl.col("float_shares") != pl.col("float_shares").shift(1).over("symbol"))
                ).fill_null(True).alias("_changed")
            )
            .filter(pl.col("_changed"))
            .drop("_changed")
        )
    return df


class TushareProvider:
    """Tushare Pro 数据源。方法签名对齐 stocksdk provider,供 services 层路由。"""

    name = "tushare"
    builtin = True

    def __init__(self) -> None:
        self.config = _TushareConfig()

    def close(self) -> None:  # loader.load_all 会对每个 provider 调 close
        pass

    # ---- daily ----
    def get_daily(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: str = "stock",
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> pl.DataFrame:
        if not symbols:
            return pl.DataFrame()

        if start_time and end_time and start_time.date() == end_time.date():
            return self._get_daily_by_date(start_time)

        logger.info("Tushare daily 拉取开始(%d symbols)", len(symbols))
        frames: list[pl.DataFrame] = []
        chunks = chunked(symbols, _BATCH)
        for i, chunk in enumerate(chunks):
            try:
                pro = _get_pro()
                raw = pro.daily(
                    ts_code=",".join(chunk),
                    start_date=_yyyymmdd(start_time),
                    end_date=_yyyymmdd(end_time),
                )
            except Exception as e:
                logger.warning("Tushare daily 拉取失败(%d symbols): %s", len(chunk), e)
                raw = None
            raw = _prep_dates(raw)
            df = normalize_daily(raw, source=self.name)
            if not df.is_empty():
                frames.append(df)
            if on_chunk_done:
                on_chunk_done(i + 1, len(chunks))
        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    def _get_daily_by_date(self, dt: datetime) -> pl.DataFrame:
        """按交易日批量拉全市场(一次调用)。"""
        try:
            pro = _get_pro()
            raw = pro.daily(trade_date=_yyyymmdd(dt))
        except Exception as e:
            logger.warning("Tushare daily by_date 拉取失败: %s", e)
            return pl.DataFrame()
        raw = _prep_dates(raw)
        return normalize_daily(raw, source=self.name)

    # ---- adj_factor ----
    def get_adj_factors(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: str = "stock",
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> pl.DataFrame:
        if not symbols:
            return pl.DataFrame()
        logger.info("Tushare adj_factor 拉取开始(%d symbols)", len(symbols))
        frames: list[pl.DataFrame] = []
        chunks = chunked(symbols, _BATCH)
        for i, chunk in enumerate(chunks):
            try:
                pro = _get_pro()
                # Tushare exposes a cumulative adjustment factor.  Include a
                # baseline before the requested range so it can be converted
                # into the event ratio used by Tickflow's internal contract.
                fetch_start = start_time - timedelta(days=30) if start_time else None
                raw = pro.adj_factor(
                    ts_code=",".join(chunk),
                    start_date=_yyyymmdd(fetch_start),
                    end_date=_yyyymmdd(end_time),
                )
            except Exception as e:
                logger.warning("Tushare adj_factor 拉取失败(%d symbols): %s", len(chunk), e)
                raw = None
            raw = _prep_dates(raw)
            df = self._normalize_adj(raw)
            if start_time and not df.is_empty():
                df = df.filter(pl.col("trade_date") >= start_time.date())
            if end_time and not df.is_empty():
                df = df.filter(pl.col("trade_date") <= end_time.date())
            if not df.is_empty():
                frames.append(df)
            if on_chunk_done:
                on_chunk_done(i + 1, len(chunks))
        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    @staticmethod
    def _normalize_adj(raw) -> pl.DataFrame:
        """Tushare adj_factor 标准化。

        Tushare 返回 ts_code/trade_date/adj_factor;normalize_adj_factors 缺 ts_code→symbol 映射,
        故在此预处理后复用 normalize_adj_factors。
        """
        if raw is None:
            return pl.DataFrame()
        if hasattr(raw, "reset_index"):
            df = pl.from_pandas(raw.reset_index())
        elif isinstance(raw, pl.DataFrame):
            df = raw
        else:
            df = pl.DataFrame(raw)
        if df.is_empty():
            return df
        # Tushare trade_date 可能是 'YYYYMMDD' 字符串, 预解析为 Date
        if "trade_date" in df.columns and df.schema["trade_date"] == pl.Utf8:
            df = df.with_columns(pl.col("trade_date").str.to_date("%Y%m%d"))
        rename_map: dict[str, str] = {}
        if "ts_code" in df.columns:
            rename_map["ts_code"] = "symbol"
        if "adj_factor" in df.columns:
            rename_map["adj_factor"] = "ex_factor"
        if rename_map:
            df = df.rename(rename_map)
        cumulative = normalize_adj_factors(df, source="tushare")
        if cumulative.is_empty():
            return cumulative
        return (
            cumulative.sort(["symbol", "trade_date"])
            .with_columns(
                (
                    pl.col("ex_factor")
                    / pl.col("ex_factor").shift(1).over("symbol")
                ).alias("ex_factor")
            )
            .drop_nulls("ex_factor")
            .filter((pl.col("ex_factor") - 1.0).abs() > 1e-10)
        )

    # ---- instruments (标的维表) ----
    def get_instruments(self, asset_type: str = "stock") -> list[dict]:
        if asset_type != "stock":
            return []
        try:
            pro = _get_pro()
            raw = pro.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,symbol,name,area,industry,market,exchange,curr_type,list_status,list_date,delist_date,is_hs",
            )
        except Exception as e:
            logger.warning("Tushare instruments 拉取失败: %s", e)
            return []
        rows: list[dict] = []
        if raw is not None and not raw.empty:
            for _, r in raw.iterrows():
                rows.append({
                    "symbol": str(r.get("ts_code") or ""),
                    "name": str(r.get("name") or ""),
                    "code": str(r.get("symbol") or ""),
                    "exchange": str(r.get("exchange") or ""),
                })
        return rows

    # ---- index_daily (指数日K,供 index_sync 用) ----
    def get_index_daily(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> pl.DataFrame:
        if not symbols:
            return pl.DataFrame()
        frames: list[pl.DataFrame] = []
        for sym in symbols:
            try:
                pro = _get_pro()
                raw = pro.index_daily(
                    ts_code=sym,
                    start_date=_yyyymmdd(start_time),
                    end_date=_yyyymmdd(end_time),
                )
            except Exception as e:
                logger.warning("Tushare index_daily 拉取失败(%s): %s", sym, e)
                raw = None
            raw = _prep_dates(raw)
            df = normalize_daily(raw, default_symbol=sym, source=self.name)
            if not df.is_empty():
                frames.append(df)
        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    # ---- financials (财务报表, 绕过 TickFlow Expert 门槛) ----

    def get_financials(
        self,
        table: str,
        symbols: list[str],
        latest_only: bool = True,
    ) -> pl.DataFrame:
        """拉取财务数据,对齐 GenericHTTPProvider.get_financials 签名。

        table: metrics/income/balance_sheet/cash_flow/shares
        返回 Polars DataFrame,至少含 symbol 列;字段由 Tushare 决定。
        shares 表用 daily_basic(含流通股本/总股本),按当日拉。
        """
        api_name = _TUSHARE_FINANCIAL_API.get(table)
        if api_name is None:
            raise ValueError(f"Tushare 不支持财务表: {table}")
        if not symbols:
            return pl.DataFrame()
        logger.info("Tushare financials %s 拉取开始(%d symbols)", table, len(symbols))
        frames: list[pl.DataFrame] = []
        # Standard Tushare financial endpoints accept one ts_code per request.
        for symbol in symbols:
            try:
                pro = _get_pro()
                if table == "shares":
                    raw = pro.daily_basic(
                        ts_code=symbol,
                        fields="ts_code,trade_date,close,turnover_rate,float_share,total_share,circ_mv,total_mv,pe,pb",
                    )
                else:
                    kwargs: dict = {"ts_code": symbol}
                    raw = getattr(pro, api_name)(**kwargs)
            except Exception as e:
                logger.warning("Tushare financials %s 拉取失败(%s): %s", table, symbol, e)
                raw = None
            df = _normalize_financial(table, raw)
            if not df.is_empty():
                frames.append(df)
        if not frames:
            return pl.DataFrame()
        result = pl.concat(frames, how="diagonal_relaxed")
        if latest_only and table != "shares":
            date_col = next((c for c in ("period_end", "announce_date", "effective_date") if c in result.columns), None)
            if date_col:
                result = result.sort("symbol", date_col).group_by("symbol").last()
        return result

    # ---- moneyflow (个股资金流, 替代 MarketLab proxy) ----
    def get_moneyflow(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> pl.DataFrame:
        """拉个股资金流(主力/超大单/大单/中单/小单净流入)。

        替代 MarketLab sector_flow 的代理公式 quality=proxy。
        """
        if not symbols:
            return pl.DataFrame()
        logger.info("Tushare moneyflow 拉取开始(%d symbols)", len(symbols))
        frames: list[pl.DataFrame] = []
        chunks = chunked(symbols, _BATCH)
        for chunk in chunks:
            try:
                pro = _get_pro()
                raw = pro.moneyflow(
                    ts_code=",".join(chunk),
                    start_date=_yyyymmdd(start_time),
                    end_date=_yyyymmdd(end_time),
                )
            except Exception as e:
                logger.warning("Tushare moneyflow 拉取失败(%d symbols): %s", len(chunk), e)
                raw = None
            raw = _prep_dates(raw)
            df = self._to_polars_with_symbol(raw)
            if not df.is_empty():
                frames.append(df)
        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    @staticmethod
    def _to_polars_with_symbol(raw) -> pl.DataFrame:
        """把 Tushare 返回(pandas/None)转 Polars,确保有 symbol 列(ts_code→symbol)。"""
        if raw is None:
            return pl.DataFrame()
        if hasattr(raw, "reset_index"):
            df = pl.from_pandas(raw.reset_index())
        elif isinstance(raw, pl.DataFrame):
            df = raw
        else:
            df = pl.DataFrame(raw)
        if df.is_empty():
            return df
        if "ts_code" in df.columns:
            df = df.rename({"ts_code": "symbol"})
        if "trade_date" in df.columns and df.schema["trade_date"] == pl.Utf8:
            df = df.with_columns(pl.col("trade_date").str.to_date("%Y%m%d"))
        if "end_date" in df.columns and df.schema["end_date"] == pl.Utf8:
            df = df.with_columns(pl.col("end_date").str.to_date("%Y%m%d"))
        return df

    # ---- test (设置页试拉) ----
    def test_dataset(self, dataset: str, symbols: list[str] | None = None) -> dict:
        symbols = symbols or ["600519.SH"]
        if dataset == "daily":
            df = self.get_daily(symbols, None, None)
            return _preview("daily", df)
        if dataset == "adj_factor":
            df = self.get_adj_factors(symbols, None, None)
            return _preview("adj_factor", df)
        if dataset == "index":
            df = self.get_index_daily(symbols or ["000001.SH"], None, None)
            return _preview("index", df)
        if dataset == "financial":
            df = self.get_financials("income", symbols)
            return _preview("financial", df)
        if dataset == "moneyflow":
            df = self.get_moneyflow(symbols, None, None)
            return _preview("moneyflow", df)
        raise ValueError(f"Tushare 不支持数据集: {dataset}")


def _preview(dataset: str, df: pl.DataFrame) -> dict:
    return {
        "provider": "tushare",
        "dataset": dataset,
        "rows": df.height,
        "columns": df.columns,
        "preview": df.head(5).to_dicts() if not df.is_empty() else [],
    }
