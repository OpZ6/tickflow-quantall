"""Deterministic dynamic topic clustering over the day's logic evidence.

This module replaces the fixed keyword table as the primary hot-view topic
source. The pipeline is:

1. extract source-specific terms from ``match_text`` (hot-list concept tags,
   anomaly keyword lists, ladder theme names, hot-list reasons);
2. map terms onto the curated legacy pattern labels when they match, then fold
   the remaining terms into canonical labels by verified alias equality;
3. keep distinct canonical labels apart even when their stocks overlap;
   co-occurrence is not evidence that two directions are synonyms;
4. keep groups with at least two member stocks and label each group with its
   highest document frequency term.

An optional LLM stage (``settings.stock_pool_topic_llm``, disabled by default)
only rewrites the alias map and drops noise labels. It never changes stock
membership. The applied aliases are persisted inside the snapshot and reused
when the same trade date is rebuilt, so recomputation stays reproducible; any
failure falls back to the deterministic labels and records ``llm-fallback``.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.stock_pools.topics import SPECIFIC_OVERRIDES, topic_labels

CLUSTER_RULE = "exact_term,explicit_alias,shared>=2,noise=v4"
PROMPT_VERSION = "stock-pool-topic-v3"
MIN_SHARED = 2
LLM_MAX_TERMS = 5
LLM_SAMPLE_CHARS = 50
MAX_SUBGROUPS = 10

GENERIC_THEMES = {"其他", "大消费", "独立逻辑"}

# Pure market-noise words never become topics.
_NOISE_TERM = re.compile(r"^(板块|大盘|市场|情绪|题材|概念|主力|资金|低位|高位|低位股|高位股)$")
_NOISE_TEXT = re.compile(
    r"板块|大盘|涨停|跌停|上涨|下跌|回落|拉升|冲高|异动|连板|首板|炸板|半年报|季报|年报"
)
# Attribute/state descriptors and background policy tags are not tradable
# directions for the hot view; corporate events (重组/收购/订单) stay.
_NON_THEME = re.compile(
    r"业绩增长|业绩扭亏|业绩预增|业绩预减|业绩预亏|业绩承压|中报增长|年报增长|"
    r"高位回调|此前涨幅|涨幅较大|股价异动|"
    r"股份回购|回购股份|股份增持|股份减持|股东减持|大股东增持|"
    r"主力资金净流出|融资融券|亏损|上市首日大涨|传闻澄清|国家大基金持股|股东拟减持|"
    r"产能扩张|扩产|募投|"
    r"全国化|乡村振兴|共同富裕示范区|国企改革|国有控股|中国AI 50|"
    r"转债下修"
)
_SPLIT_RE = re.compile(r"[+\uff0b;\uff1b]")
_SUFFIX_RE = re.compile(r"(概念|板块)$")
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)


def _code(value: Any) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[-6:] if len(digits) >= 6 else ""


def _norm(term: str) -> str:
    return _SUFFIX_RE.sub("", term).strip().lower()


_ALIAS_CACHE: dict[str, frozenset[str]] = {}
_VERIFIED_ALIASES = {
    "vna": "vna矢量网络分析仪",
    "矢量网络分析仪": "vna矢量网络分析仪",
    "网络分析仪": "vna矢量网络分析仪",
}


def _aliases(term: str) -> frozenset[str]:
    cached = _ALIAS_CACHE.get(term)
    if cached is not None:
        return cached
    name = _norm(term)
    forms = {_VERIFIED_ALIASES.get(name, name)}
    result = frozenset(form for form in forms if len(form) >= 2)
    _ALIAS_CACHE[term] = result
    return result


def split_terms(evidence_source: str, match_text: str) -> list[str]:
    """Split one evidence row's match text into raw terms."""
    text = (match_text or "").strip()
    if not text:
        return []
    parts = [text] if evidence_source == "limit_ladder" else _SPLIT_RE.split(text)
    return [
        term for term in (part.strip().strip(";\uff1b,\uff0c\u3002 ") for part in parts) if term
    ]


def keep_term(term: str) -> bool:
    return (
        2 <= len(term) <= 14
        and term not in GENERIC_THEMES
        and not _NOISE_TERM.match(term)
        and not _NOISE_TEXT.search(term)
        and not _NON_THEME.search(term)
    )


@dataclass
class _Group:
    label: str
    is_legacy: bool = False
    symbols: set[str] = field(default_factory=set)
    terms: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class TopicAssignment:
    topics: dict[str, list[str]]
    label_of: dict[str, str]
    subgroups: dict[str, list[dict]]
    meta: dict[str, Any]

    def labels_for(self, terms: Iterable[str]) -> list[str]:
        return sorted({self.label_of[term] for term in terms if term in self.label_of})


def extract_terms(
    rows: Iterable[dict],
) -> tuple[dict[str, dict[str, set[str]]], dict[str, set[str]]]:
    """Return ``symbol -> term -> sources`` and ``term -> symbols``."""
    by_symbol: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    term_stocks: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        symbol = _code(row.get("symbol"))
        if not symbol:
            continue
        source = str(row.get("evidence_source") or "")
        for term in split_terms(source, str(row.get("match_text") or "")):
            if not keep_term(term):
                continue
            by_symbol[symbol][term].add(source)
            term_stocks[term].add(symbol)
    return by_symbol, term_stocks


def _canonicalize(term_stocks: dict[str, set[str]]) -> dict[str, _Group]:
    """Seed curated labels first, then fold remaining terms into alias groups."""
    groups: dict[str, _Group] = {}

    def add(canonical_id: str, label: str, is_legacy: bool, term: str) -> None:
        group = groups.get(canonical_id)
        if group is None:
            group = _Group(label=label, is_legacy=is_legacy)
            groups[canonical_id] = group
        group.terms.add(term)
        group.symbols |= term_stocks[term]

    ordered = sorted(term_stocks, key=lambda term: (-len(term_stocks[term]), term))
    # A composite direction must not collapse into the first matched family.
    legacy_terms = [term for term in ordered if len(topic_labels(term, whole_term=True)) == 1]
    dynamic_terms = [term for term in ordered if len(topic_labels(term, whole_term=True)) != 1]
    for term in legacy_terms:
        add(topic_labels(term, whole_term=True)[0], topic_labels(term, whole_term=True)[0], True, term)

    for term in dynamic_terms:
        best: _Group | None = None
        best_overlap = -1
        for group in groups.values():
            if not _alias_match(term, group):
                continue
            overlap = len(term_stocks[term] & group.symbols)
            if overlap > best_overlap or (
                overlap == best_overlap and best is not None and group.label < best.label
            ):
                best, best_overlap = group, overlap
        if best is None:
            add(term, term, False, term)
        else:
            best.terms.add(term)
            best.symbols |= term_stocks[term]
    return groups


def _alias_match(term: str, group: _Group) -> bool:
    term_forms = _aliases(term)
    if not term_forms:
        return False
    # Match the canonical name only: a compound child term cannot become a
    # bridge that absorbs its broad parent or another industry.
    for candidate in (group.label,):
        candidate_forms = _aliases(candidate)
        if not candidate_forms:
            continue
        if term_forms & candidate_forms:
            return True
    return False


def _qualified_groups(groups: dict[str, _Group]) -> list[_Group]:
    return sorted(
        (group for group in groups.values() if len(group.symbols) >= MIN_SHARED),
        key=lambda group: (-len(group.symbols), group.label),
    )


def _apply_normalization(
    groups: list[_Group], aliases: dict[str, Any], dropped: Iterable[Any]
) -> tuple[list[_Group], dict[str, str], list[str]]:
    valid = {group.label for group in groups}
    applied_aliases = {
        str(key): str(value).strip()
        for key, value in aliases.items()
        if key in valid and isinstance(value, str) and value.strip() and value.strip() != key
        and bool(_aliases(str(key)) & _aliases(value.strip()))
    }
    applied_dropped = sorted({str(value) for value in dropped if str(value) in valid and not keep_term(str(value))})

    def resolve(label: str) -> str:
        seen: set[str] = set()
        while label in applied_aliases and label not in seen:
            seen.add(label)
            label = applied_aliases[label]
        return label

    merged: dict[str, _Group] = {}
    for group in groups:
        if group.label in applied_dropped:
            continue
        target = resolve(group.label)
        if target in applied_dropped:
            continue
        if target not in merged:
            merged[target] = _Group(label=target)
        merged[target].symbols |= group.symbols
        merged[target].terms |= group.terms
    ordered = sorted(merged.values(), key=lambda group: (-len(group.symbols), group.label))
    return ordered, applied_aliases, applied_dropped


def _term_families(group: _Group, term_stocks: dict[str, set[str]]) -> list[tuple[str, set[str]]]:
    """Fold alias-equivalent raw terms inside one cluster into display families."""
    families: list[dict] = []
    for term in sorted(group.terms, key=lambda item: (-len(term_stocks[item]), item)):
        placed = False
        for family in families:
            probe = _Group(label=family["name"], terms=family["terms"])
            if _alias_match(term, probe):
                family["terms"].add(term)
                family["symbols"] |= term_stocks[term]
                placed = True
                break
        if not placed:
            families.append({"name": term, "terms": {term}, "symbols": set(term_stocks[term])})
    return [(family["name"], family["symbols"]) for family in families]


def _samples(rows: Iterable[dict]) -> dict[str, str]:
    samples: dict[str, str] = {}
    for row in rows:
        symbol = _code(row.get("symbol"))
        text = str(row.get("text") or row.get("match_text") or "").strip()
        if symbol and symbol not in samples and text:
            samples[symbol] = text
    return samples


def _llm_payload(
    groups: list[_Group], term_stocks: dict[str, set[str]], samples: dict[str, str]
) -> list[dict]:
    payload = []
    for group in groups:
        sample = next(
            (samples[symbol] for symbol in sorted(group.symbols) if samples.get(symbol)), ""
        )
        terms = sorted(group.terms, key=lambda term: (-len(term_stocks[term]), term))
        payload.append(
            {
                "label": group.label,
                "stocks": len(group.symbols),
                "terms": terms[:LLM_MAX_TERMS],
                "sample": sample[:LLM_SAMPLE_CHARS],
            }
        )
    return payload


_LLM_SYSTEM = (
    "你是A股题材聚类归一化助手。输入是当日从涨停梯队、同花顺热点、异动解读、"
    "热榜概念等来源提取的题材标签。股票重合不代表标签同义, 保留不同产业链细分。只做两件事: "
    "1) 把表达同一题材的标签合并, 给出别名映射, 目标优先选择输入中更标准常用的标签; "
    "2) 删除不是题材的噪声标签。不得新增输入之外的标签, 不得拆分已有标签。"
    '只输出JSON: {"aliases": {"原标签": "目标标签"}, "drop": ["标签"]}; '
    '没有需要合并或删除时输出 {"aliases": {}, "drop": []}。不要输出其他文字。'
)


async def _request_normalization(payload: list[dict]) -> str:
    from app.services.ai_provider import generate_ai_text

    messages = [
        {"role": "system", "content": _LLM_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    return await generate_ai_text(messages, temperature=0.0, max_tokens=4000, timeout=120.0)


def _run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def parse_normalization(text: str) -> dict[str, Any]:
    """Parse the LLM reply into ``{"aliases": {...}, "drop": [...]}``."""
    match = _JSON_BLOCK_RE.search(text or "")
    if not match:
        raise ValueError("LLM reply contains no JSON object")
    raw = json.loads(match.group(0))
    aliases = raw.get("aliases") if isinstance(raw.get("aliases"), dict) else {}
    dropped = raw.get("drop") if isinstance(raw.get("drop"), list) else []
    return {
        "aliases": {str(key): str(value) for key, value in aliases.items()},
        "drop": [str(value) for value in dropped],
    }


def llm_normalize(payload: list[dict]) -> dict[str, Any]:
    """Call the configured LLM once and return the validated alias map."""
    return parse_normalization(_run_sync(_request_normalization(payload)))


def llm_enabled() -> bool:
    from app.config import settings
    from app.services.ai_provider import ai_configured

    return bool(settings.stock_pool_topic_llm) and ai_configured()


def build_topic_assignment(
    rows: list[dict],
    *,
    normalizer: Callable[[list[dict]], dict[str, Any]] | None = None,
    reuse: dict[str, Any] | None = None,
) -> TopicAssignment:
    """Build per-symbol topic labels from one day's logic-evidence rows."""
    by_symbol, term_stocks = extract_terms(rows)
    groups = _qualified_groups(_canonicalize(term_stocks))
    mode = "deterministic"
    extra: dict[str, Any] = {}
    if reuse and reuse.get("rule") == CLUSTER_RULE and reuse.get("mode") == "llm" and reuse.get("prompt_version") == PROMPT_VERSION:
        groups, aliases, dropped = _apply_normalization(
            groups, reuse.get("aliases") or {}, reuse.get("dropped") or []
        )
        mode = "llm"
        extra = {
            "prompt_version": PROMPT_VERSION,
            "model": str(reuse.get("model") or ""),
            "aliases": aliases,
            "dropped": dropped,
        }
    elif normalizer is not None:
        try:
            result = normalizer(_llm_payload(groups, term_stocks, _samples(rows)))
            groups, aliases, dropped = _apply_normalization(
                groups, result.get("aliases") or {}, result.get("drop") or []
            )
            from app.services.ai_provider import current_ai_model

            mode = "llm"
            extra = {
                "prompt_version": PROMPT_VERSION,
                "model": current_ai_model(),
                "aliases": aliases,
                "dropped": dropped,
            }
        except Exception as exc:  # LLM is an optional enhancement; deterministic labels stay usable
            mode = "llm-fallback"
            extra = {
                "prompt_version": PROMPT_VERSION,
                "error": f"{type(exc).__name__}: {exc}"[:200],
            }

    order = {group.label: len(group.symbols) for group in groups}
    label_of = {term: group.label for group in groups for term in group.terms}
    topics: dict[str, list[str]] = {}
    for symbol, terms in by_symbol.items():
        labels = {label_of[term] for term in terms if term in label_of}
        for broad, specific in SPECIFIC_OVERRIDES.items():
            if broad in labels and specific in labels:
                labels.discard(broad)
        if labels:
            topics[symbol] = sorted(labels, key=lambda label: (-order[label], label))

    subgroups: dict[str, list[dict]] = {}
    for group in groups:
        entries = [
            {"name": name, "count": len(symbols), "symbols": sorted(symbols)}
            for name, symbols in _term_families(group, term_stocks)
            if name != group.label and len(symbols) >= MIN_SHARED
        ]
        if entries:
            entries.sort(key=lambda entry: (-entry["count"], entry["name"]))
            subgroups[group.label] = entries[:MAX_SUBGROUPS]

    meta = {
        "mode": mode,
        "rule": CLUSTER_RULE,
        "term_count": len(term_stocks),
        "label_count": len(groups),
        "stock_count": len(topics),
        **extra,
    }
    return TopicAssignment(topics=topics, label_of=label_of, subgroups=subgroups, meta=meta)
