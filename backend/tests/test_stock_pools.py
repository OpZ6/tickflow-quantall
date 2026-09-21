from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import polars as pl
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.stock_pools import router
from app.market_facts.builders import _build_security_popularity, _build_stock_logic_evidence
from app.quantx_data.legacy_scrapers.fuyao_anomaly_scraper import run as collect_anomaly
from app.quantx_data.legacy_scrapers.security_popularity_scraper import run as collect_popularity
from app.stock_pools.repository import StockPoolRepository
from app.stock_pools.rules import build_candidates
from app.stock_pools.service import StockPoolService
from app.stock_pools.topic_cluster import build_topic_assignment, parse_normalization
from app.stock_pools.topics import theme_level, topic_labels


class _Facts:
    def __init__(self, popularity: pl.DataFrame | None = None, logic: pl.DataFrame | None = None) -> None:
        self.popularity = popularity if popularity is not None else pl.DataFrame()
        self.logic = logic if logic is not None else pl.DataFrame()

    def get_limit_events(self, _day):
        return pl.DataFrame()

    def get_limit_ladder(self, _day):
        return pl.DataFrame()

    def get_security_popularity(self, _day):
        return self.popularity

    def get_theme_members(self, _day):
        return pl.DataFrame()

    def get_stock_logic_evidence(self, _day):
        return self.logic


def _history() -> tuple[pl.DataFrame, date]:
    start = date(2025, 1, 1)
    days = [start + timedelta(days=index) for index in range(300)]
    rows = []
    for symbol, amount, turnover in (("000001.SZ", 2e8, 2.0), ("000002.SZ", 5e7, .5)):
        for index, day in enumerate(days):
            close = 10 + index * .01
            if index == len(days) - 1:
                close += 3
            rows.append({
                "symbol": symbol, "date": day, "open": close * .98,
                "high": close * 1.01, "low": close * .97, "close": close,
                "raw_close": close * 2,
                "volume": 2e7, "amount": amount, "turnover_rate": turnover,
            })
    return pl.DataFrame(rows), days[-1]


def test_rules_use_repository_inputs_and_apply_common_filter():
    history, trade_date = _history()
    instruments = pl.DataFrame({
        "symbol": ["000001.SZ", "000002.SZ"], "name": ["甲公司", "乙公司"],
        "exchange": ["SZ", "SZ"], "total_shares": [1e9, 1e9],
    })
    popularity = pl.DataFrame({
        "symbol": ["000001"], "rank": [30], "source_name": ["ths"], "source": ["security_popularity"],
    })
    candidates, details, metadata = build_candidates(history, instruments, _Facts(popularity), trade_date)
    assert metadata["eligible_count"] == 1
    assert [row["symbol"] for row in candidates] == ["000001.SZ"]
    assert {"breakthrough", "popularity_warm"}.issubset(candidates[0]["source_ids"])
    assert candidates[0]["price"] == round(history.filter(pl.col("symbol") == "000001.SZ")["raw_close"][-1], 2)
    assert candidates[0]["pct_chg"] > 10
    assert candidates[0]["market_cap_yi"] > 300
    assert candidates[0]["evidence"]
    assert candidates[0]["observation_window"]
    assert metadata["market_count"] == 2
    assert details["000001.SZ"]["source_events"]


def test_popularity_builder_preserves_independent_source_ranks():
    batch = _build_security_popularity(
        "20260914",
        {"security_popularity": {"records": [
            {"source_root": "ths", "code": "000001", "rank": 21, "observed_at": "2026-09-14T15:30:00+08:00"},
            {"source_root": "baidu", "code": "000001", "rank": 55, "observed_at": "2026-09-14T15:40:00+08:00"},
        ]}},
        "test-run", datetime.now(UTC).isoformat(),
    )
    assert batch.frame.height == 2
    assert set(batch.frame["source_name"].to_list()) == {"ths", "baidu"}
    assert set(batch.frame["source"].to_list()) == {"security_popularity"}


def test_live_popularity_collector_refuses_historical_relabeling(tmp_path):
    payload = collect_popularity("20000101", str(tmp_path))
    assert payload["status"] == "unavailable"
    assert payload["records"] == []
    assert json.loads((tmp_path / "security_popularity.json").read_text(encoding="utf-8"))["trade_date"] == "20000101"


def test_live_anomaly_collector_refuses_historical_relabeling(tmp_path):
    payload = collect_anomaly("20000101", str(tmp_path))
    assert payload["status"] == "unavailable"
    assert payload["records"] == []
    assert json.loads((tmp_path / "fuyao_anomaly.json").read_text(encoding="utf-8"))["trade_date"] == "20000101"


def test_topic_rules_merge_synonyms_and_specific_labels():
    assert topic_labels("PCB+HDI+覆铜板") == ["PCB／覆铜板"]
    assert topic_labels("网络安全+数据安全") == ["网络／AI安全"]
    assert topic_labels("人形机器人+减速器") == ["人形机器人"]
    assert topic_labels("医药+CRO") == ["创新药／CRO"]
    assert topic_labels("普通公告") == []
    assert theme_level("PCB概念") == "theme"
    assert theme_level("人工智能") == "industry"
    assert theme_level("一带一路") == "background"


def test_logic_evidence_builder_merges_three_sources():
    ladder = pl.DataFrame({
        "symbol": ["000001", "000002"],
        "name": ["甲公司", "乙公司"],
        "theme_name": ["PCB概念", "其他"],
        "theme_reason": ["覆铜板涨价", ""],
        "interpretation": ["公司PCB业务受益", ""],
        "observed_at": ["2026-09-14T15:00:00+08:00", "2026-09-14T15:00:00+08:00"],
    })
    sources = {
        "ths_hot": {"scraped_at": "2026-09-14T21:53:15", "stocks": [{"code": "000003", "name": "丙公司", "reason": "网络安全+数据安全"}]},
        "fuyao_anomaly": {"scraped_at": "2026-09-14T14:52:30+08:00", "records": [{
            "thscode": "000004.SZ", "stock_name": "丁公司",
            "analysis_content": "公司公告称上半年营收下降",
            "keyword_list": ["消费板块下跌", "此前上涨"], "tag_name": "跌停",
        }]},
    }
    batch = _build_stock_logic_evidence("20260914", sources, ladder, "run-1", "2026-09-14T16:00:00+00:00")
    rows = {row["symbol"]: row for row in batch.frame.to_dicts()}
    assert batch.frame.height == 4
    assert rows["000001"]["match_text"] == "PCB概念"
    assert rows["000001"]["text"] == "公司PCB业务受益"
    assert rows["000001"]["catalyst"] == "覆铜板涨价"
    assert rows["000003"]["match_text"] == "网络安全+数据安全"
    assert rows["000004"]["match_text"] == "消费板块下跌+此前上涨"
    assert rows["000004"]["keywords"] == "消费板块下跌+此前上涨"
    assert rows["000004"]["tag"] == "跌停"
    assert rows["000004"]["text"] == "公司公告称上半年营收下降"
    assert set(batch.frame["source"].to_list()) == {"stock_logic_evidence"}


def test_logic_evidence_hot_list_fallback_dedupes_against_anomaly():
    sources = {
        "security_popularity": {
            "scraped_at": "2026-09-15T23:31:00+08:00",
            "records": [
                {"source_root": "ths", "code": "000004", "name": "丁公司", "rank": 1, "reason": "消费板块下跌", "observed_at": "2026-09-15T23:31:00+08:00"},
                {"source_root": "ths", "code": "000005", "name": "戊公司", "rank": 2, "reason": "零售板块下跌", "observed_at": "2026-09-15T23:31:00+08:00"},
                {"source_root": "xueqiu", "code": "000006", "name": "己公司", "rank": 3, "reason": "雪球理由", "observed_at": "2026-09-15T23:31:00+08:00"},
            ],
        },
        "fuyao_anomaly": {
            "scraped_at": "2026-09-15T14:52:30+08:00",
            "records": [{
                "thscode": "000004.SZ", "stock_name": "丁公司",
                "analysis_content": "消费板块下跌", "keyword_list": ["消费板块下跌"], "tag_name": "跌停",
            }],
        },
    }
    batch = _build_stock_logic_evidence("20260915", sources, pl.DataFrame(), "run-1", "2026-09-15T16:00:00+00:00")
    rows = {row["symbol"]: row for row in batch.frame.to_dicts()}
    assert set(rows) == {"000004", "000005"}
    assert rows["000004"]["evidence_source"] == "fuyao_anomaly"
    assert rows["000004"]["is_fallback"] is False
    assert rows["000005"]["evidence_source"] == "ths_hot_list"
    assert rows["000005"]["match_text"] == "零售板块下跌"
    assert rows["000005"]["is_fallback"] is True
    assert rows["000005"]["quality_level"] == "fallback"


def test_dynamic_topic_cluster_merges_legacy_synonyms_and_filters_noise():
    rows = [
        {"symbol": "000001", "evidence_source": "ths_hot_concepts", "match_text": "光通信", "text": ""},
        {"symbol": "000002", "evidence_source": "ths_hot_concepts", "match_text": "CPO", "text": ""},
        {"symbol": "000003", "evidence_source": "ths_hot_concepts", "match_text": "风电", "text": ""},
        {"symbol": "000004", "evidence_source": "ths_hot_concepts", "match_text": "风电", "text": ""},
        {"symbol": "000005", "evidence_source": "ths_hot_concepts", "match_text": "业绩增长", "text": ""},
        {"symbol": "000006", "evidence_source": "ths_hot_concepts", "match_text": "业绩增长", "text": ""},
    ]
    assignment = build_topic_assignment(rows)
    assert assignment.meta["mode"] == "deterministic"
    assert assignment.topics["000001"] == ["光互联"]
    assert assignment.topics["000002"] == ["光互联"]
    assert assignment.topics["000003"] == ["风电"]
    assert assignment.topics["000004"] == ["风电"]
    assert "000005" not in assignment.topics
    assert "000006" not in assignment.topics


def test_dynamic_topic_cluster_keeps_specific_legacy_labels_apart():
    rows = [
        {"symbol": "000001", "evidence_source": "fuyao_anomaly", "match_text": "人形机器人+机器人", "text": ""},
        {"symbol": "000002", "evidence_source": "fuyao_anomaly", "match_text": "人形机器人+机器人", "text": ""},
        {"symbol": "000003", "evidence_source": "fuyao_anomaly", "match_text": "机器人", "text": ""},
    ]
    assignment = build_topic_assignment(rows)
    assert assignment.topics["000001"] == ["人形机器人"]
    assert assignment.topics["000002"] == ["人形机器人"]
    assert assignment.topics["000003"] == ["机器人"]
    assert assignment.meta["label_count"] == 2


def test_dynamic_topic_cluster_exposes_subgroups_for_merged_labels():
    rows = [
        {"symbol": "000001", "evidence_source": "ths_hot_concepts", "match_text": "光通信", "text": ""},
        {"symbol": "000002", "evidence_source": "ths_hot_concepts", "match_text": "光通信", "text": ""},
        {"symbol": "000003", "evidence_source": "ths_hot_concepts", "match_text": "CPO", "text": ""},
        {"symbol": "000004", "evidence_source": "ths_hot_concepts", "match_text": "CPO", "text": ""},
    ]
    assignment = build_topic_assignment(rows)
    assert assignment.topics["000001"] == ["光互联"]
    assert assignment.subgroups["光互联"] == [
        {"name": "CPO", "count": 2, "symbols": ["000003", "000004"]},
        {"name": "光通信", "count": 2, "symbols": ["000001", "000002"]},
    ]


def test_dynamic_topic_cluster_applies_and_reuses_llm_normalization():
    rows = [
        {"symbol": "000001", "evidence_source": "ths_hot_concepts", "match_text": "风电;海工装备", "text": "海上风电"},
        {"symbol": "000002", "evidence_source": "ths_hot_concepts", "match_text": "风电", "text": ""},
        {"symbol": "000003", "evidence_source": "ths_hot_concepts", "match_text": "海工装备", "text": ""},
    ]
    calls: list[list[dict]] = []

    def fake(payload: list[dict]) -> dict:
        calls.append(payload)
        return {"aliases": {"海工装备": "风电"}, "drop": []}

    assignment = build_topic_assignment(rows, normalizer=fake)
    assert assignment.meta["mode"] == "llm"
    assert assignment.meta["aliases"] == {"海工装备": "风电"}
    assert assignment.topics["000001"] == ["风电"]
    assert assignment.topics["000002"] == ["风电"]
    assert assignment.topics["000003"] == ["风电"]
    assert len(calls) == 1

    reused = build_topic_assignment(rows, normalizer=fake, reuse=assignment.meta)
    assert len(calls) == 1
    assert reused.meta["mode"] == "llm"
    assert reused.topics["000003"] == ["风电"]


def test_dynamic_topic_cluster_falls_back_when_llm_fails():
    rows = [
        {"symbol": "000001", "evidence_source": "ths_hot_concepts", "match_text": "风电;海工装备", "text": ""},
        {"symbol": "000002", "evidence_source": "ths_hot_concepts", "match_text": "风电", "text": ""},
        {"symbol": "000003", "evidence_source": "ths_hot_concepts", "match_text": "海工装备", "text": ""},
    ]

    def boom(_payload: list[dict]) -> dict:
        raise RuntimeError("network down")

    assignment = build_topic_assignment(rows, normalizer=boom)
    assert assignment.meta["mode"] == "llm-fallback"
    assert set(assignment.topics["000001"]) == {"海工装备", "风电"}


def test_parse_normalization_extracts_json_block():
    assert parse_normalization('```json\n{"aliases": {"A": "B"}, "drop": ["C"]}\n```') == {
        "aliases": {"A": "B"}, "drop": ["C"],
    }


def test_service_attaches_logic_topics_and_static_memberships():
    logic = pl.DataFrame({
        "symbol": ["000001", "000002", "000003", "000004", "000005", "000006"],
        "evidence_source": ["limit_ladder", "ths_hot_concepts", "ths_hot", "fuyao_anomaly", "limit_ladder", "fuyao_anomaly"],
        "evidence_kind": ["limit_interpretation", "hot_concept_tag", "hot_reason", "anomaly_analysis", "limit_interpretation", "anomaly_analysis"],
        "match_text": ["PCB概念", "PCB", "网络安全", "数据安全", "其他", "消费板块下跌+此前上涨"],
        "text": ["PCB业务受益", "", "数据安全业务", "营收下降", "", "营收下降"],
        "keywords": ["", "", "", "数据安全", "", "消费板块下跌+此前上涨"],
        "catalyst": ["覆铜板涨价", "", "", "", "", ""],
        "tag": ["", "", "", "跌停", "", "跌停"],
        "observed_at": ["2026-09-14T15:00:00+08:00"] * 6,
    })
    candidates = [
        {"symbol": "000001.SZ", "topics": [], "source_ids": ["limit_ladder"], "primary_stage": "涨停强化"},
        {"symbol": "000002.SZ", "topics": [], "source_ids": ["popularity_warm"], "primary_stage": "人气观察"},
        {"symbol": "000003.SZ", "topics": [], "source_ids": ["breakthrough"], "primary_stage": "突破启动"},
        {"symbol": "000004.SZ", "topics": [], "source_ids": ["abnormal_surge"], "primary_stage": "异动加速"},
        {"symbol": "000005.SZ", "topics": [], "source_ids": ["limit_ladder"], "primary_stage": "涨停强化"},
        {"symbol": "000006.SZ", "topics": [], "source_ids": ["abnormal_surge"], "primary_stage": "异动加速"},
    ]
    details = {row["symbol"]: {} for row in candidates}
    service = StockPoolService.__new__(StockPoolService)
    service.facts = _Facts(logic=logic)
    meta, subgroups = service._attach_topics(date(2026, 9, 14), candidates, details)
    assert meta["mode"] == "deterministic"
    assert subgroups == {
        "PCB／覆铜板": [{"name": "PCB", "count": 2, "symbols": ["000001.SZ", "000002.SZ"]}],
    }
    assert candidates[0]["topics"] == ["PCB／覆铜板"]
    assert candidates[1]["topics"] == ["PCB／覆铜板"]
    assert candidates[2]["topics"] == ["网络／AI安全"]
    assert candidates[3]["topics"] == ["网络／AI安全"]
    assert candidates[4]["topics"] == []
    assert candidates[5]["topics"] == []
    assert details["000001.SZ"]["logic_status"] == "当日题材标签"
    assert details["000005.SZ"]["logic_status"] == "有解读待归类"
    assert details["000003.SZ"]["topic_evidence"][0]["source"] == "同花顺热点理由"
    assert details["000003.SZ"]["topic_evidence"][0]["topics"] == ["网络／AI安全"]
    assert details["000004.SZ"]["topic_evidence"][0]["tag"] == "跌停"


def test_primary_concept_prefers_specific_theme_over_industry_proxy():
    candidates = [
        {
            "symbol": "000001.SZ", "primary_stage": "趋势延续", "source_ids": ["liquidity_trend"],
            "memberships": {"concept": ["PCB概念", "人工智能"], "industry_level2": ["元件"], "industry_level1": [], "attribute": []},
        },
        {
            "symbol": "000002.SZ", "primary_stage": "涨停强化", "source_ids": ["limit_ladder"],
            "memberships": {"concept": ["人工智能", "PCB概念"], "industry_level2": [], "industry_level1": [], "attribute": []},
        },
        {
            "symbol": "000003.SZ", "primary_stage": "回踩整理", "source_ids": ["trend_pullback"],
            "memberships": {"concept": [], "industry_level2": [], "industry_level1": [], "attribute": []},
        },
    ]
    StockPoolService._attach_primary_concepts(candidates)
    assert candidates[0]["primary_concept"] == "PCB概念"
    assert candidates[1]["primary_concept"] == "PCB概念"
    assert candidates[2]["primary_concept"] is None


def test_repository_and_api_read_only_snapshot(tmp_path):
    target = tmp_path / "stock_pools" / "date=2026-09-14"
    target.mkdir(parents=True)
    summary = {"trade_date": "2026-09-14", "candidate_count": 1}
    candidates = [{"symbol": "000001.SZ", "name": "甲公司", "source_ids": ["breakthrough"], "primary_stage": "突破启动", "topics": [], "tier": "focus", "change_types": []}]
    details = {"000001.SZ": {**candidates[0], "source_events": []}}
    for name, payload in (("summary.json", summary), ("candidates.json", candidates), ("details.json", details)):
        (target / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    class _Repo:
        class _Store:
            data_dir = tmp_path
        store = _Store()

    app = FastAPI()
    app.state.repo = _Repo()
    app.include_router(router)
    client = TestClient(app)
    assert StockPoolRepository(tmp_path).latest_date() == "2026-09-14"
    assert client.get("/api/stock-pools/20260914").json()["candidate_count"] == 1
    assert client.get("/api/stock-pools/20260914/candidates", params={"source": "breakthrough"}).json()["total"] == 1
    assert client.get("/api/stock-pools/20260914/candidates/000001").json()["name"] == "甲公司"
