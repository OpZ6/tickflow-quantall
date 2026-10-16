"""情绪三件套 + 退潮/参与度/crash_signals + 连板生态。

从 QuantX computed.py 移植,替换 regime_builder。
数据来源: data/quantx/YYYYMMDD/*.json (collect_quantx.py 产出)
输出: data/quantx/YYYYMMDD/_computed.json

核心算法:
  - 情绪三件套: market_heat = 0.5*short_term + 0.5*trend
  - 短线情绪: 6 sub-scores (zt/seal/ld/adv/prem/height) + stretch 1.7
  - 趋势情绪: 4 sub-scores (ur/idx/vol/inflow) + stretch 1.3
  - 退潮: 4 signals (relay/seal/ladder/loss) absolute + 5d trend
  - 参与度: 4 conditions (height/ladder/volume/direction)
  - crash: 3 signals (broken/leader/plunge)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================
# 常量
# ============================================================

TREND_DISPLAY_DAYS = 20
EBB_BASELINE_DAYS = 5
EBB_MIN_HISTORY = 3

ADVANCE_SCORE_ANCHORS = [(0, 5), (8, 15), (12, 35), (15, 50), (19, 65), (24, 85), (32, 95)]

PARTICIPATION_HEIGHT_MIN = 4
PARTICIPATION_BOARD2_MIN = 3
PARTICIPATION_BOARD1_MIN = 50
PARTICIPATION_VOLUME_RATIO_MIN = 0.90
PARTICIPATION_MAINLINE_MIN = 8
PARTICIPATION_MAINLINE_SHARE = 0.12
PARTICIPATION_MIN_AVAILABLE = 3

EBB_ADVANCE_ABS_MAX = 12.0
EBB_PREMIUM_ABS_MAX = 0.0
EBB_ADVANCE_DROP_PP = 5.0
EBB_PREMIUM_DROP_PP = 1.0
EBB_SEAL_ABS_MAX = 65.0
EBB_SEAL_DROP_PP = 10.0
EBB_MAX_BOARD_MAX = 3
EBB_HEIGHT_DROP_BOARDS = 2
EBB_BOARD2_MIN = 3
EBB_LIMIT_DOWN_ABS_MIN = 20
EBB_DOWN_COUNT_ABS_MIN = 3000
EBB_LIMIT_DOWN_TREND_FLOOR = 10
EBB_LIMIT_DOWN_MEDIAN_MULTIPLIER = 2.0


# ============================================================
# 共享工具
# ============================================================


def _load_json(path: str | Path) -> dict:
    p = Path(path)
    if p.exists() and p.stat().st_size > 2:
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_optional_int(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_optional_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_percent(value) -> float | None:
    if value is None:
        return None
    return _as_optional_float(str(value).replace("%", "").strip())


def _lerp_score(value: float, anchors: list[tuple[float, float]]) -> float:
    """在锚点间线性插值；超出范围则夹到两端锚点的 y 值。"""
    try:
        x = float(value)
    except (TypeError, ValueError):
        x = 0.0
    if not anchors:
        return 0.0
    if x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            ratio = (x - x0) / (x1 - x0)
            return y0 + ratio * (y1 - y0)
    return anchors[-1][1]


def _stretch_around_mid(score: float, factor: float) -> int:
    """围绕 50 中枢线性拉伸,补偿组合方差收缩。"""
    stretched = 50 + (score - 50) * factor
    return round(max(0.0, min(100.0, stretched)))


def _zone_for_score(score: float) -> str:
    if score < 30: return "冰点"
    elif score < 40: return "偏冷"
    elif score < 60: return "正常"
    elif score < 70: return "偏热"
    else: return "过热"


def _max_board_from_ladder(ladder: dict) -> int:
    boards = []
    for key in (ladder or {}).keys():
        text = str(key).replace("板", "")
        if text.isdigit():
            boards.append(int(text))
    return max(boards) if boards else 0


def _with_zhangtingke_ladder(py: dict, ztk: dict, trade_date: str) -> dict:
    """Use the published ladder fallback when PyWencai has no current ladder."""
    py_limit = py.get("limit_up", {}) if isinstance(py, dict) else {}
    if isinstance(py_limit, dict) and py_limit.get("ladder"):
        return py
    if ztk.get("trade_date") != trade_date or not ztk.get("ladder_by_height"):
        return py

    merged = dict(py) if isinstance(py, dict) else {}
    merged_limit = dict(py_limit) if isinstance(py_limit, dict) else {}
    merged_limit["ladder"] = ztk["ladder_by_height"]
    if not merged_limit.get("stocks") and ztk.get("ladder_stocks"):
        merged_limit["stocks"] = ztk["ladder_stocks"]
    merged["limit_up"] = merged_limit
    return merged


def _dx_fallback(py: dict, dx: dict) -> dict:
    """pywencai 数据异常时 (limit_up=0 but dx>0),用 duanxianxia 值替代。"""
    dx_sent = dx.get("sentiment", {}) if isinstance(dx, dict) else {}
    py_lu = py.get("limit_up", {}) if isinstance(py, dict) else {}
    py_zt = py_lu.get("count", 0) if isinstance(py_lu, dict) else 0
    dx_zt_str = dx_sent.get("涨停家数", "0") if isinstance(dx_sent, dict) else "0"
    dx_zt = int(dx_zt_str) if dx_zt_str and str(dx_zt_str).isdigit() else 0
    dx_seal_str = dx_sent.get("今日封板率", "0") if isinstance(dx_sent, dict) else "0"
    dx_seal = float(dx_seal_str.replace("%", "")) if dx_seal_str else 0.0
    dx_height_str = dx_sent.get("连板高度", "0") if isinstance(dx_sent, dict) else "0"
    dx_height = int(dx_height_str) if dx_height_str and str(dx_height_str).isdigit() else 0
    dx_dt_str = dx_sent.get("跌停家数", "0") if isinstance(dx_sent, dict) else "0"
    dx_dt = int(dx_dt_str) if dx_dt_str and str(dx_dt_str).isdigit() else 0

    py_bad = (py_zt == 0 and dx_zt > 0)
    return {
        "py_bad": py_bad,
        "limit_up_count": dx_zt if py_bad else py_zt,
        "seal_rate": dx_seal if py_bad else py.get("seal_rate", 70) if isinstance(py, dict) else 70,
        "max_board": dx_height if py_bad else 0,
        "limit_down_count": dx_dt if py_bad else 0,
        "source": "duanxianxia(fallback)" if py_bad else "pywencai",
    }


# ============================================================
# 情绪三件套
# ============================================================


def _calc_short_term_sentiment(
    py: dict, dx: dict, advance_stats: dict | None = None, loss_effect: dict | None = None,
) -> dict:
    """短线/打板情绪 0-100。"""
    fb = _dx_fallback(py, dx)
    limit_up_count = fb["limit_up_count"]
    seal_rate = fb["seal_rate"]

    advance = advance_stats or _calc_advance_stats(py, dx)
    loss = loss_effect or _calc_loss_effect(py, dx, {})
    limit_down_count = _as_optional_int(loss.get("limit_down_count"))
    advance_rate = _as_optional_float(advance.get("advance_rate"))
    premium_rate = _as_optional_float(advance.get("premium_rate"))

    lu = py.get("limit_up", {})
    ladder = lu.get("ladder", {})
    max_board = _max_board_from_ladder(ladder)
    if max_board == 0 and fb["py_bad"]:
        max_board = fb["max_board"]

    zt_score = _lerp_score(limit_up_count, [(0, 5), (48, 15), (66, 35), (90, 50), (112, 65), (142, 85), (160, 95)])
    sr_score = _lerp_score(seal_rate, [(40, 5), (58, 15), (68, 35), (75, 50), (81, 65), (84, 85), (90, 95)])
    ld_score = (
        100 - _lerp_score(limit_down_count, [(0, 90), (5, 75), (11.5, 60), (21.75, 50), (39.35, 35), (60, 15), (100, 5)])
        if limit_down_count is not None else None
    )
    adv_score = _lerp_score(advance_rate, ADVANCE_SCORE_ANCHORS) if advance_rate is not None else None
    prem_score = (
        _lerp_score(premium_rate, [(-3, 5), (-0.65, 15), (0.76, 35), (1.51, 50), (2.48, 65), (4.17, 85), (6, 95)])
        if premium_rate is not None else None
    )
    height_score = _lerp_score(max_board, [(1, 10), (3, 30), (4, 50), (5, 70), (6, 85), (8, 95)])

    components = {
        "limit_up_count": (zt_score, 0.30),
        "seal_rate": (sr_score, 0.25),
        "limit_down_count": (ld_score, 0.15),
        "advance_rate": (adv_score, 0.15),
        "premium_rate": (prem_score, 0.10),
        "max_board": (height_score, 0.05),
    }
    available_weight = sum(w for s, w in components.values() if s is not None)
    raw_score = (
        sum(s * w for s, w in components.values() if s is not None) / available_weight
        if available_weight else 50.0
    )
    score = _stretch_around_mid(raw_score, 1.7)

    return {
        "score": score, "zone": _zone_for_score(score),
        "metric_semantics_version": 2,
        "inputs": {
            "limit_up_count": limit_up_count, "seal_rate": seal_rate,
            "limit_down_count": limit_down_count, "advance_rate": advance_rate,
            "premium_rate": premium_rate, "max_board": max_board,
        },
        "weights": {
            "limit_up_count": 0.30, "seal_rate": 0.25, "limit_down_count": 0.15,
            "advance_rate": 0.15, "premium_rate": 0.10, "max_board": 0.05,
        },
        "missing_metrics": [name for name, (s, _) in components.items() if s is None],
    }


def _calc_trend_sentiment(tu: dict, ak: dict) -> dict:
    """趋势/方向情绪 0-100。"""
    dm = tu.get("daily_market", {})
    up_ratio = dm.get("up_ratio", 50)

    sff = ak.get("sector_fund_flow") or []
    main_inflow_yi = round(sum(float(x.get("net_inflow_yi") or 0) for x in sff), 2) if sff else None

    ad = tu.get("advance_decline", {}).get("history", [])
    today_amount = dm.get("total_amount_yi", 0)
    if len(ad) >= 6:
        avg_5d = sum(d.get("total_amount_yi", 0) for d in ad[-6:-1]) / 5
        volume_ratio = (today_amount / avg_5d * 100) if avg_5d > 0 else 100
    else:
        volume_ratio = 100

    indexes = tu.get("indexes", {})
    sh = indexes.get("000001.SH", {})
    index_pct = sh.get("pct_chg", 0)

    ur_score = _lerp_score(up_ratio, [(0, 5), (17, 15), (26, 30), (40, 50), (59, 65), (72, 85), (100, 95)])
    idx_score = _lerp_score(index_pct, [(-3, 5), (-1.82, 15), (-0.59, 35), (0.11, 50), (0.63, 65), (1.40, 85), (2.5, 95)])
    vol_score = _lerp_score(volume_ratio, [(85, 10), (90, 20), (94, 35), (101, 50), (106, 65), (113, 80), (120, 90), (130, 95)])
    inflow_score = _lerp_score(
        main_inflow_yi if main_inflow_yi is not None else 0,
        [(-2500, 5), (-1750, 15), (-917, 35), (-415, 50), (-45, 65), (780, 85), (1200, 95)],
    )

    raw_score = ur_score * 0.40 + idx_score * 0.30 + vol_score * 0.15 + inflow_score * 0.15
    score = _stretch_around_mid(raw_score, 1.3)

    return {
        "score": score, "zone": _zone_for_score(score),
        "main_inflow_yi": main_inflow_yi,
        "inputs": {
            "up_ratio": up_ratio, "index_pct": index_pct,
            "volume_ratio": round(volume_ratio, 1), "main_inflow_yi": main_inflow_yi,
        },
        "weights": {"up_ratio": 0.40, "index_pct": 0.30, "volume_ratio": 0.15, "main_inflow_yi": 0.15},
    }


def _calc_market_heat(
    tu: dict, py: dict, dx: dict, ak: dict,
    short_term_sentiment: dict | None = None, trend_sentiment: dict | None = None,
) -> dict:
    """市场热度 0-100:短线情绪与趋势情绪各半混合。"""
    st = short_term_sentiment if short_term_sentiment is not None else _calc_short_term_sentiment(py, dx)
    tr = trend_sentiment if trend_sentiment is not None else _calc_trend_sentiment(tu, ak)
    score = round(st["score"] * 0.5 + tr["score"] * 0.5)
    return {
        "score": score, "zone": _zone_for_score(score),
        "main_inflow_yi": tr.get("main_inflow_yi"),
        "inputs": {
            "up_ratio": tr["inputs"]["up_ratio"],
            "limit_up_count": st["inputs"]["limit_up_count"],
            "seal_rate": st["inputs"]["seal_rate"],
            "volume_ratio": tr["inputs"]["volume_ratio"],
            "index_pct": tr["inputs"]["index_pct"],
        },
        "weights": {"up_ratio": 0.4, "limit_up_count": 0.2, "seal_rate": 0.15, "volume_ratio": 0.15, "index_pct": 0.1},
    }


# ============================================================
# 连板生态
# ============================================================


def _calc_advance_stats(py: dict, dx: dict | None = None) -> dict:
    """晋级/溢价统计。"""
    yp = py.get("yesterday_perf", {})
    dx_sentiment = (dx or {}).get("sentiment", {}) if isinstance(dx, dict) else {}
    version = _as_int(yp.get("metric_semantics_version"), 1)
    primary_ok = version >= 2 and yp.get("status") == "ok"
    advance_rate = _as_optional_float(yp.get("advance_rate")) if primary_ok else None
    primary_premium = _as_optional_float(yp.get("premium_rate")) if primary_ok else None
    fallback_premium = _parse_percent(dx_sentiment.get("昨涨停表现"))
    primary_lianban = _as_optional_float(yp.get("yesterday_lianban_premium")) if primary_ok else None
    fallback_lianban = _parse_percent(dx_sentiment.get("昨连板表现"))
    premium_rate = primary_premium if primary_premium is not None else fallback_premium
    lianban_premium = primary_lianban if primary_lianban is not None else fallback_lianban
    conflict = (
        primary_premium is not None and fallback_premium is not None
        and abs(primary_premium - fallback_premium) > 0.5
    )
    if conflict:
        source_quality = "conflict"
    elif primary_ok:
        source_quality = "primary"
    elif premium_rate is not None or lianban_premium is not None:
        source_quality = "fallback"
    else:
        source_quality = "unavailable"
    return {
        "metric_semantics_version": 2,
        "as_of": yp.get("as_of"),
        "source_quality": source_quality,
        "premium_rate": premium_rate,
        "advance_rate": advance_rate,
        "yesterday_limit_up_count": _as_optional_int(yp.get("count")) if primary_ok else None,
        "advance_sample_count": _as_optional_int(yp.get("advance_sample_count")) if primary_ok else None,
        "continued_count": _as_optional_int(yp.get("continued_count")) if primary_ok else None,
        "yesterday_lianban_premium": lianban_premium,
        "yesterday_zt_pct": premium_rate,
        "yesterday_lb_pct": lianban_premium,
    }


def _calc_loss_effect(py: dict, dx: dict, tu: dict) -> dict:
    """亏钱效应扫描。"""
    bb = py.get("broken_board", {})
    broken_count = bb.get("count", 0)
    broken_stocks = bb.get("stocks", [])

    dm = tu.get("daily_market", {})
    green_avg = _as_optional_float(dm.get("green_avg_pct"))
    down_count = _as_optional_int(dm.get("down_count"))

    primary_limit_down = py.get("limit_down", {}) if isinstance(py, dict) else {}
    primary_count = (
        _as_optional_int(primary_limit_down.get("count"))
        if primary_limit_down.get("status") == "ok" else None
    )
    ps = dx.get("pool_stats", {})
    fallback_count = _as_optional_int((ps.get("跌停") or {}).get("today")) if isinstance(ps, dict) else None
    dt_today = primary_count if primary_count is not None else fallback_count
    source_quality = "primary" if primary_count is not None else "fallback" if fallback_count is not None else "unavailable"
    if primary_count is not None and fallback_count is not None:
        tolerance = max(2, round(primary_count * 0.10))
        if abs(primary_count - fallback_count) > tolerance:
            source_quality = "conflict"
    rule_limit_down = dt_today if dt_today is not None else 0
    rule_down_count = down_count if down_count is not None else 0

    severity = "收敛"
    if rule_down_count > 3000 or rule_limit_down > 20 or broken_count > 40:
        severity = "蔓延"
    elif rule_down_count > 2000 or rule_limit_down > 10 or broken_count > 25:
        severity = "扩散"
    elif rule_down_count > 1000 or rule_limit_down > 5:
        severity = "稳定"

    return {
        "severity": severity,
        "broken_board_count": broken_count,
        "broken_board_stocks": [{"code": s.get("code"), "name": s.get("name")} for s in broken_stocks[:10]],
        "limit_down_count": dt_today,
        "limit_down_source_quality": source_quality,
        "down_count": down_count,
        "green_avg_pct": green_avg,
        "detail": {
            "broken_board_stocks": [
                {"code": s.get("code"), "name": s.get("name"), "reason": s.get("reason", "")}
                for s in broken_stocks[:20]
            ],
            "inputs": {
                "broken_board_count": broken_count,
                "limit_down_count": dt_today,
                "down_count": down_count,
                "green_avg_pct": green_avg,
            },
            "rule": "炸板>40或跌停>20或下跌>3000为蔓延；炸板>25或跌停>10或下跌>2000为扩散。",
        },
    }


def _build_height_trend(history_dir: Path, trade_date: str) -> dict:
    """20 日连板高度趋势。从历史目录读每日 pywencai/ths_hot/tushare/duanxianxia JSON。"""
    if not history_dir.exists():
        return {"days": [], "latest_max_board": 0, "previous_high_5d": None, "height_compressed": False, "evidence": ""}

    trade_date_int = int(trade_date) if str(trade_date).isdigit() else 0
    date_dirs = []
    for item in history_dir.iterdir():
        if not item.is_dir() or not item.name.isdigit():
            continue
        if trade_date_int and int(item.name) > trade_date_int:
            continue
        if (item / "pywencai.json").exists() or (item / "ths_hot.json").exists():
            date_dirs.append(item)

    date_dirs = sorted(date_dirs, key=lambda p: p.name)[-(TREND_DISPLAY_DAYS + 1):]

    days = []
    for d in date_dirs:
        snap = _history_day_snapshot(d, trade_date)
        if snap.get("data_ready"):
            days.append(snap)

    for day in days:
        if _as_int(day.get("metric_semantics_version"), 1) < 2:
            day["legacy_derived"] = True

    days = days[-TREND_DISPLAY_DAYS:]
    if not days:
        return {"days": [], "latest_max_board": 0, "previous_high_5d": None, "height_compressed": False, "evidence": ""}

    latest = days[-1]
    previous = days[:-1][-EBB_BASELINE_DAYS:]
    previous_high = max((d.get("max_board") or 0 for d in previous), default=None)
    latest_height = latest.get("max_board", 0)
    height_compressed = (
        previous_high is not None and latest_height < previous_high and latest_height <= 3
    )
    evidence = f"最高{latest_height}板，近5日前高{previous_high}板" if previous_high is not None else f"最高{latest_height}板"

    return {
        "days": days,
        "latest_max_board": latest_height,
        "previous_high_5d": previous_high,
        "height_compressed": height_compressed,
        "evidence": evidence,
    }


def _history_day_snapshot(day_dir: Path, trade_date: str) -> dict:
    """单日快照:从 pywencai/tushare/duanxianxia/ths_hot JSON 提取高度趋势数据。"""
    py = _load_json(str(day_dir / "pywencai.json"))
    tu = _load_json(str(day_dir / "tushare.json"))
    dx = _load_json(str(day_dir / "duanxianxia.json"))

    lu = py.get("limit_up", {})
    ladder = lu.get("ladder", {})
    yp = py.get("yesterday_perf", {})
    limit_down = py.get("limit_down", {})
    dx_sentiment = dx.get("sentiment", {}) if isinstance(dx, dict) else {}
    dx_pool_stats = dx.get("pool_stats", {}) if isinstance(dx, dict) else {}
    dx_limit_down = (dx_pool_stats.get("跌停") or {}).get("today") if isinstance(dx_pool_stats, dict) else None
    metric_version = _as_int(yp.get("metric_semantics_version"), 1)

    max_board = _max_board_from_ladder(ladder)
    board2_count = len(ladder.get("2", []))
    limit_up_count = lu.get("count", 0)
    seal_rate = py.get("seal_rate")
    limit_down_count = (
        _as_optional_int(limit_down.get("count")) if limit_down.get("status") == "ok" else _as_optional_int(dx_limit_down)
    )
    down_count = _as_optional_int((tu.get("daily_market") or {}).get("down_count"))
    index_pct = _as_optional_float(((tu.get("indexes") or {}).get("000001.SH") or {}).get("pct_chg"))

    py_date = str(py.get("trade_date") or day_dir.name)
    data_ready = bool(limit_up_count or max_board or limit_down_count)

    return {
        "date": py_date,
        "max_board": max_board,
        "board2_count": board2_count,
        "limit_up_count": limit_up_count,
        "limit_up_codes": sorted({s.get("code", "") for s in lu.get("stocks", []) if s.get("code")}),
        "metric_semantics_version": metric_version,
        "advance_rate": _as_optional_float(yp.get("advance_rate")),
        "premium_rate": _as_optional_float(yp.get("premium_rate")),
        "legacy_derived": False,
        "seal_rate": seal_rate,
        "limit_down_count": limit_down_count,
        "down_count": down_count,
        "index_pct": index_pct,
        "data_ready": data_ready,
    }


# ============================================================
# 退潮 / 参与度 / crash
# ============================================================


def _calc_participation_check(py: dict, dx: dict, tu: dict, th: dict | None = None) -> dict:
    """4 个参与度条件。"""
    fb = _dx_fallback(py, dx)
    lu = py.get("limit_up", {})
    ladder = lu.get("ladder", {})
    max_board = _max_board_from_ladder(ladder)
    if max_board == 0 and fb["py_bad"]:
        max_board = fb["max_board"]

    board2_count = len(ladder.get("2", []))
    board1_count = len(ladder.get("1", []))
    ladder_ok = board2_count >= PARTICIPATION_BOARD2_MIN and board1_count >= PARTICIPATION_BOARD1_MIN

    dm = tu.get("daily_market", {})
    today_amount = dm.get("total_amount_yi", 0)
    ad = tu.get("advance_decline", {}).get("history", [])
    if len(ad) >= 6:
        avg_5d = sum(d.get("total_amount_yi", 0) for d in ad[-6:-1]) / 5
        volume_ok = today_amount >= avg_5d * PARTICIPATION_VOLUME_RATIO_MIN
        volume_available = avg_5d > 0 and today_amount > 0
    else:
        avg_5d = None
        volume_ok = False
        volume_available = False

    themes = lu.get("themes", [])
    top_theme_count = _as_int(themes[0].get("count")) if themes else 0
    ths_tags = (th or {}).get("reason_tags", []) or []
    top_ths_count = _as_int(ths_tags[0].get("count")) if ths_tags else 0
    limit_up_count = fb["limit_up_count"]
    direction_threshold = (
        max(PARTICIPATION_MAINLINE_MIN, int(limit_up_count * PARTICIPATION_MAINLINE_SHARE + 0.999999))
        if limit_up_count > 0 else PARTICIPATION_MAINLINE_MIN
    )
    theme_strength = max(top_theme_count, top_ths_count)
    sh = (tu.get("indexes") or {}).get("000001.SH", {})
    sh_pct = _as_optional_float(sh.get("pct_chg"))
    index_up = sh_pct is not None and sh_pct > 0
    direction_available = sh_pct is not None and (
        not index_up or (bool(themes or ths_tags) and limit_up_count > 0)
    )
    direction_ok = (not index_up) or theme_strength >= direction_threshold

    height_available = bool(ladder) or fb["py_bad"]
    ladder_available = bool(ladder)

    conditions = {
        "height_ge_4": {"ok": max_board >= PARTICIPATION_HEIGHT_MIN if height_available else None, "available": height_available, "value": max_board},
        "ladder_complete": {"ok": ladder_ok if ladder_available else None, "available": ladder_available, "value": f"2板:{board2_count} 1板:{board1_count}"},
        "volume_stable": {
            "ok": volume_ok if volume_available else None,
            "available": volume_available,
            "value": f"今日{today_amount:.0f}亿" + (f"/5日均{avg_5d:.0f}亿" if avg_5d else ""),
        },
        "direction_aligned": {
            "ok": direction_ok if direction_available else None,
            "available": direction_available,
            "value": (
                f"上证{sh_pct:+.2f}% 主线{theme_strength}只/阈值{direction_threshold}"
                if sh_pct is not None else f"主线{theme_strength}只/阈值{direction_threshold}"
            ),
        },
    }
    available_count = sum(1 for item in conditions.values() if item.get("available"))
    satisfied = sum(1 for item in conditions.values() if item.get("ok") is True)
    if available_count < PARTICIPATION_MIN_AVAILABLE:
        verdict = "数据不足"
    elif satisfied >= 3:
        verdict = "参与"
    elif satisfied == 2:
        verdict = "脉冲处理"
    else:
        verdict = "规避"

    return {
        "conditions": conditions, "satisfied": satisfied,
        "available": available_count, "total": 4, "verdict": verdict,
    }


def _history_values(days: list[dict], key: str) -> list[float]:
    values = [_as_optional_float(day.get(key)) for day in days]
    return [v for v in values if v is not None]


def _mean_if_ready(values: list[float]) -> float | None:
    return sum(values) / len(values) if len(values) >= EBB_MIN_HISTORY else None


def _median_if_ready(values: list[float]) -> float | None:
    if len(values) < EBB_MIN_HISTORY:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _calc_ebb_risk_check(
    py: dict, dx: dict, tu: dict, height_trend: dict,
    advance_stats: dict, loss_effect: dict, suspension_impact: dict | None = None,
) -> dict:
    """4 个退潮风险信号 (absolute + 5d trend)。"""
    previous_days = (height_trend.get("days") or [])[:-1][-EBB_BASELINE_DAYS:]
    advance_rate = _as_optional_float(advance_stats.get("advance_rate"))
    premium_rate = _as_optional_float(advance_stats.get("premium_rate"))
    advance_mean = _mean_if_ready(_history_values(previous_days, "advance_rate"))
    premium_mean = _mean_if_ready(_history_values(previous_days, "premium_rate"))
    relay_absolute = (
        (advance_rate is not None and advance_rate < EBB_ADVANCE_ABS_MAX)
        or (premium_rate is not None and premium_rate < EBB_PREMIUM_ABS_MAX)
    )
    relay_trend = (
        advance_rate is not None and premium_rate is not None
        and advance_mean is not None and premium_mean is not None
        and advance_rate <= advance_mean - EBB_ADVANCE_DROP_PP
        and premium_rate <= premium_mean - EBB_PREMIUM_DROP_PP
    )

    fb = _dx_fallback(py, dx)
    dx_sentiment = dx.get("sentiment", {}) if isinstance(dx, dict) else {}
    seal_rate = (
        _parse_percent(dx_sentiment.get("今日封板率"))
        if fb["py_bad"] else _as_optional_float(py.get("seal_rate"))
    )
    seal_mean = _mean_if_ready(_history_values(previous_days, "seal_rate"))
    seal_absolute = seal_rate is not None and seal_rate < EBB_SEAL_ABS_MAX
    seal_trend = seal_rate is not None and seal_mean is not None and seal_rate <= seal_mean - EBB_SEAL_DROP_PP

    ladder = (py.get("limit_up") or {}).get("ladder", {})
    max_board = _max_board_from_ladder(ladder)
    if max_board == 0 and fb["py_bad"]:
        max_board = fb["max_board"]
    board2_count = len(ladder.get("2", []) or [])
    height_values = _history_values(previous_days, "max_board")
    previous_high = max(height_values) if len(height_values) >= EBB_MIN_HISTORY else None
    ladder_available = bool(ladder) or fb["py_bad"]
    ladder_absolute = ladder_available and max_board <= EBB_MAX_BOARD_MAX
    ladder_trend = (
        ladder_available and previous_high is not None
        and max_board <= previous_high - EBB_HEIGHT_DROP_BOARDS
        and board2_count < EBB_BOARD2_MIN
    )

    limit_down_count = _as_optional_int(loss_effect.get("limit_down_count"))
    down_count = _as_optional_int(loss_effect.get("down_count"))
    limit_down_median = _median_if_ready(_history_values(previous_days, "limit_down_count"))
    loss_absolute = (
        (limit_down_count is not None and limit_down_count > EBB_LIMIT_DOWN_ABS_MIN)
        or (down_count is not None and down_count > EBB_DOWN_COUNT_ABS_MIN)
    )
    loss_trend = (
        limit_down_count is not None and limit_down_median is not None
        and limit_down_count >= EBB_LIMIT_DOWN_TREND_FLOOR
        and limit_down_count >= limit_down_median * EBB_LIMIT_DOWN_MEDIAN_MULTIPLIER
    )

    si = suspension_impact or {}
    ladder_triggered = (ladder_absolute or ladder_trend) and not si.get("impact")
    signals = {
        "relay_payoff_weak": {
            "available": advance_rate is not None or premium_rate is not None,
            "triggered": relay_absolute or relay_trend,
            "value": {"advance_rate": advance_rate, "premium_rate": premium_rate},
            "baseline": {"advance_5d_mean": advance_mean, "premium_5d_mean": premium_mean},
        },
        "seal_quality_weak": {
            "available": seal_rate is not None,
            "triggered": seal_absolute or seal_trend,
            "value": seal_rate,
            "baseline": seal_mean,
        },
        "ladder_compressed": {
            "available": ladder_available,
            "triggered": ladder_triggered,
            "value": {"max_board": max_board, "board2_count": board2_count},
            "baseline": previous_high,
            "note": f"前高板股票已停牌（{'、'.join(si['suspended_high_board_names'])}），非退潮信号" if si.get("impact") else None,
        },
        "loss_effect_expanding": {
            "available": limit_down_count is not None or down_count is not None,
            "triggered": loss_absolute or loss_trend,
            "value": {"limit_down_count": limit_down_count, "down_count": down_count},
            "baseline": limit_down_median,
        },
    }
    available_count = sum(1 for item in signals.values() if item["available"])
    signal_count = sum(1 for item in signals.values() if item["available"] and item["triggered"])
    if available_count < 3:
        level = "unknown"
        verdict = "数据不足"
    elif signal_count == 0:
        level = "stable"
        verdict = "未见退潮"
    elif signal_count == 1:
        level = "localized"
        verdict = "局部转弱"
    elif signal_count == 2:
        level = "warning"
        verdict = "退潮预警"
    else:
        level = "confirmed"
        verdict = "退潮确认"

    return {
        "signals": signals, "signal_count": signal_count,
        "available": available_count, "total": 4,
        "level": level, "verdict": verdict, "baseline_days": EBB_BASELINE_DAYS,
    }


def _calc_crash_signals(
    py: dict, dx: dict, tu: dict,
    height_trend: dict | None = None, suspension_impact: dict | None = None,
) -> dict:
    """崩塌前兆 3 信号。"""
    dm = tu.get("daily_market", {})
    down_count = dm.get("down_count", 0)
    ps = dx.get("pool_stats", {})
    dt_today = int(ps.get("跌停", {}).get("today", 0)) if ps.get("跌停") else 0

    bb = py.get("broken_board", {})
    broken_count = bb.get("count", 0)
    s1_triggered = broken_count > 30

    lu = py.get("limit_up", {})
    ladder = lu.get("ladder", {})
    max_board = _max_board_from_ladder(ladder)
    previous_high = (height_trend or {}).get("previous_high_5d")
    si = suspension_impact or {}
    if si.get("impact") and previous_high is not None and max_board < previous_high:
        s2_triggered = False
        s2_status = "停牌中"
        s2_evidence = f"前高{previous_high}板股票已停牌（{'、'.join(si['suspended_high_board_names'])}），非断板"
    elif previous_high is None:
        s2_triggered = False
        s2_status = "历史不足"
        s2_evidence = f"最高{max_board}板，缺少近5日高度对照"
    else:
        s2_triggered = max_board < previous_high and max_board <= 3
        s2_status = "已触发" if s2_triggered else "待观察"
        s2_evidence = f"最高{max_board}板，近5日前高{previous_high}板"

    s3_triggered = down_count > 2000 and dt_today > 10

    return {
        "signals": [
            {"name": "领跌含近期强势股", "triggered": s1_triggered, "status": "已触发" if s1_triggered else "待观察", "evidence": f"炸板{broken_count}只"},
            {"name": "龙头断板未修复", "triggered": s2_triggered, "status": s2_status, "evidence": s2_evidence},
            {"name": "尾部放量跌停", "triggered": s3_triggered, "status": "已触发" if s3_triggered else "待观察", "evidence": f"跌{down_count}家 跌停{dt_today}只"},
        ],
        "any_triggered": s1_triggered or s2_triggered or s3_triggered,
    }


def _check_suspension_impact(history_dir: Path, trade_date: str, suspended_stocks: dict) -> dict:
    """检查前日高板股是否停牌。"""
    suspended = suspended_stocks or {}
    suspended_list = suspended.get("stocks") or []
    if not suspended_list:
        return {"impact": False, "suspended_high_board_names": [], "suspended_high_board_level": 0}
    suspended_names = {s.get("name", "") for s in suspended_list if s.get("name")}
    if not suspended_names or not str(trade_date).isdigit():
        return {"impact": False, "suspended_high_board_names": [], "suspended_high_board_level": 0}
    trade_date_int = int(trade_date)
    candidates = sorted(
        (p for p in history_dir.iterdir() if p.is_dir() and p.name.isdigit() and int(p.name) < trade_date_int),
        reverse=True,
    )
    for prev_dir in candidates:
        prev_py = _load_json(str(prev_dir / "pywencai.json"))
        if not isinstance(prev_py, dict) or not prev_py.get("limit_up"):
            continue
        prev_ladder = (prev_py.get("limit_up") or {}).get("ladder", {})
        if not prev_ladder:
            continue
        max_level = max((int(k) for k in prev_ladder if k.isdigit()), default=0)
        if max_level == 0:
            continue
        high_board_stocks = prev_ladder.get(str(max_level), [])
        matched = [n for n in high_board_stocks if n in suspended_names]
        if matched:
            return {"impact": True, "suspended_high_board_names": matched, "suspended_high_board_level": max_level}
        break
    return {"impact": False, "suspended_high_board_names": [], "suspended_high_board_level": 0}


# ============================================================
# 主入口
# ============================================================


def compute(data_dir: Path, history_dir: Path | None = None) -> dict:
    """情绪状态主入口。从 data_dir 读 JSON,输出 _computed.json。

    Args:
        data_dir: data/quantx/YYYYMMDD/ 目录
        history_dir: data/quantx/ 目录(含历史日期子目录)
    """
    data_dir = Path(data_dir)
    history_dir = Path(history_dir) if history_dir else data_dir.parent

    tu = _load_json(str(data_dir / "tushare.json"))
    raw_py = _load_json(str(data_dir / "pywencai.json"))
    dx = _load_json(str(data_dir / "duanxianxia.json"))
    ak = _load_json(str(data_dir / "akshare.json"))
    th = _load_json(str(data_dir / "ths_hot.json"))
    ztk = _load_json(str(data_dir / "zhangtingke.json"))
    ll = _load_json(str(data_dir / "legulegu.json"))

    trade_date = str(tu.get("trade_date") or raw_py.get("trade_date") or data_dir.name)
    py = _with_zhangtingke_ladder(raw_py, ztk, trade_date)

    height_trend = _build_height_trend(history_dir, trade_date)
    advance_stats = _calc_advance_stats(py, dx)
    loss_effect = _calc_loss_effect(py, dx, tu)
    short_term_sentiment = _calc_short_term_sentiment(py, dx, advance_stats, loss_effect)
    trend_sentiment = _calc_trend_sentiment(tu, ak)
    market_heat = _calc_market_heat(tu, py, dx, ak, short_term_sentiment, trend_sentiment)
    participation_check = _calc_participation_check(py, dx, tu, th)
    suspension_impact = _check_suspension_impact(history_dir, trade_date, tu.get("suspended_stocks", {}))
    ebb_risk_check = _calc_ebb_risk_check(py, dx, tu, height_trend, advance_stats, loss_effect, suspension_impact)
    crash_signals = _calc_crash_signals(py, dx, tu, height_trend, suspension_impact)

    result = {
        "trade_date": trade_date,
        "market_heat": market_heat,
        "short_term_sentiment": short_term_sentiment,
        "trend_sentiment": trend_sentiment,
        "advance_stats": advance_stats,
        "loss_effect": loss_effect,
        "participation_check": participation_check,
        "ebb_tide_check": {
            **participation_check,
            "legacy_semantics": "participation_check_v1_compat",
            "risk_verdict": "unknown",
        },
        "ebb_risk_check": ebb_risk_check,
        "crash_signals": crash_signals,
        "suspension_impact": suspension_impact,
        "height_trend": height_trend,
        "congestion": ll.get("congestion", {}) if isinstance(ll, dict) else {},
        "limit_ladder": _build_limit_ladder(py, ztk, trade_date),
        "zhangtingke_height": _build_zhangtingke_height(ztk, history_dir),
        "daily_summary": _build_daily_summary(market_heat, short_term_sentiment, trend_sentiment, advance_stats, loss_effect, participation_check, ebb_risk_check, crash_signals),
    }

    out_path = data_dir / "_computed.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("emotion_state → %s (heat=%s, st=%s, tr=%s)",
                out_path, market_heat["score"], short_term_sentiment["score"], trend_sentiment["score"])
    return result


def _build_limit_ladder(py: dict, ztk: dict, trade_date: str) -> dict:
    """连板梯队分布。优先用 zhangtingke,降级用 pywencai。"""
    if ztk.get("trade_date") == trade_date and ztk.get("ladder_by_height"):
        return {
            "source": "zhangtingke",
            "ladder_by_height": ztk["ladder_by_height"],
            "ladder_stocks": ztk.get("ladder_stocks", []),
        }
    lu = py.get("limit_up", {})
    return {
        "source": "pywencai",
        "ladder_by_height": lu.get("ladder", {}),
        "ladder_stocks": lu.get("stocks", []),
    }


def _build_zhangtingke_height(ztk: dict, history_dir: Path) -> dict:
    """涨停客高度图表数据。"""
    height_history = ztk.get("height_history", [])
    if not height_history:
        return {"available": False, "days": [], "latest": None}
    return {
        "available": True,
        "days": list(reversed(height_history)),
        "latest": height_history[0] if height_history else None,
        "source_urls": ztk.get("source_urls", {}),
    }


def _build_daily_summary(
    market_heat: dict, st: dict, tr: dict, advance: dict, loss: dict,
    participation: dict, ebb: dict, crash: dict,
) -> str:
    """规则化中文摘要。"""
    parts = []
    parts.append(f"市场热度{market_heat['score']}({market_heat['zone']})")
    parts.append(f"短线情绪{st['score']}({st['zone']})")
    parts.append(f"趋势情绪{tr['score']}({tr['zone']})")
    if advance.get("advance_rate") is not None:
        parts.append(f"晋级率{advance['advance_rate']}%")
    if advance.get("premium_rate") is not None:
        parts.append(f"溢价率{advance['premium_rate']}%")
    parts.append(f"亏钱效应{loss.get('severity', '未知')}")
    parts.append(f"参与度{participation.get('verdict', '未知')}")
    parts.append(f"退潮{ebb.get('verdict', '未知')}")
    if crash.get("any_triggered"):
        parts.append("崩塌信号已触发")
    return "；".join(parts)
