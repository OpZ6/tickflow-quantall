from datetime import date

import pandas as pd

from app.plugins.local_financial.provider import LocalFinancialProvider


def _frame(columns: int, rows: list[list[object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=[f"c{i}" for i in range(columns)])


def test_market_income_normalizes_full_market_by_period(monkeypatch):
    import akshare

    raw = _frame(
        15,
        [[1, "600519", "贵州茅台", 10.0, 12.0, 100.0, 8.0,
          50.0, 2.0, 3.0, 1.0, 56.0, 44.0, 45.0, date(2026, 8, 20)]],
    )
    monkeypatch.setattr(akshare, "stock_lrb_em", lambda date: raw)
    df = LocalFinancialProvider().get_financial_market_table(
        "income", date(2026, 6, 30)
    )
    row = df.to_dicts()[0]
    assert row["symbol"] == "600519.SH"
    assert row["period_end"] == date(2026, 6, 30)
    assert row["net_income"] == 10.0
    assert row["revenue"] == 100.0
    assert row["announce_date"] == date(2026, 8, 20)


def test_market_balance_sheet_combines_mainland_and_beijing(monkeypatch):
    import akshare

    sh = _frame(
        15,
        [[1, "600519", "贵州茅台", 1, 2, 3, 100, 5, 4, 20, 0, 2, 20, 80,
          date(2026, 8, 20)]],
    )
    bj = _frame(
        15,
        [[1, "920001", "北交样例", 1, 2, 3, 50, 5, 4, 10, 0, 2, 20, 40,
          date(2026, 8, 21)]],
    )
    monkeypatch.setattr(akshare, "stock_zcfz_em", lambda date: sh)
    monkeypatch.setattr(akshare, "stock_zcfz_bj_em", lambda date: bj)
    df = LocalFinancialProvider().get_financial_market_table(
        "balance_sheet", date(2026, 6, 30)
    )
    assert set(df["symbol"].to_list()) == {"600519.SH", "920001.BJ"}
    assert df.filter(df["symbol"] == "920001.BJ")["total_assets"].item() == 50.0


def test_market_cash_flow_uses_canonical_fields(monkeypatch):
    import akshare

    raw = _frame(
        12,
        [[1, "000001", "平安银行", 5, 1, 20, 40, -10, -20, -5, -10,
          date(2026, 8, 22)]],
    )
    monkeypatch.setattr(akshare, "stock_xjll_em", lambda date: raw)
    df = LocalFinancialProvider().get_financial_market_table(
        "cash_flow", date(2026, 6, 30)
    )
    row = df.to_dicts()[0]
    assert row["symbol"] == "000001.SZ"
    assert row["net_operating_cash_flow"] == 20.0
    assert row["net_investing_cash_flow"] == -10.0
    assert row["net_financing_cash_flow"] == -5.0
