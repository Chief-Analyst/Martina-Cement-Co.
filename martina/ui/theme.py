"""Visual system: Mantine theme, Plotly template and number formats."""
import plotly.graph_objects as go
import plotly.io as pio

from ..brand import COLORS, SERIES

# Ten shades of the brand teal, lightest to darkest, for Mantine.
TEAL = ["#E8F3F5", "#CFE6EA", "#A6D0D8", "#79B7C3", "#4F9DAD", "#2D8496",
        "#0E5E6F", "#0B4E5D", "#083E4A", "#052D37"]
AMBER = ["#FEF6E9", "#FDEBCF", "#FAD7A1", "#F7C273", "#F4B055", "#F2A541",
         "#D98D2B", "#B4721F", "#8F5916", "#6A410E"]

MANTINE_THEME = {
    "primaryColor": "martina",
    "primaryShade": 6,
    "colors": {"martina": TEAL, "amber": AMBER},
    "fontFamily": "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif",
    "headings": {"fontFamily": "Inter, 'Segoe UI', system-ui, sans-serif", "fontWeight": "700"},
    "defaultRadius": "md",
    "radius": {"md": "10px", "lg": "14px"},
}

FONT = "Inter, Segoe UI, system-ui, sans-serif"

pio.templates["martina"] = go.layout.Template(layout=go.Layout(
    font={"family": FONT, "size": 12.5, "color": COLORS["ink"]},
    colorway=SERIES,
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin={"l": 48, "r": 16, "t": 24, "b": 40},
    xaxis={"gridcolor": "#EEF2F5", "linecolor": "#CBD5E1", "zeroline": False, "automargin": True,
           "tickfont": {"color": COLORS["muted"]}},
    yaxis={"gridcolor": "#EEF2F5", "linecolor": "rgba(0,0,0,0)", "zeroline": False, "automargin": True,
           "tickfont": {"color": COLORS["muted"]}},
    legend={"orientation": "h", "y": -0.18, "x": 0, "font": {"size": 11.5}},
    hoverlabel={"bgcolor": "white", "bordercolor": COLORS["line"],
                "font": {"family": FONT, "color": COLORS["ink"]}},
    bargap=0.28,
))
pio.templates.default = "martina"

GRAPH_CONFIG = {"displaylogo": False, "responsive": True,
                "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d",
                                           "toggleSpikelines", "hoverCompareCartesian"]}

BAND_COLORS = {
    "CRITICAL": COLORS["bad"], "HIGH": COLORS["bad"], "POOR": COLORS["bad"], "Hold": COLORS["bad"],
    "WATCH": COLORS["watch"], "MEDIUM": COLORS["watch"], "FAIR": COLORS["watch"], "Caution": COLORS["watch"],
    "HEALTHY": COLORS["good"], "GOOD": COLORS["good"], "LOW": COLORS["good"], "Ready": COLORS["good"],
    "NO TARGET": COLORS["muted"], "PROJECT": COLORS["info"],
}


def tonnes(v, unit=True):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    s = f"{v:,.0f}"
    return f"{s} t" if unit else s


def naira(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if abs(v) >= 1e9:
        return f"₦{v / 1e9:,.2f}bn"
    if abs(v) >= 1e6:
        return f"₦{v / 1e6:,.1f}m"
    return f"₦{v:,.0f}"


def pct(v, digits=0):
    try:
        return f"{float(v) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def hours(h):
    try:
        h = float(h)
    except (TypeError, ValueError):
        return "-"
    if h < 1:
        return f"{h * 60:.0f} min"
    return f"{int(h)}h {int(round((h - int(h)) * 60)):02d}m"
