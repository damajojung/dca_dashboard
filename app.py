"""Streamlit DCA dashboard: run with `streamlit run app.py`."""

from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from dca import FREQUENCIES, DcaInputs, Fee, final_value, simulate

st.set_page_config(page_title="DCA Dashboard", page_icon="📈", layout="wide")


BASE_CURRENCIES = ["CHF", "EUR", "USD", "GBP"]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ticker(symbol: str) -> dict | None:
    """Price history (adjusted closes), currency and name for a ticker, or None if not found."""
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="max", auto_adjust=True)["Close"].dropna()
        if hist.empty:
            return None
        try:
            info = t.info or {}
        except Exception:
            info = {}
        currency = info.get("currency", "") or ""
        if currency in ("GBp", "GBX"):  # London listings quoted in pence
            hist, currency = hist / 100, "GBP"
        hist.index = hist.index.tz_localize(None).normalize()
        return {
            "currency": currency.upper(),
            "name": info.get("longName") or info.get("shortName") or symbol,
            "history": hist,
        }
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fx(from_ccy: str, to_ccy: str) -> pd.Series | None:
    """Daily FX history: units of `to_ccy` per 1 `from_ccy`."""
    if from_ccy == to_ccy:
        return None
    try:
        fx = yf.Ticker(f"{from_ccy}{to_ccy}=X").history(period="max")["Close"].dropna()
        if fx.empty:
            return None
        fx.index = fx.index.tz_localize(None).normalize()
        return fx
    except Exception:
        return None


def cagr(hist: pd.Series, years: int) -> float | None:
    cutoff = hist.index[-1] - pd.DateOffset(years=years)
    past = hist[hist.index >= cutoff]
    if hist.index[0] > cutoff or len(past) < 2:
        return None
    return ((past.iloc[-1] / past.iloc[0]) ** (1 / years) - 1) * 100


def fee_inputs(label: str, key: str, default_pct: float, default_fixed: float) -> Fee:
    st.markdown(f"**{label}**")
    mode = st.radio(
        "Type",
        ["Percentage", "Fixed", "Percentage + fixed"],
        index=0 if default_fixed == 0 else 2,
        horizontal=True,
        key=f"{key}_mode",
        label_visibility="collapsed",
    )
    pct = fixed = 0.0
    c1, c2 = st.columns(2)
    if mode in ("Percentage", "Percentage + fixed"):
        pct = c1.number_input("%", 0.0, 100.0, default_pct, 0.05, format="%.2f", key=f"{key}_pct")
    if mode in ("Fixed", "Percentage + fixed"):
        fixed = c2.number_input(f"Fixed ({ccy})", 0.0, None, default_fixed, 0.5, format="%.2f", key=f"{key}_fixed")
    return Fee(pct, fixed)


# ---------------------------------------------------------------- sidebar inputs
with st.sidebar:
    st.header("Investment plan")
    base_ccy = st.selectbox("Base currency", BASE_CURRENCIES, index=0, help="The currency you invest from.")
    ccy = base_ccy
    ticker = st.text_input("Ticker", "VT", help="Yahoo Finance symbol, e.g. VT, AAPL, SPY, VWCE.DE, CSPX.L").strip().upper()
    data = fetch_ticker(ticker) if ticker else None

    hist_base = None  # price history converted to the base currency
    if data:
        tick_ccy = data["currency"] or base_ccy
        last_local = float(data["history"].iloc[-1])
        if tick_ccy == base_ccy:
            fx_rate, hist_base = 1.0, data["history"]
        else:
            fx_hist = fetch_fx(tick_ccy, base_ccy)
            live_rate = float(fx_hist.iloc[-1]) if fx_hist is not None else 1.0
            if fx_hist is None:
                st.warning(f"Couldn't load the {tick_ccy}/{base_ccy} rate — enter it manually.")
            fx_rate = st.number_input(
                f"FX rate ({base_ccy} per 1 {tick_ccy})", 0.0001, None, live_rate, 0.01, format="%.4f",
                key=f"fx_{tick_ccy}_{base_ccy}",
            )
            if fx_hist is not None:
                aligned = fx_hist.reindex(data["history"].index).ffill()
                hist_base = (data["history"] * aligned).dropna()
        start_price = last_local * fx_rate
        price_txt = f"{last_local:,.2f} {tick_ccy}"
        if tick_ccy != base_ccy:
            price_txt += f" ≈ **{start_price:,.2f} {base_ccy}**"
        st.caption(f"{data['name']} · last close {price_txt}")
    else:
        if ticker:
            st.warning("Couldn't load this ticker — enter a starting price manually.")
        start_price = st.number_input(f"Starting price per share ({base_ccy})", 0.01, None, 100.0)

    st.header("Current holdings")
    holding_mode = st.radio(
        "Enter as", ["None", "Shares", f"Value ({base_ccy})"], horizontal=True, key="holding_mode",
        help="What you already own of this investment. It grows from the start date on, and new buys are added on top.",
    )
    initial_shares = 0.0
    if holding_mode == "Shares":
        initial_shares = st.number_input("Shares held", 0.0, None, 500.0, 1.0, format="%.4f")
        st.caption(f"≈ {initial_shares * start_price:,.2f} {base_ccy} at today's price")
    elif holding_mode != "None":
        held_value = st.number_input(f"Current value ({base_ccy})", 0.0, None, 50_000.0, 1_000.0)
        initial_shares = held_value / start_price
        st.caption(f"≈ {initial_shares:,.4f} shares at today's price")

    st.header("Strategy")
    amount = st.number_input(f"Amount per buy ({base_ccy})", 0.0, None, 500.0, 50.0,
                             help="Set to 0 to see how your current holdings grow without new buys.")
    frequency = st.selectbox("Buying frequency", list(FREQUENCIES), index=2)
    start = st.date_input("Start date", date.today())
    years = st.slider("Time horizon (years)", 1, 50, 20)

    st.header("Assumptions")
    hist_cagr = {}
    if hist_base is not None and not hist_base.empty:
        hist_cagr = {y: v for y in (5, 10, 20) if (v := cagr(hist_base, y)) is not None}
    default_return = 7.0
    if hist_cagr:
        st.caption(f"Historical annual return in {base_ccy}: " + " · ".join(f"{y}y {v:.1f}%" for y, v in hist_cagr.items()))
        default_return = round(hist_cagr.get(10, next(iter(hist_cagr.values()))), 1)
    annual_return = st.number_input("Projected annual return (%)", -50.0, 100.0, default_return, 0.5)
    inflation = st.number_input("Annual inflation (%)", -10.0, 50.0, 2.0, 0.1)

    st.header("Fees per buy")
    trading_fee = fee_inputs("Trading fee", "trade", 0.10, 1.00)
    fx_fee = fee_inputs("FX fee", "fx", 0.25, 0.0)
    st.caption("FX fee is charged on the gross amount, then the trading fee on the remainder.")

inp = DcaInputs(
    amount_per_buy=amount,
    frequency=frequency,
    start=start,
    years=years,
    annual_return_pct=annual_return,
    inflation_pct=inflation,
    start_price=start_price,
    trading_fee=trading_fee,
    fx_fee=fx_fee,
    initial_shares=initial_shares,
)
df = simulate(inp)
end_nominal, end_real = final_value(inp, df)


def money(x: float) -> str:
    return f"{x:,.2f} {ccy}".strip()


# ---------------------------------------------------------------- headline metrics
st.title(f"📈 DCA projection — {ticker or 'custom'}")
st.caption(
    f"{money(amount)} {frequency.lower()} for {years} years · {annual_return:.1f}% projected return · "
    f"{inflation:.1f}% inflation"
)

total_contrib = df["Gross amount"].sum()
total_fees = df["Total fees"].sum()
start_value = inp.initial_value
total_capital = start_value + total_contrib
end_shares = df["Total shares"].iloc[-1]
new_shares = end_shares - initial_shares

m = st.columns(6)
m[0].metric("Starting portfolio", money(start_value), f"{initial_shares:,.4f} shares", delta_color="off")
m[1].metric("New contributions", money(total_contrib), f"{len(df)} buys" if total_contrib else "no new buys", delta_color="off")
fee_share = f"{total_fees / total_contrib * 100:.2f}% of contributions" if total_contrib else "no buys"
m[2].metric("Total fees", money(total_fees), fee_share, delta_color="off")
m[3].metric("Final value (nominal)", money(end_nominal), f"{money(end_nominal - total_capital)} gain")
m[4].metric("Final value (real)", money(end_real), "in today's money", delta_color="off")
m[5].metric(
    "Total shares",
    f"{end_shares:,.4f}",
    f"+{new_shares:,.4f} bought" + (f" · avg buy price {total_contrib / new_shares:,.2f}" if new_shares else ""),
    delta_color="off",
)

tab_table, tab_chart = st.tabs(["🧾 Summary table", "📊 Projected growth"])

# ---------------------------------------------------------------- summary table
with tab_table:
    view = st.radio("Group by", ["Each buy", "Year"], horizontal=True)
    money_cols = ["Gross amount", "FX fee", "Trading fee", "Total fees", "Net invested"]

    if initial_shares:
        st.caption(
            f"Starting holdings: {initial_shares:,.4f} shares worth {money(start_value)} — included in "
            "Total shares, Total capital and Portfolio value."
        )
    if view == "Each buy":
        table = df.drop(columns=["Real contributed", "Real capital"])
    else:
        g = df.assign(Year=pd.to_datetime(df["Date"]).dt.year).groupby("Year")
        table = g[money_cols + ["Shares bought"]].sum()
        table.insert(0, "Buys", g.size())
        table["Avg price"] = g["Price"].mean()
        for c in ["Total shares", "Total contributed", "Total capital", "Total fees paid", "Portfolio value", "Real value"]:
            table[c] = g[c].last()
        table = table.reset_index()

    totals = {c: table[c].sum() for c in money_cols + ["Shares bought"]}
    first_col = table.columns[0]
    table = table.astype({first_col: str})
    totals[first_col] = "TOTAL"
    table_with_total = pd.concat([table, pd.DataFrame([totals])], ignore_index=True)

    fmt = {c: "{:,.2f}" for c in table.columns if c not in ("Buy #", "Date", "Year", "Buys")}
    fmt.update({"Shares bought": "{:,.6f}", "Total shares": "{:,.6f}", "Fee %": "{:.2f}%"})
    st.dataframe(
        table_with_total.style.format(fmt, na_rep=""),
        hide_index=True,
        width="stretch",
        height=min(38 * (len(table_with_total) + 1), 600),
    )
    st.download_button("Download CSV", table.to_csv(index=False), f"dca_{ticker or 'plan'}.csv", "text/csv")

# ---------------------------------------------------------------- growth chart
with tab_chart:
    real_mode = st.toggle("Show inflation-adjusted (real) values", value=False)
    x = pd.to_datetime(df["Date"])
    value_col, contrib_col = ("Real value", "Real capital") if real_mode else ("Portfolio value", "Total capital")
    contrib_name = "Starting portfolio + contributions" if initial_shares else "Contributed"

    fig = go.Figure()
    fig.add_scatter(x=x, y=df[contrib_col], name=contrib_name, mode="lines",
                    line=dict(color="#94a3b8", width=2), fill="tozeroy", fillcolor="rgba(148,163,184,0.25)")
    fig.add_scatter(x=x, y=df[value_col], name="Portfolio value", mode="lines",
                    line=dict(color="#2563eb", width=3), fill="tonexty", fillcolor="rgba(37,99,235,0.15)")
    if not real_mode:
        fig.add_scatter(x=x, y=df["Real value"], name="Real value (today's money)", mode="lines",
                        line=dict(color="#16a34a", width=2, dash="dash"))
    if initial_shares:
        held_only = initial_shares * df["Price"]
        if real_mode:
            held_only = held_only * df["Real value"] / df["Portfolio value"]
        fig.add_scatter(x=x, y=held_only, name="Current holdings only (no new buys)", mode="lines",
                        line=dict(color="#a855f7", width=2, dash="dashdot"))
    fig.add_scatter(x=x, y=df["Total fees paid"], name="Cumulative fees", mode="lines",
                    line=dict(color="#dc2626", width=2, dash="dot"))
    fig.update_layout(
        hovermode="x unified",
        height=520,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=1.08, x=0),
        yaxis_title=ccy or "Value",
    )
    st.plotly_chart(fig, width="stretch")

    gain = df[value_col].iloc[-1] - df[contrib_col].iloc[-1]
    st.caption(
        f"At the last buy: capital put in {money(df[contrib_col].iloc[-1])}, value {money(df[value_col].iloc[-1])}, "
        f"projected gain {money(gain)}. Projection assumes a constant return — real markets fluctuate."
    )

    if hist_base is not None and not hist_base.empty:
        with st.expander(f"Historical price of {ticker} in {base_ccy}"):
            st.line_chart(hist_base, height=250)
