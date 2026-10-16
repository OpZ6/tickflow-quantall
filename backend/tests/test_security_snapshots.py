import json
from datetime import UTC, datetime, timedelta

import pytest

from app.quantx_data import security_snapshots as snapshots
from app.quantx_data.io import write_json_atomic
from app.quantx_data.schemas import SourceSpec
from app.quantx_data.source_manager import SourceManager

NOW = datetime(2026, 9, 7, 4, tzinfo=UTC)


def row(code="600000.SH", endpoint="namechange", status="L"):
    record = dict.fromkeys(snapshots.FIELDS[endpoint].split(","))
    record.update(ts_code=code, name="example")
    if endpoint == "namechange":
        record["start_date"] = "20200101"
    else:
        record["list_status"] = status
    return record


def manager_for(responses, calls):
    manager = SourceManager()

    def collect(day, directory):
        request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        calls.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return {"status": "ok", "scraped_at": NOW.isoformat(), "request": request, "rows": response}

    manager.register(SourceSpec("security_history_snapshot", True, "test", "test", max_retries=0), collect)
    return manager


def test_offline_new_does_not_create_directory(tmp_path):
    target = tmp_path / "new"
    assert snapshots.collect_step(target, "namechange")["status"] == "pending"
    assert not target.exists()


def test_resume_failure_cooldown_and_terminal_reuse(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "PAGE_SIZE", 2)
    calls = []
    manager = manager_for([[row(), row("000001.SZ")], RuntimeError("访问频次超限"), []], calls)
    first = snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=NOW)
    saved = (tmp_path / "page-000000.json").read_bytes()
    assert first["next_page"] == 1
    assert snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=NOW)["status"] == "cooldown"
    failed = snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=NOW + timedelta(seconds=70))
    assert failed["error_kind"] == "rate_limit"
    assert failed["next_page"] == 1
    final = snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=NOW + timedelta(seconds=140))
    assert final["status"] == "collected_unverified"
    assert final["rows"] == 2
    assert final["production_published"] is False
    snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=NOW + timedelta(seconds=210))
    assert [call["params"]["offset"] for call in calls] == [0, 2, 2]
    assert (tmp_path / "page-000000.json").read_bytes() == saved


def test_duplicate_page_is_retained_as_rejected_not_advanced(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "PAGE_SIZE", 1)
    calls = []
    manager = manager_for([[row()], [row()]], calls)
    snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=NOW)
    state = snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=NOW + timedelta(seconds=70))
    assert state["error_kind"] == "invalid_page"
    assert state["next_page"] == 1
    assert not (tmp_path / "page-000001.json").exists()
    assert (tmp_path / "request-000001/rejected.json").exists()
    blocked = snapshots.collect_step(
        tmp_path,
        "namechange",
        allow_network=True,
        manager=manager,
        now=NOW + timedelta(seconds=140),
    )
    assert blocked["requires_resolution"] is True
    assert len(calls) == 2


def test_stock_statuses_include_unlisted_and_paused(tmp_path):
    calls = []
    manager = manager_for([[row(endpoint="stock_basic")], [], [], [], []], calls)
    for index in range(5):
        state = snapshots.collect_step(tmp_path, "stock_basic", allow_network=True, manager=manager, now=NOW + timedelta(hours=2 * index))
    assert [call["params"]["list_status"] for call in calls] == list(snapshots.STATUSES)
    assert state["status"] == "collected_unverified"
    assert state["rows"] == 1


@pytest.mark.parametrize("response", [[{}], [row(endpoint="stock_basic", status="D")], [row(endpoint="stock_basic")] * 6000])
def test_invalid_listing_response_is_not_accepted(tmp_path, response):
    state = snapshots.collect_step(tmp_path, "stock_basic", allow_network=True, manager=manager_for([response], []), now=NOW)
    assert state["error_kind"] == "invalid_page"
    assert state["pages"] == 0


def test_corrupt_manifest_fails_closed(tmp_path):
    (tmp_path / "manifest.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        snapshots.collect_step(tmp_path, "namechange", allow_network=True)
    assert not (tmp_path / ".writer.lock").exists()


def test_missing_committed_page_does_not_refetch(tmp_path):
    write_json_atomic(tmp_path / "manifest.json", {"endpoint": "namechange", "pages": 1})
    with pytest.raises(ValueError, match="committed page is missing"):
        snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager_for([], []))


def test_durable_page_survives_manifest_update_interruption(tmp_path):
    request = {**snapshots.request_for("namechange", 0), "page": 0}
    write_json_atomic(tmp_path / "page-000000.json", {"request": request, "status": "ok", "scraped_at": NOW.isoformat(), "rows": [row()]})
    state = snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager_for([], []), now=NOW)
    assert state["status"] == "collected_unverified"
    assert state["rows"] == 1


def test_existing_writer_is_not_removed(tmp_path):
    lock = tmp_path / ".writer.lock"
    lock.write_text("another writer", encoding="utf-8")
    with pytest.raises(FileExistsError):
        snapshots.collect_step(tmp_path, "namechange", allow_network=True)
    assert lock.read_text(encoding="utf-8") == "another writer"


@pytest.mark.parametrize("error,expected", [("1次/小时", 3605), ("5次/天", 86405), ("1次/分钟", 65)])
def test_actual_quota_window_controls_retry(tmp_path, error, expected):
    calls = []
    manager = manager_for([RuntimeError(f"频率超限({error})")], calls)
    state = snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=NOW)
    assert datetime.fromisoformat(state["next_attempt_at"]) == NOW + timedelta(seconds=expected)
    assert snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=NOW + timedelta(seconds=30))["status"] == "cooldown"
    assert len(calls) == 1


def test_success_keeps_learned_hourly_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "PAGE_SIZE", 1)
    calls = []
    manager = manager_for([RuntimeError("频率超限(1次/小时)"), [row()]], calls)
    snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=NOW)
    success_time = NOW + timedelta(seconds=3700)
    success = snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=success_time)
    assert success["retry_delay_seconds"] == 3605
    assert datetime.fromisoformat(success["next_attempt_at"]) == success_time + timedelta(seconds=3605)
    cooldown = snapshots.collect_step(tmp_path, "namechange", allow_network=True, manager=manager, now=success_time + timedelta(seconds=70))
    assert cooldown["status"] == "cooldown"
    assert len(calls) == 2
