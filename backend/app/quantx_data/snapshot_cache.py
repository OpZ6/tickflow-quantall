"""按交易日缓存重型 QuantX 快照。

复盘页一次刷新要算两份快照: 高级图表(原 14.6s)与复盘主体(原 7.8s)。这两个构建
都是「输入=当日事实文件, 输出=一份 JSON」的纯函数, 同一交易日重复请求时完全没必要
重算; 而历史日的输入在当晚管道跑完后基本不再变化。

缓存策略:
  - 落盘为 gzip JSON, 一份快照一个文件, 服务重启后仍有效;
  - 新鲜度 = 「缓存未过期」且「输入文件没有比缓存更新」。任一输入被重写(补数、重跑
    管道), mtime 就超过缓存文件的 mtime, 自动失效, 不需要人工清缓存;
  - 当日数据仍在更新, 用短 TTL(默认 60s); 历史日用长 TTL(默认 6h)兜底, 防止
    跨日回补(改写窗口内更早的交易日)这类 mtime 指纹抓不到的变化;
  - 写盘走临时文件 + os.replace, 并发请求不会读到半份 JSON。
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PAST_TTL_SECONDS = 6 * 3600
LIVE_TTL_SECONDS = 60

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = _locks[key] = threading.Lock()
        return lock


def _max_mtime_ns(inputs: Iterable[Path]) -> int:
    newest = 0
    for path in inputs:
        try:
            newest = max(newest, path.stat().st_mtime_ns)
        except OSError:
            continue
    return newest


def _json_default(value: Any) -> Any:
    # numpy 标量 / date 之类偶尔会混进快照; 只做保守转换, 转不了就让缓存写入失败,
    # 由调用方退回「本次照常返回、只是没缓存」。
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    raise TypeError(f"not JSON serialisable: {type(value)!r}")


def _read(path: Path) -> Any | None:
    try:
        return json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, ValueError, EOFError):
        return None


def _write(path: Path, payload: Any) -> bool:
    try:
        raw = json.dumps(payload, ensure_ascii=False, default=_json_default).encode()
    except (TypeError, ValueError) as exc:
        logger.warning("quantx snapshot cache skipped (%s): %s", path.name, exc)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(gzip.compress(raw, 6))
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("quantx snapshot cache write failed (%s): %s", path.name, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def load_or_build(
    cache_dir: Path,
    key: str,
    builder: Callable[[], Any],
    *,
    inputs: Iterable[Path] = (),
    ttl: float = PAST_TTL_SECONDS,
    refresh: bool = False,
) -> Any:
    """返回快照: 命中缓存直接读, 否则调用 builder 并落盘。"""
    path = Path(cache_dir) / f"{key}.json.gz"
    input_paths = list(inputs)
    if not refresh:
        cached = _fresh_payload(path, input_paths, ttl)
        if cached is not None:
            return cached

    with _lock_for(path):
        # 同一 key 的并发请求: 抢到锁后先复查, 避免同时重算同一份 15s 的快照。
        if not refresh:
            cached = _fresh_payload(path, input_paths, ttl)
            if cached is not None:
                return cached
        started = time.perf_counter()
        payload = builder()
        elapsed = time.perf_counter() - started
        _write(path, payload)
        logger.info("quantx snapshot built: %s (%.2fs)", key, elapsed)
        return payload


def _fresh_payload(path: Path, inputs: list[Path], ttl: float) -> Any | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if ttl > 0 and time.time() - stat.st_mtime > ttl:
        return None
    if _max_mtime_ns(inputs) > stat.st_mtime_ns:
        return None
    return _read(path)
