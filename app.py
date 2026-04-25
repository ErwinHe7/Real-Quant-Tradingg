"""
RealQuantTrading — Public Dashboard
Deployable to Render / Railway / Fly.io with zero config.
Reads from public/demo_data.json (baked at commit time).
Live local mode: also reads live/state/ if present.
"""

import json
import os
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash
from dash import dcc, html, Input, Output, dash_table
import dash_bootstrap_components as dbc

# ── paths ──────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent
DEMO_DATA  = ROOT / "public" / "demo_data.json"
STATE_ROOT = ROOT / "live" / "state"
PAPER_DIR  = STATE_ROOT / "paper"
SESSIONS_DIR = STATE_ROOT / "sessions"

# ── palette ────────────────────────────────────────────────────────────────
BG      = "#0d1117"
CARD    = "#161b22"
BORDER  = "#30363d"
GREEN   = "#3fb950"
RED     = "#f85149"
YELLOW  = "#d29922"
BLUE    = "#58a6ff"
PURPLE  = "#d2a8ff"
MUTED   = "#8b949e"
WHITE   = "#e6edf3"

STRAT_COLORS = {
    "ons":                BLUE,
    "eg":                 GREEN,
    "mean_reversion":     PURPLE,
    "equal_weight":       YELLOW,
    "universal_portfolio":"#79c0ff",
    "momentum":           "#ffa657",
    "bcrp":               "#8b949e",
    "ridge_alpha":        "#ff7b72",
    "attention_alpha":    "#56d364",
    "blend_alpha":        "#e3b341",
}

# ── data loading ────────────────────────────────────────────────────────────

def _load_demo() -> dict:
    if DEMO_DATA.exists():
        with DEMO_DATA.open() as f:
            return json.load(f)
    return {}


def _load_live_account() -> dict | None:
    """Return live paper account if running locally, else None."""
    p = PAPER_DIR / "account.json"
    if p.exists():
        with p.open() as f:
            return json.load(f)
    return None


def _load_live_fills() -> list:
    p = PAPER_DIR / "fills.jsonl"
    if not p.exists():
        return []
    rows = []
    with p.open() as f:
        for line in f:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def _load_live_sessions() -> list:
    rows = []
    if SESSIONS_DIR.exists():
        for jl in sorted(SESSIONS_DIR.glob("*.jsonl")):
            with jl.open() as f:
                for line in f:
                    if line.strip():
                        try:
                            rows.append(json.loads(line))
                        except Exception:
                            pass
    return rows


def _kill_switch_engaged() -> tuple[bool, str]:
    kf = STATE_ROOT / "KILL"
    if kf.exists():
        return True, kf.read_text().strip()
    return False, ""


# ── app layout ──────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="RealQuantTrading",
    update_title=None,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server  # for gunicorn


def _card(title: str, children, accent: str = BLUE):
    return dbc.Card([
        dbc.CardHeader(
            title,
            style={"background": CARD, "color": WHITE, "fontSize": "12px",
                   "fontWeight": "700", "borderBottom": f"2px solid {accent}",
                   "padding": "8px 16px", "letterSpacing": "0.05em",
                   "textTransform": "uppercase"},
        ),
        dbc.CardBody(children, style={"background": CARD, "padding": "12px 16px"}),
    ], style={"border": f"1px solid {BORDER}", "borderRadius": "8px", "marginBottom": "14px"})


def _kpi(label, value, color=WHITE, sub=None):
    return html.Div([
        html.Div(label, style={"color": MUTED, "fontSize": "10px", "textTransform": "uppercase",
                                "letterSpacing": "0.1em", "marginBottom": "2px"}),
        html.Div(value, style={"color": color, "fontSize": "26px", "fontWeight": "800",
                                "fontFamily": "monospace", "lineHeight": "1"}),
        html.Div(sub, style={"color": MUTED, "fontSize": "10px", "fontFamily": "monospace"}) if sub else None,
    ], style={"textAlign": "center", "padding": "8px 12px"})


def _badge(text, color):
    return html.Span(text, style={
        "background": color + "22", "color": color, "border": f"1px solid {color}55",
        "borderRadius": "4px", "padding": "2px 8px", "fontSize": "11px",
        "fontFamily": "monospace", "fontWeight": "600",
    })


app.layout = dbc.Container([

    # ── top bar ──
    dbc.Row([
        dbc.Col([
            html.Div([
                html.Span("RealQuantTrading", style={
                    "color": WHITE, "fontSize": "18px", "fontWeight": "800",
                    "fontFamily": "monospace", "marginRight": "12px",
                }),
                _badge("ONS · ETF Sector Rotation", BLUE),
                html.Span("  "),
                _badge("Paper Account", GREEN),
            ]),
            html.Div("github.com/ErwinHe7/Real-Quant-Tradingg",
                     style={"color": MUTED, "fontSize": "11px", "marginTop": "2px"}),
        ], width=8),
        dbc.Col(
            html.Div(id="last-update",
                     style={"color": MUTED, "fontSize": "11px", "textAlign": "right",
                            "fontFamily": "monospace", "paddingTop": "10px"}),
            width=4,
        ),
    ], style={"padding": "16px 0 12px 0", "borderBottom": f"1px solid {BORDER}",
              "marginBottom": "16px"}),

    # ── KPI row ──
    dbc.Row(id="kpi-row", style={"marginBottom": "14px"}),

    # ── row 2 ──
    dbc.Row([
        dbc.Col(
            _card("Portfolio Positions", html.Div(id="pos-table")),
            md=5,
        ),
        dbc.Col(
            _card("Paper Equity vs ONS Backtest",
                  dcc.Graph(id="eq-chart", config={"displayModeBar": False},
                            style={"height": "300px"})),
            md=7,
        ),
    ]),

    # ── row 3 ──
    dbc.Row([
        dbc.Col(
            _card("All Strategy Performance — 2020 to 2026",
                  dcc.Graph(id="all-strat-chart", config={"displayModeBar": False},
                            style={"height": "320px"})),
            md=8,
        ),
        dbc.Col([
            _card("Risk & Kill Switch", html.Div(id="risk-panel"), accent=RED),
            _card("How to Use", html.Div([
                html.P("Run paper trading locally:", style={"color": MUTED, "fontSize": "12px", "margin": "0 0 4px"}),
                html.Code("python start_paper_trading.py",
                          style={"color": GREEN, "fontSize": "11px", "display": "block",
                                 "background": BG, "padding": "4px 8px", "borderRadius": "4px",
                                 "marginBottom": "6px"}),
                html.P("Run this dashboard locally:", style={"color": MUTED, "fontSize": "12px", "margin": "0 0 4px"}),
                html.Code("python dashboard.py",
                          style={"color": BLUE, "fontSize": "11px", "display": "block",
                                 "background": BG, "padding": "4px 8px", "borderRadius": "4px"}),
            ], style={"padding": "4px 0"}), accent=MUTED),
        ], md=4),
    ]),

    # ── row 4: strategy equity curves ──
    dbc.Row([
        dbc.Col(
            _card("Cumulative Equity Curves — All Strategies (net of cost)",
                  dcc.Graph(id="curves-chart", config={"displayModeBar": False},
                            style={"height": "320px"})),
            md=12,
        ),
    ]),

    # ── row 5: fills ──
    dbc.Row([
        dbc.Col(
            _card("Recent Paper Fills", html.Div(id="fills-table")),
            md=12,
        ),
    ]),

    dcc.Interval(id="tick", interval=15_000, n_intervals=0),

], fluid=True, style={"backgroundColor": BG, "minHeight": "100vh", "padding": "0 24px"})


# ── callback ────────────────────────────────────────────────────────────────

@app.callback(
    Output("last-update",     "children"),
    Output("kpi-row",         "children"),
    Output("pos-table",       "children"),
    Output("eq-chart",        "figure"),
    Output("all-strat-chart", "figure"),
    Output("risk-panel",      "children"),
    Output("curves-chart",    "figure"),
    Output("fills-table",     "children"),
    Input("tick", "n_intervals"),
)
def refresh(_n):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S local")
    demo  = _load_demo()
    snap  = demo.get("snapshot", {})
    baked_account  = demo.get("paper_account", {"cash": 10_000, "positions": {}})
    baked_fills    = demo.get("fills", [])
    baked_sessions = demo.get("session_equity", [])
    last_px        = demo.get("last_prices", {})
    bt_curves      = demo.get("backtest_curves", {})

    # Prefer live data if running locally
    live_account  = _load_live_account()
    live_fills    = _load_live_fills()
    live_sessions = _load_live_sessions()
    kill, kill_reason = _kill_switch_engaged()

    account  = live_account  if live_account  else baked_account
    fills    = live_fills    if live_fills    else baked_fills
    sessions = live_sessions if live_sessions else baked_sessions

    positions = account.get("positions", {})
    cash = float(account.get("cash", 10_000))
    START = 10_000.0

    # ── mark-to-market ──
    pos_rows, mkt_val, total_cost = [], 0.0, 0.0
    for sym, pd_data in positions.items():
        qty  = float(pd_data["quantity"])
        cost = float(pd_data["avg_cost"])
        lp   = float(last_px.get(sym, cost))
        val  = qty * lp
        pnl  = val - qty * cost
        pct  = (lp / cost - 1) * 100 if cost > 0 else 0.0
        mkt_val   += val
        total_cost += qty * cost
        pos_rows.append({
            "Symbol": sym, "Qty": int(qty),
            "Avg Cost": f"${cost:.2f}", "Last": f"${lp:.2f}",
            "Value": f"${val:,.0f}",
            "P&L": f"${pnl:+,.0f}", "P&L %": f"{pct:+.2f}%",
        })

    equity       = cash + mkt_val
    total_ret    = (equity / START - 1) * 100
    unrealised   = mkt_val - total_cost
    color_ret    = GREEN if total_ret    >= 0 else RED
    color_unreal = GREEN if unrealised   >= 0 else RED

    # ── KPI bar ──
    kpis = [
        dbc.Col(_kpi("Total Equity",   f"${equity:,.2f}", WHITE),   md=2),
        dbc.Col(_kpi("Total Return",   f"{total_ret:+.2f}%",  color_ret),   md=2),
        dbc.Col(_kpi("Unrealised P&L", f"${unrealised:+,.0f}", color_unreal), md=2),
        dbc.Col(_kpi("Cash",           f"${cash:,.0f}",  MUTED, sub="available"), md=2),
        dbc.Col(_kpi("Positions",      str(len(positions)), WHITE, sub="names held"), md=2),
        dbc.Col(_kpi("Kill Switch",
                      "ENGAGED" if kill else "ARMED",
                      RED if kill else GREEN,
                      sub="trading halted" if kill else "orders allowed"), md=2),
    ]

    # ── positions table ──
    if pos_rows:
        df_pos = pd.DataFrame(pos_rows)
        pos_widget = dash_table.DataTable(
            data=df_pos.to_dict("records"),
            columns=[{"name": c, "id": c} for c in df_pos.columns],
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": BG, "color": MUTED,
                          "fontWeight": "700", "fontSize": "11px",
                          "border": f"1px solid {BORDER}"},
            style_cell={"backgroundColor": CARD, "color": WHITE,
                        "fontSize": "12px", "fontFamily": "monospace",
                        "border": f"1px solid {BORDER}", "padding": "5px 10px",
                        "textAlign": "right"},
            style_data_conditional=[
                {"if": {"filter_query": '{P&L %} contains "+"'}, "color": GREEN},
                {"if": {"filter_query": '{P&L %} contains "-"'}, "color": RED},
            ],
        )
    else:
        pos_widget = html.Div(
            "No positions yet. Run: python start_paper_trading.py",
            style={"color": MUTED, "fontSize": "12px", "padding": "20px 0"},
        )

    # ── equity chart (paper vs ONS backtest) ──
    fig_eq = go.Figure()
    _chart_style(fig_eq)

    # ONS backtest curve normalised to $10K
    ons_bt = bt_curves.get("ons", {})
    if ons_bt:
        dates_bt = ons_bt["dates"]
        eq_bt    = ons_bt["equity"]
        norm     = [v / eq_bt[0] * START for v in eq_bt]
        fig_eq.add_trace(go.Scatter(
            x=dates_bt, y=norm,
            name="ONS Backtest (2020–2026)",
            line=dict(color=BLUE, width=1.5, dash="dot"),
            opacity=0.6, mode="lines",
        ))

    # Paper equity from session log
    if sessions:
        df_sess = pd.DataFrame(sessions)
        if "equity" in df_sess.columns and "ts" in df_sess.columns:
            df_sess["ts"] = pd.to_datetime(df_sess["ts"])
            df_sess = df_sess.sort_values("ts")
            fig_eq.add_trace(go.Scatter(
                x=df_sess["ts"], y=df_sess["equity"],
                name="Paper Account",
                line=dict(color=GREEN, width=2.5),
                mode="lines",
            ))

    # Current mark-to-market dot
    fig_eq.add_trace(go.Scatter(
        x=[datetime.now().strftime("%Y-%m-%d")],
        y=[equity],
        mode="markers",
        marker=dict(color=GREEN, size=10, symbol="circle"),
        name=f"Now: ${equity:,.0f}",
    ))
    fig_eq.update_layout(
        yaxis_title="Portfolio Value ($)",
        legend=dict(orientation="h", y=1.05, font=dict(size=10)),
    )

    # ── all-strategy bar chart ──
    all_metrics = []
    for track in snap.get("tracks", {}).values():
        for sk, sv in track.get("strategies", {}).items():
            m = sv.get("metrics", {})
            if sk == "bcrp":
                continue
            name = sv["definition"]["name"]
            name = name.replace("Approximate ", "").replace(" Portfolio", "")
            name = name.replace("Rolling ", "").replace(" Alpha", "")
            all_metrics.append({
                "key":    sk,
                "name":   name,
                "ret":    m.get("annualized_return", 0) * 100,
                "sharpe": m.get("sharpe", 0),
                "maxdd":  m.get("max_drawdown", 0) * 100,
            })

    fig_bar = make_subplots(
        rows=1, cols=3,
        subplot_titles=["Annualised Return (%)", "Sharpe Ratio", "Max Drawdown (%)"],
        horizontal_spacing=0.08,
    )
    if all_metrics:
        df_m = pd.DataFrame(all_metrics).sort_values("sharpe", ascending=False)
        names  = df_m["name"].tolist()
        colors = [STRAT_COLORS.get(k, BLUE) for k in df_m["key"]]

        fig_bar.add_trace(
            go.Bar(x=names, y=df_m["ret"], marker_color=colors,
                   text=[f"{v:.1f}%" for v in df_m["ret"]],
                   textposition="outside", textfont=dict(color=WHITE, size=9)),
            row=1, col=1,
        )
        fig_bar.add_trace(
            go.Bar(x=names, y=df_m["sharpe"], marker_color=colors,
                   text=[f"{v:.2f}" for v in df_m["sharpe"]],
                   textposition="outside", textfont=dict(color=WHITE, size=9)),
            row=1, col=2,
        )
        fig_bar.add_trace(
            go.Bar(x=names, y=df_m["maxdd"], marker_color=colors,
                   text=[f"{v:.1f}%" for v in df_m["maxdd"]],
                   textposition="outside", textfont=dict(color=WHITE, size=9)),
            row=1, col=3,
        )
        fig_bar.add_hline(y=1.0, line_dash="dot", line_color=YELLOW, row=1, col=2,
                          annotation_text="Sharpe=1", annotation_font_color=YELLOW,
                          annotation_font_size=9)
    _chart_style(fig_bar, margin=dict(l=30, r=10, t=40, b=80))
    fig_bar.update_xaxes(tickangle=-35, tickfont=dict(size=9))

    # ── risk panel ──
    dd_pct = 0.0
    if sessions:
        df_s = pd.DataFrame(sessions)
        if "equity" in df_s.columns:
            eq_arr = df_s["equity"].astype(float).to_numpy()
            hwm    = np.maximum.accumulate(eq_arr)
            dd_pct = float(((hwm - eq_arr) / np.where(hwm > 0, hwm, 1)).max()) * 100

    def _row(label, ok, detail):
        sym   = "●"
        color = GREEN if ok else RED
        return html.Div([
            html.Span(sym + " ", style={"color": color}),
            html.Span(label, style={"color": WHITE, "fontSize": "12px", "fontWeight": "600"}),
            html.Div(detail, style={"color": MUTED, "fontSize": "10px",
                                    "paddingLeft": "14px", "fontFamily": "monospace"}),
        ], style={"marginBottom": "10px"})

    risk_items = [
        _row("Kill Switch", not kill,
             f"ENGAGED: {kill_reason[:50]}" if kill else "Disengaged — orders flow normally"),
        _row("Drawdown from HWM", dd_pct < 15.0,
             f"{dd_pct:.2f}% of 15% limit"),
        _row("Position Count", len(positions) <= 25,
             f"{len(positions)} / 25 max positions"),
        _row("Long-Only", all(float(p["quantity"]) >= 0 for p in positions.values()),
             "No short positions"),
        html.Hr(style={"borderColor": BORDER, "margin": "10px 0"}),
        html.Div([
            html.Div("Limits in effect", style={"color": MUTED, "fontSize": "10px",
                                                "textTransform": "uppercase", "marginBottom": "6px"}),
            *[html.Div(t, style={"color": MUTED, "fontSize": "11px",
                                  "fontFamily": "monospace", "marginBottom": "3px"})
              for t in [
                  "Max per name:    10% of equity",
                  "Vol target:      12% annualised",
                  "DD breaker:      15% from HWM",
                  "Daily loss:       3% of equity",
                  "Kelly fraction:  0.25 (quarter)",
              ]],
        ]),
    ]

    # ── equity curves for all strategies ──
    fig_curves = go.Figure()
    _chart_style(fig_curves)
    for sk, curve in bt_curves.items():
        if not curve.get("dates"):
            continue
        eq = curve["equity"]
        norm = [v / eq[0] * START for v in eq]
        is_ons = sk == "ons"
        fig_curves.add_trace(go.Scatter(
            x=curve["dates"], y=norm,
            name=sk.replace("_", " ").title(),
            line=dict(
                color=STRAT_COLORS.get(sk, MUTED),
                width=2.5 if is_ons else 1,
                dash="solid" if is_ons else "dot",
            ),
            opacity=1.0 if is_ons else 0.5,
            mode="lines",
        ))
    fig_curves.update_layout(
        yaxis_title="Portfolio Value (rebased $10K)",
        legend=dict(orientation="h", y=1.05, font=dict(size=9)),
    )

    # ── fills table ──
    if fills:
        df_f = pd.DataFrame(fills)
        show = [c for c in ["fill_time", "symbol", "side", "filled_quantity",
                              "fill_price", "commission_usd"] if c in df_f.columns]
        df_f = df_f[show].tail(20).iloc[::-1].copy()
        for col in ["fill_price", "commission_usd"]:
            if col in df_f.columns:
                df_f[col] = df_f[col].apply(lambda x: f"${float(x):.4f}")
        fills_widget = dash_table.DataTable(
            data=df_f.to_dict("records"),
            columns=[{"name": c.replace("_"," ").title(), "id": c} for c in df_f.columns],
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": BG, "color": MUTED,
                          "fontWeight": "700", "fontSize": "11px",
                          "border": f"1px solid {BORDER}"},
            style_cell={"backgroundColor": CARD, "color": WHITE,
                        "fontSize": "11px", "fontFamily": "monospace",
                        "border": f"1px solid {BORDER}", "padding": "4px 10px"},
            style_data_conditional=[
                {"if": {"filter_query": '{side} = "BUY"'},  "color": GREEN},
                {"if": {"filter_query": '{side} = "SELL"'}, "color": RED},
            ],
        )
    else:
        fills_widget = html.Div(
            "No fills in baked data. Run start_paper_trading.py locally to generate live fills.",
            style={"color": MUTED, "fontSize": "12px", "padding": "10px 0"},
        )

    return (
        f"Data as of {demo.get('generated_at','—')}  |  {now}",
        kpis,
        pos_widget,
        fig_eq,
        fig_bar,
        risk_items,
        fig_curves,
        fills_widget,
    )


def _chart_style(fig, margin=None):
    fig.update_layout(
        paper_bgcolor=CARD, plot_bgcolor=CARD,
        margin=margin or dict(l=50, r=10, t=10, b=30),
        font=dict(color=MUTED, size=10),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=MUTED, size=10)),
        xaxis=dict(gridcolor=BORDER, color=MUTED, showgrid=False, zeroline=False),
        yaxis=dict(gridcolor=BORDER, color=MUTED, zeroline=False),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    print(f"Dashboard: http://localhost:{port}")
    app.run(debug=False, host="0.0.0.0", port=port)
