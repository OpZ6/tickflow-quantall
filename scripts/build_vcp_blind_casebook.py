#!/usr/bin/env python3
"""Build a deterministic, outcome-blind VCP chart-labeling packet."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/research/vcp/casebooks/classic-vcp-blind-v1"
CANDIDATE_INPUTS = (
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2017-2020-v1/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-v4/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2024-2026-v1/discovery-candidates.parquet",
)
YEARS = tuple(range(2018, 2026))
CASES_PER_YEAR = 3
PAGE_SIZE = (2400, 1950)


def _hash(row: dict) -> str:
    key = "|".join(str(row[name]) for name in ("symbol", "signal_date", "scale", "pivot_date"))
    return hashlib.sha256(key.encode()).hexdigest()


def _candidates() -> pl.DataFrame:
    return (
        pl.concat([pl.read_parquet(path) for path in CANDIDATE_INPUTS], how="diagonal_relaxed")
        .with_columns(
            pl.col("signal_date").cast(pl.Utf8).str.to_date(strict=True),
            pl.col("pivot_date").cast(pl.Utf8).str.to_date(strict=True),
        )
        .sort(["signal_date", "symbol", "scale", "pivot_date"])
        .unique(["symbol", "scale", "pivot_date"], keep="first", maintain_order=True)
        .filter(pl.col("signal_date").dt.year().is_in(YEARS))
    )


def _market(symbols: list[str], start, end) -> dict[str, pl.DataFrame]:
    frame = (
        pl.scan_parquet(str(ROOT / "data/kline_daily_enriched/date=*/part.parquet"))
        .select("symbol", "date", "open", "high", "low", "close", "volume")
        .filter(
            pl.col("symbol").is_in(symbols)
            & (pl.col("date") >= start)
            & (pl.col("date") <= end)
        )
        .collect()
        .sort(["symbol", "date"])
    )
    return {
        str(key[0] if isinstance(key, tuple) else key): value
        for key, value in frame.partition_by("symbol", as_dict=True).items()
    }


def _select(candidates: pl.DataFrame, market: dict[str, pl.DataFrame]) -> list[dict]:
    selected = []
    for year in YEARS:
        rows = candidates.filter(pl.col("signal_date").dt.year() == year).to_dicts()
        for row in sorted(rows, key=_hash):
            bars = market.get(row["symbol"])
            if bars is None:
                continue
            visible = bars.filter(pl.col("date") <= row["signal_date"]).tail(160)
            if visible.height < 100 or visible.get_column("date")[-1] != row["signal_date"]:
                continue
            selected.append({**row, "selection_hash": _hash(row), "bars": visible})
            if sum(item["signal_date"].year == year for item in selected) == CASES_PER_YEAR:
                break
        if sum(item["signal_date"].year == year for item in selected) != CASES_PER_YEAR:
            raise RuntimeError(f"could not select {CASES_PER_YEAR} blind cases for {year}")
    return selected


def _font(size: int):
    path = Path("C:/Windows/Fonts/arial.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def _draw_case(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    case_id: str,
    row: dict,
    *,
    show_structure: bool = True,
) -> None:
    bars = row["bars"]
    first_close = float(bars.get_column("close")[0])
    high = bars.get_column("high").to_numpy() / first_close * 100
    low = bars.get_column("low").to_numpy() / first_close * 100
    close = bars.get_column("close").to_numpy() / first_close * 100
    volume = bars.get_column("volume").to_numpy().astype(float)
    prior_volume = volume[-51:-1]
    baseline = float(np.nanmean(prior_volume)) if len(prior_volume) else 1.0
    volume_ratio = volume / baseline if baseline > 0 else volume

    left, top, right, bottom = box
    plot_left, plot_right = left + 52, right - 12
    price_top, price_bottom = top + 34, bottom - 150
    volume_top, volume_bottom = price_bottom + 12, bottom - 18
    draw.rectangle(box, outline="#d1d5db", width=1)
    draw.text((left + 8, top + 5), f"{case_id}  scale={row['scale']}", fill="#111827", font=_font(20))

    pivot_value = float(row["pivot"]) / first_close * 100 if show_structure else None
    price_values = np.r_[low, pivot_value] if pivot_value is not None else low
    price_min = float(np.nanmin(price_values))
    price_max = float(np.nanmax(np.r_[high, pivot_value] if pivot_value is not None else high))
    padding = max((price_max - price_min) * 0.04, 0.5)
    price_min -= padding
    price_max += padding

    def px(index: int) -> float:
        return plot_left + index * (plot_right - plot_left) / max(1, bars.height - 1)

    def py(value: float) -> float:
        return price_bottom - (value - price_min) * (price_bottom - price_top) / (price_max - price_min)

    for index in range(bars.height):
        draw.line((px(index), py(float(low[index])), px(index), py(float(high[index]))), fill="#9ca3af", width=1)
    draw.line([(px(index), py(float(value))) for index, value in enumerate(close)], fill="#1d4ed8", width=2)
    dates = bars.get_column("date").to_list()
    if show_structure and pivot_value is not None:
        pivot_y = py(pivot_value)
        for dash_start in range(int(plot_left), int(plot_right), 14):
            draw.line(
                (dash_start, pivot_y, min(dash_start + 8, plot_right), pivot_y),
                fill="#dc2626",
                width=2,
            )
        date_lookup = {value: index for index, value in enumerate(dates)}
        pivot_index = date_lookup.get(row["pivot_date"])
        if pivot_index is not None:
            draw.line((px(pivot_index), price_top, px(pivot_index), price_bottom), fill="#f59e0b", width=1)
        last_low_date = row["signal_date"] - timedelta(days=int(row["last_low_age_days"]))
        low_index = date_lookup.get(last_low_date)
        if low_index is not None:
            draw.line((px(low_index), price_top, px(low_index), price_bottom), fill="#059669", width=1)
    draw.line((px(bars.height - 1), price_top, px(bars.height - 1), price_bottom), fill="#111827", width=2)
    draw.text((left + 3, price_top), f"{price_max:.0f}", fill="#6b7280", font=_font(13))
    draw.text((left + 3, price_bottom - 14), f"{price_min:.0f}", fill="#6b7280", font=_font(13))

    colors = np.where(np.diff(np.r_[close[0], close]) >= 0, "#ef4444", "#10b981")
    volume_cap = min(6.0, max(2.0, float(np.nanpercentile(volume_ratio, 98)) * 1.1))
    bar_width = max(1.0, (plot_right - plot_left) / bars.height * 0.75)
    for index, value in enumerate(volume_ratio):
        height = min(float(value), volume_cap) / volume_cap * (volume_bottom - volume_top)
        draw.rectangle(
            (px(index) - bar_width / 2, volume_bottom - height, px(index) + bar_width / 2, volume_bottom),
            fill=str(colors[index]),
        )
    baseline_y = volume_bottom - (volume_bottom - volume_top) / volume_cap
    draw.line((plot_left, baseline_y, plot_right, baseline_y), fill="#6b7280", width=1)
    draw.text((left + 3, volume_top), "vol", fill="#6b7280", font=_font(13))


def main() -> int:
    candidates = _candidates()
    market = _market(
        candidates.get_column("symbol").unique().to_list(),
        candidates.get_column("signal_date").min() - timedelta(days=300),
        candidates.get_column("signal_date").max(),
    )
    selected = _select(candidates, market)
    OUTPUT.mkdir(parents=True, exist_ok=False)

    manifest = []
    outcomes = []
    labels = []
    for offset in range(0, len(selected), 6):
        page = offset // 6 + 1
        subset = selected[offset : offset + 6]
        image = Image.new("RGB", PAGE_SIZE, "white")
        draw = ImageDraw.Draw(image)
        draw.text((55, 20), "Blind VCP structure packet - outcomes and identities hidden", fill="#111827", font=_font(30))
        draw.text(
            (55, 58),
            "red dashed: broad pivot | orange: pivot date | green: broad final low | black: signal day",
            fill="#374151",
            font=_font(18),
        )
        for local_index, row in enumerate(subset):
            case_number = offset + local_index + 1
            case_id = f"C{case_number:02d}"
            column = local_index % 2
            panel_row = local_index // 2
            panel_left = 55 + column * 1165
            panel_top = 105 + panel_row * 605
            _draw_case(draw, (panel_left, panel_top, panel_left + 1125, panel_top + 575), case_id, row)
            manifest.append({
                "case_id": case_id,
                "scale": row["scale"],
                "visible_bars": row["bars"].height,
                "page": f"page-{page}.png",
                "panel": local_index + 1,
                "selection_hash": row["selection_hash"],
            })
            outcomes.append({
                "case_id": case_id,
                "symbol": row["symbol"],
                "signal_date": row["signal_date"].isoformat(),
                "pivot_date": row["pivot_date"].isoformat(),
                "true_breakout_10_7_20": row["true_breakout_10_7_20"],
                "return_40d": row["return_40d"],
                "mfe_40d": row["mfe_40d"],
            })
            labels.append({
                "case_id": case_id,
                "classification": None,
                "confidence": None,
                "present": [],
                "missing_or_contrary": [],
                "note": None,
            })
        image.save(OUTPUT / f"page-{page}.png")

    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUTPUT / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    (OUTPUT / "outcomes.json").write_text(json.dumps(outcomes, indent=2), encoding="utf-8")
    (OUTPUT / "README.md").write_text(
        "# Blind VCP structure packet\n\n"
        "Review `page-1.png` through `page-4.png` and freeze `labels.json` before opening `outcomes.json`. "
        "The sampling hash does not use outcomes. Red dashed is the broad pivot, orange dotted its date, "
        "green dotted the broad final low, and black the signal day.\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(OUTPUT),
        "cases": len(selected),
        "pages": 4,
        "years": list(YEARS),
        "outcomes_opened": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
