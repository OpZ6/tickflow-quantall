"""Read access to canonical non-OHLCV market facts."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from app.market_facts.registry import DatasetId, get_dataset


class MarketFactRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    def _empty(self, dataset_id: DatasetId) -> pl.DataFrame:
        return pl.DataFrame(schema=get_dataset(dataset_id).storage_schema)

    def _read_date(self, dataset_id: DatasetId, trade_date: date) -> pl.DataFrame:
        path = (
            self.data_dir
            / dataset_id.value
            / f"date={trade_date.isoformat()}"
            / "part.parquet"
        )
        if not path.is_file():
            return self._empty(dataset_id)
        return pl.read_parquet(path)

    def has_partition(self, dataset_id: DatasetId, trade_date: date) -> bool:
        return (
            self.data_dir
            / dataset_id.value
            / f"date={trade_date.isoformat()}"
            / "part.parquet"
        ).is_file()

    def get_market_breadth(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.MARKET_BREADTH_DAILY, trade_date)

    def get_limit_events(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.LIMIT_EVENT_DAILY, trade_date)

    def get_theme_observations(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.THEME_OBSERVATION_DAILY, trade_date)

    def get_sector_flows(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.SECTOR_FLOW_DAILY, trade_date)

    def get_range(
        self,
        dataset_id: DatasetId,
        start: date,
        end: date,
    ) -> pl.DataFrame:
        if end < start:
            raise ValueError("end must not be before start")
        root = self.data_dir / dataset_id.value
        parts = [
            path
            for path in root.glob("date=*/part.parquet")
            if start.isoformat() <= path.parent.name.removeprefix("date=") <= end.isoformat()
        ]
        if not parts:
            return self._empty(dataset_id)
        return pl.read_parquet(sorted(parts)).sort("trade_date")

    def available_dates(self, dataset_id: DatasetId) -> list[date]:
        root = self.data_dir / dataset_id.value
        values: list[date] = []
        for path in root.glob("date=*/part.parquet"):
            try:
                values.append(date.fromisoformat(path.parent.name.removeprefix("date=")))
            except ValueError:
                continue
        return sorted(set(values))
