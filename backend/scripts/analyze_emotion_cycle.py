"""情绪周期：用自有历史回算 6 阶段 + 同景矩阵（连板网 qingxu.html 的口径对照）。

输出用于 docs/analysis/quantx-emotion-cycle-vs-lianban.md 里的数字，可复现。

温度 = 短线情绪分（与 app/services/emotion_state.py 同锚点，去掉溢价子项，因为
regime_history 没有 premium_rate）。

阶段 = 温度在「滚动 250 日分位」中的位置 + 3 日温度变化方向。用滚动分位而不是固定
阈值，是因为 2026 年涨停家数整体上移，固定阈值（现网 phase 用的 p90×2=220 首板）
已经打不出标签 —— 现网 2026 年 89.9% 的日子都被兜底成 repair。
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import polars as pl

from app.tickflow.repository import DataStore, KlineRepository

STAGES = ("ice", "repair", "ignite", "rally", "climax", "ebb")
STAGE_LABELS = {
    "ice": "冰点",
    "repair": "修复",
    "ignite": "升温",
    "rally": "主升",
    "climax": "高潮",
    "ebb": "退潮",
}


def lerp(value: float, anchors: list[tuple[float, float]]) -> float:
    if value <= anchors[0][0]:
        return anchors[0][1]
    if value >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= value <= x1:
            return y0 + (value - x0) / (x1 - x0) * (y1 - y0)
    return anchors[-1][1]


def temperature(rows: list[dict]) -> list[float]:
    out: list[float] = []
    for row in rows:
        limit_up = row["limit_up"] or 0
        seal = (row["seal_rate"] or 0) * 100
        limit_down = row["limit_down"] or 0
        height = row["max_consecutive"] or 0
        breadth = (
            row["up_count"] / (row["up_count"] + row["down_count"]) * 100
            if (row["up_count"] or 0) + (row["down_count"] or 0) > 0
            else 50.0
        )
        parts = [
            (lerp(limit_up, [(0, 5), (48, 15), (66, 35), (90, 50), (112, 65), (142, 85), (160, 95)]), 0.30),
            (lerp(seal, [(40, 5), (58, 15), (68, 35), (75, 50), (81, 65), (84, 85), (90, 95)]), 0.25),
            (100 - lerp(limit_down, [(0, 90), (5, 75), (11.5, 60), (21.75, 50), (39.35, 35), (60, 15), (100, 5)]), 0.15),
            (lerp(breadth, [(0, 5), (8, 15), (12, 35), (15, 50), (19, 65), (24, 85), (32, 95)]), 0.20),
            (lerp(height, [(1, 10), (3, 30), (4, 50), (5, 70), (6, 85), (8, 95)]), 0.10),
        ]
        raw = sum(score * weight for score, weight in parts)
        out.append(max(0.0, min(100.0, 50 + (raw - 50) * 1.7)))
    return out


def stage_series(temps: list[float], window: int = 250) -> list[str]:
    """温度在滚动窗口内的分位 + 3 日温度变化 → 阶段。"""
    stages: list[str] = []
    for index, temp in enumerate(temps):
        history = temps[max(0, index - window): index] or [temp]
        rank = sum(1 for value in history if value <= temp) / len(history)
        delta = temp - (temps[index - 3] if index >= 3 else temp)
        if rank <= 0.10:
            stage = "ice"
        elif rank <= 0.30:
            stage = "repair" if delta > 3 else "ebb"
        elif rank <= 0.55:
            stage = "ignite" if delta > 5 else ("ebb" if delta < -5 else "repair")
        elif rank <= 0.80:
            stage = "ignite" if delta > 3 else ("climax" if delta >= 0 else "rally")
        else:
            stage = "climax" if delta >= -3 else "rally"
        stages.append(stage)
    return stages


def runs(stages: list[str]) -> list[tuple[str, int]]:
    """连续段: (stage, 长度)。"""
    out: list[tuple[str, int]] = []
    for stage in stages:
        if out and out[-1][0] == stage:
            out[-1] = (stage, out[-1][1] + 1)
        else:
            out.append((stage, 1))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2015-01-05")
    args = parser.parse_args()

    store = DataStore()
    repo = KlineRepository(store)
    df = pl.read_parquet(Path(store.data_dir) / "regime_history" / "part.parquet").sort("date")
    df = df.filter(pl.col("date") >= date.fromisoformat(args.start))
    rows = df.to_dicts()
    temps = temperature(rows)
    stages = stage_series(temps)

    # 上证收盘 + 250 日年线，用于牛熊分层
    sh = repo.get_index_daily("000001.SH", date(2014, 6, 1), df["date"].max(), columns=["date", "close"])
    sh = sh.sort("date").with_columns(pl.col("close").rolling_mean(250).alias("ma250"))
    ma_by_date = {r["date"]: r["ma250"] for r in sh.to_dicts()}
    sh_close = {r["date"]: r["close"] for r in sh.to_dicts()}
    sh_pct = {r["date"]: r["index_pct"] for r in rows}

    print(f"== 样本 {len(rows)} 个交易日 {rows[0]['date']} → {rows[-1]['date']}")
    counts = Counter(stages)
    segments = runs(stages)
    seg_len: dict[str, list[int]] = defaultdict(list)
    for stage, length in segments:
        seg_len[stage].append(length)
    print("\n== 阶段分布 / 持续天数")
    print(f"{'阶段':<6}{'天数':>6}{'占比':>8}{'段数':>6}{'平均':>7}{'最长':>6}")
    for stage in STAGES:
        days = counts.get(stage, 0)
        lengths = seg_len.get(stage, [])
        print(
            f"{STAGE_LABELS[stage]:<6}{days:>6}{days / len(stages) * 100:>7.1f}%{len(lengths):>6}"
            f"{(sum(lengths) / len(lengths) if lengths else 0):>7.1f}{(max(lengths) if lengths else 0):>6}"
        )

    print("\n== 阶段转移矩阵 (行=今日, 列=次日, %)")
    header = "".join(f"{STAGE_LABELS[s]:>8}" for s in STAGES)
    print(f"{'今日\\次日':<8}{header}")
    for left in STAGES:
        counter: Counter[str] = Counter()
        for index in range(len(stages) - 1):
            if stages[index] == left:
                counter[stages[index + 1]] += 1
        total = sum(counter.values()) or 1
        cells = "".join(f"{counter.get(right, 0) / total * 100:>7.1f}%" for right in STAGES)
        print(f"{STAGE_LABELS[left]:<8}{cells}  n={total}")

    print("\n== 同景矩阵: 阶段连续第 k 天 → 次日表现")
    print(f"{'阶段':<6}{'连续':>5}{'样本':>6}{'次日上证':>9}{'上涨率':>8}{'后3日':>8}{'Δ温度':>8}  次日去向")
    for stage in STAGES:
        for k in (1, 2, 3, 4):
            bucket = []
            for index in range(len(stages) - 3):
                if stages[index] != stage:
                    continue
                # 该日处于本阶段连续第 k 天
                run_start = index
                while run_start > 0 and stages[run_start - 1] == stage:
                    run_start -= 1
                if index - run_start + 1 != k:
                    continue
                bucket.append(index)
            if len(bucket) < 3:
                continue
            nxt = [sh_pct.get(rows[i + 1]["date"]) for i in bucket]
            nxt = [value for value in nxt if value is not None]
            cum3 = []
            for i in bucket:
                total = 1.0
                for offset in (1, 2, 3):
                    pct = sh_pct.get(rows[i + offset]["date"]) or 0
                    total *= 1 + pct
                cum3.append(total - 1)
            d_temp = [temps[i + 1] - temps[i] for i in bucket]
            downs = Counter(stages[i + 1] for i in bucket)
            top_text = " / ".join(
                f"{STAGE_LABELS[name]}{count / len(bucket) * 100:.0f}%"
                for name, count in downs.most_common(2)
            )
            label = "≥4天" if k == 4 else f"第{k}天"
            print(
                f"{STAGE_LABELS[stage]:<6}{label:>5}{len(bucket):>6}"
                f"{sum(nxt) / len(nxt) * 100:>8.2f}%{sum(1 for v in nxt if v > 0) / len(nxt) * 100:>7.0f}%"
                f"{sum(cum3) / len(cum3) * 100:>7.2f}%{sum(d_temp) / len(d_temp):>8.1f}"
                f"  {top_text}"
            )

    print("\n== 冰点期按牛熊分层 (次日上证)")
    for side in ("年线上方", "年线下方"):
        picked = []
        for index in range(len(stages) - 1):
            if stages[index] != "ice":
                continue
            ma = ma_by_date.get(rows[index]["date"])
            close = sh_close.get(rows[index]["date"])
            if ma is None or close is None:
                continue
            above = close >= ma
            if (side == "年线上方") != above:
                continue
            pct = sh_pct.get(rows[index + 1]["date"])
            if pct is not None:
                picked.append(pct)
        if picked:
            print(
                f"  {side}: n={len(picked):<4} 次日均值 {sum(picked) / len(picked) * 100:+.2f}%"
                f" 上涨率 {sum(1 for v in picked if v > 0) / len(picked) * 100:.0f}%"
            )


if __name__ == "__main__":
    main()
