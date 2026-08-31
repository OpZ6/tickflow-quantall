"""Real-data advanced chart snapshot for the QuantX review dashboard."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import polars as pl

from app.market_facts.registry import DatasetId, get_route

SCHEMA_VERSION = "tickflow-quantx-advanced-v1"
CARD_KEYS = (
    "sentiment_phase",
    "liquidity_participation",
    "state_transition",
    "sector_diffusion",
    "theme_river",
    "promotion_funnel",
    "anomaly_calendar",
    "return_distribution",
    "advance_decline",
    "turnover_lorenz",
    "industry_correlation",
    "mainline_waterfall",
    "theme_ladder_sunburst",
    "rps_rotation_clock",
    "turnover_return_density",
)


def _round(value: Any, digits: int = 2) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits) if math.isfinite(number) else None


def _empty_card(reason: str = "该日期没有足够的标准事实") -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, "data": {}}


def _card(data: dict[str, Any], *, rows: int, note: str | None = None) -> dict[str, Any]:
    if not data or rows <= 0:
        return _empty_card()
    result: dict[str, Any] = {"status": "ok", "rows": rows, "data": data}
    if note:
        result["note"] = note
    return result


def _read_range(root: Path, dataset: str, start: date, end: date) -> pl.DataFrame:
    paths = [
        path
        for path in (root / dataset).glob("date=*/part.parquet")
        if start.isoformat() <= path.parent.name.removeprefix("date=") <= end.isoformat()
    ]
    if not paths:
        return pl.DataFrame()
    frames = [pl.read_parquet(path) for path in sorted(paths)]
    return pl.concat(frames, how="diagonal_relaxed")


def _history_dates(root: Path, dataset: str, end: date, limit: int) -> list[date]:
    values: list[date] = []
    for path in (root / dataset).glob("date=*/part.parquet"):
        try:
            day = date.fromisoformat(path.parent.name.removeprefix("date="))
        except ValueError:
            continue
        if day <= end:
            values.append(day)
    return sorted(set(values))[-limit:]


def _regime_history(root: Path, end: date) -> pl.DataFrame:
    path = root / "regime_history" / "part.parquet"
    if not path.is_file():
        return pl.DataFrame()
    frame = pl.read_parquet(path)
    return frame.filter(pl.col("date") <= end).sort("date")


def _state_transition(frame: pl.DataFrame) -> dict[str, Any]:
    states = ["weak", "lean_weak", "range", "lean_strong", "strong"]
    labels = ["弱势", "偏弱", "震荡", "偏强", "强势"]
    counts = [[0 for _ in states] for _ in states]
    if not frame.is_empty() and "state" in frame.columns:
        sequence = [str(value) for value in frame.sort("date")["state"].to_list()]
        index = {value: idx for idx, value in enumerate(states)}
        for previous, current in pairwise(sequence):
            if previous in index and current in index:
                counts[index[previous]][index[current]] += 1
    matrix = []
    for row in counts:
        total = sum(row)
        matrix.append([round(value * 100 / total, 1) if total else 0.0 for value in row])
    return {
        "states": states,
        "labels": labels,
        "matrix": matrix,
        "counts": counts,
        "visual_max": 50.0,
    }


def _gini_lorenz(values: list[float]) -> dict[str, Any]:
    positive = sorted(value for value in values if math.isfinite(value) and value >= 0)
    if not positive or sum(positive) <= 0:
        return {"gini": None, "points": []}
    total = sum(positive)
    cumulative = 0.0
    points = [{"population_pct": 0.0, "amount_pct": 0.0}]
    area = 0.0
    previous_x = previous_y = 0.0
    for index, value in enumerate(positive, start=1):
        cumulative += value
        x = index / len(positive)
        y = cumulative / total
        area += (y + previous_y) * (x - previous_x) / 2
        points.append({"population_pct": round(x * 100, 2), "amount_pct": round(y * 100, 2)})
        previous_x, previous_y = x, y
    return {"gini": round(1 - 2 * area, 4), "points": points}


def _mean_lorenz_points(curves: list[list[dict[str, float]]]) -> list[dict[str, float]]:
    if not curves:
        return []
    points = []
    for population_pct in range(101):
        values = []
        for curve in curves:
            position = population_pct / 100 * (len(curve) - 1)
            left = math.floor(position)
            right = math.ceil(position)
            fraction = position - left
            amount_pct = curve[left]["amount_pct"]
            if right != left:
                amount_pct += (curve[right]["amount_pct"] - amount_pct) * fraction
            values.append(amount_pct)
        points.append(
            {
                "population_pct": float(population_pct),
                "amount_pct": round(sum(values) / len(values), 2),
            }
        )
    return points


def _turnover_lorenz(
    returns: pl.DataFrame,
    end: date,
    *,
    period_days: int = 20,
) -> dict[str, Any]:
    if returns.is_empty() or not {"date", "amount"}.issubset(returns.columns):
        return {}
    current = _gini_lorenz(
        returns.filter(pl.col("date") == end)["amount"].drop_nulls().to_list()
    )
    if not current["points"]:
        return {}

    baseline_dates = sorted(
        day for day in returns["date"].drop_nulls().unique().to_list() if day < end
    )[-period_days:]
    baselines = []
    for day in baseline_dates:
        curve = _gini_lorenz(
            returns.filter(pl.col("date") == day)["amount"].drop_nulls().to_list()
        )
        if curve["points"]:
            baselines.append((day, curve))

    result = dict(current)
    if baselines:
        previous_date, previous = baselines[-1]
        result["previous"] = {"date": str(previous_date), **previous}
        result["period_mean"] = {
            "days": len(baselines),
            "start_date": str(baselines[0][0]),
            "end_date": str(baselines[-1][0]),
            "gini": round(
                sum(float(curve["gini"]) for _, curve in baselines) / len(baselines),
                4,
            ),
            "points": _mean_lorenz_points(
                [curve["points"] for _, curve in baselines]
            ),
        }
    return result


def _stock_returns(
    root: Path,
    end: date,
    days: int = 35,
    repo: Any = None,
) -> pl.DataFrame:
    dates = _history_dates(root, "kline_daily_enriched", end, days + 1)
    if len(dates) < 2:
        return pl.DataFrame()
    required = {"symbol", "date", "close", "amount", "turnover_rate"}
    frame = None
    get_enriched_range = getattr(repo, "get_enriched_range", None)
    if callable(get_enriched_range):
        frame = get_enriched_range(dates[0], dates[-1], columns=sorted(required))
    if frame is None:
        frame = _read_range(root, "kline_daily_enriched", dates[0], dates[-1])
    if frame.is_empty() or not required.issubset(frame.columns):
        return pl.DataFrame()
    return (
        frame.select(sorted(required))
        .sort(["symbol", "date"])
        .with_columns((pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("return"))
    )


def _sentiment_phase(state: pl.DataFrame) -> dict[str, Any]:
    points = []
    for row in state.to_dicts():
        points.append(
            {
                "date": str(row.get("trade_date")),
                "x": _round(row.get("trend_sentiment_score")),
                "y": _round(row.get("short_term_sentiment_score")),
                "size": row.get("limit_up_count"),
                "heat": _round(row.get("market_heat_score")),
                "zone": row.get("market_heat_zone"),
            }
        )
    return {"points": points}


def _liquidity_participation(state: pl.DataFrame, liquidity: pl.DataFrame) -> dict[str, Any]:
    if state.is_empty() or liquidity.is_empty():
        return {}
    joined = state.join(liquidity, on="trade_date", how="inner", suffix="_liq")
    amounts = joined["total_amount_yi_liq"].drop_nulls().to_list()
    amount_mid = float(pl.Series(amounts).median()) if amounts else None
    points = [
        {
            "date": str(row["trade_date"]),
            "x": _round(row.get("total_amount_yi_liq")),
            "y": _round(row.get("up_ratio_pct")),
            "size": row.get("limit_up_count"),
            "heat": _round(row.get("market_heat_score")),
        }
        for row in joined.to_dicts()
    ]
    return {"points": points, "amount_mid": _round(amount_mid), "participation_mid": 50.0}


def _sector_diffusion(frame: pl.DataFrame) -> dict[str, Any]:
    if frame.is_empty():
        return {}
    views: dict[str, Any] = {}
    for dimension, label in (
        ("sw_level1", "申万一级"),
        ("sw_level2", "申万二级"),
    ):
        scoped = frame.filter(pl.col("dimension") == dimension)
        if scoped.is_empty():
            continue
        dates = sorted(scoped["trade_date"].unique().to_list())[-30:]
        scoped = scoped.filter(pl.col("trade_date").is_in(dates))
        latest = scoped.filter(pl.col("trade_date") == dates[-1]).sort(
            "above_ma20_pct", descending=True
        )
        sectors = latest["sector_name"].to_list()
        metrics: dict[str, list[list[float | None]]] = {}
        for window in (5, 10, 20):
            column = f"above_ma{window}_pct"
            lookup = {
                (str(row["trade_date"]), row["sector_name"]): _round(row[column])
                for row in scoped.select(["trade_date", "sector_name", column]).to_dicts()
            }
            metrics[str(window)] = [
                [lookup.get((str(day), sector)) for day in dates]
                for sector in sectors
            ]
        views[dimension] = {
            "label": label,
            "dates": [str(day) for day in dates],
            "sectors": sectors,
            "metrics": metrics,
        }
    if not views:
        return {}
    default = views.get("sw_level1") or next(iter(views.values()))
    return {
        "dates": default["dates"],
        "views": views,
        "default_dimension": "sw_level1" if "sw_level1" in views else next(iter(views)),
        "default_window": 20,
        # Additive compatibility fields for existing v1 consumers.
        "sectors": default["sectors"],
        "values": default["metrics"]["20"],
        "metric": "above_ma20_pct",
    }


def _theme_river(frame: pl.DataFrame) -> dict[str, Any]:
    if frame.is_empty():
        return {}
    dates = sorted(frame["trade_date"].unique().to_list())[-20:]
    recent = frame.filter(pl.col("trade_date").is_in(dates))
    source = None
    if "source" in recent.columns:
        coverage = {
            str(row["source"]): int(row["days"])
            for row in recent.group_by("source")
            .agg(pl.col("trade_date").n_unique().alias("days"))
            .to_dicts()
        }
        priority = list(get_route(DatasetId.THEME_OBSERVATION_DAILY).sources)
        source = min(
            coverage,
            key=lambda value: (-coverage[value], priority.index(value) if value in priority else len(priority)),
        )
        recent = recent.filter(pl.col("source") == source)
    daily = (
        recent.with_columns(pl.col("rank").cast(pl.Float64, strict=False))
        .group_by(["trade_date", "theme_name"])
        .agg(pl.col("rank").min().alias("rank"))
    )
    top = (
        daily.group_by("theme_name")
        .agg(pl.col("rank").mean().alias("avg_rank"), pl.len().alias("days"))
        .sort(["days", "avg_rank"], descending=[True, False])
        .head(10)["theme_name"].to_list()
    )
    daily = daily.filter(pl.col("theme_name").is_in(top))
    lookup = {
        (str(row["trade_date"]), row["theme_name"]): _round(row["rank"], 0)
        for row in daily.to_dicts()
    }
    return {
        "dates": [str(day) for day in dates],
        "themes": top,
        "values": [[lookup.get((str(day), theme)) for day in dates] for theme in top],
        "metric": "rank",
        "source": source,
        "rank_max": max((value for value in lookup.values() if value is not None), default=1),
    }


def _promotion_funnel(frame: pl.DataFrame, events: pl.DataFrame | None = None) -> dict[str, Any]:
    if frame.is_empty() and (events is None or events.is_empty()):
        return {}
    events = events if events is not None else pl.DataFrame()
    dates = sorted(
        set(frame["trade_date"].unique().to_list() if not frame.is_empty() else [])
        | set(events["trade_date"].unique().to_list() if not events.is_empty() else [])
    )
    by_day = {
        day: {str(row["symbol"]).split(".")[0]: int(row["board_height"]) for row in frame.filter(pl.col("trade_date") == day).to_dicts()}
        for day in dates
    }
    event_by_day: dict[date, list[dict[str, Any]]] = {
        day: events.filter(pl.col("trade_date") == day).to_dicts()
        for day in dates
    } if not events.is_empty() else {}
    max_height = int(frame["board_height"].max() or 0) if not frame.is_empty() else 0
    observations: dict[date, dict[str, tuple[int, int]]] = {}
    for previous, current in pairwise(dates):
        previous_symbols = set(by_day.get(previous, {}))
        current_rows = event_by_day.get(current, [])
        sealed = {
            str(row["symbol"]).split(".")[0]
            for row in current_rows
            if row.get("event_type") == "limit_up" and int(row.get("board_height") or 1) == 1
        }
        if not sealed:
            sealed = {symbol for symbol, height in by_day.get(current, {}).items() if height == 1}
        broken_first_attempts = {
            str(row["symbol"]).split(".")[0]
            for row in current_rows
            if row.get("event_type") == "broken_board"
            and (
                int(row["board_height"]) == 1
                if row.get("board_height") is not None
                else str(row["symbol"]).split(".")[0] not in previous_symbols
            )
        }
        daily = {
            "first": (len(sealed | broken_first_attempts), len(sealed)),
        }
        for height in range(1, max_height + 1):
            candidates = {
                symbol
                for symbol, value in by_day.get(previous, {}).items()
                if value == height
            }
            daily[str(height)] = (
                len(candidates),
                sum(
                    1
                    for symbol in candidates
                    if by_day.get(current, {}).get(symbol, 0) >= height + 1
                ),
            )
        observations[current] = daily

    evaluation_dates = sorted(observations)
    stage_specs = [
        ("first", "0→1 首板封板", "same_day_seal"),
        *[
            (str(height), f"{height}→{height + 1}", "next_trade_day_promotion")
            for height in range(1, max_height + 1)
        ],
    ]

    def aggregate(selected_dates: list[date], *, keep_empty: bool = False) -> dict[str, Any]:
        stages = []
        for key, name, basis in stage_specs:
            pool = sum(observations[day][key][0] for day in selected_dates)
            promoted = sum(observations[day][key][1] for day in selected_dates)
            if not pool and not keep_empty:
                continue
            stages.append(
                {
                    "name": name,
                    "pool": pool,
                    "promoted": promoted,
                    "failed": pool - promoted,
                    "rate": round(promoted * 100 / pool, 1) if pool else None,
                    "basis": basis,
                }
            )
        return {
            "stages": stages,
            "sample_days": len(selected_dates),
            "start_date": str(selected_dates[0]) if selected_dates else None,
            "end_date": str(selected_dates[-1]) if selected_dates else None,
        }

    global_view = aggregate(evaluation_dates)
    visible_names = {row["name"] for row in global_view["stages"]}
    stage_specs = [spec for spec in stage_specs if spec[1] in visible_names]

    def window_view(size: int, label: str) -> dict[str, Any]:
        selected = evaluation_dates[-size:]
        return {"label": label, **aggregate(selected, keep_empty=True)}

    current_dates = evaluation_dates[-1:] if evaluation_dates else []
    views = {
        "current": {"label": "当天", **aggregate(current_dates, keep_empty=True)},
        "5": window_view(5, "5日均值"),
        "20": window_view(20, "20日均值"),
    }
    return {
        # Compatibility fields keep existing consumers on the full-sample result.
        "stages": global_view["stages"],
        "sample_days": len(dates),
        "max_observed_board": max_height,
        "default_view": "current",
        "views": views,
        "baseline": {"label": "全样本基线", **global_view},
        "aggregation": "sample_weighted_rate",
    }


def _anomaly_calendar(regime: pl.DataFrame) -> dict[str, Any]:
    if regime.is_empty():
        return {}
    columns = [name for name in ("index_pct", "up_count", "limit_up", "total_amount") if name in regime.columns]
    scored = regime
    z_columns = []
    for name in columns:
        std = float(regime[name].std() or 0)
        mean = float(regime[name].mean() or 0)
        alias = f"_{name}_z"
        z_columns.append(alias)
        scored = scored.with_columns(((pl.col(name) - mean) / std if std else pl.lit(0.0)).alias(alias))
    scored = scored.with_columns(pl.max_horizontal([pl.col(name).abs() for name in z_columns]).alias("anomaly"))
    latest_day = scored["date"].max()
    year_start = date(latest_day.year, 1, 1)
    recent = scored.filter(pl.col("date") >= year_start)
    rows = [
        {"date": str(row["date"]), "value": _round(row["anomaly"]), "return_pct": _round(float(row.get("index_pct") or 0) * 100), "state": row.get("state")}
        for row in recent.to_dicts()
        if row["date"].weekday() < 5
    ]
    return {"records": rows, "start_date": str(year_start), "end_date": str(latest_day)}


def _return_distribution(returns: pl.DataFrame, end: date) -> dict[str, Any]:
    if returns.is_empty():
        return {}
    latest = returns.filter(pl.col("date") == end).drop_nulls("return")
    if latest.is_empty():
        return {}
    values = (latest["return"] * 100).clip(-11, 21).to_list()
    edges = [-11, -8, -5, -3, -1, 0, 1, 3, 5, 8, 11, 21]
    edge_pairs = list(pairwise(edges))
    counts = [sum(1 for value in values if left <= value < right) for left, right in edge_pairs]
    return {
        "bins": [f"{left}~{right}%" for left, right in edge_pairs],
        "counts": counts,
        "median": _round(pl.Series(values).median()),
        "positive_pct": _round(sum(value > 0 for value in values) * 100 / len(values)),
        "sample": len(values),
    }


def _advance_decline(root: Path, breadth: pl.DataFrame, end: date) -> dict[str, Any]:
    if breadth.is_empty():
        return {}
    rows = breadth.sort("trade_date").with_columns(pl.col("advance_decline").cum_sum().alias("ad_line"))
    start = rows["trade_date"].min()
    indexes = _read_range(root, "kline_index_daily", start, end)
    index_rows = pl.DataFrame()
    if not indexes.is_empty():
        for symbol in ("000985.SH", "000001.SH"):
            candidate = indexes.filter(pl.col("symbol") == symbol).sort("date")
            if not candidate.is_empty():
                index_rows = candidate
                break
    closes = {str(row["date"]): _round(row["close"]) for row in index_rows.to_dicts()}
    dates = [str(value) for value in rows["trade_date"].to_list()]
    ad_line = [_round(value) for value in rows["ad_line"].to_list()]
    index_close = [closes.get(value) for value in dates]
    return {
        "dates": dates,
        "ad_line": ad_line,
        "index_close": index_close,
        "index_symbol": index_rows["symbol"][0] if not index_rows.is_empty() else None,
        "divergences": _detect_ad_divergences(dates, ad_line, index_close),
        "divergence_window": 5,
    }


def _detect_ad_divergences(
    dates: list[str],
    ad_line: list[float | None],
    index_close: list[float | None],
    *,
    window: int = 5,
) -> list[dict[str, Any]]:
    """Find sustained five-session direction disagreements between breadth and index."""
    signals: list[tuple[int, str]] = []
    for index in range(window, min(len(dates), len(ad_line), len(index_close))):
        current_ad, previous_ad = ad_line[index], ad_line[index - window]
        current_close, previous_close = index_close[index], index_close[index - window]
        if None in (current_ad, previous_ad, current_close, previous_close) or not previous_close:
            continue
        ad_change = float(current_ad) - float(previous_ad)
        index_change_pct = (float(current_close) / float(previous_close) - 1) * 100
        if index_change_pct >= 0.5 and ad_change < 0:
            signals.append((index, "bearish"))
        elif index_change_pct <= -0.5 and ad_change > 0:
            signals.append((index, "bullish"))

    periods: list[dict[str, Any]] = []
    for index, kind in signals:
        if periods and periods[-1]["type"] == kind and index <= periods[-1]["_last_index"] + 1:
            periods[-1]["end_date"] = dates[index]
            periods[-1]["_last_index"] = index
            continue
        periods.append(
            {
                "start_date": dates[max(0, index - window)],
                "end_date": dates[index],
                "type": kind,
                "label": "指数强、广度弱" if kind == "bearish" else "指数弱、广度强",
                "_last_index": index,
            }
        )
    for period in periods:
        period.pop("_last_index", None)
    return periods


def _industry_daily_returns(returns: pl.DataFrame, repo: Any) -> pl.DataFrame:
    if returns.is_empty() or repo is None:
        return pl.DataFrame()
    try:
        from app.services.rps_rotation import _load_concept_map_df

        loaded = _load_concept_map_df(repo, "industry")
        mapping = loaded[0] if isinstance(loaded, tuple) else loaded
    except (ImportError, OSError, ValueError):
        return pl.DataFrame()
    if mapping.is_empty() or "industry" not in mapping.columns:
        return pl.DataFrame()
    joined = returns.drop_nulls("return").with_columns(pl.col("symbol").str.to_uppercase().alias("_sym_up")).join(mapping, on="_sym_up", how="inner")
    if joined.is_empty():
        return pl.DataFrame()
    parts = pl.col("industry").str.split("-")
    level1 = joined.with_columns(
        pl.lit("industry_level1").alias("dimension"),
        parts.list.first().alias("industry"),
    )
    level2 = (
        joined.with_columns(
            pl.lit("industry_level2").alias("dimension"),
            parts.list.get(1, null_on_oob=True).alias("industry"),
        )
        .filter(pl.col("industry").is_not_null() & (pl.col("industry") != ""))
    )
    return (
        pl.concat([level1, level2], how="diagonal_relaxed")
        .group_by(["date", "dimension", "industry"])
        .agg(pl.col("return").mean().alias("return"))
        .sort(["date", "dimension", "industry"])
    )


def _industry_correlation(daily: pl.DataFrame) -> dict[str, Any]:
    if daily.is_empty():
        return {}
    views: dict[str, Any] = {}
    scopes = (
        ("industry_level1", "同花顺一级"),
        ("industry_level2", "同花顺二级"),
    )
    for dimension, label in scopes:
        scoped = daily.filter(pl.col("dimension") == dimension)
        if scoped.is_empty():
            continue
        counts = scoped.group_by("industry").len().sort(
            ["len", "industry"], descending=[True, False]
        )
        names = counts["industry"].to_list()
        pivot = (
            scoped.filter(pl.col("industry").is_in(names))
            .pivot(on="industry", index="date", values="return")
            .sort("date")
        )
        matrix = []
        pairs = []
        for left_index, left in enumerate(names):
            row = []
            for right_index, right in enumerate(names):
                if left == right:
                    row.append(1.0)
                    continue
                pair = pivot.select(
                    pl.col(left).alias("left"), pl.col(right).alias("right")
                ).drop_nulls()
                corr = (
                    pair.select(pl.corr("left", "right")).item()
                    if pair.height >= 3
                    else None
                )
                rounded = _round(corr, 3)
                row.append(rounded)
                if right_index > left_index and rounded is not None:
                    pairs.append(
                        {
                            "left": left,
                            "right": right,
                            "correlation": rounded,
                            "sample_days": pair.height,
                        }
                    )
            matrix.append(row)
        highest = sorted(
            pairs,
            key=lambda item: (-item["correlation"], item["left"], item["right"]),
        )[:8]
        lowest = sorted(
            pairs,
            key=lambda item: (item["correlation"], item["left"], item["right"]),
        )[:8]
        views[dimension] = {
            "label": label,
            "industries": names,
            "matrix": matrix,
            "sample_days": pivot.height,
            "pair_rankings": {"highest": highest, "lowest": lowest},
        }
    if not views:
        return {}
    default_dimension = (
        "industry_level1" if "industry_level1" in views else next(iter(views))
    )
    default = views[default_dimension]
    return {
        "views": views,
        "default_dimension": default_dimension,
        # Additive compatibility fields for existing v1 consumers.
        **default,
    }


def _mainline_waterfall(root: Path, end: date) -> dict[str, Any]:
    path = root / "mainline_history" / "part.parquet"
    if not path.is_file():
        return {}
    frame = pl.read_parquet(path).filter((pl.col("date") <= end) & (pl.col("kind") == "concept"))
    if frame.is_empty():
        return {}
    latest_day = frame["date"].max()
    latest = frame.filter(pl.col("date") == latest_day)
    weights = {
        "limit_up_count": ("涨停广度", 0.35),
        "max_boards": ("连板高度", 0.25),
        "rungs_filled": ("梯队完整", 0.25),
        "ge2_count": ("二板以上", 0.15),
    }
    denominator = max(latest.height - 1, 1)
    latest = latest.with_columns(
        [
            ((pl.col(column).rank(method="average") - 1) / denominator).alias(f"_{column}_norm")
            for column in weights
        ]
    )
    mainlines = []
    for row in latest.sort("rank").to_dicts():
        components = [
            {
                "name": label,
                "value": _round(
                    100 * weight * float(row[f"_{column}_norm"] or 0)
                ),
                "raw": row[column],
            }
            for column, (label, weight) in weights.items()
        ]
        mainlines.append(
            {
                "focus": row["member"],
                "rank": int(row["rank"]),
                "score": _round(row["score"]),
                "leader_symbol": row.get("leader_symbol"),
                "components": components,
            }
        )
    leader = mainlines[0]
    return {
        "trade_date": str(latest_day),
        # Compatibility fields keep existing consumers on the first-ranked mainline.
        "focus": leader["focus"],
        "score": leader["score"],
        "components": leader["components"],
        "mainlines": mainlines,
    }


def _sunburst(ladder: pl.DataFrame, end: date) -> dict[str, Any]:
    latest = ladder.filter(pl.col("trade_date") == end)
    if latest.is_empty():
        return {}
    themes: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in latest.to_dicts():
        theme = str(row.get("theme_name") or "其他")
        themes[theme][int(row.get("board_height") or 1)].append(str(row.get("name") or row.get("symbol")))
    ranked = sorted(themes.items(), key=lambda item: -sum(len(values) for values in item[1].values()))[:8]
    children = []
    for theme, levels in ranked:
        level_nodes = []
        for height, stocks in sorted(levels.items(), reverse=True):
            level_nodes.append(
                {
                    "name": f"{height}板 · {len(stocks)}股",
                    "value": len(stocks),
                    "height": height,
                    "stocks": stocks,
                }
            )
        children.append({"name": theme, "children": level_nodes})
    return {"children": children, "stock_count": latest.height}


def _rotation_clock(daily: pl.DataFrame) -> dict[str, Any]:
    if daily.is_empty():
        return {}
    if "dimension" in daily.columns:
        daily = daily.filter(pl.col("dimension") == "industry_level1")
    if daily.is_empty():
        return {}
    dates = sorted(daily["date"].unique().to_list())
    if len(dates) < 6:
        return {}
    recent_dates = dates[-5:]
    previous_dates = dates[-10:-5] or dates[:-5]
    recent = daily.filter(pl.col("date").is_in(recent_dates)).group_by("industry").agg(pl.col("return").mean().alias("recent"))
    previous = daily.filter(pl.col("date").is_in(previous_dates)).group_by("industry").agg(pl.col("return").mean().alias("previous"))
    joined = recent.join(previous, on="industry", how="inner")
    joined = joined.with_columns(
        (pl.col("recent").rank(method="average") / pl.len() * 100).alias("recent_rps"),
        (pl.col("previous").rank(method="average") / pl.len() * 100).alias("previous_rps"),
    ).with_columns(
        (pl.col("recent_rps") - 50).alias("momentum"),
        (pl.col("recent_rps") - pl.col("previous_rps")).alias("acceleration"),
    )
    rows = [
        {
            "name": row["industry"],
            "momentum": _round(row["momentum"]),
            "acceleration": _round(row["acceleration"]),
            "recent_rps": _round(row["recent_rps"]),
            "recent_return_pct": _round(float(row["recent"]) * 100),
        }
        for row in joined.sort("recent_rps", descending=True).to_dicts()
    ]
    return {
        "points": rows,
        "recent_days": len(recent_dates),
        "previous_days": len(previous_dates),
        "metric": "cross_sectional_rps",
    }


def _density(returns: pl.DataFrame, end: date) -> dict[str, Any]:
    latest = returns.filter(pl.col("date") == end).drop_nulls(["return", "turnover_rate"])
    if latest.is_empty():
        return {}
    x_edges = [0, 1, 2, 3, 5, 8, 12, 20, 35, 60, 100]
    y_edges = [-11, -7, -4, -2, 0, 2, 4, 7, 11, 21]
    bins: Counter[tuple[int, int]] = Counter()
    for row in latest.select(["turnover_rate", "return"]).to_dicts():
        x = float(row["turnover_rate"])
        y = float(row["return"]) * 100
        xi = next((idx for idx, (left, right) in enumerate(pairwise(x_edges)) if left <= x < right), None)
        yi = next((idx for idx, (left, right) in enumerate(pairwise(y_edges)) if left <= y < right), None)
        if xi is not None and yi is not None:
            bins[(xi, yi)] += 1
    values = [
        [x, y, bins.get((x, y), 0)]
        for y in range(len(y_edges) - 1)
        for x in range(len(x_edges) - 1)
    ]
    return {"x_bins": [f"{left}-{right}%" for left, right in pairwise(x_edges)], "y_bins": [f"{left}~{right}%" for left, right in pairwise(y_edges)], "values": values, "sample": latest.height}


def build_advanced_snapshot(root: Path, trade_date: date, repo: Any = None) -> dict[str, Any]:
    """Build all supported advanced cards from Tickflow-owned data only."""
    root = Path(root)
    cards = {key: _empty_card() for key in CARD_KEYS}
    history = _history_dates(root, "market_state_daily", trade_date, 75)
    if not history:
        return {"schema_version": SCHEMA_VERSION, "trade_date": trade_date.strftime("%Y%m%d"), "generated_at": datetime.now(UTC).isoformat(), "cards": cards, "coverage": {"available": 0, "total": len(CARD_KEYS)}}
    start = history[0]
    state = _read_range(root, "market_state_daily", start, trade_date)
    breadth = _read_range(root, "market_breadth_daily", start, trade_date)
    liquidity = _read_range(root, "market_liquidity_daily", start, trade_date)
    events = _read_range(root, "limit_event_daily", start, trade_date)
    ladder = _read_range(root, "limit_ladder_daily", start, trade_date)
    themes = _read_range(root, "theme_observation_daily", start, trade_date)
    sectors = _read_range(root, "sector_breadth_daily", start, trade_date)
    regime = _regime_history(root, trade_date)
    returns = _stock_returns(root, trade_date, repo=repo)
    industry_daily = _industry_daily_returns(returns, repo)

    mainline = _mainline_waterfall(root, trade_date)
    builders = {
        "sentiment_phase": (_sentiment_phase(state), state.height),
        "liquidity_participation": (_liquidity_participation(state, liquidity), min(state.height, liquidity.height)),
        "state_transition": (_state_transition(regime), regime.height),
        "sector_diffusion": (_sector_diffusion(sectors), sectors.height),
        "theme_river": (_theme_river(themes), themes.height),
        "promotion_funnel": (_promotion_funnel(ladder, events), ladder.height + events.height),
        "anomaly_calendar": (_anomaly_calendar(regime), regime.height),
        "return_distribution": (_return_distribution(returns, trade_date), returns.filter(pl.col("date") == trade_date).height if not returns.is_empty() else 0),
        "advance_decline": (_advance_decline(root, breadth, trade_date), breadth.height),
        "turnover_lorenz": (_turnover_lorenz(returns, trade_date), returns.filter(pl.col("date") == trade_date).height if not returns.is_empty() else 0),
        "industry_correlation": (_industry_correlation(industry_daily), industry_daily.height),
        "mainline_waterfall": (mainline, len(mainline.get("mainlines", []))),
        "theme_ladder_sunburst": (_sunburst(ladder, trade_date), ladder.filter(pl.col("trade_date") == trade_date).height if not ladder.is_empty() else 0),
        "rps_rotation_clock": (_rotation_clock(industry_daily), industry_daily.height),
        "turnover_return_density": (_density(returns, trade_date), returns.filter(pl.col("date") == trade_date).height if not returns.is_empty() else 0),
    }
    industry_membership_note = "行业收益按当前行业成分回看历史计算,不是历史时点成分;越接近当前日期越可靠。"
    mainline_membership_note = "主线历史按当前概念成分回看历史计算,不是历史时点成分;越接近当前日期越可靠。"
    for key, (data, rows) in builders.items():
        note = (
            industry_membership_note
            if key in {"industry_correlation", "rps_rotation_clock"}
            else mainline_membership_note
            if key == "mainline_waterfall"
            else None
        )
        cards[key] = _card(data, rows=rows, note=note)
    available = sum(card["status"] == "ok" for card in cards.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": trade_date.strftime("%Y%m%d"),
        "generated_at": datetime.now(UTC).isoformat(),
        "cards": cards,
        "coverage": {"available": available, "total": len(CARD_KEYS), "history_start": str(start), "history_end": str(history[-1])},
    }
