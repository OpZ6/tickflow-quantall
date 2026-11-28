from __future__ import annotations

import gzip
import json
import os
import time

from app.quantx_data.snapshot_cache import load_or_build


def _build_returns(payload: dict[str, object]) -> tuple[list[int], object]:
    calls: list[int] = []

    def builder() -> dict[str, object]:
        calls.append(1)
        return payload

    return calls, builder


def test_first_call_builds_and_second_reads_cache(tmp_path) -> None:
    calls, builder = _build_returns({"value": 1})

    first = load_or_build(tmp_path, "k", builder, ttl=3600)
    second = load_or_build(tmp_path, "k", builder, ttl=3600)

    assert first == second == {"value": 1}
    assert len(calls) == 1
    assert (tmp_path / "k.json.gz").is_file()


def test_stale_input_mtime_invalidates_cache(tmp_path) -> None:
    calls, builder = _build_returns({"value": 1})
    source = tmp_path / "part.parquet"
    source.write_text("v1")

    load_or_build(tmp_path, "k", builder, inputs=[source], ttl=3600)
    load_or_build(tmp_path, "k", builder, inputs=[source], ttl=3600)
    assert len(calls) == 1

    # 输入被重写(补数/重跑管道) → mtime 超过缓存文件的 mtime, 自动失效
    time.sleep(0.01)
    source.write_text("v2")
    os.utime(source, None)
    load_or_build(tmp_path, "k", builder, inputs=[source], ttl=3600)
    assert len(calls) == 2


def test_expired_ttl_rebuilds_even_without_inputs(tmp_path) -> None:
    calls, builder = _build_returns({"value": 1})
    load_or_build(tmp_path, "k", builder, ttl=3600)
    cache = tmp_path / "k.json.gz"
    old = time.time() - 120
    os.utime(cache, (old, old))

    load_or_build(tmp_path, "k", builder, ttl=60)
    assert len(calls) == 2


def test_refresh_forces_rebuild(tmp_path) -> None:
    calls, builder = _build_returns({"value": 1})
    load_or_build(tmp_path, "k", builder, ttl=3600)
    load_or_build(tmp_path, "k", builder, ttl=3600, refresh=True)
    assert len(calls) == 2


def test_corrupt_cache_is_rebuilt_instead_of_raised(tmp_path) -> None:
    calls, builder = _build_returns({"value": 1})
    load_or_build(tmp_path, "k", builder, ttl=3600)
    (tmp_path / "k.json.gz").write_bytes(b"not gzip")

    result = load_or_build(tmp_path, "k", builder, ttl=3600)

    assert result == {"value": 1}
    assert len(calls) == 2
    assert json.loads(gzip.decompress((tmp_path / "k.json.gz").read_bytes())) == {"value": 1}


def test_unserialisable_payload_is_returned_without_caching(tmp_path) -> None:
    calls: list[int] = []

    def builder() -> dict[str, object]:
        calls.append(1)
        return {"bad": object()}

    result = load_or_build(tmp_path, "k", builder, ttl=3600)

    assert isinstance(result["bad"], object)
    assert not (tmp_path / "k.json.gz").exists()
    load_or_build(tmp_path, "k", builder, ttl=3600)
    assert len(calls) == 2
