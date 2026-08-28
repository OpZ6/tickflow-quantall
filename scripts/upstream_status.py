#!/usr/bin/env python3
"""Read-only upstream divergence and merge-readiness report."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HOTSPOTS = {
    "backend/app/main.py",
    "backend/app/jobs/daily_pipeline.py",
    "backend/app/api/pipeline.py",
    "backend/app/data_providers/custom/loader.py",
    "backend/app/strategy/engine.py",
    "frontend/src/router.tsx",
    "frontend/src/components/Layout.tsx",
    "frontend/src/lib/api.ts",
    "frontend/src/lib/queryKeys.ts",
    "frontend/package.json",
}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def build_report(root: Path, target: str) -> dict[str, object]:
    root = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    current = _git(root, "rev-parse", "HEAD")
    target_commit = _git(root, "rev-parse", "--verify", f"{target}^{{commit}}")
    base = _git(root, "merge-base", current, target_commit)
    left, right = _git(root, "rev-list", "--left-right", "--count", f"{target}...HEAD").split()
    local_paths = set(_git(root, "diff", "--name-only", f"{base}..HEAD").splitlines())
    upstream_paths = set(_git(root, "diff", "--name-only", f"{base}..{target}").splitlines())
    remotes = {
        line.split()[0]: line.split()[1]
        for line in _git(root, "remote", "-v").splitlines()
        if line.endswith("(fetch)")
    }
    dirty = [line for line in _git(root, "status", "--short").splitlines() if line]
    overlap = sorted(local_paths & upstream_paths)
    return {
        "repository": str(root),
        "current": current,
        "target": target,
        "target_commit": target_commit,
        "merge_base": base,
        "upstream_only_commits": int(left),
        "local_only_commits": int(right),
        "overlap": overlap,
        "hotspot_overlap": sorted(set(overlap) & HOTSPOTS),
        "dirty_entries": dirty,
        "remotes": remotes,
        "ready_for_merge_preview": not dirty,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="upstream/main")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.repo.resolve(), args.target)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"upstream status failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("TickFlow upstream status")
        print(f"current={str(report['current'])[:12]}")
        print(f"target={report['target']} ({str(report['target_commit'])[:12]})")
        print(f"merge_base={str(report['merge_base'])[:12]}")
        print(f"upstream_only={report['upstream_only_commits']}")
        print(f"local_only={report['local_only_commits']}")
        print(f"overlap={len(report['overlap'])}")
        print(f"hotspot_overlap={len(report['hotspot_overlap'])}")
        print(f"dirty_entries={len(report['dirty_entries'])}")
    if report["dirty_entries"] and not args.allow_dirty:
        print("merge readiness failed: commit or stash scoped work first", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
