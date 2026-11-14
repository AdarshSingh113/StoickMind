"""Shared UI components and styling.

Streamlit gives us layout and widgets; this module adds a consistent design:
KPI cards, white "card" containers, badges, insight cards and a chart style.
Every page uses these, so the whole app looks like one product.
"""

from __future__ import annotations

import html
from contextlib import contextmanager

import altair as alt
import streamlit as st

PALETTE = {
    "indigo": "#4F46E5", "indigo_soft": "#EEF2FF", "teal": "#14B8A6", "teal_soft": "#E6FAF7",
    "amber": "#F59E0B", "amber_soft": "#FEF6E7", "rose": "#F43F5E", "rose_soft": "#FFF0F2",
    "green": "#16A34A", "green_soft": "#ECFDF3", "slate": "#64748B", "ink": "#0F172A",
    "muted": "#94A3B8", "border": "#E6E8F0", "grid": "#EEF0F5",
}
PAGES: dict = {}  # filled by app.py: key -> st.Page, so components can link to pages

FONT = "Inter, -apple-system, Segoe UI, Roboto, sans-serif"

CSS = f"""
<style>
/* ---------- page ---------- */
.block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1320px; }}
h1, h2, h3 {{ letter-spacing: -0.02em; }}
[data-testid="stHeader"] {{ background: transparent; }}

/* ---------- cards: st.container(key="card-...") ---------- */
[class*="st-key-card"] {{
  background: #FFFFFF; border: 1px solid {PALETTE["border"]}; border-radius: 16px;
  padding: 20px 22px 18px; box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 4px 16px rgba(15,23,42,.03);
}}
[class*="st-key-card"] [data-testid="stVerticalBlock"] {{ gap: .6rem; }}

/* ---------- KPI strip ---------- */
.k-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  background: #fff; border: 1px solid {PALETTE["border"]}; border-radius: 16px;
  box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 4px 16px rgba(15,23,42,.03); overflow: hidden; }}
.k-kpi {{ padding: 18px 22px; border-left: 1px solid {PALETTE["grid"]}; min-width: 0; }}
.k-kpi:first-child {{ border-left: none; }}
.k-kpi .lbl {{ color: {PALETTE["slate"]}; font-size: .82rem; font-weight: 500; display: flex; gap: 6px; align-items: center; }}
.k-kpi .val {{ color: {PALETTE["ink"]}; font-size: 1.75rem; font-weight: 700; letter-spacing: -0.02em;
  margin: 6px 0 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.k-kpi .sub {{ color: {PALETTE["muted"]}; font-size: .78rem; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }}

/* ---------- badges ---------- */
.k-badge {{ display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 999px;
  font-size: .74rem; font-weight: 600; line-height: 1.5; white-space: nowrap; }}
.k-good {{ background: {PALETTE["green_soft"]}; color: {PALETTE["green"]}; }}
.k-bad  {{ background: {PALETTE["rose_soft"]}; color: #E11D48; }}
.k-neutral {{ background: #F1F5F9; color: {PALETTE["slate"]}; }}
.k-indigo {{ background: {PALETTE["indigo_soft"]}; color: {PALETTE["indigo"]}; }}
.k-amber {{ background: {PALETTE["amber_soft"]}; color: #B45309; }}
.k-teal {{ background: {PALETTE["teal_soft"]}; color: #0F766E; }}

/* ---------- headers ---------- */
.k-eyebrow {{ color: {PALETTE["indigo"]}; font-size: .78rem; font-weight: 600; letter-spacing: .06em;
  text-transform: uppercase; margin-bottom: 2px; }}
.k-title {{ font-size: 1.85rem; font-weight: 700; color: {PALETTE["ink"]}; letter-spacing: -0.02em; line-height: 1.2; }}
.k-subtitle {{ color: {PALETTE["slate"]}; font-size: .95rem; margin-top: 4px; }}
.k-section {{ font-size: 1.02rem; font-weight: 650; color: {PALETTE["ink"]}; }}
.k-section-sub {{ color: {PALETTE["muted"]}; font-size: .82rem; margin-top: 1px; }}

/* ---------- insight cards ---------- */
.k-insight-head {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
.k-insight-title {{ font-weight: 650; font-size: 1rem; color: {PALETTE["ink"]}; }}
.k-insight-body {{ color: {PALETTE["slate"]}; font-size: .88rem; line-height: 1.5; min-height: 2.9em; }}
.k-insight-metric {{ color: {PALETTE["indigo"]}; font-weight: 600; font-size: .88rem; }}

/* ---------- profile ---------- */
.k-profile {{ display: flex; gap: 16px; align-items: center; }}
.k-avatar {{ width: 56px; height: 56px; border-radius: 16px; display: grid; place-items: center; flex: none;
  background: linear-gradient(135deg, #6366F1, #8B5CF6); color: #fff; font-weight: 700; font-size: 1.2rem; }}
.k-profile-name {{ font-size: 1.35rem; font-weight: 700; color: {PALETTE["ink"]}; letter-spacing: -0.01em; }}
.k-profile-meta {{ color: {PALETTE["slate"]}; font-size: .86rem; margin-top: 2px; }}

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] .k-brand {{ display: flex; align-items: center; gap: 10px; padding: 4px 4px 2px; }}
.k-logo {{ width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; color: #fff;
  font-weight: 800; background: linear-gradient(135deg, #4F46E5, #8B5CF6); }}
.k-brand-name {{ font-weight: 700; font-size: 1.05rem; color: {PALETTE["ink"]}; line-height: 1.1; }}
.k-brand-sub {{ color: {PALETTE["muted"]}; font-size: .74rem; }}
.k-phase {{ background: {PALETTE["indigo_soft"]}; color: {PALETTE["indigo"]}; border-radius: 12px; padding: 10px 12px;
  font-size: .8rem; line-height: 1.45; }}

/* ---------- chat ---------- */
[data-testid="stChatMessage"] {{ background: transparent; padding: .4rem 0; }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarCustom"]) [data-testid="stChatMessageContent"],
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] {{
  background: #fff; border: 1px solid {PALETTE["border"]}; border-radius: 4px 16px 16px 16px; padding: 14px 18px;
  box-shadow: 0 1px 2px rgba(15,23,42,.04); }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {{
  background: {PALETTE["indigo_soft"]}; border-radius: 16px 4px 16px 16px; padding: 12px 18px; }}
[data-testid="stChatMessageAvatarUser"] {{ background: {PALETTE["indigo"]} !important; color: #fff; }}
[data-testid="stChatMessageAvatarCustom"] {{ background: linear-gradient(135deg, #14B8A6, #4F46E5) !important;
  color: #fff !important; border: none !important; }}
.k-agent {{ display: flex; gap: 14px; align-items: center; }}
.k-agent-avatar {{ width: 48px; height: 48px; border-radius: 50%; display: grid; place-items: center; font-size: 1.4rem;
  background: linear-gradient(135deg, #14B8A6, #4F46E5); color: #fff; flex: none; }}
.k-online {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #22C55E; margin-right: 6px; }}

/* ---------- logo ---------- */
[data-testid="stSidebarHeader"] img, [data-testid="stLogo"] {{ height: 2.1rem; max-width: 12rem; }}

/* ---------- misc ---------- */
[data-testid="stExpander"] details {{ border-radius: 12px; border-color: {PALETTE["border"]}; background: #fff; }}
div[data-testid="stSegmentedControl"] button {{ font-weight: 500; }}
@media (max-width: 640px) {{ .k-kpi {{ border-left: none; border-top: 1px solid {PALETTE["grid"]}; }} .k-title {{ font-size: 1.5rem; }} }}
</style>
"""


def esc(text) -> str:
    return html.escape(str(text))


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def sidebar_brand() -> None:
    st.logo("static/logo.svg", size="large", icon_image="static/favicon.svg")


def sidebar_footer(phase: str, note: str) -> None:
    with st.sidebar:
        st.markdown(f'<div class="k-phase"><b>{esc(phase)}</b><br>{esc(note)}</div>', unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    eb = f'<div class="k-eyebrow">{esc(eyebrow)}</div>' if eyebrow else ""
    sub = f'<div class="k-subtitle">{esc(subtitle)}</div>' if subtitle else ""
    st.markdown(f'<div style="margin-bottom:.4rem">{eb}<div class="k-title">{esc(title)}</div>{sub}</div>',
                unsafe_allow_html=True)


def badge(text: str, tone: str = "neutral") -> str:
    return f'<span class="k-badge k-{tone}">{esc(text)}</span>'


def delta_badge(delta: float | None, good_when_up: bool = True, unit: str = "%") -> str:
    """Green/red pill with an arrow. `delta` is a fraction for %, or points for pts."""
    if delta is None:
        return ""
    if abs(delta) < (0.0005 if unit == "pts" else 0.005):  # rounds to zero: no colour, no arrow
        return badge("0" + (" pts" if unit == "pts" else "%"), "neutral")
    up = delta > 0
    tone = "good" if up == good_when_up else "bad"
    text = f"{delta * 100:+.1f} pts" if unit == "pts" else f"{delta:+.0%}"
    return badge(("▲ " if up else "▼ ") + text.lstrip("+-"), tone)


def kpi_strip(items: list[dict]) -> None:
    """items: {label, value, delta_html?, sub?, help?}"""
    cells = []
    for it in items:
        tip = f' title="{esc(it["help"])}"' if it.get("help") else ""
        info = ' <span style="color:#CBD5E1">ⓘ</span>' if it.get("help") else ""
        sub = f'{it.get("delta_html", "")} <span>{esc(it.get("sub", ""))}</span>'
        cells.append(f'<div class="k-kpi"{tip}><div class="lbl">{esc(it["label"])}{info}</div>'
                     f'<div class="val">{esc(it["value"])}</div><div class="sub">{sub}</div></div>')
    st.markdown(f'<div class="k-kpis">{"".join(cells)}</div>', unsafe_allow_html=True)


@contextmanager
def card(key: str, title: str = "", subtitle: str = ""):
    with st.container(key=f"card-{key}"):
        if title:
            sub = f'<div class="k-section-sub">{esc(subtitle)}</div>' if subtitle else ""
            st.markdown(f'<div class="k-section">{esc(title)}</div>{sub}', unsafe_allow_html=True)
        yield


def insight(key: str, title: str, priority: str, body: str, metric: str, page: str | None = None,
            link_label: str = "Take action") -> None:
    tone = {"High": "bad", "Medium": "amber", "Low": "teal", "Good": "good"}.get(priority, "neutral")
    label = {"Good": "On track"}.get(priority, f"{priority} priority")
    with card(f"insight-{key}"):
        st.markdown(f"""<div class="k-insight-head"><span class="k-insight-title">{esc(title)}</span>{badge(label, tone)}</div>
            <div class="k-insight-body">{esc(body)}</div>""", unsafe_allow_html=True)
        left, right = st.columns([3, 2], vertical_alignment="center")
        left.markdown(f'<span class="k-insight-metric">{esc(metric)}</span>', unsafe_allow_html=True)
        if page and page in PAGES:
            right.page_link(PAGES[page], label=f"{link_label} →")


def profile_header(name: str, meta: str, badges_html: str = "") -> None:
    initials = "".join(p[0] for p in name.split()[:2]).upper()
    st.markdown(f"""<div class="k-profile"><div class="k-avatar">{esc(initials)}</div><div>
        <div class="k-profile-name">{esc(name)}</div><div class="k-profile-meta">{esc(meta)}</div>
        <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">{badges_html}</div></div></div>""",
                unsafe_allow_html=True)


# ------------------------------------------------------------------ charts
def style(chart: alt.Chart, height: int = 260) -> alt.Chart:
    """One chart style everywhere: Inter, light grid, no borders, quiet axes."""
    return (chart.properties(height=height, background="transparent")
            .configure(font=FONT)
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor=PALETTE["slate"], titleColor=PALETTE["slate"], labelFontSize=11,
                            titleFontSize=11, titleFontWeight=500, gridColor=PALETTE["grid"],
                            domain=False, tickColor="transparent", labelPadding=6)
            .configure_legend(labelColor=PALETTE["slate"], labelFontSize=11, titleFontSize=11, orient="top",
                              symbolType="circle", symbolSize=70, title=None)
            .configure_axisX(grid=False))


def inr_axis(title: str | None = None) -> alt.Axis:
    expr = ("datum.value >= 10000000 ? '₹' + format(datum.value / 10000000, '.1f') + 'Cr' : "
            "datum.value >= 100000 ? '₹' + format(datum.value / 100000, '.1f') + 'L' : "
            "datum.value >= 10000 ? '₹' + format(datum.value / 1000, '.0f') + 'K' : "
            "datum.value >= 1000 ? '₹' + format(datum.value / 1000, '.1f') + 'K' : '₹' + format(datum.value, '.0f')")
    return alt.Axis(labelExpr=expr, title=title, tickCount=5)


def show(chart: alt.Chart, height: int = 260) -> None:
    st.altair_chart(style(chart, height), use_container_width=True)


# ------------------------------------------------------------ table styling
_STATUS_TONES = {
    # good
    "active": ("#ECFDF3", "#15803D"), "delivered": ("#ECFDF3", "#15803D"), "resolved": ("#ECFDF3", "#15803D"),
    "low": ("#E6FAF7", "#0F766E"),
    # in progress
    "shipped": ("#EEF2FF", "#4338CA"), "out for delivery": ("#EEF2FF", "#4338CA"), "placed": ("#EEF2FF", "#4338CA"),
    "open": ("#EEF2FF", "#4338CA"), "medium": ("#FEF6E7", "#B45309"), "at risk": ("#FEF6E7", "#B45309"),
    # bad
    "rto": ("#FFF0F2", "#BE123C"), "returned": ("#FFF0F2", "#BE123C"), "cancelled": ("#F1F5F9", "#64748B"),
    "lapsed": ("#FFF0F2", "#BE123C"), "high": ("#FFF0F2", "#BE123C"), "escalated": ("#FFF0F2", "#BE123C"),
}


def status_styler(value) -> str:
    """pandas Styler function: coloured cell for statuses and priorities."""
    tone = _STATUS_TONES.get(str(value).lower().replace("_", " "))
    if not tone:
        return ""
    bg, fg = tone
    return f"background-color: {bg}; color: {fg}; font-weight: 600"
