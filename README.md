# DCA Dashboard

A Streamlit app that projects a dollar-cost-averaging plan for any Yahoo Finance ticker.

**Inputs (sidebar):** base currency (default CHF), ticker (default VT), current holdings (as shares or a value; optional), amount per buy, buying frequency (weekly → yearly), start date, time horizon,
projected annual return (pre-filled from the ticker's historical return), inflation, and trading + FX fees —
each fee can be a percentage, a fixed amount per buy, or both.

**Outputs:**
- Headline metrics: total contributed, total fees, final nominal and inflation-adjusted value, shares and average cost.
- **Summary table**: every buy (or grouped per year) with FX fee, trading fee, net invested, price, shares and running totals, plus a TOTAL row and CSV download.
- **Projected growth**: interactive chart of portfolio value vs. contributions, real value and cumulative fees.

Prices are converted from the ticker's currency into your base currency at the live FX rate (editable), and the
historical-return hint is computed in base-currency terms.

Fee order: the FX fee is charged on the gross amount, then the trading fee on the remainder.
The share price compounds at the projected return from the latest close; real values are in start-date money.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Tests: `.venv/bin/pip install pytest && .venv/bin/python -m pytest tests`
