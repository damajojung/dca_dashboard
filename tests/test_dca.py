from datetime import date

import pytest

from dca import DcaInputs, Fee, buy_dates, final_value, simulate


def make(**kw):
    base = dict(amount_per_buy=100, frequency="Monthly", start=date(2025, 1, 31), years=2,
                annual_return_pct=0, inflation_pct=0, start_price=10)
    base.update(kw)
    return DcaInputs(**base)


@pytest.mark.parametrize("freq,n", [("Weekly", 105), ("Bi-weekly", 53), ("Monthly", 24), ("Quarterly", 8), ("Yearly", 2)])
def test_buy_counts(freq, n):
    assert len(buy_dates(date(2025, 1, 1), 2, freq)) == n


def test_month_end_does_not_drift():
    d = buy_dates(date(2025, 1, 31), 1, "Monthly")
    assert [x.day for x in d[:3]] == [31, 28, 31]


def test_fees_percentage_and_fixed():
    df = simulate(make(fx_fee=Fee(1.0, 0), trading_fee=Fee(0.5, 2)))
    row = df.iloc[0]
    assert row["FX fee"] == pytest.approx(1.0)
    assert row["Trading fee"] == pytest.approx(99 * 0.005 + 2)
    assert row["Net invested"] == pytest.approx(100 - 1 - 2.495)
    assert df["Total fees paid"].iloc[-1] == pytest.approx(24 * 3.495)


def test_zero_return_value_equals_net_invested():
    df = simulate(make(trading_fee=Fee(0, 1)))
    assert df["Portfolio value"].iloc[-1] == pytest.approx(24 * 99)


def test_growth_and_inflation():
    inp = make(frequency="Yearly", years=1, annual_return_pct=10, inflation_pct=10)
    df = simulate(inp)
    nominal, real = final_value(inp, df)
    assert nominal == pytest.approx(110)
    assert real == pytest.approx(100)


def test_fee_never_exceeds_amount():
    df = simulate(make(trading_fee=Fee(0, 500)))
    assert (df["Net invested"] >= 0).all()


def test_initial_shares_grow_with_price():
    inp = make(frequency="Yearly", years=1, annual_return_pct=10, initial_shares=50)
    df = simulate(inp)
    assert inp.initial_value == pytest.approx(500)
    assert df["Total shares"].iloc[-1] == pytest.approx(60)
    assert df["Total capital"].iloc[-1] == pytest.approx(600)
    nominal, _ = final_value(inp, df)
    assert nominal == pytest.approx(60 * 11)


def test_holdings_only_no_buys():
    inp = make(amount_per_buy=0, initial_shares=10, trading_fee=Fee(0.1, 1))
    df = simulate(inp)
    assert df["Total fees paid"].iloc[-1] == 0
    assert df["Total shares"].iloc[-1] == pytest.approx(10)
