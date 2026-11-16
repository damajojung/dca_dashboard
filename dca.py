"""Dollar-cost averaging (DCA) projection logic, independent of the UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

# label -> (pandas DateOffset kwargs, buys per year)
FREQUENCIES: dict[str, tuple[dict, int]] = {
    "Weekly": ({"weeks": 1}, 52),
    "Bi-weekly": ({"weeks": 2}, 26),
    "Monthly": ({"months": 1}, 12),
    "Quarterly": ({"months": 3}, 4),
    "Yearly": ({"years": 1}, 1),
}


@dataclass(frozen=True)
class Fee:
    """A fee made of a percentage component and/or a fixed amount per transaction."""

    percent: float = 0.0  # e.g. 0.25 means 0.25 %
    fixed: float = 0.0

    def on(self, amount: float) -> float:
        return amount * self.percent / 100 + self.fixed


@dataclass(frozen=True)
class DcaInputs:
    amount_per_buy: float
    frequency: str
    start: date
    years: int
    annual_return_pct: float
    inflation_pct: float
    start_price: float
    trading_fee: Fee = Fee()
    fx_fee: Fee = Fee()
    initial_shares: float = 0.0  # shares already held at the start date

    @property
    def initial_value(self) -> float:
        return self.initial_shares * self.start_price


def buy_dates(start: date, years: int, frequency: str) -> list[pd.Timestamp]:
    offset_kwargs, _ = FREQUENCIES[frequency]
    start_ts = pd.Timestamp(start)
    end_ts = start_ts + pd.DateOffset(years=years)
    offset = pd.DateOffset(**offset_kwargs)
    dates, i = [], 0
    while True:
        # Offset from the start each time so month-end dates don't drift (Jan 31 -> Feb 28 -> Mar 31).
        d = start_ts + offset * i
        if d >= end_ts:
            break
        dates.append(d)
        i += 1
    return dates


def simulate(inp: DcaInputs) -> pd.DataFrame:
    """Return one row per buy with fees, shares and projected portfolio values.

    Fee order: the FX fee is charged on the gross amount when converting currency,
    then the trading fee is charged on what is left. The remainder buys (fractional) shares.
    The share price compounds at the projected annual return; real values are deflated
    by inflation back to start-date money. Shares already held (`initial_shares`) are part of the
    portfolio from the start; "Total capital" = their start value + all new contributions.
    """
    r = inp.annual_return_pct / 100
    infl = inp.inflation_pct / 100
    start_ts = pd.Timestamp(inp.start)

    rows = []
    cum_shares, cum_gross, cum_fees = inp.initial_shares, 0.0, 0.0
    for n, d in enumerate(buy_dates(inp.start, inp.years, inp.frequency), start=1):
        t = (d - start_ts).days / 365.25
        price = inp.start_price * (1 + r) ** t

        gross = inp.amount_per_buy
        fx = min(inp.fx_fee.on(gross), gross)
        trading = min(inp.trading_fee.on(gross - fx), gross - fx)
        fees = fx + trading
        net = gross - fees
        shares = net / price if price > 0 else 0.0

        cum_shares += shares
        cum_gross += gross
        cum_fees += fees
        value = cum_shares * price
        deflator = (1 + infl) ** t

        rows.append(
            {
                "Buy #": n,
                "Date": d.date(),
                "Gross amount": gross,
                "FX fee": fx,
                "Trading fee": trading,
                "Total fees": fees,
                "Net invested": net,
                "Fee %": fees / gross * 100 if gross else 0.0,
                "Price": price,
                "Shares bought": shares,
                "Total shares": cum_shares,
                "Total contributed": cum_gross,
                "Total fees paid": cum_fees,
                "Portfolio value": value,
                "Real value": value / deflator,
                "Real contributed": None,  # filled below
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Contributions expressed in start-date money (each payment deflated at its own date).
    t_years = (pd.to_datetime(df["Date"]) - start_ts).dt.days / 365.25
    df["Real contributed"] = (df["Gross amount"] / (1 + infl) ** t_years).cumsum()
    df["Total capital"] = inp.initial_value + df["Total contributed"]
    df["Real capital"] = inp.initial_value + df["Real contributed"]
    return df


def final_value(inp: DcaInputs, df: pd.DataFrame) -> tuple[float, float]:
    """Nominal and real portfolio value at the end of the horizon (not just at the last buy)."""
    if df.empty:
        return 0.0, 0.0
    price_end = inp.start_price * (1 + inp.annual_return_pct / 100) ** inp.years
    nominal = df["Total shares"].iloc[-1] * price_end
    real = nominal / (1 + inp.inflation_pct / 100) ** inp.years
    return nominal, real
