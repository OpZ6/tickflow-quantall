#!/usr/bin/env python3
"""Build a fresh outcome-blind packet for classic-structure semantic validation."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from build_vcp_blind_casebook import (
    OUTPUT as PRIOR_CASEBOOK,
)
from build_vcp_blind_casebook import (
    PAGE_SIZE,
    _candidates,
    _draw_case,
    _font,
    _market,
)
from PIL import Image, ImageDraw
from vcp_classic_structure import represent_classic_structure

OUTPUT = PRIOR_CASEBOOK.parent / "classic-structure-v1-blind"
YEARS = tuple(range(2018, 2026))
PER_STATUS_PER_YEAR = 2


def _selection_hash(row: dict, supported: bool) -> str:
    key = "|".join(
        str(value)
        for value in (
            row["symbol"],
            row["signal_date"],
            row["scale"],
            row["pivot_date"],
            "supported" if supported else "unsupported",
        )
    )
    return hashlib.sha256(key.encode()).hexdigest()


def main() -> int:
    candidates = _candidates()
    market = _market(
        candidates.get_column("symbol").unique().to_list(),
        candidates.get_column("signal_date").min() - timedelta(days=300),
        candidates.get_column("signal_date").max(),
    )
    prior_outcomes = json.loads((PRIOR_CASEBOOK / "outcomes.json").read_text(encoding="utf-8"))
    prior_ids = {(row["symbol"], row["signal_date"]) for row in prior_outcomes}

    represented = []
    for row in candidates.to_dicts():
        identity = (row["symbol"], row["signal_date"].isoformat())
        if row["signal_date"].year not in YEARS or identity in prior_ids:
            continue
        bars = market.get(row["symbol"])
        if bars is None:
            continue
        visible = bars.filter(bars["date"] <= row["signal_date"]).tail(160)
        if visible.height < 100 or visible.get_column("date")[-1] != row["signal_date"]:
            continue
        representation = represent_classic_structure(
            visible["high"].to_numpy(),
            visible["low"].to_numpy(),
            visible["close"].to_numpy(),
            visible["volume"].to_numpy(),
            visible["date"].to_numpy(),
        )
        represented.append(
            {
                **row,
                "bars": visible,
                "representation": representation,
                "selection_hash": _selection_hash(row, representation["supported"]),
            }
        )

    selected = []
    availability = {}
    for year in YEARS:
        availability[str(year)] = {}
        for supported in (True, False):
            group = [
                row
                for row in represented
                if row["signal_date"].year == year
                and row["representation"]["supported"] is supported
            ]
            group.sort(key=lambda row: row["selection_hash"])
            status = "supported" if supported else "unsupported"
            availability[str(year)][status] = len(group)
            if len(group) < PER_STATUS_PER_YEAR:
                raise RuntimeError(f"not enough {status} cases for {year}: {len(group)}")
            selected.extend(group[:PER_STATUS_PER_YEAR])
    selected.sort(key=lambda row: (row["signal_date"].year, row["selection_hash"]))

    OUTPUT.mkdir(parents=True, exist_ok=False)
    manifest = []
    sealed = []
    labels = []
    page_count = (len(selected) + 5) // 6
    for offset in range(0, len(selected), 6):
        page = offset // 6 + 1
        subset = selected[offset : offset + 6]
        image = Image.new("RGB", PAGE_SIZE, "white")
        draw = ImageDraw.Draw(image)
        draw.text(
            (55, 20),
            "Blind classic-structure validation - prediction, identity and outcome hidden",
            fill="#111827",
            font=_font(30),
        )
        draw.text((55, 58), "black: signal day | all other structure must be judged from the chart", fill="#374151", font=_font(18))
        for local_index, row in enumerate(subset):
            case_number = offset + local_index + 1
            case_id = f"S{case_number:02d}"
            column = local_index % 2
            panel_row = local_index // 2
            panel_left = 55 + column * 1165
            panel_top = 105 + panel_row * 605
            _draw_case(
                draw,
                (panel_left, panel_top, panel_left + 1125, panel_top + 575),
                case_id,
                row,
                show_structure=False,
            )
            manifest.append(
                {
                    "case_id": case_id,
                    "scale": row["scale"],
                    "visible_bars": row["bars"].height,
                    "page": f"page-{page}.png",
                    "panel": local_index + 1,
                    "selection_hash": row["selection_hash"],
                }
            )
            sealed.append(
                {
                    "case_id": case_id,
                    "symbol": row["symbol"],
                    "signal_date": row["signal_date"].isoformat(),
                    "broad_pivot_date": row["pivot_date"].isoformat(),
                    "representation": row["representation"],
                    "true_breakout_10_7_20": row["true_breakout_10_7_20"],
                    "return_40d": row["return_40d"],
                    "mfe_40d": row["mfe_40d"],
                }
            )
            labels.append(
                {
                    "case_id": case_id,
                    "classification": None,
                    "confidence": None,
                    "present": [],
                    "missing_or_contrary": [],
                    "note": None,
                }
            )
        image.save(OUTPUT / f"page-{page}.png")

    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUTPUT / "sealed.json").write_text(json.dumps(sealed, indent=2), encoding="utf-8")
    (OUTPUT / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    (OUTPUT / "README.md").write_text(
        "# Blind classic-structure validation packet\n\n"
        "Review the PNG pages and freeze `labels.json` before opening `sealed.json`. "
        "Representation status, identities and outcomes are all hidden. The selection does not use future outcomes.\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "cases": len(selected),
                "pages": page_count,
                "availability": availability,
                "sealed_opened": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
