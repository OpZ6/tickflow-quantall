#!/usr/bin/env python3
"""Build a fresh outcome-blind semantic packet for the supply-wave v3 representation."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from build_vcp_blind_casebook import OUTPUT as FIRST_PACKET
from build_vcp_blind_casebook import PAGE_SIZE, _candidates, _draw_case, _font, _market
from build_vcp_classic_structure_blind_casebook import OUTPUT as SECOND_PACKET
from PIL import Image, ImageDraw
from vcp_supply_wave_v3 import represent_supply_waves

OUTPUT = FIRST_PACKET.parent / "supply-wave-v3-blind"
YEARS = tuple(range(2018, 2026))
PER_STATUS_PER_YEAR = 2


def _selection_hash(row: dict, supported: bool) -> str:
    key = "|".join(
        str(value)
        for value in (row["symbol"], row["signal_date"], row["scale"], "supported" if supported else "unsupported")
    )
    return hashlib.sha256(key.encode()).hexdigest()


def _excluded_cases() -> set[tuple[str, str]]:
    first = json.loads((FIRST_PACKET / "outcomes.json").read_text(encoding="utf-8"))
    second = json.loads((SECOND_PACKET / "sealed.json").read_text(encoding="utf-8"))
    return {(row["symbol"], row["signal_date"]) for row in [*first, *second]}


def main() -> int:
    candidates = _candidates()
    market = _market(
        candidates.get_column("symbol").unique().to_list(),
        candidates.get_column("signal_date").min() - timedelta(days=300),
        candidates.get_column("signal_date").max(),
    )
    excluded = _excluded_cases()
    represented = []
    for row in candidates.to_dicts():
        identity = (row["symbol"], row["signal_date"].isoformat())
        if row["signal_date"].year not in YEARS or identity in excluded:
            continue
        bars = market.get(row["symbol"])
        if bars is None:
            continue
        visible = bars.filter(bars["date"] <= row["signal_date"]).tail(160)
        if visible.height < 100 or visible.get_column("date")[-1] != row["signal_date"]:
            continue
        representation = represent_supply_waves(
            visible["high"].to_numpy(), visible["low"].to_numpy(), visible["close"].to_numpy(),
            visible["volume"].to_numpy(), visible["date"].to_numpy()
        )
        represented.append(
            {**row, "bars": visible, "representation": representation,
             "selection_hash": _selection_hash(row, representation["supported"])}
        )

    selected = []
    availability = {}
    for year in YEARS:
        availability[str(year)] = {}
        for supported in (True, False):
            status = "supported" if supported else "unsupported"
            group = [row for row in represented if row["signal_date"].year == year and row["representation"]["supported"] is supported]
            group.sort(key=lambda row: row["selection_hash"])
            availability[str(year)][status] = len(group)
            if len(group) < PER_STATUS_PER_YEAR:
                raise RuntimeError(f"not enough {status} cases for {year}: {len(group)}")
            selected.extend(group[:PER_STATUS_PER_YEAR])
    selected.sort(key=lambda row: (row["signal_date"].year, row["selection_hash"]))

    OUTPUT.mkdir(parents=True, exist_ok=False)
    manifest, sealed, labels = [], [], []
    for offset in range(0, len(selected), 6):
        page = offset // 6 + 1
        image = Image.new("RGB", PAGE_SIZE, "white")
        draw = ImageDraw.Draw(image)
        draw.text((55, 20), "Blind supply-wave v3 validation - status, identity and outcome hidden", fill="#111827", font=_font(30))
        draw.text((55, 58), "black: completed signal day | classify price and volume structure only", fill="#374151", font=_font(18))
        for local_index, row in enumerate(selected[offset : offset + 6]):
            case_id = f"W{offset + local_index + 1:02d}"
            column, panel_row = local_index % 2, local_index // 2
            panel_left, panel_top = 55 + column * 1165, 105 + panel_row * 605
            _draw_case(draw, (panel_left, panel_top, panel_left + 1125, panel_top + 575), case_id, row, show_structure=False)
            manifest.append({"case_id": case_id, "scale": row["scale"], "visible_bars": row["bars"].height,
                             "page": f"page-{page}.png", "panel": local_index + 1,
                             "selection_hash": row["selection_hash"]})
            sealed.append({"case_id": case_id, "symbol": row["symbol"], "signal_date": row["signal_date"].isoformat(),
                           "representation": row["representation"], "true_breakout_10_7_20": row["true_breakout_10_7_20"],
                           "return_40d": row["return_40d"], "mfe_40d": row["mfe_40d"]})
            labels.append({"case_id": case_id, "classification": None, "confidence": None,
                           "present": [], "missing_or_contrary": [], "note": None})
        image.save(OUTPUT / f"page-{page}.png")
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUTPUT / "sealed.json").write_text(json.dumps(sealed, indent=2), encoding="utf-8")
    (OUTPUT / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "cases": len(selected), "pages": (len(selected) + 5) // 6,
                      "availability": availability, "sealed_opened": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
