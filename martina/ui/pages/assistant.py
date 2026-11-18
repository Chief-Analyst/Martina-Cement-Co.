"""AI Assistant: chat on the left, the matching table or chart on the right."""
import dash_mantine_components as dmc
from dash import ALL, Input, Output, State, callback, clientside_callback, ctx, dcc, html, no_update

from ... import brand
from ...ai import llm
from ...ai.assistant import answer
from ..charts import bars, forecast as forecast_fig
from ..components import card, empty, graph, icon, table

SUGGESTIONS = ["Give me a morning briefing across all tabs", "Which customers should we call today?",
               "How much should we release for the next 3 days?", "Which trucks have been on site the longest?",
               "What will be ordered next week?", "Which customers are on hold?", "How are the transporters doing?",
               "Summarise the last shift"]


def layout():
    mode = ("Groq " + llm.SETTINGS.groq_model) if llm.enabled() else "Demo mode"
    tip = ("Answers are written by Groq from the dashboard's figures only." if llm.enabled() else
           "No GROQ_API_KEY is set, so answers are assembled from the dashboard's figures by a built-in writer. ")
    return html.Div(className="mc-page", children=[
        html.Div(className="mc-page-head", children=[
            html.Div([html.H1("AI Assistant", className="mc-page-title"),
                      html.Div("Ask about the order book, release planning, a customer, the fleet or next week's "
                               "demand. Every answer uses only the figures this dashboard holds.", className="mc-page-sub")]),
            html.Span([icon("mdi:shield-check-outline", 15), " ", mode], className="mc-pill", title=tip)]),
        html.Div(className="suggest", children=[
            html.Button(s, id={"type": "ai-suggest", "q": s}, n_clicks=0) for s in SUGGESTIONS]),
        dcc.Store(id="ai-history", storage_type="session", data=[]),
        dcc.Store(id="ai-visual"),
        html.Div(className="mc-split", children=[
            card("Conversation", html.Div([
                dcc.Loading(html.Div(id="ai-chat", className="chat"), type="dot", color=brand.COLORS["primary"],
                            parent_style={"position": "relative"}),
                html.Div(style={"display": "flex", "gap": "8px", "marginTop": "12px", "alignItems": "flex-end"}, children=[
                    dmc.Textarea(id="ai-input", placeholder="Ask a question (Enter to send, Shift+Enter for a new line)",
                                 autosize=True, minRows=2, maxRows=5, style={"flex": 1}),
                    dmc.Button("Send", id="ai-send", disabled=True, leftSection=icon("mdi:send", 16))]),
                html.Div(tip, className="note", style={"marginTop": "8px"})]),
                right=dmc.Tooltip(label="Clear the conversation", children=dmc.ActionIcon(
                    icon("mdi:broom", 16), id="ai-clear", variant="subtle", color="gray"))),
            card("Results", html.Div(id="ai-results"), description="The table or chart behind the latest answer"),
        ]),
    ])


def _bubble(m):
    if m["role"] == "user":
        return html.Div(m["content"], className="msg msg-user")
    meta = m.get("meta", "")
    return html.Div(className="msg msg-bot", children=[dcc.Markdown(m["content"]),
                                                      html.Div(meta, className="msg-meta") if meta else None])


def _welcome():
    return html.Div(className="welcome", children=[
        html.Img(src="/assets/logo-mark.svg", style={"height": "54px"}),
        html.H3(f"Welcome to the {brand.COMPANY['product']} Assistant"),
        html.Div("Pick a suggestion above or ask in your own words. Name a customer, region, product or truck "
                 "(for example KES-004) to focus the answer.")])


@callback(Output("ai-chat", "children"), Input("ai-history", "data"))
def show(history):
    if not history:
        return _welcome()
    return [_bubble(m) for m in history]


clientside_callback("function(v) { return !(v && v.trim().length); }",
                    Output("ai-send", "disabled"), Input("ai-input", "value"))

clientside_callback(
    """function(h) {
        setTimeout(function () { const c = document.getElementById('ai-chat'); if (c) c.scrollTop = c.scrollHeight; }, 80);
        return window.dash_clientside.no_update;
    }""", Output("ai-chat", "title"), Input("ai-history", "data"))


@callback(Output("ai-history", "data"), Output("ai-input", "value"), Output("ai-visual", "data"),
          Input("ai-send", "n_clicks"), Input({"type": "ai-suggest", "q": ALL}, "n_clicks"), Input("ai-clear", "n_clicks"),
          State("ai-input", "value"), State("ai-history", "data"), prevent_initial_call=True)
def ask(_send, _sugg, _clear, text, history):
    trig = ctx.triggered_id
    if trig == "ai-clear":
        return [], "", None
    if isinstance(trig, dict):
        if not any(x.get("value") for x in ctx.triggered):
            return no_update, no_update, no_update
        text = trig["q"]
    text = (text or "").strip()
    if not text:
        return no_update, no_update, no_update
    history = list(history or [])
    convo = [{"role": m["role"], "content": m["content"]} for m in history[-6:]]
    r = answer(text, convo)
    meta = {"groq": "Written by Groq from the dashboard's figures", "demo": "Built from the dashboard's figures",
            "guardrail": "Guardrail"}.get(r["mode"], "")
    history += [{"role": "user", "content": text}, {"role": "assistant", "content": r["text"], "meta": meta}]
    vis = r.get("visual")
    return history[-30:], "", _pack(vis)


def _pack(vis):
    """Visuals hold DataFrames; keep only what the results panel needs, as JSON."""
    if not vis:
        return None
    if vis["kind"] == "forecast":
        region, d, r = vis["data"]
        return {"kind": "forecast", "title": vis["title"], "region": region}
    df = vis["df"].copy()
    for c in df.columns:
        if str(df[c].dtype) in ("category", "object"):
            df[c] = df[c].astype(str)
    return {"kind": vis["kind"], "title": vis["title"], "rows": df.head(300).to_dict("records"),
            "cols": list(df.columns)}


@callback(Output("ai-results", "children"), Input("ai-visual", "data"))
def results(vis):
    import pandas as pd
    if not vis:
        return empty("Ask a question to see the figures behind the answer.", "mdi:table-eye")
    if vis["kind"] == "forecast":
        from ...orderbook.forecast import FORECASTER
        r = FORECASTER.get()
        if not r:
            return empty("The forecast is still training.")
        hist = r["history"][vis["region"]].iloc[-42:]
        fc = r["forecast"][r["forecast"]["region"] == vis["region"]]
        return html.Div([html.B(vis["title"]), graph(forecast_fig(hist, fc), 380)])
    df = pd.DataFrame(vis["rows"], columns=vis["cols"])
    if vis["kind"] == "region":
        return html.Div([html.B(vis["title"]), graph(bars(df, "region", "open_t", color="region"), 360)])
    spec = {}
    for c in df.columns:
        kind = "text"
        if c in ("band", "status", "priority", "level"):
            kind = "band"
        elif c.endswith("_t") or c in ("open_t",):
            kind = "t"
        elif c in ("ratio", "on_time", "tracking", "risk"):
            kind = "pct"
        elif c in ("cover_days", "age_days", "avg_site_h"):
            kind = "dec"
        wide = 2.0 if c in ("what", "where", "reasons", "customer_name", "note", "action") else None
        spec[c] = (c.replace("_", " ").replace(" t", " (t)").capitalize(), kind, wide)
    return html.Div([html.B(vis["title"]), html.Div(style={"height": "8px"}),
                     table("ai-results-grid", df, spec, height=470, quick_filter=False)])
