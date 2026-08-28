#!/usr/bin/env python3
"""Audit QuantX single-day frontend response consumers against V2 contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.quantx_data.review_contract import (  # noqa: E402
    classify_frontend_review_paths,
    extract_frontend_review_paths,
)


def main() -> int:
    pages = [
        REPO_ROOT / "frontend/src/pages/QuantXDashboard.tsx",
        REPO_ROOT / "frontend/src/pages/QuantXReview.tsx",
    ]
    paths = sorted(
        {
            path
            for page in pages
            for path in extract_frontend_review_paths(
                page.read_text(encoding="utf-8")
            )
        }
    )
    classification = classify_frontend_review_paths(paths)
    report = {
        "schema_version": "quantx-review-consumer-audit.v2",
        "consumers": [
            str(page.relative_to(REPO_ROOT)).replace("\\", "/")
            for page in pages
        ],
        "field_count": len(paths),
        "fields": paths,
        **classification,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if classification["missing"] or classification["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
