#!/usr/bin/env python3
"""Validate authoritative docs and machine-readable data contracts."""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

AUTHORITATIVE_DOCS = (
    "architecture.md",
    "data-foundation.md",
    "custom-data-source.md",
    "plugin-development.md",
    "analysis-development.md",
    "upstream-sync.md",
)
INTERNAL_FACT_SOURCES = {
    "tickflow_enriched_aggregate",
    "enriched_ohlcv_proxy",
    "tickflow_published_fact",
    "quantx_deterministic_v1",
    "quantx_rule_screen_v1",
}
LINK_RE = re.compile(r"\[[^]]+\]\(([^)]+)\)")
PRODUCTION_ROOTS = (REPO_ROOT / "backend" / "app", REPO_ROOT / "frontend" / "src")
ALLOWED_SCRAPER_IMPORTERS = {
    Path("backend/app/quantx_data/collectors.py"),
    Path("backend/app/quantx_data/source_manager.py"),
}
FORBIDDEN_RUNTIME_PATTERNS = {
    "retired TickFlow directory": re.compile(r"tickflow-prototype-retired", re.IGNORECASE),
    "legacy QuantX service port": re.compile(r"(?:127\.0\.0\.1|localhost):8766", re.IGNORECASE),
    "absolute legacy QuantX path": re.compile(r"[A-Z]:[\\/][^\n\"']*(?:apps[\\/]quantx|quantx-review)", re.IGNORECASE),
}
DIRECT_SCRAPER_IMPORT_RE = re.compile(
    r"(?:from|import|import_module\()[^\n]*(?:quantx_data\.)?legacy_scrapers"
)


def _markdown_link_errors(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    for target in LINK_RE.findall(text):
        clean = target.split("#", 1)[0].strip()
        if not clean or clean.startswith(("http://", "https://", "mailto:")):
            continue
        if not (path.parent / clean).resolve().exists():
            errors.append(f"{path.relative_to(REPO_ROOT)}: broken link {target}")
    return errors


def validate() -> list[str]:
    from app.market_facts.registry import ROUTES, validate_registry_contracts
    from app.quantx_data.collectors import SOURCE_MANAGER

    errors: list[str] = []
    for root in PRODUCTION_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                continue
            relative = path.relative_to(REPO_ROOT)
            if "legacy_scrapers" in relative.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for label, pattern in FORBIDDEN_RUNTIME_PATTERNS.items():
                if pattern.search(text):
                    errors.append(f"{relative.as_posix()}: forbidden {label}")
            if relative not in ALLOWED_SCRAPER_IMPORTERS and DIRECT_SCRAPER_IMPORT_RE.search(text):
                errors.append(f"{relative.as_posix()}: business layer imports a legacy scraper directly")
    docs_root = REPO_ROOT / "docs"
    index = docs_root / "README.md"
    if not index.is_file():
        errors.append("docs/README.md is missing")
        index_text = ""
    else:
        index_text = index.read_text(encoding="utf-8")
    for name in AUTHORITATIVE_DOCS:
        path = docs_root / name
        if not path.is_file():
            errors.append(f"docs/{name} is missing")
            continue
        if f"({name})" not in index_text:
            errors.append(f"docs/README.md does not link {name}")
        errors.extend(_markdown_link_errors(path))
    if index.is_file():
        errors.extend(_markdown_link_errors(index))

    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for name in AUTHORITATIVE_DOCS:
        if f"docs/{name}" not in agents:
            errors.append(f"AGENTS.md does not route to docs/{name}")

    errors.extend(validate_registry_contracts())
    registered = {spec.name for spec in SOURCE_MANAGER.specs} | INTERNAL_FACT_SOURCES
    for dataset_id, route in ROUTES.items():
        for source_id in route.sources:
            if source_id not in registered:
                errors.append(
                    f"{dataset_id.value}: route source is not registered: {source_id}"
                )
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("PROJECT_CONTRACTS_INVALID")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PROJECT_CONTRACTS_OK")
    print(f"authoritative_docs={len(AUTHORITATIVE_DOCS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
