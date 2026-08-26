"""Chan theory analysis pipeline."""
from __future__ import annotations

from typing import Any

from app.chanlun.bi import _extract_bi, MIN_BI_LEN
from app.chanlun.bsp import detect_bsp
from app.chanlun.macd import macd
from app.chanlun.merge_klines import merge_klines
from app.chanlun.segment import build_segments
from app.chanlun.zhongshu import build_zhongshu


def analyze(candles: list[dict[str, Any]], min_bi_len: int = MIN_BI_LEN) -> dict[str, Any]:
    merged = merge_klines(candles)
    strokes, points = _extract_bi(candles, min_bi_len)
    segments = build_segments(strokes, enable_additional_splits=False)
    zhongshu = build_zhongshu(strokes, segments)
    zhongshu_seg = build_zhongshu(segments)
    macd_rows = macd(candles)
    bsp = detect_bsp(candles, strokes, zhongshu, macd_rows, segments, zhongshu_seg)
    return {
        "merged_klines": merged, "fenxing": points, "bi": strokes,
        "segments": segments, "zhongshu": zhongshu,
        "zhongshu_seg": zhongshu_seg, "macd": macd_rows, "bsp": bsp,
    }