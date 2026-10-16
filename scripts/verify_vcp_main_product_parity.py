"""Compare the full product run with the frozen per-entry execution ledger."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from research_cup_fresh_pivot_cross import summarize  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--raw-midpoints", action="store_true")
    args = parser.parse_args()
    run = ROOT / "data/research/vcp/runs" / args.run_id
    result = json.loads((run / "result.json").read_text(encoding="utf-8"))
    reference = "vcp-frozen-chronology-rebase-v1" + ("-raw-midpoints" if args.raw_midpoints else "")
    frozen = json.loads((ROOT / "data/research/vcp" / reference / "ledger.json").read_text(encoding="utf-8"))
    def key(t):
        return t["symbol"], t["entry_signal_date"], t["entry_date"]
    actual = {key(t): t for t in result["trades"]}
    expected = {key(r["corrected_full_breakeven"]): r for r in frozen}
    if len(actual) != len(result["trades"]):
        raise ValueError("Duplicate product event keys")
    missing, extra = sorted(expected.keys() - actual.keys()), sorted(actual.keys() - expected.keys())
    fields = ("entry_price", "exit_date", "exit_price", "pnl_pct", "duration", "blocked_exit_days")
    mismatches = [{"key": k, "field": f, "product": actual[k][f], "research": expected[k]["corrected_full_breakeven"][f]}
                  for k in sorted(actual.keys() & expected.keys()) for f in fields
                  if actual[k][f] != expected[k]["corrected_full_breakeven"][f]]
    report = {"run_id": args.run_id, "reference": reference, "product_trades": len(actual), "expected_trades": len(expected),
              "missing": missing, "extra": extra, "mismatches": mismatches,
              "exit_reasons": dict(Counter(t["exit_reason"] for t in actual.values())),
              "scope": "Full-universe product execution vs independently reconstructed frozen membership and fills; exposed history",
              "periods": {period: summarize([actual[k] for k, r in expected.items() if k in actual and r["period"] == period])
                          for period in ("training", "exposed_validation")},
              "passed": not (missing or extra or mismatches or result.get("error"))}
    (ROOT / "docs/research/vcp/vcp-main-product-parity-v1-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (run / "main-product-parity.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "periods"}), flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
