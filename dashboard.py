"""
RealQuantTrading — Risk & Performance Dashboard

Startup:
    python dashboard.py
Then open: http://localhost:8050

Layout (4 panels):
  1. Portfolio snapshot  — live equity, cash, positions, PnL per name
  2. Strategy performance — cumulative equity curves, Sharpe/DD table
  3. Risk status         — kill switch, drawdown breaker, daily loss
  4. Backtest vs paper   — overlay of backtest expectation vs paper P&L
"""

import json
import warnings
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import dash
from dash import dcc, html, Input, Output, dash_table
import dash_bootstrap_components as dbc

# ── paths ──────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent
STATE_ROOT   = ROOT / "live" / "state"
PAPER_DIR    = STATE_ROOT / "paper"
SESSIONS_DIR = STATE_ROOT / "sessions"
SNAPSHOT     = ROOT / "public" / "project-snapshot.json"
CACHE_ROOT   = ROOT / "data" / "cache"
SYMBOLS = ("XLB","XLC","XLE","XLF","XLI","XLK","XLP","XLRE","XLU","XLV","XLY")

# ── colour palette (dark terminal feel) ────────────────────────────────────
BG       = "#0d1117"
CARD_BG  = "#161b22"
BORDER   = "#30363d"
GREEN    = "#3fb950"
RED      = "#f85149"
YELLOW   = "#d29922"
BLUE     = "#58a6ff"
MUTED    = "#8b949e"
WHITE    = "#e6edf3"

COLORS = [BLUE, GREEN, "#ff7b72", "#ffa657", "#d2a8ff",
          "#79c0ff", "#56d364", "#e3b341", "#f0883e", "#a5d6ff", "#bc8cff"]

# ── helpers ────────────────────────────────────────────────────────────────

def _load_paper_account() -> dict:
    p = PAPER_DIR / "account.json"
    if not p.exists():
        return {"cash": 10_000.0, "positions": {}}
    with p.open() as f:
        return json.load(f)

def _load_fills() -> pd.DataFrame:
    p = PAPER_DIR / "fills.jsonl"
    if not p.exists():
        return pd.DataFrame()
    rows = []
    with p.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def _load_session_equity() -> pd.DataFrame:
    rows = []
    if SESSIONS_DIR.exists():
        for jl in sorted(SESSIONS_DIR.glob("*.jsonl")):
            with jl.open() as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except Exception:
                            pass
    if not rows:
        return pd.DataFrame(columns=["ts","equity"])
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"])
    return df.sort_values("ts").reset_index(drop=True)

def _last_prices() -> dict[str, float]:
    try:
        from research_harness.data_store import load_prices_wide
        close = load_prices_wide(SYMBOLS, "2020-01-01", None,
                                 field="adj_close", cache_root=CACHE_ROOT)
        if not close.empty:
            return close.iloc[-1].to_dict()
    except Exception:
        pass
    return {}

def _load_snapshot() -> dict:
    if not SNAPSHOT.exists():
        return {}
    with SNAPSHOT.open() as f:
        return json.load(f)

def _kill_switch_status() -> tuple[bool, str]:
    kill_file = STATE_ROOT / "KILL"
    if kill_file.exists():
        try:
            return True, kill_file.read_text().strip()
        except Exception:
            return True, "unknown reason"
    return False, ""

def _backtest_equity_curve() -> pd.DataFrame:
    """Return the ONS backtest equity curve from the research artifacts."""
    snap = _load_snapshot()
    try:
        ts_path = ROOT / "artifacts" / "research" / "project-timeseries.json"
        if not ts_path.exists():
            return pd.DataFrame()
        with ts_path.open() as f:
            ts = json.load(f)
        ons = next(
            (s for s in ts.get("series", []) if s.get("strategy") == "ons"),
            None
        )
        if ons is None:
            return pd.DataFrame()
        df = pd.DataFrame({"date": ons["dates"], "equity": ons["equity"]})
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()

# ── Dash app ───────────────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="RealQuantTrading Dashboard",
    update_title=None,
)

def _card(title: str, children, color_left: str = BLUE) -> dbc.Card:
    return dbc.Card([
        dbc.CardHeader(
            html.Span(title, style={"fontWeight": "600", "color": WHITE, "fontSize": "13px"}),
            style={"background": CARD_BG, "borderBottom": f"2px solid {color_left}",
                   "padding": "8px 16px"}
        ),
        dbc.CardBody(children, style={"background": CARD_BG, "padding": "12px 16px"}),
    ], style={"border": f"1px solid {BORDER}", "borderRadius": "6px", "marginBottom": "12px"})


def _metric(label: str, value: str, color: str = WHITE, size: str = "22px") -> html.Div:
    return html.Div([
        html.Div(label, style={"color": MUTED, "fontSize": "11px", "textTransform": "uppercase",
                                "letterSpacing": "0.08em"}),
        html.Div(value, style={"color": color, "fontSize": size, "fontWeight": "700",
                                "fontFamily": "monospace"}),
    ], style={"textAlign": "center", "padding": "4px 8px"})


app.layout = dbc.Container([

    # ── header ──
    dbc.Row([
        dbc.Col([
            html.H4("RealQuantTrading", style={"color": WHITE, "margin": "0",
                                                "fontFamily": "monospace", "fontWeight": "700"}),
            html.Span("ONS · ETF Sector Rotation · Paper Account",
                      style={"color": MUTED, "fontSize": "12px"}),
        ]),
        dbc.Col([
            html.Div(id="last-update", style={"color": MUTED, "fontSize": "11px",
                                              "textAlign": "right", "fontFamily": "monospace"}),
        ]),
    ], align="center", style={"padding": "14px 0 10px 0",
                               "borderBottom": f"1px solid {BORDER}", "marginBottom": "14px"}),

    # ── row 1: headline numbers ──
    dbc.Row(id="headline-row", style={"marginBottom": "8px"}),

    # ── row 2: left=positions table | right=equity chart ──
    dbc.Row([
        dbc.Col(_card("Positions", html.Div(id="positions-table")), width=5),
        dbc.Col(_card("Paper Equity vs Backtest", dcc.Graph(id="equity-chart",
                config={"displayModeBar": False},
                style={"height": "280px"})), width=7),
    ]),

    # ── row 3: strategy performance | risk status ──
    dbc.Row([
        dbc.Col(_card("Strategy Performance (Backtest)", dcc.Graph(id="strategy-chart",
                config={"displayModeBar": False},
                style={"height": "280px"})), width=8),
        dbc.Col(_card("Risk Status", html.Div(id="risk-panel"), color_left=RED), width=4),
    ]),

    # ── row 4: fills log ──
    dbc.Row([
        dbc.Col(_card("Recent Fills", html.Div(id="fills-table")), width=12),
    ]),

    dcc.Interval(id="timer", interval=15_000, n_intervals=0),

], fluid=True, style={"backgroundColor": BG, "minHeight": "100vh", "padding": "0 20px"})


# ── callbacks ──────────────────────────────────────────────────────────────

@app.callback(
    Output("last-update",    "children"),
    Output("headline-row",   "children"),
    Output("positions-table","children"),
    Output("equity-chart",   "figure"),
    Output("strategy-chart", "figure"),
    Output("risk-panel",     "children"),
    Output("fills-table",    "children"),
    Input("timer", "n_intervals"),
)
def refresh(_n):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── data ──
    acct      = _load_paper_account()
    last_px   = _last_prices()
    fills_df  = _load_fills()
    session   = _load_session_equity()
    snap      = _load_snapshot()
    kill, kill_reason = _kill_switch_status()

    cash = float(acct.get("cash", 10_000))
    positions = acct.get("positions", {})

    # compute mark-to-market equity
    mkt_value = 0.0
    pos_rows  = []
    for sym, pd_data in positions.items():
        qty  = float(pd_data["quantity"])
        cost = float(pd_data["avg_cost"])
        lp   = float(last_px.get(sym, cost))
        val  = qty * lp
        pnl  = val - qty * cost
        pnl_pct = (lp / cost - 1) * 100 if cost > 0 else 0.0
        mkt_value += val
        pos_rows.append({
            "Symbol": sym, "Qty": int(qty),
            "Avg Cost": f"${cost:.2f}",
            "Last": f"${lp:.2f}",
            "Value": f"${val:,.0f}",
            "P&L": f"${pnl:+.0f}",
            "P&L %": f"{pnl_pct:+.2f}%",
            "_pnl": pnl,
        })
    total_equity = cash + mkt_value
    total_cost   = sum(
        float(positions[s]["quantity"]) * float(positions[s]["avg_cost"])
        for s in positions
    )
    total_pnl    = mkt_value - total_cost

    # ── headline metrics ──
    start_equity = 10_000.0
    total_return = (total_equity / start_equity - 1) * 100
    color_ret    = GREEN if total_return >= 0 else RED
    color_pnl    = GREEN if total_pnl  >= 0 else RED

    headline = [
        dbc.Col(_metric("Total Equity",  f"${total_equity:,.2f}", WHITE, "28px"), width=3),
        dbc.Col(_metric("Total Return",  f"{total_return:+.2f}%", color_ret, "28px"), width=2),
        dbc.Col(_metric("Unrealized P&L",f"${total_pnl:+,.2f}",  color_pnl, "28px"), width=2),
        dbc.Col(_metric("Cash",          f"${cash:,.2f}",         MUTED,  "20px"), width=2),
        dbc.Col(_metric("Positions",     str(len(positions)),     WHITE,  "20px"), width=1),
        dbc.Col(_metric("Kill Switch",
                         "ENGAGED" if kill else "ARMED",
                         RED if kill else GREEN, "18px"), width=2),
    ]

    # ── positions table ──
    if pos_rows:
        df_pos = pd.DataFrame(pos_rows).drop(columns=["_pnl"])
        pos_table = dash_table.DataTable(
            data=df_pos.to_dict("records"),
            columns=[{"name": c, "id": c} for c in df_pos.columns],
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": BG, "color": MUTED,
                          "fontWeight": "600", "fontSize": "11px",
                          "border": f"1px solid {BORDER}"},
            style_cell={"backgroundColor": CARD_BG, "color": WHITE,
                        "fontSize": "12px", "fontFamily": "monospace",
                        "border": f"1px solid {BORDER}", "textAlign": "right",
                        "padding": "5px 10px"},
            style_data_conditional=[
                {"if": {"filter_query": '{P&L %} contains "+"'},
                 "color": GREEN},
                {"if": {"filter_query": '{P&L %} contains "-"'},
                 "color": RED},
            ],
        )
    else:
        pos_table = html.Div("No positions yet. Run: python start_paper_trading.py",
                             style={"color": MUTED, "fontSize": "12px", "padding": "20px"})

    # ── equity chart ──
    fig_eq = go.Figure()
    fig_eq.update_layout(
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        margin=dict(l=40, r=10, t=10, b=30),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=MUTED, size=10)),
        xaxis=dict(gridcolor=BORDER, color=MUTED, showgrid=False),
        yaxis=dict(gridcolor=BORDER, color=MUTED, tickprefix="$", tickformat=",.0f"),
    )

    # paper equity from session log
    if not session.empty and "equity" in session.columns:
        fig_eq.add_trace(go.Scatter(
            x=session["ts"], y=session["equity"],
            name="Paper Account", line=dict(color=GREEN, width=2),
            mode="lines",
        ))

    # backtest equity curve (ONS, normalised to $10K start)
    bt = _backtest_equity_curve()
    if not bt.empty:
        bt_norm = bt["equity"] / bt["equity"].iloc[0] * start_equity
        fig_eq.add_trace(go.Scatter(
            x=bt["date"], y=bt_norm,
            name="Backtest (ONS)", line=dict(color=BLUE, width=1.5, dash="dot"),
            mode="lines", opacity=0.7,
        ))

    # current equity marker
    if not session.empty:
        last_ts = session["ts"].iloc[-1]
        fig_eq.add_trace(go.Scatter(
            x=[last_ts], y=[total_equity],
            mode="markers", marker=dict(color=GREEN, size=8),
            name="Now", showlegend=False,
        ))

    # ── strategy performance chart ──
    fig_strat = make_subplots(
        rows=1, cols=2,
        subplot_titles=["Annualised Return", "Sharpe Ratio"],
    )

    strategies_data = []
    for track_key, track in snap.get("tracks", {}).items():
        for skey, sv in track.get("strategies", {}).items():
            m = sv.get("metrics", {})
            if skey == "bcrp":
                continue
            strategies_data.append({
                "name": sv["definition"]["name"].replace("Approximate ","").replace(" Portfolio",""),
                "ann_return": m.get("annualized_return", 0) * 100,
                "sharpe":     m.get("sharpe", 0),
                "max_dd":     m.get("max_drawdown", 0) * 100,
                "track":      track_key,
            })

    if strategies_data:
        df_s = pd.DataFrame(strategies_data).sort_values("sharpe", ascending=False)
        bar_colors_ret = [GREEN if v >= 0 else RED for v in df_s["ann_return"]]
        bar_colors_sh  = [GREEN if v >= 1 else (YELLOW if v >= 0.5 else RED)
                          for v in df_s["sharpe"]]

        fig_strat.add_trace(
            go.Bar(x=df_s["name"], y=df_s["ann_return"],
                   marker_color=bar_colors_ret, name="Return %",
                   text=[f"{v:.1f}%" for v in df_s["ann_return"]],
                   textposition="outside", textfont=dict(size=9, color=WHITE)),
            row=1, col=1,
        )
        fig_strat.add_trace(
            go.Bar(x=df_s["name"], y=df_s["sharpe"],
                   marker_color=bar_colors_sh, name="Sharpe",
                   text=[f"{v:.2f}" for v in df_s["sharpe"]],
                   textposition="outside", textfont=dict(size=9, color=WHITE)),
            row=1, col=2,
        )
        fig_strat.add_hline(y=1.0, line_dash="dot", line_color=YELLOW,
                             annotation_text="Sharpe=1", row=1, col=2,
                             annotation_font_color=YELLOW)

    fig_strat.update_layout(
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        margin=dict(l=40, r=10, t=30, b=60),
        showlegend=False,
        font=dict(color=MUTED, size=10),
    )
    fig_strat.update_xaxes(gridcolor=BORDER, color=MUTED, tickangle=-30)
    fig_strat.update_yaxes(gridcolor=BORDER, color=MUTED)

    # ── risk panel ──
    def _status_badge(label, ok, detail=""):
        color = GREEN if ok else RED
        badge = "✓" if ok else "✗"
        return html.Div([
            html.Span(f"{badge} {label}", style={"color": color, "fontWeight": "600",
                                                  "fontSize": "12px", "fontFamily": "monospace"}),
            html.Div(detail, style={"color": MUTED, "fontSize": "10px",
                                    "paddingLeft": "16px"}) if detail else None,
        ], style={"marginBottom": "8px"})

    # drawdown estimate
    dd_pct = 0.0
    if not session.empty and "equity" in session.columns:
        eq_arr = session["equity"].to_numpy(dtype=float)
        hwm = np.maximum.accumulate(eq_arr)
        dd_pct = float((1 - eq_arr / np.where(hwm > 0, hwm, 1)).max()) * 100

    risk_items = [
        _status_badge("Kill Switch", not kill,
                      kill_reason[:60] if kill else "Disengaged — trading allowed"),
        _status_badge("Drawdown from HWM",
                      dd_pct < 15,
                      f"{dd_pct:.2f}% (limit 15%)"),
        _status_badge("Position Count",
                      len(positions) <= 25,
                      f"{len(positions)} / 25 max"),
        _status_badge("Long-Only",
                      all(float(p["quantity"]) >= 0 for p in positions.values()),
                      "No short positions"),
        html.Hr(style={"borderColor": BORDER, "margin": "8px 0"}),
        html.Div("Risk Limits", style={"color": MUTED, "fontSize": "10px",
                                        "textTransform": "uppercase", "marginBottom": "4px"}),
        html.Div("Max per name: 10%", style={"color": MUTED, "fontSize": "11px", "fontFamily": "monospace"}),
        html.Div("Vol target: 12% ann.", style={"color": MUTED, "fontSize": "11px", "fontFamily": "monospace"}),
        html.Div("DD breaker: 15% from HWM", style={"color": MUTED, "fontSize": "11px", "fontFamily": "monospace"}),
        html.Div("Daily loss limit: 3%", style={"color": MUTED, "fontSize": "11px", "fontFamily": "monospace"}),
    ]

    # ── fills table ──
    if not fills_df.empty:
        show_cols = [c for c in ["fill_time","symbol","side","filled_quantity",
                                  "fill_price","commission_usd"] if c in fills_df.columns]
        df_fills = fills_df[show_cols].tail(20).iloc[::-1].copy()
        if "fill_price" in df_fills.columns:
            df_fills["fill_price"] = df_fills["fill_price"].apply(lambda x: f"${float(x):.2f}")
        if "commission_usd" in df_fills.columns:
            df_fills["commission_usd"] = df_fills["commission_usd"].apply(lambda x: f"${float(x):.4f}")
        fills_widget = dash_table.DataTable(
            data=df_fills.to_dict("records"),
            columns=[{"name": c.replace("_"," ").title(), "id": c} for c in df_fills.columns],
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": BG, "color": MUTED,
                          "fontWeight": "600", "fontSize": "11px",
                          "border": f"1px solid {BORDER}"},
            style_cell={"backgroundColor": CARD_BG, "color": WHITE,
                        "fontSize": "11px", "fontFamily": "monospace",
                        "border": f"1px solid {BORDER}", "padding": "4px 10px"},
            style_data_conditional=[
                {"if": {"filter_query": '{side} = "BUY"'},  "color": GREEN},
                {"if": {"filter_query": '{side} = "SELL"'}, "color": RED},
            ],
        )
    else:
        fills_widget = html.Div(
            "No fills yet. Run: python start_paper_trading.py",
            style={"color": MUTED, "fontSize": "12px", "padding": "10px"},
        )

    return (
        f"Last update: {now}",
        headline,
        pos_table,
        fig_eq,
        fig_strat,
        risk_items,
        fills_widget,
    )


if __name__ == "__main__":
    print("=" * 55)
    print("  RealQuantTrading Dashboard")
    print("  http://localhost:8050")
    print("  Ctrl+C to stop")
    print("=" * 55)
    app.run(debug=False, host="0.0.0.0", port=8050)
