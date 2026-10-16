"""Read access to canonical non-OHLCV market facts."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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

    def get_security_listing_snapshot(self, snapshot_date: date) -> pl.DataFrame:
        """Read one explicit observation snapshot, not a historical universe."""
        return self._read_date(DatasetId.SECURITY_LISTING_HISTORY, snapshot_date)

    def get_security_name_snapshot(self, snapshot_date: date) -> pl.DataFrame:
        """Read reconstructed intervals; callers must enforce knowledge cutoffs."""
        return self._read_date(DatasetId.SECURITY_NAME_HISTORY, snapshot_date)

    def get_security_names_at(
        self, symbols: list[str], *, snapshot_date: date, cutoff: datetime,
        allow_reconstructed: bool = False,
    ) -> pl.DataFrame:
        """Resolve an explicit snapshot without current-name or future fallback."""
        from app.market_facts.security_history import resolve_security_names

        return resolve_security_names(
            self.get_security_name_snapshot(snapshot_date), symbols, cutoff=cutoff,
            allow_reconstructed=allow_reconstructed,
        )

    def get_daily_security_eligibility(
        self,
        symbols: list[str],
        *,
        day: date,
        listing_snapshot_date: date,
        name_snapshot_date: date,
        calendar_as_of: date,
        cutoff: datetime,
        exclude_new_days: int = 0,
        exclude_st: bool = True,
        allow_reconstructed_names: bool = False,
    ) -> pl.DataFrame:
        """Resolve one universe day from explicit fact versions only."""
        if cutoff.tzinfo is None:
            raise ValueError("cutoff must have a timezone")
        if cutoff.astimezone(ZoneInfo("Asia/Shanghai")).date() != day:
            raise ValueError("cutoff Beijing date must equal eligibility day")
        listings = self.get_security_listing_snapshot(listing_snapshot_date)
        names = self.get_security_names_at(
            symbols,
            snapshot_date=name_snapshot_date,
            cutoff=cutoff,
            allow_reconstructed=allow_reconstructed_names,
        )
        calendars: list[pl.DataFrame] = []
        if exclude_new_days > 0 and not listings.is_empty():
            relevant = listings.filter(pl.col("symbol").is_in(symbols))
            for exchange in relevant["exchange"].drop_nulls().unique().to_list():
                exchange_rows = relevant.filter(pl.col("exchange") == exchange)
                starts = exchange_rows["list_date"].drop_nulls()
                start = min(starts) if len(starts) else day
                calendars.append(
                    self.get_trading_calendar(
                        start,
                        day,
                        exchange=exchange,
                        as_of=calendar_as_of,
                    )
                )
        calendar = (
            pl.concat(calendars)
            if calendars
            else self._empty(DatasetId.TRADING_CALENDAR)
        )
        from app.market_facts.security_history import resolve_daily_security_eligibility

        return resolve_daily_security_eligibility(
            listings,
            names,
            calendar,
            symbols,
            day=day,
            exclude_new_days=exclude_new_days,
            exclude_st=exclude_st,
        )

    def get_market_liquidity(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.MARKET_LIQUIDITY_DAILY, trade_date)

    def get_margin_history(
        self,
        start: date,
        end: date,
        *,
        scope: str = "CN_A",
        as_of: date | None = None,
    ) -> pl.DataFrame:
        """Return the newest known margin rows as of the requested horizon."""
        if end < start:
            raise ValueError("end must not be before start")
        cutoff = as_of or end
        root = self.data_dir / DatasetId.MARGIN_DAILY.value
        parts = sorted(
            [
                path
                for path in root.glob("date=*/part.parquet")
                if path.parent.name.removeprefix("date=") <= cutoff.isoformat()
            ],
            reverse=True,
        )
        selected: list[pl.DataFrame] = []
        seen: set[date] = set()
        for path in parts:
            frame = pl.read_parquet(path).filter(
                (pl.col("scope") == scope)
                & pl.col("trade_date").is_between(start, end, closed="both")
                & (pl.col("as_of_date") <= cutoff)
            )
            if seen:
                frame = frame.filter(~pl.col("trade_date").is_in(seen))
            if not frame.is_empty():
                selected.append(frame)
                seen.update(frame["trade_date"].to_list())
        return (
            pl.concat(selected).sort("trade_date")
            if selected
            else self._empty(DatasetId.MARGIN_DAILY)
        )

    def get_trading_calendar(
        self,
        start: date,
        end: date,
        *,
        exchange: str = "SSE",
        as_of: date | None = None,
    ) -> pl.DataFrame:
        """Return the newest known calendar row as of the requested horizon."""
        if end < start:
            raise ValueError("end must not be before start")
        cutoff = as_of or end
        root = self.data_dir / DatasetId.TRADING_CALENDAR.value
        parts = sorted(
            [
            path
            for path in root.glob("date=*/part.parquet")
            if path.parent.name.removeprefix("date=") <= cutoff.isoformat()
            ],
            reverse=True,
        )
        if not parts:
            return self._empty(DatasetId.TRADING_CALENDAR)
        selected: list[pl.DataFrame] = []
        seen: set[date] = set()
        expected_days = (end - start).days + 1
        for path in parts:
            frame = pl.read_parquet(path).filter(
                (pl.col("exchange") == exchange)
                & pl.col("trade_date").is_between(start, end, closed="both")
                & (pl.col("as_of_date") <= cutoff)
            )
            if seen:
                frame = frame.filter(~pl.col("trade_date").is_in(seen))
            if not frame.is_empty():
                selected.append(frame)
                seen.update(frame["trade_date"].to_list())
            if len(seen) >= expected_days:
                break
        return (
            pl.concat(selected).sort("trade_date")
            if selected
            else self._empty(DatasetId.TRADING_CALENDAR)
        )

    def is_trading_day(
        self,
        day: date,
        *,
        exchange: str = "SSE",
        as_of: date | None = None,
    ) -> bool | None:
        frame = self.get_trading_calendar(
            day,
            day,
            exchange=exchange,
            as_of=as_of or day,
        )
        return None if frame.is_empty() else bool(frame["is_open"].item())

    def get_limit_events(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.LIMIT_EVENT_DAILY, trade_date)

    def get_limit_ladder(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.LIMIT_LADDER_DAILY, trade_date)

    def get_theme_observations(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.THEME_OBSERVATION_DAILY, trade_date)

    def get_theme_members(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.THEME_MEMBER_DAILY, trade_date)

    def get_sector_flows(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.SECTOR_FLOW_DAILY, trade_date)

    def get_sector_breadth(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.SECTOR_BREADTH_DAILY, trade_date)

    def get_market_state(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.MARKET_STATE_DAILY, trade_date)

    def get_market_signals(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.MARKET_SIGNAL_DAILY, trade_date)

    def get_screening_candidates(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.SCREENING_CANDIDATE_DAILY, trade_date)

    def get_security_popularity(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.SECURITY_POPULARITY_DAILY, trade_date)

    def get_stock_logic_evidence(self, trade_date: date) -> pl.DataFrame:
        return self._read_date(DatasetId.STOCK_LOGIC_EVIDENCE_DAILY, trade_date)

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
        frames = [pl.read_parquet(path) for path in sorted(parts)]
        return pl.concat(frames, how="diagonal_relaxed").sort("trade_date")

    def available_dates(self, dataset_id: DatasetId) -> list[date]:
        root = self.data_dir / dataset_id.value
        values: list[date] = []
        for path in root.glob("date=*/part.parquet"):
            try:
                values.append(date.fromisoformat(path.parent.name.removeprefix("date=")))
            except ValueError:
                continue
        return sorted(set(values))
