#!/usr/bin/env python
"""从 Quants ppgu_unified.duckdb 导出历史数据到 TickFlow Parquet 格式。

只读 Quants 库,不修改。导出后可关闭 Quants,数据已在 TickFlow Parquet。

用法:
    cd backend
    uv run python ../scripts/migrate_from_quants.py \\
        --quants-db D:/quantall/apps/quants/data/warehouse/ppgu_unified.duckdb \\
        --tickflow-data ./data \\
        --tables daily,adj_factor,moneyflow

表映射:
    dwd_daily_bar   → kline_daily/date=YYYY-MM-DD/part.parquet (用 raw 列)
    dwd_adj_factor  → adj_factor/symbol=XXX/part.parquet
    dwd_moneyflow   → moneyflow/date=YYYY-MM-DD/part.parquet

前置:Quants AGENTS.md 规定"测试不得连接或写入生产 DuckDB"。
本脚本只读(read_only=True),不修改 Quants 库。但建议先备份 Quants 库再运行。
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Quants → TickFlow 字段映射
_DAILY_RENAME = {
    "ts_code": "symbol",
    "trade_date": "date",
    "open_raw": "open",
    "high_raw": "high",
    "low_raw": "low",
    "close_raw": "close",
    "volume_raw": "volume",
    "amount_raw": "amount",
}
_ADJ_RENAME = {
    "ts_code": "symbol",
    "trade_date": "trade_date",
    "adj_factor": "ex_factor",
}


def _parse_yyyymmdd(s):
    """YYYYMMDD 字符串/int → date 对象;无法解析返回 None。"""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    if isinstance(s, (int, float)):
        s = str(int(s))
    try:
        return pd.to_datetime(str(s), format="%Y%m%d").date()
    except (ValueError, TypeError):
        return None


def _write_date_partitions(df: pd.DataFrame, out_dir: Path, date_col: str = "date") -> int:
    """按 date_col 分区写 Parquet:date=YYYY-MM-DD/part.parquet。返回分区数。"""
    if df is None or df.empty:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for d, group in df.groupby(date_col):
        ds = pd.Timestamp(d).strftime("%Y-%m-%d") if not isinstance(d, str) else str(d)
        part_path = out_dir / f"date={ds}" / "part.parquet"
        part_path.parent.mkdir(parents=True, exist_ok=True)
        group.to_parquet(part_path, index=False)
        count += 1
    return count


def _write_symbol_partitions(df: pd.DataFrame, out_dir: Path, symbol_col: str = "symbol") -> int:
    """按 symbol 分区写 Parquet:symbol=XXX/part.parquet(.替换为_)。返回分区数。"""
    if df is None or df.empty:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for sym, group in df.groupby(symbol_col):
        safe_sym = str(sym).replace(".", "_")
        part_path = out_dir / f"symbol={safe_sym}" / "part.parquet"
        part_path.parent.mkdir(parents=True, exist_ok=True)
        group.to_parquet(part_path, index=False)
        count += 1
    return count


def _table_exists(con, table: str) -> bool:
    try:
        result = con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchall()
        return len(result) > 0
    except Exception:
        return False


def export_daily(con, tickflow_data: Path) -> int:
    """dwd_daily_bar → kline_daily(用 raw 列,TickFlow 存不复权)。"""
    logger.info("导出 dwd_daily_bar → kline_daily")
    if not _table_exists(con, "dwd_daily_bar"):
        logger.warning("dwd_daily_bar 表不存在,跳过")
        return 0
    df = con.execute(
        "SELECT ts_code, trade_date, open_raw, high_raw, low_raw, close_raw, "
        "volume_raw, amount_raw FROM dwd_daily_bar WHERE open_raw IS NOT NULL"
    ).fetchdf()
    if df is None or df.empty:
        logger.warning("dwd_daily_bar 无数据")
        return 0
    df = df.rename(columns=_DAILY_RENAME)
    df["date"] = df["date"].apply(_parse_yyyymmdd)
    df = df.dropna(subset=["date", "symbol"])
    # 停牌过滤(open=0 且 high=0),对齐 TickFlow filter_halt_days
    df = df[~((df["open"] == 0) & (df["high"] == 0))]
    n = _write_date_partitions(df, tickflow_data / "kline_daily")
    logger.info("kline_daily: %d 个日期分区", n)
    return n


def export_adj_factor(con, tickflow_data: Path) -> int:
    """dwd_adj_factor → adj_factor(按 symbol 分区)。"""
    logger.info("导出 dwd_adj_factor → adj_factor")
    if not _table_exists(con, "dwd_adj_factor"):
        logger.warning("dwd_adj_factor 表不存在,跳过")
        return 0
    df = con.execute("SELECT ts_code, trade_date, adj_factor FROM dwd_adj_factor").fetchdf()
    if df is None or df.empty:
        logger.warning("dwd_adj_factor 无数据")
        return 0
    df = df.rename(columns=_ADJ_RENAME)
    df["trade_date"] = df["trade_date"].apply(_parse_yyyymmdd)
    df = df.dropna(subset=["trade_date", "symbol", "ex_factor"])
    n = _write_symbol_partitions(df, tickflow_data / "adj_factor")
    logger.info("adj_factor: %d 个标的分区", n)
    return n


def export_moneyflow(con, tickflow_data: Path) -> int:
    """dwd_moneyflow → moneyflow(按 date 分区)。"""
    logger.info("导出 dwd_moneyflow → moneyflow")
    if not _table_exists(con, "dwd_moneyflow"):
        logger.warning("dwd_moneyflow 表不存在,跳过")
        return 0
    df = con.execute("SELECT * FROM dwd_moneyflow").fetchdf()
    if df is None or df.empty:
        logger.warning("dwd_moneyflow 无数据")
        return 0
    if "ts_code" in df.columns:
        df = df.rename(columns={"ts_code": "symbol"})
    if "trade_date" in df.columns:
        df["trade_date"] = df["trade_date"].apply(_parse_yyyymmdd)
        df = df.rename(columns={"trade_date": "date"})
        n = _write_date_partitions(df, tickflow_data / "moneyflow")
    else:
        n = 0
    logger.info("moneyflow: %d 个日期分区", n)
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description="从 Quants DuckDB 导出历史到 TickFlow Parquet")
    parser.add_argument("--quants-db", required=True, help="Quants ppgu_unified.duckdb 路径")
    parser.add_argument("--tickflow-data", required=True, help="TickFlow data/ 目录路径")
    parser.add_argument(
        "--tables", default="daily,adj_factor,moneyflow", help="导出的表,逗号分隔"
    )
    args = parser.parse_args()

    quants_db = Path(args.quants_db)
    if not quants_db.exists():
        logger.error("Quants 数据库不存在: %s", quants_db)
        sys.exit(1)
    tickflow_data = Path(args.tickflow_data)
    tickflow_data.mkdir(parents=True, exist_ok=True)

    import duckdb

    con = duckdb.connect(str(quants_db), read_only=True)
    tables = [t.strip() for t in args.tables.split(",")]
    total = 0
    exporters = {
        "daily": export_daily,
        "adj_factor": export_adj_factor,
        "moneyflow": export_moneyflow,
    }
    try:
        for t in tables:
            fn = exporters.get(t)
            if fn is None:
                logger.warning("未知表: %s,跳过", t)
                continue
            total += fn(con, tickflow_data)
    finally:
        con.close()
    logger.info("导出完成,共 %d 个分区", total)


if __name__ == "__main__":
    main()
