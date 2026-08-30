"""Pure calculations and repository adapters for the prototype market lab."""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from statistics import fmean
from typing import Any

import polars as pl

from app.market_facts.registry import DatasetId, get_route


def _pct(now: float, before: float) -> float:
    return (now / before - 1) * 100 if before else 0.0


def _period_return(closes: list[float], period: int, offset: int = 0) -> float | None:
    end = len(closes) - 1 - offset
    start = end - period
    if start < 0 or end < 0:
        return None
    return _pct(closes[end], closes[start])


def _slope_momentum(closes: list[float], window: int = 20, offset: int = 0) -> float | None:
    end = len(closes) - offset
    values = closes[max(0, end - window):end]
    if len(values) < window or any(v <= 0 for v in values):
        return None
    ys = [math.log(v) for v in values]
    xs = list(range(len(ys)))
    x_bar, y_bar = fmean(xs), fmean(ys)
    denom = sum((x - x_bar) ** 2 for x in xs)
    slope = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys, strict=True)) / denom
    fitted = [y_bar + slope * (x - x_bar) for x in xs]
    ss_tot = sum((y - y_bar) ** 2 for y in ys)
    ss_res = sum((y - fit) ** 2 for y, fit in zip(ys, fitted, strict=True))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return (math.exp(slope * 252) - 1) * 100 * max(0.0, r2)


def _momentum_row(symbol: str, frame: pl.DataFrame, name: str, offset: int = 0) -> dict[str, Any] | None:
    if frame.is_empty() or "close" not in frame.columns:
        return None
    frame = frame.sort("date")
    closes = [float(v) for v in frame["close"].to_list() if v is not None]
    volumes = [float(v or 0) for v in frame.get_column("volume").to_list()] if "volume" in frame.columns else []
    required = {p: _period_return(closes, p, offset) for p in (1, 5, 20, 50)}
    if any(v is None for v in required.values()):
        return None
    end = len(volumes) - offset
    vol5 = fmean(volumes[max(0, end - 5):end]) if end >= 5 else 0.0
    vol20 = fmean(volumes[max(0, end - 20):end]) if end >= 20 else 0.0
    weighted = required[1] * 0.4 + required[5] * 0.3 + required[20] * 0.2 + required[50] * 0.1
    return {
        "symbol": symbol,
        "name": name or symbol,
        "as_of": str(frame["date"][len(frame) - 1 - offset])[:10],
        "return_1d_pct": required[1],
        "return_5d_pct": required[5],
        "return_20d_pct": required[20],
        "return_50d_pct": required[50],
        "weighted_momentum_pct": weighted,
        "slope_momentum_pct": _slope_momentum(closes, offset=offset),
        "volume_ratio_5_20": vol5 / vol20 if vol20 else None,
    }


def build_etf_momentum(
    frames: dict[str, pl.DataFrame], names: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    names = names or {}
    current = [
        row for symbol, frame in frames.items()
        if (row := _momentum_row(symbol, frame, names.get(symbol, symbol))) is not None
    ]
    previous = {
        symbol: row for symbol, frame in frames.items()
        if (row := _momentum_row(symbol, frame, names.get(symbol, symbol), offset=1)) is not None
    }
    current.sort(key=lambda row: row["weighted_momentum_pct"], reverse=True)
    previous_rank = {
        row["symbol"]: rank
        for rank, row in enumerate(
            sorted(previous.values(), key=lambda item: item["weighted_momentum_pct"], reverse=True), 1
        )
    }
    for rank, row in enumerate(current, 1):
        old = previous.get(row["symbol"])
        row["rank"] = rank
        row["previous_rank"] = previous_rank.get(row["symbol"])
        row["rank_change"] = (
            previous_rank[row["symbol"]] - rank if row["symbol"] in previous_rank else None
        )
        row["momentum_change_pct"] = (
            row["weighted_momentum_pct"] - old["weighted_momentum_pct"] if old else None
        )
    return current


def compute_dispersion(returns_pct: dict[str, float]) -> dict[str, Any]:
    if not returns_pct:
        return {"mean_pct": 0.0, "dispersion": 0.0, "contributions": []}
    mean = fmean(returns_pct.values())
    squares = {name: (value - mean) ** 2 for name, value in returns_pct.items()}
    total = sum(squares.values())
    contributions = [
        {
            "name": name,
            "return_pct": returns_pct[name],
            "signed_deviation": returns_pct[name] - mean,
            "share": value / total if total else 0.0,
        }
        for name, value in squares.items()
    ]
    contributions.sort(key=lambda row: row["share"], reverse=True)
    return {"mean_pct": mean, "dispersion": math.sqrt(total), "contributions": contributions}


def calculate_position(
    *, balance: float, risk_pct: float, entry: float, stop: float,
    target: float | None = None, mode: str = "brave", trade_type: str = "B1",
) -> dict[str, Any]:
    ratios = {
        "B1": {"brave": (10.0, 4.0), "sensitive": (6.0, 2.5)},
        "B2": {"brave": (5.0, 1.0), "sensitive": (3.0, 2.0)},
    }
    if trade_type not in ratios or mode not in ratios[trade_type]:
        raise ValueError("trade_type must be B1/B2 and mode brave/sensitive")
    per_share = entry - stop
    if min(balance, entry, stop) <= 0 or per_share <= 0 or not 0 < risk_pct <= 1:
        raise ValueError("balance/prices must be positive and risk_pct must be in (0, 1]")
    risk_budget = balance * risk_pct
    risk_shares = math.floor(risk_budget / per_share / 100) * 100
    cash_shares = math.floor(balance / entry / 100) * 100
    shares = max(0, min(risk_shares, cash_shares))
    planned_loss = shares * per_share
    target_r, breakeven_r = ratios[trade_type][mode]
    target_price = target if target is not None else entry + per_share * target_r
    if target_price <= entry:
        raise ValueError("target must be above entry for a long position")
    breakeven_price = entry + per_share * breakeven_r
    risk_percent_value = risk_pct * 100
    if mode == "brave":
        risk_level = (
            "保守" if risk_percent_value <= 1 else
            "稳健" if risk_percent_value <= 2 else
            "积极" if risk_percent_value <= 3 else
            "重仓" if risk_percent_value <= 4 else "激进"
        )
    else:
        risk_level = (
            "敏感" if risk_percent_value <= 0.5 else
            "保守" if risk_percent_value <= 1 else
            "稳健" if risk_percent_value <= 1.5 else
            "适中" if risk_percent_value <= 1.95 else "积极"
        )
    capital_usage_pct = shares * entry / balance * 100
    stop_pct = per_share / entry * 100
    target_upside_pct = (target_price / entry - 1) * 100
    warnings: list[str] = []
    if mode == "sensitive" and capital_usage_pct > 25:
        warnings.append("敏感模式下资金利用率超过 25%, 仓位偏重")
    if capital_usage_pct > 50:
        warnings.append("资金利用率超过 50%, 注意风险敞口")
    if stop_pct > 10:
        warnings.append("止损幅度超过 10%, 请重新核对止损位置")
    if target_upside_pct > 50:
        warnings.append("目标涨幅超过 50%, 请核对预期是否合理")
    return {
        "shares": shares,
        "market_value": shares * entry,
        "risk_budget": risk_budget,
        "planned_loss": planned_loss,
        "capital_usage_pct": capital_usage_pct,
        "reward_risk": (target_price - entry) / per_share,
        "target_price": target_price,
        "target_r": target_r,
        "breakeven_price": breakeven_price,
        "breakeven_r": breakeven_r,
        "projected_profit": (target_price - entry) * shares,
        "actual_risk_pct": planned_loss / balance * 100,
        "stop_pct": stop_pct,
        "target_upside_pct": target_upside_pct,
        "risk_level": risk_level,
        "cash_limited": cash_shares < risk_shares,
        "warnings": warnings,
    }


def calculate_pit(*, top: float, bottom: float, current: float) -> dict[str, float]:
    if min(top, bottom, current) <= 0 or bottom >= top:
        raise ValueError("top/current must be positive and bottom must be below top")
    target = top * 2 - bottom
    return {
        "target": target,
        "depth_pct": (top - bottom) / top * 100,
        "upside_pct": (target / current - 1) * 100,
    }


def calculate_drawdown(
    *, entry: float, stop: float, high: float, target_r: float = 10,
    drawdown_pct: float = 0.1,
) -> dict[str, float | bool]:
    if min(entry, stop, high) <= 0 or stop >= entry or high < entry:
        raise ValueError("require 0 < stop < entry <= high")
    if target_r <= 0 or not 0 < drawdown_pct < 1:
        raise ValueError("target_r must be positive and drawdown_pct in (0, 1)")
    risk = entry - stop
    actual_r = (high - entry) / risk
    draw_amount = (high - entry) * drawdown_pct
    exit_price = high - draw_amount
    return {
        "actual_r": actual_r,
        "draw_amount": draw_amount,
        "exit_price": exit_price,
        "max_profit_pct": (high / entry - 1) * 100,
        "locked_profit_pct": (exit_price / entry - 1) * 100,
        "target_achieved": actual_r >= target_r,
    }


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    idx = (len(ordered) - 1) * q
    lo, hi = math.floor(idx), math.ceil(idx)
    return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def _minimum_risk_for_target(
    win_rate: float, reward_ratio: float, annual_trades: int,
    target_return_pct: float, full_kelly: float,
) -> float | None:
    if full_kelly <= 0 or annual_trades <= 0:
        return None
    target_growth = math.log1p(target_return_pct / 100) / annual_trades
    max_growth = (
        win_rate * math.log1p(reward_ratio * full_kelly)
        + (1 - win_rate) * math.log1p(-full_kelly)
    )
    if max_growth < target_growth:
        return None
    low, high = 0.0, full_kelly
    for _ in range(24):
        mid = (low + high) / 2
        growth = (
            win_rate * math.log1p(reward_ratio * mid)
            + (1 - win_rate) * math.log1p(-mid)
        )
        if growth < target_growth:
            low = mid
        else:
            high = mid
    return high


def _drawdown_p80(
    *, win_rate: float, reward_ratio: float, trades: int,
    fraction: float, rng: random.Random, runs: int = 300,
) -> float:
    values: list[float] = []
    for _ in range(runs):
        equity = peak = 1.0
        max_drawdown = 0.0
        for _ in range(trades):
            equity *= 1 + reward_ratio * fraction if rng.random() < win_rate else 1 - fraction
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 1.0)
        values.append(max_drawdown)
    return _quantile(values, 0.8)


def _risk_reverse(
    *, win_rate: float, reward_ratio: float, trades: int,
    full_kelly: float, target_return_pct: float, max_drawdown_pct: float,
    annual_trades: int, seed: int,
) -> dict[str, Any]:
    expectancy = win_rate * reward_ratio - (1 - win_rate)
    if expectancy <= 0 or full_kelly <= 0:
        return {
            "recommended_risk_pct": 0.0, "test_risk_pct": 0.0,
            "target_required_risk_pct": None, "drawdown_risk_pct": 0.0,
            "limiting_factor": "negative_expectancy", "target_reachable": False,
            "target_return_pct": target_return_pct,
        }
    target_required = _minimum_risk_for_target(
        win_rate, reward_ratio, annual_trades, target_return_pct, full_kelly
    )
    rng = random.Random(seed ^ 0x5EED5EED)
    low, high = 0.0, full_kelly
    drawdown_risk = 0.0
    for _ in range(8):
        mid = (low + high) / 2
        if _drawdown_p80(
            win_rate=win_rate, reward_ratio=reward_ratio, trades=trades,
            fraction=mid, rng=rng,
        ) > max_drawdown_pct / 100:
            high = mid
        else:
            low = drawdown_risk = mid
    recommended = min(full_kelly, drawdown_risk)
    return {
        "recommended_risk_pct": recommended * 100,
        "test_risk_pct": recommended * 50,
        "target_required_risk_pct": target_required * 100 if target_required is not None else None,
        "drawdown_risk_pct": drawdown_risk * 100,
        "limiting_factor": "drawdown" if drawdown_risk < full_kelly else "kelly",
        "target_reachable": target_required is not None and recommended >= target_required,
        "target_return_pct": target_return_pct,
    }


def _distribution_bins(values: list[float], count: int = 36) -> list[dict[str, float]]:
    if not values:
        return []
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [{"from": low, "to": high, "count": float(len(values)), "density": 1.0}]
    width = (high - low) / count
    counts = [0] * count
    for value in values:
        index = min(count - 1, int((value - low) / width))
        counts[index] += 1
    return [
        {
            "from": low + index * width,
            "to": low + (index + 1) * width,
            "count": float(value),
            "density": value / len(values),
        }
        for index, value in enumerate(counts)
    ]


def _simulate_strategy(
    *, outcomes: list[list[bool]], balance: float, reward_ratio: float,
    fraction: float, strategy_id: str, name: str, basis: str,
) -> dict[str, Any]:
    paths: list[list[float]] = []
    finals: list[float] = []
    drawdowns: list[float] = []
    ruin_count = halve_count = 0
    for outcomes_path in outcomes:
        equity = peak = balance
        values = [equity]
        max_drawdown = 0.0
        for won in outcomes_path:
            equity = max(0.001, equity * (1 + reward_ratio * fraction if won else 1 - fraction))
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 1.0)
            values.append(equity)
        paths.append(values)
        finals.append(equity)
        drawdowns.append(max_drawdown * 100)
        ruin_count += equity < balance * 0.1
        halve_count += equity < balance * 0.5
    path_length = len(outcomes[0]) + 1 if outcomes else 0
    p10_path: list[float] = []
    median_path: list[float] = []
    p90_path: list[float] = []
    for index in range(path_length):
        column = [path[index] for path in paths]
        p10_path.append(_quantile(column, 0.1))
        median_path.append(_quantile(column, 0.5))
        p90_path.append(_quantile(column, 0.9))
    return {
        "id": strategy_id, "name": name, "basis": basis,
        "risk_pct": fraction * 100,
        "p10_final": _quantile(finals, 0.1), "p50_final": _quantile(finals, 0.5),
        "p90_final": _quantile(finals, 0.9), "p80_drawdown_pct": _quantile(drawdowns, 0.8),
        "p50_drawdown_pct": _quantile(drawdowns, 0.5),
        "p95_drawdown_pct": _quantile(drawdowns, 0.95),
        "ruin_probability_pct": ruin_count / len(finals) * 100 if finals else 0.0,
        "halve_probability_pct": halve_count / len(finals) * 100 if finals else 0.0,
        "p10_path": p10_path, "median_path": median_path, "p90_path": p90_path,
        "sample_paths": paths[:8], "final_values": finals,
    }


def monte_carlo(
    *, balance: float, win_rate: float, win_r: float, loss_r: float,
    risk_pct: float, trades: int, paths: int, seed: int = 42,
    target_return_pct: float = 50, max_drawdown_pct: float = 20,
    annual_trades: int = 50,
) -> dict[str, Any]:
    if balance <= 0 or win_r <= 0 or loss_r <= 0:
        raise ValueError("balance, win_r and loss_r must be positive")
    if not 0 <= win_rate <= 1 or not 0 < risk_pct <= 1:
        raise ValueError("win_rate must be in [0, 1] and risk_pct in (0, 1]")
    if not 1 <= trades <= 500 or not 10 <= paths <= 2_000:
        raise ValueError("trades/paths outside supported range")
    rng = random.Random(seed)
    b = win_r / loss_r
    kelly = max(0.0, win_rate - (1 - win_rate) / b)
    outcomes = [[rng.random() < win_rate for _ in range(trades)] for _ in range(paths)]
    reverse = _risk_reverse(
        win_rate=win_rate, reward_ratio=b, trades=trades, full_kelly=kelly,
        target_return_pct=target_return_pct, max_drawdown_pct=max_drawdown_pct,
        annual_trades=annual_trades, seed=seed,
    )
    decision_base = reverse["recommended_risk_pct"] / 100
    definitions = [
        ("decision-quarter", "保守 1/4", "decision", min(0.99, decision_base * 0.25)),
        ("decision-half", "稳健半额", "decision", min(0.99, decision_base * 0.5)),
        ("decision-full", "满额风险", "decision", min(0.99, decision_base)),
        ("decision-150", "激进 1.5x", "decision", min(0.99, decision_base * 1.5)),
        ("decision-200", "极限 2x", "decision", min(0.99, decision_base * 2)),
        ("kelly-1-12", "1/12 Kelly", "theory", kelly / 12),
        ("kelly-1-8", "1/8 Kelly", "theory", kelly / 8),
        ("kelly-1-6", "1/6 Kelly", "theory", kelly / 6),
        ("kelly-1-4", "1/4 Kelly", "theory", kelly / 4),
        ("kelly-half", "半 Kelly", "theory", kelly / 2),
        ("kelly-full", "满 Kelly", "theory", kelly),
        ("kelly-150", "1.5x Kelly", "theory", min(0.99, kelly * 1.5)),
        ("kelly-210", "2.1x Kelly", "theory", min(0.99, kelly * 2.1)),
    ]
    strategies = [
        _simulate_strategy(
            outcomes=outcomes, balance=balance, reward_ratio=b, fraction=fraction,
            strategy_id=strategy_id, name=name, basis=basis,
        )
        for strategy_id, name, basis, fraction in definitions
    ]
    manual = _simulate_strategy(
        outcomes=outcomes, balance=balance, reward_ratio=b, fraction=risk_pct,
        strategy_id="manual", name="当前输入", basis="manual",
    )
    return {
        "paths": paths,
        "trades": trades,
        "kelly_pct": kelly * 100,
        "half_kelly_pct": kelly * 50,
        "expectancy_r": win_rate * win_r - (1 - win_rate) * loss_r,
        "break_even_pct": 100 / (1 + b),
        "p10_final": manual["p10_final"],
        "p50_final": manual["p50_final"],
        "p90_final": manual["p90_final"],
        "p50_max_drawdown_pct": manual["p50_drawdown_pct"],
        "p95_max_drawdown_pct": manual["p95_drawdown_pct"],
        "loss_probability_pct": sum(v < balance for v in manual["final_values"]) / paths * 100,
        "sample_paths": manual["sample_paths"][:12],
        "reverse": reverse,
        "strategies": [{key: value for key, value in row.items() if key != "final_values"} for row in strategies],
        "distribution": {"bins": _distribution_bins(manual["final_values"])},
    }


def etf_momentum_from_repo(repo, limit: int = 40) -> dict[str, Any]:
    instruments = repo.get_etf_instruments()
    if instruments.is_empty() or "symbol" not in instruments.columns:
        return {"available": False, "detail": "本地暂无 ETF 标的或日线数据", "unit": "percent", "rows": []}
    symbols: list[str] = []
    if hasattr(repo, "get_enriched_latest_asset"):
        latest, _ = repo.get_enriched_latest_asset("etf")
        if not latest.is_empty() and {"symbol", "amount"}.issubset(latest.columns):
            symbols = (
                latest.sort("amount", descending=True)["symbol"]
                .cast(pl.Utf8).unique(maintain_order=True).head(limit).to_list()
            )
    if not symbols:
        symbols = instruments["symbol"].cast(pl.Utf8).unique().head(limit).to_list()
    names = {}
    if "name" in instruments.columns:
        names = dict(zip(instruments["symbol"].cast(pl.Utf8), instruments["name"].cast(pl.Utf8), strict=False))
    end = date.today()
    start = end - timedelta(days=140)
    frames = {symbol: repo.get_etf_daily(symbol, start, end) for symbol in symbols}
    rows = build_etf_momentum(frames, names)
    return {
        "available": bool(rows),
        "detail": None if rows else "ETF 历史不足 51 个交易日",
        "unit": "percent",
        "formula": "1d x 0.4 + 5d x 0.3 + 20d x 0.2 + 50d x 0.1",
        "universe": "latest turnover top" if hasattr(repo, "get_enriched_latest_asset") else "instrument order",
        "rows": rows,
    }


def _attach_dimension(repo, history: pl.DataFrame, dimension: str) -> pl.DataFrame:
    if dimension in history.columns or history.is_empty() or "symbol" not in history.columns:
        return history
    from app.services.rps_rotation import _load_concept_map_df

    mapping, _ = _load_concept_map_df(repo, dimension)
    if mapping.is_empty():
        return history
    return (
        history.with_columns(pl.col("symbol").cast(pl.Utf8).str.to_uppercase().alias("_sym_up"))
        .join(mapping, on="_sym_up", how="inner")
        .drop("_sym_up")
    )


def _select_flow_extremes(rows: list[dict[str, Any]], limit: int = 30) -> list[dict[str, Any]]:
    """Keep both tails visible instead of truncating the weaker-sign side."""
    if len(rows) <= limit:
        return sorted(rows, key=lambda row: row["total_flow_yuan"], reverse=True)

    side_limit = limit // 2
    inflows = sorted(
        (row for row in rows if row["total_flow_yuan"] > 0),
        key=lambda row: row["total_flow_yuan"],
        reverse=True,
    )[:side_limit]
    outflows = sorted(
        (row for row in rows if row["total_flow_yuan"] < 0),
        key=lambda row: row["total_flow_yuan"],
    )[:side_limit]
    selected = inflows + outflows
    selected_sectors = {row["sector"] for row in selected}
    remaining = sorted(
        (row for row in rows if row["sector"] not in selected_sectors),
        key=lambda row: abs(row["total_flow_yuan"]),
        reverse=True,
    )
    selected.extend(remaining[:limit - len(selected)])
    return sorted(selected, key=lambda row: row["total_flow_yuan"], reverse=True)


def _sector_flow_from_facts(fact_repo, dimension: str) -> dict[str, Any] | None:
    dates = fact_repo.available_dates(DatasetId.SECTOR_FLOW_DAILY)[-3:]
    if not dates:
        return None
    frame = fact_repo.get_range(DatasetId.SECTOR_FLOW_DAILY, dates[0], dates[-1])
    if frame.is_empty():
        return None
    frame = frame.filter(pl.col("dimension") == dimension)
    selected: list[pl.DataFrame] = []
    for trade_date in dates:
        daily = frame.filter(pl.col("trade_date") == trade_date)
        for source in get_route(DatasetId.SECTOR_FLOW_DAILY).sources:
            source_rows = daily.filter(pl.col("source") == source)
            if not source_rows.is_empty():
                selected.append(source_rows)
                break
    if not selected:
        return None
    chosen = pl.concat(selected)
    rows: list[dict[str, Any]] = []
    for sector_name in chosen["sector_name"].unique().sort().to_list():
        sector = chosen.filter(pl.col("sector_name") == sector_name).sort("trade_date")
        points = [
            {
                "date": str(row["trade_date"]),
                "flow_yuan": (row.get("net_inflow_yi") or 0) * 100_000_000,
            }
            for row in sector.to_dicts()
        ]
        rows.append(
            {
                "sector": sector_name,
                "points": points,
                "total_flow_yuan": sum(point["flow_yuan"] for point in points),
            }
        )
    rows = _select_flow_extremes(rows)
    fallback_only = chosen["is_fallback"].all()
    return {
        "available": bool(rows),
        "quality": "fallback" if fallback_only else "observed",
        "basis": "sector_flow_daily.net_inflow_yi",
        "unit": "CNY",
        "detail": "来自统一标准事实; fallback 表示主来源缺失" if fallback_only else None,
        "dates": [str(value) for value in dates],
        "rows": rows,
    }


def sector_flow_from_repo(repo, dimension: str = "industry", fact_repo=None) -> dict[str, Any]:
    if fact_repo is not None:
        canonical = _sector_flow_from_facts(fact_repo, dimension)
        if canonical is not None:
            return canonical
    latest, latest_date = repo.get_enriched_latest()
    if latest_date is None or latest.is_empty():
        return {"available": False, "quality": "unavailable", "detail": "本地暂无股票日线", "rows": []}
    history = repo.get_enriched_range(latest_date - timedelta(days=10), latest_date)
    if history is None or history.is_empty():
        return {"available": False, "quality": "unavailable", "detail": "本地历史日线不足", "rows": []}
    history = _attach_dimension(repo, history, dimension)
    if dimension not in history.columns:
        return {"available": False, "quality": "unavailable", "detail": f"缺少 {dimension} 维度历史", "rows": []}
    flow_columns = [c for c in ("main_net_inflow", "main_net", "net_inflow") if c in history.columns]
    quality = "observed" if flow_columns else "proxy"
    basis = flow_columns[0] if flow_columns else "clv_amount_pressure"
    dates = history["date"].unique().sort().tail(3).to_list()
    data = history.filter(pl.col("date").is_in(dates) & pl.col(dimension).is_not_null())
    if quality == "observed":
        data = data.with_columns(pl.col(basis).cast(pl.Float64, strict=False).fill_null(0).alias("flow"))
    elif all(c in data.columns for c in ("high", "low", "close", "amount")):
        spread = pl.col("high") - pl.col("low")
        data = data.with_columns(
            pl.when(spread.abs() > 1e-12)
            .then(((2 * pl.col("close") - pl.col("high") - pl.col("low")) / spread) * pl.col("amount"))
            .otherwise(0.0)
            .alias("flow")
        )
    else:
        return {"available": False, "quality": "unavailable", "detail": "缺少真实资金流与 OHLCV 代理字段", "rows": []}
    grouped = data.group_by([dimension, "date"]).agg(pl.col("flow").sum()).sort([dimension, "date"])
    rows = [
        {"sector": sector, "points": [{"date": str(r["date"])[:10], "flow_yuan": r["flow"]} for r in part.to_dicts()]}
        for sector, part in grouped.partition_by(dimension, as_dict=True).items()
    ]
    for row in rows:
        if isinstance(row["sector"], tuple):
            row["sector"] = row["sector"][0]
        row["total_flow_yuan"] = sum(point["flow_yuan"] or 0 for point in row["points"])
    rows = _select_flow_extremes(rows)
    return {
        "available": bool(rows), "quality": quality, "basis": basis, "unit": "CNY",
        "detail": "代理值仅表示收盘位置 x 成交额, 不等同主力净流入" if quality == "proxy" else None,
        "dates": [str(value)[:10] for value in dates], "rows": rows,
    }


def _longest_enriched_history(repo, end_date: date, windows: tuple[int, ...]) -> pl.DataFrame | None:
    """Return the longest range covered by the repository's all-or-none cache contract."""
    for days in windows:
        history = repo.get_enriched_range(end_date - timedelta(days=days), end_date)
        if history is not None and not history.is_empty():
            return history
    return None


def _aggregate_sector_returns(data: pl.DataFrame, dimension: str) -> pl.DataFrame:
    data = data.sort(["symbol", "date"]).with_columns(
        ((pl.col("close") / pl.col("close").shift(1).over("symbol") - 1) * 100)
        .alias("daily_return_pct")
    ).filter(pl.col("daily_return_pct").is_not_null())
    weight_column = next(
        (name for name in ("market_cap", "float_market_cap") if name in data.columns),
        None,
    )
    if weight_column is None:
        return data.group_by([dimension, "date"]).agg(
            pl.col("daily_return_pct").mean().alias("return_pct")
        )

    data = data.with_columns(
        pl.col(weight_column).cast(pl.Float64, strict=False).fill_null(0).clip(lower_bound=0).alias("_weight")
    ).with_columns((pl.col("daily_return_pct") * pl.col("_weight")).alias("_weighted_return"))
    grouped = data.group_by([dimension, "date"]).agg(
        pl.col("_weighted_return").sum().alias("_weighted_sum"),
        pl.col("_weight").sum().alias("_weight_sum"),
        pl.col("daily_return_pct").mean().alias("_equal_return"),
    )
    return grouped.with_columns(
        pl.when(pl.col("_weight_sum") > 0)
        .then(pl.col("_weighted_sum") / pl.col("_weight_sum"))
        .otherwise(pl.col("_equal_return"))
        .alias("return_pct")
    ).select([dimension, "date", "return_pct"])


def _rank_sector_snapshots(daily: pl.DataFrame, dimension: str) -> dict[str, list[dict[str, Any]]]:
    metric_specs = {
        "swing": ("swing_ratio_pct", 9.16, 61.53),
        "ratio": ("flow_ratio_pct", 10.74, -10.61),
        "amount": ("flow_yuan", 11.11, -28.26),
    }
    swing_state: dict[str, tuple[float, float]] = {}
    rank_history: dict[str, dict[str, list[tuple[int, float]]]] = {
        metric: {} for metric in metric_specs
    }
    snapshots: dict[str, list[dict[str, Any]]] = {}

    for current_date, part in daily.sort(["date", dimension]).partition_by("date", as_dict=True).items():
        date_value = current_date[0] if isinstance(current_date, tuple) else current_date
        date_text = str(date_value)[:10]
        rows: list[dict[str, Any]] = []
        for item in part.to_dicts():
            sector = str(item[dimension])
            ratio = float(item.get("flow_ratio_pct") or 0)
            amount = float(item.get("flow_yuan") or 0)
            previous = swing_state.get(sector)
            swing_ratio = ratio if previous is None else 0.24 * ratio + 0.76 * previous[0]
            swing_amount = amount if previous is None else 0.22 * amount + 0.78 * previous[1]
            swing_state[sector] = (swing_ratio, swing_amount)
            rows.append({
                "sector": sector,
                "as_of": date_text,
                "return_pct": float(item.get("return_pct") or 0),
                "flow_yuan": amount,
                "flow_ratio_pct": ratio,
                "swing_ratio_pct": swing_ratio,
                "swing_amount_yuan": swing_amount,
            })

        universe_size = len(rows)
        for metric, (value_field, slope, intercept) in metric_specs.items():
            ranked = sorted(rows, key=lambda row: row[value_field], reverse=True)
            for rank, row in enumerate(ranked, 1):
                rank_pct = (universe_size - rank + 1) / universe_size * 100
                history = rank_history[metric].setdefault(row["sector"], [])
                row[f"{metric}_rank"] = rank
                row[f"{metric}_rank_pct"] = rank_pct
                row[f"{metric}_score"] = slope * rank_pct + intercept
                for days_ago in (1, 3, 5):
                    old_rank = history[-days_ago][0] if len(history) >= days_ago else None
                    row[f"{metric}_rank_change_{days_ago}d"] = (
                        old_rank - rank if old_rank is not None else 0
                    )
                recent = history[-30:]
                row[f"{metric}_top_30d"] = sum(old_pct >= 90 for _, old_pct in recent)
                row[f"{metric}_bottom_30d"] = sum(old_pct <= 10 for _, old_pct in recent)
            for row in ranked:
                rank_history[metric][row["sector"]].append(
                    (row[f"{metric}_rank"], row[f"{metric}_rank_pct"])
                )

        for row in rows:
            row["rank"] = row["swing_rank"]
            row["score"] = row["swing_score"]
            row["ema_swing_pct"] = row["swing_ratio_pct"]
            row["positive_days_30"] = row["swing_top_30d"]
        snapshots[date_text] = sorted(rows, key=lambda row: row["swing_rank"])
    return snapshots


def _rank_history_payload(
    snapshots: dict[str, list[dict[str, Any]]], limit: int = 60
) -> dict[str, list[dict[str, Any]]]:
    history: dict[str, list[dict[str, Any]]] = {}
    for date_text in sorted(snapshots)[-limit:]:
        for row in snapshots[date_text]:
            history.setdefault(row["sector"], []).append({
                "date": date_text,
                "swing_rank": row["swing_rank"],
                "ratio_rank": row["ratio_rank"],
                "amount_rank": row["amount_rank"],
                "swing_rank_pct": row["swing_rank_pct"],
                "ratio_rank_pct": row["ratio_rank_pct"],
                "amount_rank_pct": row["amount_rank_pct"],
            })
    return history


def _sector_radar_from_facts(fact_repo, dimension: str, as_of: date | None) -> dict[str, Any] | None:
    available = fact_repo.available_dates(DatasetId.SECTOR_FLOW_DAILY)
    if as_of is not None:
        available = [value for value in available if value <= as_of]
    available = available[-60:]
    if not available:
        return None
    frame = fact_repo.get_range(
        DatasetId.SECTOR_FLOW_DAILY, available[0], available[-1]
    ).filter(pl.col("dimension") == dimension)
    selected: list[pl.DataFrame] = []
    for trade_date in available:
        daily = frame.filter(pl.col("trade_date") == trade_date)
        for source in get_route(DatasetId.SECTOR_FLOW_DAILY).sources:
            source_rows = daily.filter(pl.col("source") == source)
            if not source_rows.is_empty():
                selected.append(source_rows)
                break
    if not selected:
        return None
    chosen = pl.concat(selected).with_columns(
        pl.col("sector_name").alias(dimension),
        pl.col("trade_date").alias("date"),
        (pl.col("net_inflow_yi").fill_null(0) * 100_000_000).alias("flow_yuan"),
        (pl.col("amount_yi").fill_null(0) * 100_000_000).alias("turnover_yuan"),
        pl.col("pct_chg").fill_null(0).alias("return_pct"),
    )
    daily_abs_flow = pl.col("flow_yuan").abs().sum().over("date")
    daily = chosen.with_columns(
        pl.when(pl.col("turnover_yuan").abs() > 1e-12)
        .then(pl.col("flow_yuan") / pl.col("turnover_yuan").abs() * 100)
        .when(daily_abs_flow > 1e-12)
        .then(pl.col("flow_yuan") / daily_abs_flow * 100)
        .otherwise(0.0)
        .alias("flow_ratio_pct")
    ).select([dimension, "date", "return_pct", "flow_yuan", "flow_ratio_pct"])
    snapshots = _rank_sector_snapshots(daily, dimension)
    if not snapshots:
        return None
    available_dates = sorted(snapshots)
    selected_date = available_dates[-1]
    fallback_only = chosen["is_fallback"].all()
    return {
        "available": True,
        "quality": "fallback" if fallback_only else "observed",
        "basis": "sector_flow_daily.net_inflow_yi",
        "detail": "来自统一标准事实; fallback 表示主来源缺失" if fallback_only else None,
        "as_of": selected_date,
        "available_dates": available_dates,
        "universe_size": len(snapshots[selected_date]),
        "unit": "CNY",
        "score_formula": {
            "swing": "9.16 x RankPct + 61.53",
            "ratio": "10.74 x RankPct - 10.61",
            "amount": "11.11 x RankPct - 28.26",
        },
        "rows": snapshots[selected_date],
        "rank_history": _rank_history_payload(snapshots),
    }


def sector_radar_from_repo(
    repo, dimension: str = "industry", as_of: date | None = None, fact_repo=None
) -> dict[str, Any]:
    """Build OneChart-compatible money-flow radar ranks for every local sector."""
    if fact_repo is not None:
        canonical = _sector_radar_from_facts(fact_repo, dimension, as_of)
        if canonical is not None:
            return canonical
    latest, latest_date = repo.get_enriched_latest()
    if latest_date is None or latest.is_empty():
        return {"available": False, "quality": "unavailable", "detail": "本地暂无股票日线", "rows": []}
    target_date = min(as_of, latest_date) if as_of is not None else latest_date
    history = _longest_enriched_history(repo, target_date, (140, 100, 75, 55, 35, 14))
    if history is None:
        return {"available": False, "quality": "unavailable", "detail": "本地历史日线不足", "rows": []}
    history = _attach_dimension(repo, history, dimension)
    required = {dimension, "symbol", "date", "close", "amount"}
    if not required.issubset(history.columns):
        return {"available": False, "quality": "unavailable", "detail": f"缺少 {dimension} 或行情历史", "rows": []}

    flow_columns = [name for name in ("main_net_inflow", "main_net", "net_inflow") if name in history.columns]
    quality = "observed" if flow_columns else "proxy"
    flow_basis = flow_columns[0] if flow_columns else "clv_amount_pressure"
    data = history.filter(pl.col(dimension).is_not_null()).sort(["symbol", "date"])
    if quality == "observed":
        data = data.with_columns(
            pl.col(flow_basis).cast(pl.Float64, strict=False).fill_null(0).alias("flow_yuan")
        )
    elif {"high", "low"}.issubset(data.columns):
        spread = pl.col("high") - pl.col("low")
        data = data.with_columns(
            pl.when(spread.abs() > 1e-12)
            .then(((2 * pl.col("close") - pl.col("high") - pl.col("low")) / spread) * pl.col("amount"))
            .otherwise(0.0)
            .alias("flow_yuan")
        )
    else:
        return {"available": False, "quality": "unavailable", "detail": "缺少真实资金流与 OHLCV 代理字段", "rows": []}

    returns = _aggregate_sector_returns(data, dimension)
    flows = data.group_by([dimension, "date"]).agg(
        pl.col("flow_yuan").sum(),
        pl.col("amount").cast(pl.Float64, strict=False).fill_null(0).sum().alias("turnover_yuan"),
    )
    daily = flows.join(returns, on=[dimension, "date"], how="left").with_columns(
        pl.col("return_pct").fill_null(0),
        pl.when(pl.col("turnover_yuan").abs() > 1e-12)
        .then(pl.col("flow_yuan") / pl.col("turnover_yuan").abs() * 100)
        .otherwise(0.0)
        .alias("flow_ratio_pct")
    )
    snapshots = _rank_sector_snapshots(daily, dimension)
    if not snapshots:
        return {"available": False, "quality": quality, "detail": "板块聚合结果为空", "rows": []}
    available_dates = sorted(snapshots)
    selected_date = max((value for value in available_dates if value <= str(target_date)), default=available_dates[-1])
    rows = snapshots[selected_date]
    return {
        "available": True,
        "quality": quality,
        "basis": flow_basis,
        "detail": "资金项为收盘位置 x 成交额代理, 不等同主力净流入" if quality == "proxy" else None,
        "as_of": selected_date,
        "available_dates": available_dates[-60:],
        "universe_size": len(rows),
        "unit": "CNY",
        "score_formula": {
            "swing": "9.16 x RankPct + 61.53",
            "ratio": "10.74 x RankPct - 10.61",
            "amount": "11.11 x RankPct - 28.26",
        },
        "rows": rows,
        "rank_history": _rank_history_payload(snapshots),
    }


def sector_members_from_repo(
    repo, *, dimension: str, sector: str, as_of: date | None = None, limit: int = 10
) -> dict[str, Any]:
    """Return stock-level evidence for one radar sector from the local repository."""
    latest, latest_date = repo.get_enriched_latest()
    if latest_date is None or latest.is_empty():
        return {"available": False, "detail": "本地暂无股票日线", "metrics": {}}
    target_date = min(as_of, latest_date) if as_of is not None else latest_date
    history = repo.get_enriched_range(target_date - timedelta(days=12), target_date)
    if history is None or history.is_empty():
        return {"available": False, "detail": "个股历史不足", "metrics": {}}
    history = _attach_dimension(repo, history, dimension)
    required = {"symbol", "date", "close", dimension}
    if not required.issubset(history.columns):
        return {"available": False, "detail": "缺少板块成分映射或收盘价", "metrics": {}}
    dimension_text = pl.col(dimension).cast(pl.Utf8)
    member_filter = dimension_text == sector
    if dimension == "industry":
        # 统一事实中的行业名可能是一级/二级简称, 而 ext_hy_ths 保存的是
        # “一级-二级-三级”全路径。点击雷达行时两种口径都应能下钻到成分股。
        member_filter = member_filter | dimension_text.str.split("-").list.contains(sector)
    data = history.filter(member_filter).sort(["symbol", "date"])
    if data.is_empty():
        return {"available": False, "detail": f"未找到 {sector} 的本地成分股", "metrics": {}}
    data = data.with_columns(
        ((pl.col("close") / pl.col("close").shift(1).over("symbol") - 1) * 100).alias("return_pct")
    )
    current = data.filter(pl.col("date") == target_date)
    if current.is_empty():
        actual_date = data["date"].max()
        current = data.filter(pl.col("date") == actual_date)
    else:
        actual_date = target_date
    flow_column = next(
        (name for name in ("main_net_inflow", "main_net", "net_inflow") if name in current.columns),
        None,
    )
    if flow_column:
        current = current.with_columns(
            pl.col(flow_column).cast(pl.Float64, strict=False).alias("main_net_amount")
        )
        flow_quality = "observed"
    elif {"high", "low", "amount"}.issubset(current.columns):
        spread = pl.col("high") - pl.col("low")
        current = current.with_columns(
            pl.when(spread.abs() > 1e-12)
            .then(((2 * pl.col("close") - pl.col("high") - pl.col("low")) / spread) * pl.col("amount"))
            .otherwise(None)
            .alias("main_net_amount")
        )
        flow_quality = "proxy"
    else:
        current = current.with_columns(pl.lit(None, dtype=pl.Float64).alias("main_net_amount"))
        flow_quality = "unavailable"
    active_columns = {"buy_elg_amount", "sell_elg_amount", "buy_lg_amount", "sell_lg_amount"}
    if active_columns.issubset(current.columns):
        current = current.with_columns(
            (
                pl.col("buy_elg_amount") - pl.col("sell_elg_amount")
                + pl.col("buy_lg_amount") - pl.col("sell_lg_amount")
            ).cast(pl.Float64, strict=False).alias("active_buy_net_amount")
        )
        active_quality = "observed"
    else:
        current = current.with_columns(pl.lit(None, dtype=pl.Float64).alias("active_buy_net_amount"))
        active_quality = "unavailable"
    names = pl.col("name").cast(pl.Utf8) if "name" in current.columns else pl.col("symbol").cast(pl.Utf8)
    rows = current.with_columns(names.alias("name")).select(
        ["symbol", "name", "return_pct", "main_net_amount", "active_buy_net_amount"]
    ).to_dicts()

    def ranked(field: str) -> dict[str, list[dict[str, Any]]]:
        available_rows = [row for row in rows if row.get(field) is not None]
        return {
            "top": sorted(available_rows, key=lambda row: row[field], reverse=True)[:limit],
            "bottom": sorted(available_rows, key=lambda row: row[field])[:limit],
        }

    return {
        "available": bool(rows), "as_of": str(actual_date)[:10], "dimension": dimension,
        "sector": sector, "member_count": len(rows), "flow_quality": flow_quality,
        "active_quality": active_quality,
        "metrics": {
            "return_pct": ranked("return_pct"),
            "main_net_amount": ranked("main_net_amount"),
            "active_buy_net_amount": ranked("active_buy_net_amount"),
        },
    }


def _macro_zone(ma3: float) -> str:
    if ma3 < 30:
        return "低位趋同"
    if ma3 < 70:
        return "正常区间"
    if ma3 < 120:
        return "中高位 · 潜在高切低动力"
    return "极致化抱团 · 谨慎"


def _contribution_windows(
    industry_details: list[list[dict[str, Any]]]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    windows: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for days in (1, 3, 5, 10):
        totals: dict[str, dict[str, float]] = {}
        for daily in industry_details[-days:]:
            for item in daily:
                aggregate = totals.setdefault(item["name"], {"contribution": 0.0, "direction": 0.0})
                aggregate["contribution"] += item["share"]
                aggregate["direction"] += item["direction"]
        rows = [
            {
                "name": name,
                "contribution_pct": values["contribution"] * 100,
                "direction": values["direction"],
                "state": "强者扩张" if values["direction"] >= 0 else "弱者下沉",
            }
            for name, values in totals.items()
        ]
        rows.sort(key=lambda row: row["contribution_pct"], reverse=True)
        windows[str(days)] = {"high": rows[:10], "low": list(reversed(rows[-10:]))}
    return windows


def macro_dispersion_from_repo(repo) -> dict[str, Any]:
    """Compute OneChart dispersion from local daily industry return cross-sections."""
    latest, latest_date = repo.get_enriched_latest()
    if latest_date is None or latest.is_empty():
        return {"available": False, "detail": "本地暂无股票日线", "history": [], "indices": []}
    history = _longest_enriched_history(repo, latest_date, (420, 300, 220, 160, 100, 60, 30))
    if history is None:
        return {"available": False, "detail": "本地行业历史不足", "history": [], "indices": []}
    history = _attach_dimension(repo, history, "industry")
    required = {"industry", "symbol", "date", "close"}
    if not required.issubset(history.columns):
        return {"available": False, "detail": "缺少本地行业映射或收盘价历史", "history": [], "indices": []}

    # OneChart 宏观离散度以二级行业为横截面。本地 ext_hy_ths 映射保存为
    # “一级-二级-三级”全路径, 必须在计算 D 前收敛到第二级, 否则行业数量
    # 会改变未标准化离散度的绝对尺度。注意本地分类是同花顺, 不冒充申万。
    history = history.with_columns(
        pl.col("industry").cast(pl.Utf8).str.split("-").list.get(1, null_on_oob=True)
        .fill_null(pl.col("industry").cast(pl.Utf8).str.split("-").list.first())
        .alias("industry")
    )

    daily = _aggregate_sector_returns(
        history.filter(pl.col("industry").is_not_null()), "industry"
    ).sort(["date", "industry"])
    history_points: list[dict[str, Any]] = []
    industry_details: list[list[dict[str, Any]]] = []
    for current_date, part in daily.partition_by("date", as_dict=True).items():
        date_value = current_date[0] if isinstance(current_date, tuple) else current_date
        returns = {
            str(row["industry"]): float(row["return_pct"])
            for row in part.to_dicts()
            if row["return_pct"] is not None and math.isfinite(float(row["return_pct"]))
        }
        if len(returns) < 2:
            continue
        result = compute_dispersion(returns)
        details = [
            {
                **item,
                "direction": item["share"] * (1 if item["signed_deviation"] >= 0 else -1),
                "state": "强者扩张" if item["signed_deviation"] >= 0 else "弱者下沉",
            }
            for item in result["contributions"]
        ]
        industry_details.append(details)
        history_points.append({
            "date": str(date_value)[:10],
            "dispersion": result["dispersion"],
            "mean_pct": result["mean_pct"],
            "industry_count": len(returns),
        })

    if not history_points:
        return {"available": False, "detail": "行业收益横截面不足", "history": [], "indices": []}
    for index, point in enumerate(history_points):
        point["ma3"] = fmean(
            item["dispersion"] for item in history_points[max(0, index - 2):index + 1]
        )

    latest_point = history_points[-1]
    dispersion_values = [point["dispersion"] for point in history_points]
    ma3_values = [point["ma3"] for point in history_points]
    percentile = sum(value <= latest_point["dispersion"] for value in dispersion_values) / len(dispersion_values) * 100
    ma3_percentile = sum(value <= latest_point["ma3"] for value in ma3_values) / len(ma3_values) * 100
    change_1d = latest_point["dispersion"] - history_points[-2]["dispersion"] if len(history_points) >= 2 else 0.0
    change_5d = latest_point["dispersion"] - history_points[-6]["dispersion"] if len(history_points) >= 6 else 0.0

    index_specs = (
        ("000001.SH", "上证", "上证指数"),
        ("399006.SZ", "创业", "创业板指"),
        ("000688.SH", "科创", "科创50"),
        ("000016.SH", "50", "上证50"),
        ("000300.SH", "300", "沪深300"),
        ("000852.SH", "1000", "中证1000"),
        ("932000.CSI", "2000", "中证2000"),
    )
    start_date = date.fromisoformat(history_points[0]["date"])
    indices: list[dict[str, Any]] = []
    for symbol, label, name in index_specs:
        frame = repo.get_index_daily(symbol, start_date, latest_date, columns=["date", "close"])
        if frame is None or frame.is_empty() or not {"date", "close"}.issubset(frame.columns):
            continue
        ordered = frame.select(["date", "close"]).drop_nulls().sort("date").to_dicts()
        if not ordered or float(ordered[0]["close"]) <= 0:
            continue
        base = float(ordered[0]["close"])
        points = [
            {
                "date": str(row["date"])[:10],
                "normalized": 100 * math.log(float(row["close"]) / base),
            }
            for row in ordered
            if float(row["close"]) > 0
        ]
        indices.append({"symbol": symbol, "label": label, "name": name, "points": points})

    latest_contributions = industry_details[-1]
    return {
        "available": True,
        "as_of": latest_point["date"],
        "window": "daily industry cross-section",
        "industry_level": 2,
        "unit": "percent",
        "basis": "本地同花顺二级行业当前成分快照回看历史的成分股市值加权日收益横截面",
        "mean_pct": latest_point["mean_pct"],
        "dispersion": latest_point["dispersion"],
        "ma3": latest_point["ma3"],
        "percentile": percentile,
        "ma3_percentile": ma3_percentile,
        "change_1d": change_1d,
        "change_5d": change_5d,
        "zone": _macro_zone(latest_point["ma3"]),
        "industry_count": latest_point["industry_count"],
        "history": history_points[-180:],
        "indices": indices,
        "contributions": latest_contributions,
        "contribution_windows": _contribution_windows(industry_details),
    }
