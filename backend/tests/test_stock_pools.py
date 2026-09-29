from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.stock_pools import router
from app.market_facts.builders import _build_security_popularity, _build_stock_logic_evidence
from app.quantx_data.legacy_scrapers.fuyao_anomaly_scraper import run as collect_anomaly
from app.quantx_data.legacy_scrapers.security_popularity_scraper import run as collect_popularity
from app.stock_pools.evolution import (
    _comparison_quality,
    _low_labels,
    build_evolution,
    candidate_history,
)
from app.stock_pools.publisher import publish_stock_pool
from app.stock_pools.repository import StockPoolRepository
from app.stock_pools.review import _snapshot_status, build_review
from app.stock_pools.rules import _exchange_coverage, build_candidates
from app.stock_pools.scheduler import run_scheduled as run_stock_pool_scheduled
from app.stock_pools.service import StockPoolService
from app.stock_pools.theme_context import build_theme_context
from app.stock_pools.topic_cluster import build_topic_assignment, keep_term, parse_normalization
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
    closes = history.filter(pl.col("symbol") == "000001.SZ")["close"].to_list()
    assert candidates[0]["price_context"]["ma20_distance_pct"] == round((closes[-1] / (sum(closes[-20:]) / 20) - 1) * 100, 2)
    assert candidates[0]["price_context"]["high20_drawdown_pct"] <= 0
    assert metadata["market_count"] == 2
    assert details["000001.SZ"]["source_events"]


def test_market_coverage_detects_missing_exchange_and_missing_eligible_stocks():
    instruments = pl.DataFrame({"exchange": ["SH"] * 1000 + ["SZ"] * 1000})
    complete_market = pl.DataFrame({"exchange": ["SH"] * 900 + ["SZ"] * 900})
    complete_eligible = pl.DataFrame({"exchange": ["SH"] * 100 + ["SZ"] * 100})
    coverage, complete = _exchange_coverage(complete_market, complete_eligible, instruments)
    assert complete
    assert coverage["SH"] == {"listed": 1000, "market": 900, "eligible": 100}
    assert not _exchange_coverage(complete_market.filter(pl.col("exchange") == "SZ"), complete_eligible, instruments)[1]
    assert not _exchange_coverage(complete_market, complete_eligible.filter(pl.col("exchange") == "SZ"), instruments)[1]


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
    assert theme_level("芯片") == "industry"
    assert theme_level("华为") == "background"
    assert theme_level("比亚迪") == "background"
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


def test_dynamic_topic_cluster_keeps_cooccurring_subtheme_separate():
    rows = [
        {"symbol": "000001", "evidence_source": "fuyao_anomaly", "match_text": "VNA矢量网络分析仪+仪器仪表", "text": ""},
        {"symbol": "000002", "evidence_source": "fuyao_anomaly", "match_text": "矢量网络分析仪+仪器仪表", "text": ""},
        {"symbol": "000003", "evidence_source": "limit_ladder", "match_text": "仪器仪表", "text": ""},
    ]
    assignment = build_topic_assignment(rows)
    assert set(assignment.topics["000001"]) == {"仪器仪表", "VNA矢量网络分析仪"}
    assert set(assignment.topics["000002"]) == {"仪器仪表", "VNA矢量网络分析仪"}
    assert assignment.meta["label_count"] == 2


def test_topic_noise_filter_keeps_specific_directions():
    assert all(keep_term(term) for term in ("矢量网络分析仪", "存储芯片", "PCB概念"))
    assert all(not keep_term(term) for term in (
        "主力资金净流出", "融资融券", "上半年仍亏损", "上市首日大涨",
        "英伟达供货传闻澄清", "大股东增持", "国家大基金持股",
    ))


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
    build_topic_assignment(rows, normalizer=fake, reuse={**assignment.meta, "rule": "older"})
    assert len(calls) == 2


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


def test_theme_context_keeps_source_rank_availability_and_date_separate():
    days = [date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24)]
    observations = [
        {"trade_date": days[0], "source": "ths_hot", "theme_name": "机器人概念", "rank": 4},
        {"trade_date": days[0], "source": "pywencai", "theme_name": "其他题材", "rank": 1},
        {"trade_date": days[1], "source": "pywencai", "theme_name": "其他题材", "rank": 2},
        {"trade_date": days[2], "source": "ths_hot", "theme_name": "机器人", "rank": 2},
        {"trade_date": days[2], "source": "pywencai", "theme_name": "其他题材", "rank": 3},
        {"trade_date": date(2026, 9, 25), "source": "deepq", "theme_name": "机器人", "rank": 1},
    ]
    context = build_theme_context(days[-1], days, observations, {"机器人"}, {"机器人"}, {"机器人概念": "机器人"})["机器人"]
    ths, pywencai, deepq = context["sources"]
    assert context["basis"] == "dated_logic"
    assert (ths["status"], ths["rank"], ths["previous_date"], ths["previous_rank"]) == (
        "ranked", 2, "2026-09-22", 4,
    )
    assert (ths["seen_days"], ths["available_days"]) == (2, 2)
    assert (pywencai["status"], pywencai["seen_days"], pywencai["available_days"]) == ("not_ranked", 0, 3)
    assert (deepq["status"], deepq["available_days"]) == ("unavailable", 0)


def test_theme_context_rejects_ambiguous_alias_instead_of_merging_topics():
    day = date(2026, 9, 24)
    context = build_theme_context(day, [day], [
        {"trade_date": day, "source": "ths_hot", "theme_name": "共同别名", "rank": 1},
    ], {"甲方向", "乙方向"}, set(), {"共同别名": "甲方向", "共同别名概念": "乙方向"})
    assert context["甲方向"]["sources"][0]["status"] == "ambiguous"
    assert context["乙方向"]["sources"][0]["status"] == "ambiguous"


def test_theme_context_shows_narrower_source_names_without_claiming_rank_or_membership():
    day = date(2026, 9, 24)
    context = build_theme_context(day, [day], [
        {"trade_date": day, "source": "ths_hot", "theme_name": "风电轴承", "rank": 7},
    ], {"风电"}, {"风电"}, {})["风电"]["sources"][0]
    assert context["status"] == "not_ranked"
    assert context["rank"] is None
    assert context["related_narrower"] == [{"name": "风电轴承", "rank": 7}]


def test_service_attaches_logic_topics_and_static_memberships():
    logic = pl.DataFrame({
        "symbol": ["000001", "000002", "000003", "000004", "000005", "000006"],
        "evidence_source": ["limit_ladder", "ths_hot_concepts", "ths_hot", "fuyao_anomaly", "limit_ladder", "fuyao_anomaly"],
        "evidence_kind": ["limit_interpretation", "hot_concept_tag", "hot_reason", "anomaly_analysis", "limit_interpretation", "anomaly_analysis"],
        "match_text": ["PCB概念", "PCB", "网络安全", "数据安全", "白酒概念", "消费板块下跌+此前上涨"],
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
    meta, subgroups, term_labels = service._attach_topics(date(2026, 9, 14), candidates, details)
    assert meta["mode"] == "deterministic"
    assert meta["term_labels"] == term_labels
    assert subgroups == {
        "PCB／覆铜板": [{"name": "PCB", "count": 2, "symbols": ["000001.SZ", "000002.SZ"]}],
    }
    assert candidates[0]["topics"] == ["PCB／覆铜板"]
    assert candidates[1]["topics"] == ["PCB／覆铜板"]
    assert candidates[2]["topics"] == ["网络／AI安全"]
    assert candidates[3]["topics"] == ["网络／AI安全"]
    assert candidates[4]["topics"] == []
    assert candidates[4]["unclustered_terms"] == ["白酒概念"]
    assert candidates[4]["logic_evidence_count"] == 1
    assert candidates[5]["topics"] == []
    assert details["000001.SZ"]["logic_status"] == "当日题材标签"
    assert details["000005.SZ"]["logic_status"] == "有解读待归类"
    assert details["000003.SZ"]["topic_evidence"][0]["source"] == "同花顺热点理由"
    assert details["000003.SZ"]["topic_evidence"][0]["topics"] == ["网络／AI安全"]
    assert details["000004.SZ"]["topic_evidence"][0]["tag"] == "跌停"


def test_financial_and_shareholder_status_are_not_single_stock_theme_cues():
    assert not keep_term("半年度亏损")
    assert not keep_term("股东拟减持")
    assert not keep_term("共同富裕示范区")
    assert keep_term("白酒概念")


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


def test_primary_concept_does_not_prefer_broad_brand_tag():
    candidates = [{
        "symbol": "000001.SZ", "primary_stage": "趋势延续", "source_ids": ["liquidity_trend"],
        "memberships": {"concept": ["华为", "固态电池"], "industry_level2": [], "industry_level1": [], "attribute": []},
    }]
    StockPoolService._attach_primary_concepts(candidates)
    assert candidates[0]["primary_concept"] == "固态电池"


def test_research_is_attached_without_daily_topic():
    class _Research:
        def query_company(self, company, trade_date, *, limit=3):
            assert company == "甲公司"
            assert trade_date == date(2026, 9, 24)
            assert limit is None
            return [{"title": "已审计主证据", "source": "review", "match_basis": "audited", "material_role": "primary"},
                    {"title": "已审计辅助证据", "source": "review", "match_basis": "audited", "material_role": "supporting"},
                    {"title": "市场提及", "source": "smnc", "match_basis": "mention"},
                    {"title": "公司材料", "source": "smnc", "match_basis": "focused"}]

    service = StockPoolService.__new__(StockPoolService)
    service.research = _Research()
    candidates = [{"symbol": "000001.SZ", "name": "甲公司", "topics": []}]
    details = {"000001.SZ": {}}
    service._attach_research(date(2026, 9, 24), candidates, details)
    assert candidates[0]["research_count"] == 3
    assert candidates[0]["research_breakdown"]["smnc_focused"] == 1
    assert candidates[0]["research_focus"]["title"] == "公司材料"
    assert details["000001.SZ"]["research_focus"] == candidates[0]["research_focus"]
    assert details["000001.SZ"]["research_breakdown"] == candidates[0]["research_breakdown"]
    assert details["000001.SZ"]["research"][0]["title"] == "已审计主证据"
    assert len(details["000001.SZ"]["research"]) == 3


def test_research_focus_records_literal_theme_cues_freshness_and_counter():
    class _Research:
        def query_company(self, company, trade_date, *, limit=None):
            return [
                {"title": "陶瓷混压PCB订单放量【甲公司】", "match_excerpt": "甲公司提及液冷项目",
                 "source": "smnc", "match_basis": "focused", "created_at": "2026-09-22T19:00:00+08:00",
                 "available_at": "2026-09-23T01:00:00+00:00", "source_url": "https://example.com/research"},
                {"title": "已审计反证", "source": "review", "match_basis": "audited",
                 "material_role": "counter", "source_url": "https://example.com/counter"},
            ]

    service = StockPoolService.__new__(StockPoolService)
    service.research = _Research()
    candidates = [{"symbol": "000001.SZ", "name": "甲公司", "topics": [],
                   "memberships": {"concept": ["低空经济", "PCB概念"]}}]
    details = {"000001.SZ": {}}
    service._attach_research(date(2026, 9, 24), candidates, details, {"液冷": "液冷"})
    focus = candidates[0]["research_focus"]
    assert focus["source_date"] == "2026-09-22"
    assert focus["age_days"] == 1
    assert focus["topic_mentions"] == [
        {"label": "PCB概念", "surface": "PCB", "location": "title"},
        {"label": "液冷", "surface": "液冷", "location": "excerpt"},
    ]
    assert focus["counter"]["title"] == "已审计反证"
    assert candidates[0]["topics"] == []
    assert StockPoolService._research_topic_mentions(
        {"title": "定制芯片订单", "match_excerpt": ""}, {"memberships": {"concept": []}},
        {"芯片概念": "人工智能芯片", "芯片": "芯片"},
    ) == [{"label": "芯片", "surface": "芯片", "location": "title"}]


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


def test_topic_rule_change_makes_hot_migration_incomparable():
    previous = {"rule_version": "stock-pools-v2", "topic_normalization": {"rule": "jaccard>=0.3,shared>=2", "mode": "deterministic"}}
    current = {"rule_version": "stock-pools-v2", "topic_normalization": {"rule": "alias_equivalence,shared>=2", "mode": "deterministic"}}
    assert _comparison_quality(current, previous, "hot") == "incompatible"
    assert _comparison_quality(current, previous, "low") == "complete"


def test_low_topic_prefers_dated_logic_to_static_membership():
    row = {"topics": ["PCB／覆铜板"], "primary_concept": "低空经济", "memberships": {"concept": ["低空经济"]}}
    assert _low_labels(row) == {"PCB／覆铜板"}
    assert _low_labels({**row, "topics": []}) == {"低空经济"}


def test_daily_topic_change_skips_incompatible_cluster_rule():
    class _Snapshots:
        def list_dates(self):
            return ["2026-09-23"]

        def get_candidates(self, _date):
            return [{"symbol": "000001.SZ", "source_ids": ["liquidity_trend"],
                     "primary_stage": "趋势延续", "topics": ["机器人"]}]

        def get_summary(self, _date):
            return {"topic_normalization": {"rule": "old", "mode": "deterministic"}}

    service = StockPoolService.__new__(StockPoolService)
    service.snapshots = _Snapshots()
    current = [{"symbol": "000001.SZ", "source_ids": ["liquidity_trend"],
                "primary_stage": "趋势延续", "topics": ["光互联"]}]
    result = service._attach_changes(date(2026, 9, 24), current, {"rule": "new", "mode": "deterministic"})
    assert result["topic_status"] == "incompatible"
    assert current[0]["change_types"] == []
    assert "topic" not in result["counts"]
    result = service._attach_changes(date(2026, 9, 24), current, {"rule": "old", "mode": "deterministic"})
    assert result["topic_status"] == "complete"
    assert current[0]["change_types"] == ["topic"]


def test_evolution_separates_pool_and_topic_movement_and_history(tmp_path):
    def row(symbol, stage, topics, source, concept=""):
        return {
            "symbol": symbol, "name": symbol, "primary_stage": stage, "topics": topics,
            "source_ids": [source], "sources": [source], "primary_concept": concept,
            "memberships": {"concept": [concept] if concept else []},
            "pct_chg": 2.0, "research_count": 1,
        }

    snapshots = {
        "2026-09-22": [row("000005.SZ", "活跃观察", [], "active_character")],
        "2026-09-23": [
            row("000001.SZ", "活跃观察", ["机器人"], "active_character"),
            row("000002.SZ", "趋势延续", ["机器人"], "liquidity_trend"),
            row("000003.SZ", "回踩整理", ["机器人"], "trend_pullback"),
            row("000004.SZ", "活跃观察", ["其他"], "active_character"),
            row("000006.SZ", "活跃观察", [], "active_character", "人工智能"),
        ],
        "2026-09-24": [
            row("000001.SZ", "涨停强化", ["机器人"], "limit_ladder"),
            row("000002.SZ", "趋势延续", ["其他"], "liquidity_trend"),
            row("000004.SZ", "异动加速", ["机器人"], "abnormal_surge"),
            row("000005.SZ", "突破启动", ["机器人"], "breakthrough"),
            row("000006.SZ", "趋势延续", [], "liquidity_trend", "人工智能"),
        ],
    }
    for day, rows in snapshots.items():
        folder = tmp_path / "stock_pools" / f"date={day}"
        folder.mkdir(parents=True)
        summary = {"rule_version": "stock-pools-v2", "status": "complete",
                   "source_quality": {"market_universe": "complete", "logic_evidence": "complete"}}
        (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (folder / "candidates.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    repo = StockPoolRepository(tmp_path)
    result = build_evolution(repo, date(2026, 9, 24), "hot", "机器人", 10)
    assert result is not None
    assert (result["current_count"], result["previous_count"]) == (3, 3)
    assert result["counts"] == {
        "retained": 1, "entered_topic": 1, "entered_pool": 1,
        "left_topic": 1, "left_pool": 1, "stage_changed": 1, "source_changed": 0,
    }
    assert result["current_count"] == result["counts"]["retained"] + result["counts"]["entered_topic"] + result["counts"]["entered_pool"]
    assert result["previous_count"] == result["counts"]["retained"] + result["counts"]["left_topic"] + result["counts"]["left_pool"]
    assert next(item for item in result["members"] if item["symbol"] == "000001.SZ")["added_sources"] == ["limit_ladder"]
    assert next(item for item in result["members"] if item["symbol"] == "000005.SZ")["reentry"]
    assert {item["kind"] for item in result["exits"]} == {"left_topic", "left_pool"}
    assert result["history"][-2:][0]["count"] == 3
    low = build_evolution(repo, date(2026, 9, 24), "low", "人工智能", 10)
    assert low is not None
    assert low["basis"] == "current_cohort"
    assert (low["current_count"], low["previous_count"]) == (1, 1)
    assert low["members"][0]["previous_stage"] == "活跃观察"
    timeline = candidate_history(repo, date(2026, 9, 24), "000005", 10)
    assert timeline is not None
    assert [item["present"] for item in timeline["timeline"]] == [True, False, True]
    assert build_evolution(repo, date(2026, 9, 21), "hot", "", 10) is None
    assert candidate_history(repo, date(2026, 9, 24), "999999", 10) is None

    class _Repo:
        class _Store:
            data_dir = tmp_path
        store = _Store()

    app = FastAPI()
    app.state.repo = _Repo()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/stock-pools/20260924/evolution", params={"topic": "机器人"}).json()["counts"]["entered_topic"] == 1
    assert len(client.get("/api/stock-pools/20260924/candidates/000005/history").json()["timeline"]) == 3
    assert client.get("/api/stock-pools/20260922/evolution").json()["comparison_status"] == "unavailable"


def test_evolution_api_missing_and_validation(tmp_path):
    class _Repo:
        class _Store:
            data_dir = tmp_path
        store = _Store()

    app = FastAPI()
    app.state.repo = _Repo()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/stock-pools/20260924/evolution").status_code == 404
    assert client.get("/api/stock-pools/20260924/evolution", params={"window": 0}).status_code == 422
    assert client.get("/api/stock-pools/20260924/candidates/000001/history").status_code == 404


def test_stock_pool_recovery_skips_readable_snapshot(tmp_path, monkeypatch):
    class _Repo:
        class _Store:
            data_dir = tmp_path

        store = _Store()

        def latest_enriched_date(self, _asset_type):
            return date(2026, 9, 24)

    calls = []
    monkeypatch.setattr("app.stock_pools.scheduler.publish_stock_pool", lambda _repo, day: calls.append(day) or {"trade_date": day.isoformat()})
    repo = _Repo()
    assert run_stock_pool_scheduled(repo)["trade_date"] == "2026-09-24"
    folder = StockPoolRepository(tmp_path).date_dir("2026-09-24")
    folder.mkdir(parents=True)
    for name, content in (("manifest.json", "{}"), ("summary.json", "{}"), ("candidates.json", "[]"), ("details.json", "{}")):
        (folder / name).write_text(content, encoding="utf-8")
    assert run_stock_pool_scheduled(repo) is None
    assert len(calls) == 1
    (folder / "details.json").unlink()
    assert run_stock_pool_scheduled(repo)["trade_date"] == "2026-09-24"
    (folder / "details.json").write_text("{}", encoding="utf-8")
    assert run_stock_pool_scheduled(repo, trade_date=date(2026, 9, 24))["trade_date"] == "2026-09-24"


def test_stock_pool_first_publication_survives_rebuild(tmp_path, monkeypatch):
    class _Repo:
        class _Store:
            data_dir = tmp_path

        store = _Store()

    state = {"symbol": "A.SZ"}

    class _Service:
        def __init__(self, _repo):
            pass

        def build(self, trade_date):
            candidate = {"symbol": state["symbol"], "name": state["symbol"]}
            return {
                "summary": {"trade_date": trade_date.isoformat(), "status": "complete", "candidate_count": 1,
                            "source_quality": {"market_universe": "complete"},
                            "input_generation": "test", "instrument_generation": "test"},
                "candidates": [candidate], "details": {state["symbol"]: candidate},
                "eligible": [state["symbol"], "C.SZ"],
            }

    monkeypatch.setattr("app.stock_pools.publisher.StockPoolService", _Service)
    monkeypatch.setattr("app.research_materials.builder.refresh_if_configured", lambda _root: None)
    first = publish_stock_pool(_Repo(), date(2026, 9, 24))
    snapshots = StockPoolRepository(tmp_path)
    assert snapshots.get_manifest("2026-09-24")["first_publication"] is True
    shutil.rmtree(snapshots.first_date_dir("2026-09-24"))  # Simulate interruption after current publication.
    state["symbol"] = "B.SZ"
    publish_stock_pool(_Repo(), date(2026, 9, 24))
    assert snapshots.get_candidates("2026-09-24")[0]["symbol"] == "B.SZ"
    assert snapshots.get_review_snapshot("2026-09-24")[1][0]["symbol"] == "A.SZ"
    assert snapshots.get_review_snapshot("2026-09-24")[2]["run_id"] == first["run_id"]
    assert any(item["path"] == "eligible.json" for item in first["artifacts"])
    assert snapshots.get_first_details("2026-09-24")["A.SZ"]["symbol"] == "A.SZ"
    assert snapshots.get_review_eligible("2026-09-24") == ["A.SZ", "C.SZ"]
    state["symbol"] = "C.SZ"
    publish_stock_pool(_Repo(), date(2026, 9, 24))
    assert snapshots.get_review_snapshot("2026-09-24")[1][0]["symbol"] == "A.SZ"
    app = FastAPI()
    app.state.repo = _Repo()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/stock-pools/20260924/candidates/A.SZ", params={"snapshot": "first"}).status_code == 200
    assert client.get("/api/stock-pools/20260924/candidates/A.SZ").status_code == 404
    assert client.get("/api/stock-pools/20260924").json()["first_published_available"] is True
    replace = os.replace

    def fail_first(source, target):
        if "first_published" in str(target):
            raise OSError("archive unavailable")
        return replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr("app.stock_pools.publisher.os.replace", fail_first)
        with pytest.raises(OSError, match="archive unavailable"):
            publish_stock_pool(_Repo(), date(2026, 9, 25))
    assert not snapshots.date_dir("2026-09-25").exists()
    assert not snapshots.first_date_dir("2026-09-25").exists()


def test_stock_pool_review_distinguishes_recorded_and_late_publications():
    assert _snapshot_status("first_published", {"trade_date": "2026-09-17", "published_at": "2026-09-18T01:00:00+00:00"}, "2026-09-18") == "recorded"
    assert _snapshot_status("first_published", {"trade_date": "2026-09-17", "published_at": "2026-09-18T02:00:00+00:00"}, "2026-09-18") == "late"
    assert _snapshot_status("first_published", {"trade_date": "2026-09-17", "published_at": "2026-09-17T03:00:00+00:00"}, "2026-09-18") == "early"
    assert _snapshot_status("first_published", {"trade_date": "2026-09-17", "published_at": "2026-09-17T18:00:00"}, "2026-09-18") == "unknown"
    assert _snapshot_status("replay", {"published_at": "2026-09-17T08:00:00+00:00"}, "2026-09-18") == "replay"


def test_stock_pool_review_marks_elapsed_horizon_with_missing_snapshot_unavailable(tmp_path, monkeypatch):
    class _Calendar:
        def __init__(self, _root):
            pass

        def get_trading_calendar(self, start, end, *, as_of):
            days = [date(2026, 9, day) for day in (14, 15, 16, 17, 18, 21, 22, 23)]
            return pl.DataFrame({"trade_date": [day for day in days if start <= day <= end],
                                 "is_open": [True] * sum(start <= day <= end for day in days)})

    monkeypatch.setattr("app.stock_pools.review.MarketFactRepository", _Calendar)
    for day in (14, 15, 17, 18):
        folder = tmp_path / "stock_pools" / f"date=2026-09-{day}"
        folder.mkdir(parents=True)
        (folder / "summary.json").write_text(json.dumps({
            "rule_version": "stock-pools-v2", "status": "complete",
            "source_quality": {"market_universe": "complete", "logic_evidence": "complete"},
        }), encoding="utf-8")
        (folder / "candidates.json").write_text(json.dumps([{
            "symbol": "A.SZ", "name": "A", "primary_stage": "趋势延续",
            "source_ids": ["liquidity_trend"], "sources": ["趋势"], "topics": [],
        }]), encoding="utf-8")

    class _Klines:
        def get_daily_batch(self, *args, **kwargs):
            return pl.DataFrame()

    result = build_review(StockPoolRepository(tmp_path), _Klines(), date(2026, 9, 18), 3, 3)
    row = next(item for item in result["rows"] if item["date"] == "2026-09-15")
    assert row["outcome_status"] == "unavailable"
    assert row["target_date"] == "2026-09-18"
    assert result["groups"]["all"]["pending_count"] == 2
    assert result["groups"]["all"]["unavailable_count"] == 1


def test_stock_pool_review_tracks_reentry_exit_price_and_maturity(tmp_path, monkeypatch):
    class _Calendar:
        def __init__(self, _root):
            pass

        def get_trading_calendar(self, start, end, *, as_of):
            days = [date(2026, 9, day) for day in (15, 16, 17, 18, 21, 22, 23, 24, 28)]
            return pl.DataFrame({"trade_date": [day for day in days if start <= day <= end],
                                 "is_open": [True] * sum(start <= day <= end for day in days)})

    monkeypatch.setattr("app.stock_pools.review.MarketFactRepository", _Calendar)
    def row(symbol, stage, source, price):
        return {"symbol": symbol, "name": symbol, "primary_stage": stage,
                "source_ids": [source], "sources": [source], "topics": [], "price": price}

    snapshots = {
        "2026-09-15": [row("A.SZ", "活跃观察", "active_character", 9)],
        "2026-09-16": [row("A.SZ", "活跃观察", "active_character", 10)],
        "2026-09-17": [row("A.SZ", "突破启动", "breakthrough", 10), row("C.SZ", "活跃观察", "active_character", 20)],
        "2026-09-18": [row("C.SZ", "活跃观察", "active_character", 21)],
        "2026-09-21": [row("A.SZ", "突破启动", "breakthrough", 12), row("C.SZ", "突破启动", "breakthrough", 22)],
        "2026-09-22": [row("A.SZ", "趋势延续", "liquidity_trend", 13), row("C.SZ", "突破启动", "breakthrough", 23)],
    }
    for day, rows in snapshots.items():
        folder = tmp_path / "stock_pools" / f"date={day}"
        folder.mkdir(parents=True)
        summary = {"rule_version": "stock-pools-v1" if day == "2026-09-15" else "stock-pools-v2",
                   "status": "complete", "source_quality": {"market_universe": "complete", "logic_evidence": "complete"}}
        (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (folder / "candidates.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        if day in {"2026-09-17", "2026-09-18"}:
            first = tmp_path / "stock_pools" / "first_published" / f"date={day}"
            first.mkdir(parents=True)
            (first / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            (first / "candidates.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            if day == "2026-09-17":
                (first / "eligible.json").write_text(json.dumps(["A.SZ", "C.SZ", "D.SZ"]), encoding="utf-8")
            published_at = "2026-09-17T18:00:00+00:00" if day == "2026-09-17" else "2026-09-18T08:00:00+00:00"
            (first / "manifest.json").write_text(json.dumps({"trade_date": day, "published_at": published_at}), encoding="utf-8")

    prices = pl.DataFrame({
        "symbol": ["A.SZ", "A.SZ", "A.SZ", "A.SZ", "C.SZ", "C.SZ", "C.SZ", "C.SZ"],
        "date": [date(2026, 9, 17), date(2026, 9, 18), date(2026, 9, 21), date(2026, 9, 22)] * 2,
        "close": [10., 11., 12., 13., 20., 21., 22., 23.],
    }).with_columns(pl.col("close").alias("open"), pl.col("close").alias("high"), pl.col("close").alias("low"))
    prices = pl.concat([prices, pl.DataFrame({
        "symbol": ["D.SZ", "D.SZ"], "date": [date(2026, 9, 17), date(2026, 9, 18)],
        "open": [10., 10.], "high": [10., 10.], "low": [10., 9.], "close": [10., 9.],
    }).select(prices.columns)])

    class _Repo:
        class _Store:
            data_dir = tmp_path
        store = _Store()

        def get_daily_batch(self, symbols, start, end, columns):
            assert columns == ["symbol", "date", "open", "high", "low", "close"]
            return prices.filter(pl.col("symbol").is_in(symbols) & pl.col("date").is_between(start, end)).select(columns)

    repo = StockPoolRepository(tmp_path)
    result = build_review(repo, _Repo(), date(2026, 9, 22), 10, 1)
    assert result is not None
    assert {item["date"] for item in result["skipped_dates"]} == {"2026-09-15", "2026-09-16"}
    assert result["groups"]["new"]["sample_count"] == 1
    assert result["groups"]["reentry"]["sample_count"] == 1
    assert result["groups"]["stage"]["sample_count"] == 3
    assert result["groups"]["source"]["sample_count"] == 3
    leaving = next(row for row in result["rows"] if row["date"] == "2026-09-17" and row["symbol"] == "A.SZ")
    assert leaving["target_stage"] is None
    assert leaving["return_pct"] == 10.0
    assert leaving["open_proxy_pct"] == 0.0
    assert leaving["snapshot_status"] == "recorded"
    assert leaving["added_sources"] == ["breakthrough"]
    assert leaving["removed_sources"] == ["active_character"]
    assert next(row for row in result["rows"] if row["date"] == "2026-09-22")["outcome_status"] == "pending"
    assert result["groups"]["all"]["matured_count"] == 5
    assert result["groups"]["all"]["median_return_pct"] == 5.0
    assert result["groups"]["all"]["pending_count"] == 2
    assert result["groups"]["all"]["unavailable_count"] == 0
    assert result["groups"]["all"]["unique_symbols"] == 2
    assert result["groups"]["all"]["recorded_count"] == 2
    assert result["groups"]["all"]["recorded_transition_count"] == 0
    assert result["groups"]["all"]["open_proxy_count"] == 5
    assert result["audit_counts"]["replay"] == 3
    assert result["audit_counts"]["recorded"] == 2
    assert result["groups"]["new"]["eligible_diff_pct"] == 10.0
    assert result["groups"]["new"]["eligible_days"] == 1
    assert result["attribution"]["sources"]["breakthrough"]["matured_count"] == 3
    three_day = build_review(repo, _Repo(), date(2026, 9, 22), 10, 3)
    three_day_a = next(row for row in three_day["rows"] if row["date"] == "2026-09-17" and row["symbol"] == "A.SZ")
    assert three_day_a["entry_date"] == "2026-09-18"
    assert three_day_a["open_proxy_pct"] == 18.18
    class _CloseOnly(_Repo):
        def get_daily_batch(self, symbols, start, end, columns):
            return super().get_daily_batch(symbols, start, end, columns).select("symbol", "date", "close")

    close_only = build_review(repo, _CloseOnly(), date(2026, 9, 22), 10, 1)
    assert close_only["groups"]["all"]["priced_count"] == 5
    assert close_only["groups"]["all"]["open_proxy_count"] == 0
    assert result["groups"]["all"]["peer_diff_pct"] is None
    assert result["groups"]["new"]["peer_diff_pct"] == -5.0
    assert result["groups"]["new"]["peer_days"] == 1

    class _MissingPublicationCalendar(_Calendar):
        def get_trading_calendar(self, start, end, *, as_of):
            known = super().get_trading_calendar(start, end, as_of=as_of)
            missing = pl.DataFrame({"trade_date": [date(2026, 9, 19)], "is_open": [True]})
            return pl.concat([known, missing]).sort("trade_date")

    with monkeypatch.context() as patch:
        patch.setattr("app.stock_pools.review.MarketFactRepository", _MissingPublicationCalendar)
        gap = build_review(repo, _Repo(), date(2026, 9, 22), 10, 1)
    assert next(row for row in gap["rows"] if row["date"] == "2026-09-18")["outcome_status"] == "unavailable"

    app = FastAPI()
    app.state.repo = _Repo()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/api/stock-pools/20260922/review", params={"horizon": 1, "cost_bps": 20})
    assert response.status_code == 200, response.text
    assert response.json()["cost_bps"] == 20
    assert next(row for row in response.json()["rows"] if row["date"] == "2026-09-17" and row["symbol"] == "C.SZ")["open_proxy_net_pct"] == -0.2
    assert response.json()["groups"]["reentry"]["sample_count"] == 1
    assert client.get("/api/stock-pools/20260922/review", params={"horizon": 2}).status_code == 422
    assert client.get("/api/stock-pools/20260922/review", params={"cost_bps": 101}).status_code == 422
    assert client.get("/api/stock-pools/20260923/review").status_code == 404

    degraded_path = tmp_path / "stock_pools" / "first_published" / "date=2026-09-18" / "summary.json"
    degraded = json.loads(degraded_path.read_text(encoding="utf-8"))
    degraded["status"] = "degraded"
    degraded_path.write_text(json.dumps(degraded), encoding="utf-8")
    limited = build_review(repo, _Repo(), date(2026, 9, 22), 10, 1)
    assert limited is not None
    assert next(row for row in limited["rows"] if row["date"] == "2026-09-17")["outcome_status"] == "unavailable"
    assert limited["groups"]["all"]["matured_count"] == 0
    assert limited["groups"]["all"]["unavailable_count"] == 2
