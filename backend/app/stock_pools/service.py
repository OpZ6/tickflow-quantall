from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.market_facts.registry import DatasetId
from app.market_facts.repository import MarketFactRepository
from app.quantx_data.new_high_clusters import load_ths_memberships as load_security_memberships
from app.research_materials.repository import ResearchMaterialRepository, is_direct_research
from app.services.screener import ScreenerService
from app.stock_pools import topic_cluster
from app.stock_pools.repository import StockPoolRepository
from app.stock_pools.rules import (
    EVENT_SOURCES,
    RULE_VERSION,
    SOURCE_META,
    STAGE_PRIORITY,
    build_candidates,
)
from app.stock_pools.theme_context import VERSION as THEME_CONTEXT_VERSION
from app.stock_pools.theme_context import build_theme_context
from app.stock_pools.topics import (
    INDUSTRY_DISPLAY_THEMES,
    THEME_LEVEL_ORDER,
    theme_level,
)
from app.tickflow.repository import KlineRepository

MEMBERSHIP_DIMENSIONS = ("concept", "industry_level1", "industry_level2", "attribute")
LOGIC_SOURCE_LABELS = {
    "limit_ladder": "涨停梯队解读",
    "ths_hot": "同花顺热点理由",
    "fuyao_anomaly": "同花顺异动解读",
    "ths_hot_concepts": "同花顺热榜概念",
    "ths_hot_list": "同花顺热榜解读",
}


def _code(value: Any) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[-6:] if len(digits) >= 6 else ""


class StockPoolService:
    def __init__(self, repo: KlineRepository) -> None:
        self.repo = repo
        self.data_root = repo.store.data_dir
        self.facts = MarketFactRepository(self.data_root)
        self.snapshots = StockPoolRepository(self.data_root)
        self.research = ResearchMaterialRepository(self.data_root)

    def build(self, trade_date: date) -> dict[str, Any]:
        history = ScreenerService(self.repo)._load_enriched_history(trade_date, 320)
        instruments = self.repo.get_instruments_asset("stock")
        candidates, details, metadata = build_candidates(
            history, instruments, self.facts, trade_date,
        )
        metadata["instrument_generation"] = hashlib.sha256(
            instruments.select("symbol", "name", "exchange", "total_shares").sort("symbol").write_csv().encode("utf-8")
        ).hexdigest()
        topic_meta, topic_subgroups, term_labels = self._attach_topics(trade_date, candidates, details)
        self._attach_memberships(candidates, details)
        self._attach_research(trade_date, candidates, details, term_labels)
        theme_contexts = self._theme_contexts(trade_date, candidates, term_labels)
        changes = self._attach_changes(trade_date, candidates, topic_meta)
        candidates.sort(key=lambda row: (
            {"core": 0, "focus": 1, "all": 2}[row["tier"]],
            -len(row["source_ids"]),
            STAGE_PRIORITY.index(row["primary_stage"]),
            -row["amount_yi"], row["symbol"],
        ))
        summary = self._summary(
            trade_date, candidates, details, changes, metadata, topic_meta, topic_subgroups, theme_contexts,
        )
        return {"summary": summary, "candidates": candidates, "details": details,
                "eligible": metadata["eligible_symbols"]}

    def _attach_topics(self, trade_date: date, candidates: list[dict], details: dict[str, dict]) -> tuple[dict, dict, dict]:
        """Attach dynamic topic labels derived from dated per-stock logic evidence.

        The fact keeps one evidence row per upstream source. Structured
        ``match_text`` fields are extracted and clustered by
        ``app.stock_pools.topic_cluster``; the original text is preserved for
        display. The optional LLM alias stage only rewrites labels, is disabled
        by default, and its applied aliases are stored in the summary and reused
        when the same trade date is rebuilt.
        """
        by_code = {_code(row["symbol"]): row for row in candidates}
        evidence: dict[str, list[dict]] = defaultdict(list)
        cluster_rows: list[dict] = []
        for item in self.facts.get_stock_logic_evidence(trade_date).to_dicts():
            code = _code(item.get("symbol"))
            row = by_code.get(code)
            if row is None:
                continue
            source = str(item.get("evidence_source") or "")
            match_text = str(item.get("match_text") or "").strip()
            text = str(item.get("text") or "").strip()
            if not match_text and not text:
                continue
            evidence[code].append({
                "source": LOGIC_SOURCE_LABELS.get(source, source),
                "source_id": source,
                "kind": item.get("evidence_kind"),
                "observed_at": item.get("observed_at"),
                "text": text or match_text,
                "match_text": match_text,
                "keywords": item.get("keywords") or "",
                "catalyst": item.get("catalyst") or "",
                "tag": item.get("tag") or "",
                "fallback": bool(item.get("is_fallback")),
                "topics": [],
            })
            cluster_rows.append({
                "symbol": code, "evidence_source": source,
                "match_text": match_text, "text": text or match_text,
            })
        normalizer = topic_cluster.llm_normalize if topic_cluster.llm_enabled() else None
        reuse = None
        if normalizer is not None:
            previous = self.snapshots.get_summary(trade_date) or {}
            existing = previous.get("topic_normalization") or {}
            if existing.get("mode") == "llm" and existing.get("prompt_version") == topic_cluster.PROMPT_VERSION:
                reuse = existing
        assignment = topic_cluster.build_topic_assignment(cluster_rows, normalizer=normalizer, reuse=reuse)
        for code, entries in evidence.items():
            row = by_code[code]
            topics = assignment.topics.get(code, [])
            row["topics"] = topics
            row["logic_evidence_count"] = len(entries)
            row["unclustered_terms"] = sorted({
                term for entry in entries
                for term in topic_cluster.split_terms(entry["source_id"], entry["match_text"])
                if topic_cluster.keep_term(term) and term not in assignment.label_of
            })[:3]
            details[row["symbol"]]["topics"] = topics
            for entry in entries:
                entry["topics"] = assignment.labels_for(
                    topic_cluster.split_terms(entry["source_id"], entry["match_text"])
                )
            details[row["symbol"]]["topic_evidence"] = entries
            details[row["symbol"]]["logic_status"] = (
                "当日题材标签" if topics else "有解读待归类" if entries else "今日逻辑待确认"
            )
        subgroups = {
            label: [
                {
                    "name": entry["name"],
                    "count": entry["count"],
                    "symbols": [by_code[code]["symbol"] for code in entry["symbols"] if code in by_code],
                }
                for entry in entries
            ]
            for label, entries in assignment.subgroups.items()
        }
        return {**assignment.meta, "term_labels": assignment.label_of}, subgroups, assignment.label_of

    def _theme_contexts(self, trade_date: date, candidates: list[dict], term_labels: dict[str, str]) -> dict:
        labels = {label for row in candidates for label in [*row["topics"], row.get("primary_concept")] if label}
        dynamic = {label for row in candidates for label in row["topics"]}
        calendar = self.facts.get_trading_calendar(trade_date - timedelta(days=45), trade_date, as_of=trade_date)
        days = [row["trade_date"] for row in calendar.iter_rows(named=True) if row["is_open"]]
        observations = (
            self.facts.get_range(DatasetId.THEME_OBSERVATION_DAILY, days[-5], trade_date).to_dicts()
            if days else []
        )
        return build_theme_context(trade_date, days, observations, labels, dynamic, term_labels)

    def _attach_memberships(self, candidates: list[dict], details: dict[str, dict]) -> None:
        """Attach the latest static ext-data memberships and a display concept.

        ext_data is a latest-snapshot proxy, not a historical membership fact;
        the summary records that basis explicitly.
        """
        memberships = load_security_memberships(self.data_root)
        for row in candidates:
            code = _code(row["symbol"])
            row_memberships = {
                dimension: sorted(memberships[dimension].get(code, set()))
                for dimension in MEMBERSHIP_DIMENSIONS
            }
            row["memberships"] = row_memberships
            industries = row_memberships["industry_level2"] or row_memberships["industry_level1"]
            row["industry"] = industries[0] if industries else ""
            details[row["symbol"]]["memberships"] = row_memberships
            details[row["symbol"]]["industry"] = row["industry"]
        self._attach_primary_concepts(candidates)

    @staticmethod
    def _attach_primary_concepts(candidates: list[dict]) -> None:
        """Pick one display concept per candidate using the demo ordering rule.

        Specific themes first, then concepts already implied by the stock's
        industry, then concepts with more limit-up and event members. The raw
        concept list is never reduced.
        """
        stats: dict[str, dict[str, float]] = {}
        for row in candidates:
            concepts = row["memberships"]["concept"]
            for label in concepts:
                stat = stats.setdefault(label, {"limit": 0, "events": 0, "weighted": 0.0})
                stat["limit"] += row["primary_stage"] == "涨停强化"
                stat["events"] += any(source in EVENT_SOURCES for source in row["source_ids"])
                stat["weighted"] += 1 / max(1, len(concepts))
        ordered = sorted(
            stats,
            key=lambda label: (
                THEME_LEVEL_ORDER[theme_level(label)],
                -stats[label]["limit"],
                -stats[label]["events"],
                -stats[label]["weighted"],
                label,
            ),
        )
        priority = {label: index for index, label in enumerate(ordered)}
        for row in candidates:
            industry_themes = set().union(*(
                INDUSTRY_DISPLAY_THEMES.get(industry, set())
                for industry in row["memberships"]["industry_level2"]
            ))
            concepts = sorted(
                row["memberships"]["concept"],
                key=lambda label: (label not in industry_themes, priority.get(label, len(priority))),
            )
            row["primary_concept"] = concepts[0] if concepts else None

    @staticmethod
    def _research_topic_mentions(focused: dict, row: dict, term_labels: dict[str, str]) -> list[dict[str, str]]:
        """Find literal theme mentions without assigning a new trading-logic topic."""
        vocabulary = {term: label for term, label in term_labels.items()}
        for label in row.get("memberships", {}).get("concept", []):
            vocabulary.setdefault(label, label)
        title = str(focused.get("title") or "")
        excerpt = str(focused.get("match_excerpt") or "")
        found: dict[tuple[str, str], set[str]] = defaultdict(set)
        for term, label in sorted(vocabulary.items(), key=lambda item: (-len(item[0]), item[0])):
            surfaces = {re.sub(r"(概念|板块)$", "", term, flags=re.I)}
            surfaces.update(re.findall(r"\(([A-Za-z]{3,})\)", term))
            for surface in sorted(surfaces, key=len, reverse=True):
                if len(surface) < (3 if surface.isascii() else 2):
                    continue
                location = "title" if surface.casefold() in title.casefold() else "excerpt" if surface.casefold() in excerpt.casefold() else ""
                if location:
                    found[(location, surface)].add(label)
                    break
        cues = []
        for (location, surface), labels in found.items():
            if any(location == other_location and surface != other_surface and surface.casefold() in other_surface.casefold()
                   for other_location, other_surface in found):
                continue
            label = surface if surface in labels else next(iter(labels)) if len(labels) == 1 else None
            if label:
                cues.append({"label": label, "surface": surface, "location": location})
        return sorted(cues, key=lambda item: (item["location"] != "title", -len(item["surface"]), item["label"]))[:3]

    def _attach_research(self, trade_date: date, candidates: list[dict], details: dict[str, dict],
                         term_labels: dict[str, str] | None = None) -> None:
        for row in candidates:
            matches = self.research.query_company(row["name"], trade_date, limit=None)
            details[row["symbol"]]["research"] = matches[:3]
            focused = next((item for item in matches if item.get("source") == "smnc" and item.get("match_basis") == "focused"), None)
            source_date = None
            available_date = None
            if focused:
                try:
                    source_date = datetime.fromisoformat(str(focused.get("created_at") or "").replace("Z", "+00:00"))
                    available_date = datetime.fromisoformat(str(focused.get("available_at") or "").replace("Z", "+00:00"))
                    source_date = source_date.astimezone(ZoneInfo("Asia/Shanghai")).date() if source_date.tzinfo else source_date.date()
                    available_date = available_date.astimezone(ZoneInfo("Asia/Shanghai")).date() if available_date.tzinfo else available_date.date()
                except ValueError:
                    source_date = available_date = None
            counter = next((item for item in matches if item.get("match_basis") == "audited" and item.get("material_role") == "counter"), None)
            row["research_focus"] = ({
                "title": focused.get("title"),
                "excerpt": focused.get("match_excerpt"),
                "available_at": focused.get("available_at"),
                "source_date": source_date.isoformat() if source_date else None,
                "age_days": (trade_date - available_date).days if available_date else None,
                "source_url": focused.get("source_url"),
                "topic_mentions": self._research_topic_mentions(focused, row, term_labels or {}),
                "counter": {"title": counter.get("title"), "source_url": counter.get("source_url")} if counter else None,
            } if focused else None)
            details[row["symbol"]]["research_focus"] = row["research_focus"]
            row["research_count"] = sum(is_direct_research(item) for item in matches)
            row["research_breakdown"] = {
                "smnc_focused": sum(item.get("source") == "smnc" and item.get("match_basis") == "focused" for item in matches),
                "audited_primary": sum(item.get("match_basis") == "audited" and item.get("material_role") == "primary" for item in matches),
                "counter": sum(item.get("match_basis") == "audited" and item.get("material_role") == "counter" for item in matches),
            }
            details[row["symbol"]]["research_breakdown"] = row["research_breakdown"]

    def _attach_changes(self, trade_date: date, candidates: list[dict], topic_meta: dict) -> dict[str, Any]:
        dates = [value for value in self.snapshots.list_dates() if value < trade_date.isoformat()]
        previous_date = dates[-1] if dates else None
        previous = self.snapshots.get_candidates(previous_date) if previous_date else None
        if previous is None:
            return {"status": "unavailable", "topic_status": "unavailable", "previous_date": None, "counts": {}, "exits": []}
        prior_topic = (self.snapshots.get_summary(previous_date) or {}).get("topic_normalization") or {}
        topic_comparable = all(
            prior_topic.get(key) == topic_meta.get(key) for key in ("rule", "mode", "prompt_version")
        )
        prior = {row["symbol"]: row for row in previous}
        current = {row["symbol"]: row for row in candidates}
        counts: Counter[str] = Counter()
        for symbol, row in current.items():
            before = prior.get(symbol)
            changes = []
            if before is None:
                changes.append("new")
            else:
                if set(before.get("source_ids", [])) != set(row["source_ids"]):
                    changes.append("source")
                if before.get("primary_stage") != row["primary_stage"]:
                    changes.append("stage")
                if topic_comparable and set(before.get("topics", [])) != set(row["topics"]):
                    changes.append("topic")
            row["change_types"] = changes
            counts.update(changes)
        exits = [
            {"symbol": symbol, "name": row.get("name"), "previous_stage": row.get("primary_stage"), "previous_sources": row.get("sources", [])}
            for symbol, row in prior.items() if symbol not in current
        ]
        counts["exit"] = len(exits)
        counts["changed"] = sum(bool(row["change_types"]) for row in candidates)
        return {"status": "complete", "topic_status": "complete" if topic_comparable else "incompatible",
                "previous_date": previous_date, "counts": dict(counts), "exits": exits}

    def _summary(
        self,
        trade_date: date,
        candidates: list[dict],
        details: dict[str, dict],
        changes: dict,
        metadata: dict,
        topic_meta: dict,
        topic_subgroups: dict,
        theme_contexts: dict,
    ) -> dict[str, Any]:
        source_counts = Counter(source for row in candidates for source in row["source_ids"])
        source_overlap = Counter(source for row in candidates if len(row["source_ids"]) > 1 for source in row["source_ids"])
        source_stats = [
            {
                "id": source_id, "label": values[0], "stage": values[1], "expiry": values[2],
                "count": source_counts[source_id], "overlap_count": source_overlap[source_id],
                "status": metadata["quality"].get("popularity", "complete") if source_id == "popularity_warm" else "complete",
            }
            for source_id, values in SOURCE_META.items()
        ]
        stage_counts = Counter(row["primary_stage"] for row in candidates)
        cluster_rows: dict[str, list[dict]] = defaultdict(list)
        for row in candidates:
            for topic in row["topics"]:
                cluster_rows[topic].append(row)
        clusters = []
        for topic, rows in cluster_rows.items():
            stages = Counter(row["primary_stage"] for row in rows)
            catalysts: list[str] = []
            for row in rows:
                for entry in details[row["symbol"]].get("topic_evidence", []):
                    if topic in entry.get("topics", []) and entry.get("catalyst"):
                        catalysts.append(str(entry["catalyst"]))
            clusters.append({
                "name": topic, "dimension": "logic", "count": len(rows),
                "event_count": sum(any(source in EVENT_SOURCES for source in row["source_ids"]) for row in rows),
                "up_count": sum(row["pct_chg"] > 0 for row in rows),
                "mean_pct_chg": round(sum(row["pct_chg"] for row in rows) / len(rows), 2),
                "stage_counts": dict(stages),
                "symbols": [row["symbol"] for row in rows],
                "catalysts": list(dict.fromkeys(catalysts))[:5],
                "subgroups": topic_subgroups.get(topic, []),
                "research_background": self.research.query_topic(
                    topic, trade_date,
                    aliases=[term for term, label in (topic_meta.get("term_labels") or {}).items() if label == topic],
                ),
                "research_count": sum(int(row.get("research_count") or 0) for row in rows),
            })
        clusters.sort(key=lambda row: (-row["event_count"], -row["count"], row["name"]))
        quality = metadata["quality"]
        degraded = sorted(name for name, status in quality.items() if status != "complete")
        return {
            "trade_date": trade_date.isoformat(), "rule_version": RULE_VERSION,
            "status": "degraded" if degraded else "complete", "degraded_sources": degraded,
            "input_generation": self.repo.get_matrix_data_generation("stock"),
            "instrument_generation": metadata["instrument_generation"],
            "market_count": metadata["market_count"],
            "eligible_count": metadata["eligible_count"], "candidate_count": len(candidates),
            "exchange_coverage": metadata["exchange_coverage"],
            "raw_hit_count": sum(source_counts.values()),
            "overlap_count": sum(len(row["source_ids"]) > 1 for row in candidates),
            "event_count": sum(any(source in EVENT_SOURCES for source in row["source_ids"]) for row in candidates),
            "source_stats": source_stats,
            "stage_stats": [{"stage": stage, "count": stage_counts[stage]} for stage in STAGE_PRIORITY],
            "tier_stats": dict(Counter(row["tier"] for row in candidates)),
            "clusters": clusters, "daily_changes": changes, "source_quality": quality,
            "topic_normalization": topic_meta,
            "theme_context_version": THEME_CONTEXT_VERSION,
            "theme_contexts": theme_contexts,
        }
