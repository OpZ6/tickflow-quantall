from datetime import date

import polars as pl

from app.services.financial_analysis import analyze_stock


def test_analysis_respects_announcement_date(tmp_path):
    out = tmp_path / "financials" / "metrics"
    out.mkdir(parents=True)
    pl.DataFrame({
        "symbol": ["600519.SH", "600519.SH"],
        "period_end": [date(2025, 12, 31), date(2026, 3, 31)],
        "announce_date": [date(2026, 3, 1), date(2026, 5, 1)],
        "revenue_yoy": [20.0, 99.0], "net_income_yoy": [25.0, 99.0],
        "roe": [10.0, 99.0], "gross_margin": [30.0, 99.0], "eps_basic": [1.0, 9.0],
    }).write_parquet(out / "part.parquet")
    result = analyze_stock(tmp_path, "600519.SH", date(2026, 4, 1))
    assert result["cards"]["growth"]["revenue_yoy"] == 20.0
    assert result["coverage"]["latest_period"] == "2025-12-31"
