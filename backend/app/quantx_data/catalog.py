from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import read_json, validate_trade_date, write_json_atomic

PUBLIC_ARTIFACTS = {
    "market_overview", "market_breadth", "market_liquidity", "limit_summary",
    "limit_ladder", "limit_stocks", "promotion_stats", "premium_stats",
    "theme_snapshot", "theme_rankings", "theme_history", "theme_stocks", "sentiment_state",
    "risk_signals", "participation", "sector_fund_flow", "sector_rotation",
    "screening_candidates", "trend_history", "trend_pool", "_computed",
    "review_data",
}


def _metrics(date_dir: Path) -> dict[str, Any]:
    computed = read_json(date_dir / "_computed.json", {}) or {}
    limit = read_json(date_dir / "limit_summary.json", {}) or {}
    overview = read_json(date_dir / "market_overview.json", {}) or {}
    mh = computed.get("market_heat", {})
    st = computed.get("short_term_sentiment", {})
    tr = computed.get("trend_sentiment", {})
    advance = computed.get("advance_stats", {})
    participation = computed.get("participation_check", {})
    ebb = computed.get("ebb_risk_check", {})
    crash = computed.get("crash_signals", {})
    return {
        "market_heat_score": mh.get("score"), "market_heat_zone": mh.get("zone"),
        "short_term_sentiment_score": st.get("score"), "short_term_sentiment_zone": st.get("zone"),
        "trend_sentiment_score": tr.get("score"), "trend_sentiment_zone": tr.get("zone"),
        "limit_up_count": limit.get("limit_up_count", st.get("inputs", {}).get("limit_up_count")),
        "seal_rate": limit.get("seal_rate", st.get("inputs", {}).get("seal_rate")),
        "max_board": limit.get("max_board", st.get("inputs", {}).get("max_board")),
        "advance_rate": advance.get("advance_rate"), "premium_rate": advance.get("premium_rate"),
        "participation_verdict": participation.get("verdict"), "participation_satisfied": participation.get("satisfied"),
        "ebb_risk_verdict": ebb.get("verdict"), "ebb_signal_count": ebb.get("signal_count"),
        "crash_triggered": crash.get("any_triggered"),
        "total_amount_yi": overview.get("total_amount_yi"),
    }


def build_catalog(quantx_dir: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    if quantx_dir.exists():
        for date_dir in sorted(quantx_dir.iterdir()):
            if not date_dir.is_dir() or not date_dir.name.isdigit() or len(date_dir.name) != 8:
                continue
            status = read_json(date_dir / "_pipeline_status.json", {}) or {}
            computed = (date_dir / "_computed.json").is_file()
            if not computed and not status:
                continue
            stage = status.get("status") or ("data_only" if computed else "pending")
            theme_data = read_json(date_dir / "theme_snapshot.json", {}) or {}
            themes = theme_data.get("themes", [])[:5]
            records.append({
                "trade_date": date_dir.name,
                "stage": stage,
                "metrics": _metrics(date_dir),
                "themes": themes,
                "run_id": status.get("run_id"),
                "errors": status.get("errors", []),
                "warnings": status.get("warnings", []),
                "multiday_available": (date_dir / "multiday_snapshot.json").is_file(),
                "artifacts": {name: ("_computed.json" if name == "_computed" else f"{name}.json") for name in PUBLIC_ARTIFACTS if (date_dir / ("_computed.json" if name == "_computed" else f"{name}.json")).is_file()},
            })
    records.sort(key=lambda item: item["trade_date"])
    for index, record in enumerate(records):
        previous = records[index - 1]["metrics"] if index else {}
        deltas = {}
        for key in ("market_heat_score", "short_term_sentiment_score", "trend_sentiment_score", "limit_up_count", "seal_rate", "advance_rate", "premium_rate"):
            current, old = record["metrics"].get(key), previous.get(key)
            if isinstance(current, (int, float)) and isinstance(old, (int, float)):
                deltas[key] = round(current - old, 2)
        record["deltas"] = deltas
        record["change_summary"] = ";".join(f"{key}:{value:+g}" for key, value in deltas.items()) or ("首日" if index == 0 else "持平")
    stats = {
        "total_dates": len(records),
        "complete": sum(r["stage"] == "complete" for r in records),
        "degraded": sum(r["stage"] == "degraded" for r in records),
        "failed": sum(r["stage"] == "failed" for r in records),
        "data_only": sum(r["stage"] == "data_only" for r in records),
    }
    return {"schema_version": 2, "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "llm": False, "stats": stats, "records": records}


def build_and_save_catalog(quantx_dir: Path) -> dict[str, Any]:
    catalog = build_catalog(quantx_dir)
    write_json_atomic(quantx_dir / "catalog.json", catalog)
    return catalog


def load_tables(quantx_dir: Path, trade_date: str) -> dict[str, Any]:
    validate_trade_date(trade_date)
    date_dir = quantx_dir / trade_date
    if not date_dir.is_dir():
        raise FileNotFoundError(trade_date)
    result: dict[str, Any] = {"trade_date": trade_date}
    for name in sorted(PUBLIC_ARTIFACTS):
        payload = read_json(date_dir / f"{name}.json")
        if payload is not None:
            result[name] = payload
    result["quality"] = read_json(date_dir / "_pipeline_status.json", {}) or {}
    result["manifest"] = read_json(date_dir / "_data_manifest.json", {}) or {}
    return result


def load_artifact(quantx_dir: Path, trade_date: str, artifact: str) -> Any:
    validate_trade_date(trade_date)
    name = artifact.removesuffix(".json")
    if name not in PUBLIC_ARTIFACTS:
        raise KeyError(artifact)
    path = quantx_dir / trade_date / f"{name}.json"
    payload = read_json(path)
    if payload is None:
        raise FileNotFoundError(artifact)
    return payload
