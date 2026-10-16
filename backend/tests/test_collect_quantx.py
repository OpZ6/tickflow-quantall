"""collect_quantx.py 采集器测试。

mock requests/playwright,不实际联网。测试 ths_hot/zhangtingke/pywencai/duanxianxia + JSON 写入。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_scripts = Path(__file__).resolve().parents[1].parent / "scripts"
sys.path.insert(0, str(_scripts))

from collect_quantx import (  # noqa: E402
    _extract_js_object,
    _float_or_none,
    _stock_code,
    _write_json,
    collect_pywencai,
    collect_ths_hot,
    collect_zhangtingke,
)

# ---- ths_hot ----

@patch("collect_quantx.requests.get")
def test_collect_ths_hot(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "errocode": 0,
        "data": [
            {"code": "600519", "name": "贵州茅台", "reason": "白酒+业绩", "zhangfu": "10.0",
             "huanshou": "1.5", "chengjiaoe": "1000000", "close": "1510", "zhangdie": "137",
             "ddejingliang": "50000", "market": "SH"},
        ],
    }
    mock_get.return_value = mock_resp

    result = collect_ths_hot("20260821")
    assert result["status"] == "ok"
    assert result["count"] == 1
    assert result["stocks"][0]["code"] == "600519"
    assert result["stocks"][0]["name"] == "贵州茅台"
    assert result["stocks"][0]["pct_chg"] == 10.0
    assert len(result["reason_tags"]) >= 1


@patch("collect_quantx.requests.get")
def test_collect_ths_hot_error(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"errocode": 1, "errormsg": "no data"}
    mock_get.return_value = mock_resp
    result = collect_ths_hot("20260821")
    assert result["status"] == "error"
    assert result["count"] == 0


# ---- zhangtingke ----

@patch("collect_quantx._ztk_fetch")
def test_collect_zhangtingke(mock_fetch):
    height_html = 'var lbgd_dict = {"lbgd_header": ["交易日期", "股票代码", "连板天数"], "lbgd_lst": [["20260821", "600519.SH", 3]]};'
    ladder_html = 'var dictData = {"lbtd_header": ["股票代码", "连板天数"], "lbtd_lst": [["600519.SH", 3]], "date": "20260821"};'
    mock_fetch.side_effect = [height_html, ladder_html]

    result = collect_zhangtingke("20260821")
    assert result["status"] == "ok"
    assert result["available"] is True
    assert len(result["height_history"]) == 1
    assert result["height_history"][0]["code"] == "600519"
    assert result["height_history"][0]["limit_times"] == 3
    assert result["ladder_by_height"]["3"][0]["code"] == "600519"
    assert result["today_height"].get("code") == "600519"


# ---- _extract_js_object ----

def test_extract_js_object_valid():
    text = 'var dictData = {"key": "value", "num": 42};'
    result = _extract_js_object(text, "dictData")
    assert result == {"key": "value", "num": 42}


def test_extract_js_object_missing():
    assert _extract_js_object("no var here", "dictData") == {}


def test_extract_js_object_nan():
    text = 'var data = {"val": NaN, "x": 1};'
    result = _extract_js_object(text, "data")
    assert result["val"] is None
    assert result["x"] == 1


# ---- pywencai (mock akshare) ----

@patch("collect_quantx._py_fetch_limit_up")
@patch("collect_quantx._py_fetch_broken_board")
@patch("collect_quantx._py_fetch_limit_down")
@patch("collect_quantx._py_fetch_yesterday_perf")
@patch("collect_quantx._py_fetch_new_high_100d")
def test_collect_pywencai(mock_nh, mock_yp, mock_ld, mock_bb, mock_lu):
    mock_lu.return_value = {"count": 80, "stocks": [], "ladder": {"3": ["C"]}, "themes": []}
    mock_bb.return_value = {"count": 5, "stocks": []}
    mock_ld.return_value = {"status": "ok", "count": 3, "stocks": []}
    mock_yp.return_value = {"status": "ok", "advance_rate": 15.0, "premium_rate": 2.0, "metric_semantics_version": 2}
    mock_nh.return_value = {"status": "unavailable", "stocks": []}

    result = collect_pywencai("20260821")
    assert result["trade_date"] == "20260821"
    assert result["limit_up"]["count"] == 80
    assert result["broken_board"]["count"] == 5
    assert result["seal_rate"] > 0
    assert result["broken_rate"] > 0


# ---- _float_or_none ----

def test_float_or_none():
    assert _float_or_none("1.5") == 1.5
    assert _float_or_none(None) is None
    assert _float_or_none("abc") is None


# ---- _stock_code ----

def test_stock_code():
    assert _stock_code("600519.SH") == "600519"
    assert _stock_code("000001.SZ") == "000001"
    assert _stock_code("600519") == "600519"
    assert _stock_code("") == ""


# ---- _write_json ----

def test_write_json(tmp_path):
    data = {"trade_date": "20260821", "status": "ok"}
    path = _write_json(data, "ths_hot", "20260821", tmp_path)
    assert path.exists()
    assert path.name == "ths_hot.json"
    assert "quantx" in str(path)
    assert "20260821" in str(path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["trade_date"] == "20260821"
