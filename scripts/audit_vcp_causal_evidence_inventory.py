#!/usr/bin/env python3
"""Audit existing causal catalyst and sponsorship data before choosing a VCP mechanism test."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
QUANTS_DB = Path("D:/quantall/apps/quants/data/warehouse/ppgu_unified.duckdb")
OUTPUT = ROOT / "data/research/vcp/analysis/causal-evidence-inventory-v1.json"
CANDIDATE_INPUTS = (
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2017-2020-v1/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-v4/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2024-2026-v1/discovery-candidates.parquet",
)


def _partition_inventory(dataset: str, suffix: str = "part.parquet") -> dict:
    root = ROOT / "data" / dataset
    paths = sorted(root.glob(f"date=*/{suffix}")) if suffix else sorted(root.glob("date=*"))
    dates = [path.parent.name.removeprefix("date=") for path in paths]
    return {
        "dataset": dataset,
        "partitions": len(paths),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
    }


def _json_inventory(dataset: str) -> dict:
    paths = sorted((ROOT / "data" / dataset).glob("date=*.json"))
    dates = [path.stem.removeprefix("date=") for path in paths]
    return {
        "dataset": dataset,
        "partitions": len(paths),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
    }


def _quants_table(connection: duckdb.DuckDBPyConnection, table: str, date_field: str) -> dict:
    row = connection.execute(
        f"""
        SELECT
            COUNT(*)::BIGINT,
            COUNT(DISTINCT ts_code)::BIGINT,
            COUNT(DISTINCT {date_field})::BIGINT,
            MIN({date_field}),
            MAX({date_field})
        FROM {table}
        """
    ).fetchone()
    sources = connection.execute(
        f"SELECT source_name, COUNT(*)::BIGINT FROM {table} GROUP BY source_name ORDER BY 2 DESC"
    ).fetchall()
    return {
        "table": table,
        "rows": row[0],
        "symbols": row[1],
        "dates": row[2],
        "first_date": row[3].isoformat() if row[3] else None,
        "last_date": row[4].isoformat() if row[4] else None,
        "sources": [{"source": source, "rows": count} for source, count in sources],
    }


def main() -> int:
    connection = duckdb.connect(str(QUANTS_DB), read_only=True)
    try:
        moneyflow = _quants_table(connection, "dwd_moneyflow", "trade_date")
        moneyflow["yearly"] = [
            {"year": int(year), "rows": rows, "symbols": symbols, "dates": dates}
            for year, rows, symbols, dates in connection.execute(
                """
                SELECT YEAR(trade_date), COUNT(*)::BIGINT,
                       COUNT(DISTINCT ts_code)::BIGINT, COUNT(DISTINCT trade_date)::BIGINT
                FROM dwd_moneyflow
                GROUP BY 1 ORDER BY 1
                """
            ).fetchall()
        ]
        component_net = " + ".join(
            f"COALESCE({side}_{size}_amount, 0) * {sign}"
            for size in ("sm", "md", "lg", "elg")
            for side, sign in (("buy", 1), ("sell", -1))
        )
        component_total = " + ".join(
            f"COALESCE({side}_{size}_amount, 0)"
            for size in ("sm", "md", "lg", "elg")
            for side in ("buy", "sell")
        )
        moneyflow["contract_observations"] = [
            {
                "source": source,
                "rows": rows,
                "net_mf_amount_abs_median": net_median,
                "net_mf_amount_abs_p99": net_p99,
                "net_equals_component_net_rate": equal_rate,
                "component_amount_to_daily_bar_amount_median": turnover_ratio,
            }
            for source, rows, net_median, net_p99, equal_rate, turnover_ratio in connection.execute(
                f"""
                SELECT
                    mf.source_name,
                    COUNT(*)::BIGINT,
                    MEDIAN(ABS(mf.net_mf_amount)),
                    QUANTILE_CONT(ABS(mf.net_mf_amount), 0.99),
                    AVG(CASE WHEN ABS(mf.net_mf_amount - ({component_net})) <= 0.01
                             THEN 1.0 ELSE 0.0 END),
                    MEDIAN(({component_total}) / NULLIF(bar.amount_raw, 0))
                FROM dwd_moneyflow AS mf
                LEFT JOIN dwd_daily_bar AS bar
                  ON bar.ts_code = mf.ts_code AND bar.trade_date = mf.trade_date
                GROUP BY mf.source_name
                ORDER BY 2 DESC
                """
            ).fetchall()
        ]
        moneyflow["source_by_year"] = [
            {"year": int(year), "source": source, "rows": rows, "symbols": symbols}
            for year, source, rows, symbols in connection.execute(
                """
                SELECT YEAR(trade_date), source_name, COUNT(*)::BIGINT,
                       COUNT(DISTINCT ts_code)::BIGINT
                FROM dwd_moneyflow GROUP BY 1, 2 ORDER BY 1, 2
                """
            ).fetchall()
        ]
        candidates = (
            pl.concat([pl.read_parquet(path) for path in CANDIDATE_INPUTS], how="diagonal_relaxed")
            .select("symbol", "signal_date", "scale", "pivot_date")
            .unique(["symbol", "scale", "pivot_date"], maintain_order=True)
            .with_columns(pl.col("signal_date").str.to_date(strict=True))
        )
        connection.register("vcp_candidate_keys", candidates)
        moneyflow["vcp_signal_date_coverage"] = [
            {
                "year": int(year),
                "candidates": total,
                "covered": covered,
                "coverage_rate": covered / total,
            }
            for year, total, covered in connection.execute(
                """
                SELECT YEAR(c.signal_date), COUNT(*)::BIGINT,
                       COUNT(mf.ts_code)::BIGINT
                FROM vcp_candidate_keys AS c
                LEFT JOIN dwd_moneyflow AS mf
                  ON mf.ts_code = c.symbol AND mf.trade_date = c.signal_date
                GROUP BY 1 ORDER BY 1
                """
            ).fetchall()
        ]
        quants = {
            "database": str(QUANTS_DB),
            "mode": "read_only",
            "moneyflow": moneyflow,
            "daily_basic": _quants_table(connection, "dwd_daily_basic", "trade_date"),
            "quarter_finance": _quants_table(
                connection, "dwd_quarter_finance", "announce_date"
            ),
        }
    finally:
        connection.close()

    tickflow = [
        _json_inventory("dragon_tiger"),
        _partition_inventory("limit_event_daily"),
        _partition_inventory("limit_ladder_daily"),
        _partition_inventory("theme_member_daily"),
        _partition_inventory("sector_flow_daily"),
        _partition_inventory("margin_daily"),
    ]
    result = {
        "audit": "vcp-causal-evidence-inventory-v1",
        "quants": quants,
        "tickflow_market_facts": tickflow,
        "selection_rule": (
            "A mechanism may proceed only if the evidence predates the signal and has enough "
            "cross-year coverage for a descriptive audit. Sparse current snapshots remain forward-only."
        ),
        "official_contract_reference": {
            "url": "https://tushare.pro/document/2?doc_id=170",
            "amount_unit": "ten_thousand_yuan",
            "volume_unit": "round_lot",
            "net_definition_note": (
                "Tushare documents net flow as an L2 active-order measure and warns that it is not "
                "necessarily the simple sum of size-bucket buy minus sell amounts."
            ),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
