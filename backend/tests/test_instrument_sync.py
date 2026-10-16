from __future__ import annotations

from app.services import instrument_sync


def test_sync_instruments_keeps_local_dimension_when_client_is_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    def _unavailable():
        raise ImportError("missing proxy transport")

    monkeypatch.setattr(instrument_sync, "get_client", _unavailable)

    assert instrument_sync.sync_instruments(tmp_path) == 0
    assert not (tmp_path / "instruments" / "instruments.parquet").exists()
