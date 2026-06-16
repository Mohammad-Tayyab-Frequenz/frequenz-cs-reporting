# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Chart rendering functions for the reporting module."""

from math import isfinite

import plotly.graph_objects as go

# ── Professional colour palette ───────────────────────────────────────────────
# Ordered so the most semantically meaningful colours come first:
#   blue = grid / primary,  green = generation,  amber = consumption,
#   purple = balance,  teal = export,  slate = others
_PROFESSIONAL_PALETTE = [
    "#3b82f6",  # blue      – Netzbezug / grid
    "#10b981",  # green     – PV / generation
    "#f59e0b",  # amber     – consumption
    "#8b5cf6",  # purple    – battery / storage
    "#14b8a6",  # teal      – feed-in / export
    "#ef4444",  # red       – alerts / peaks
    "#f97316",  # orange    – wind / CHP
    "#64748b",  # slate     – others / residual
]

_OTHERS_COLOR = "#94a3b8"  # light slate for residual segment


def _apply_professional_layout(fig: go.Figure) -> None:
    """Apply a clean, corporate-grade layout to any Plotly figure."""
    fig.update_layout(
        font={
            "family": "Inter, Segoe UI, Arial, sans-serif",
            "size": 12,
            "color": "#374151",
        },
        paper_bgcolor="#ffffff",
        plot_bgcolor="#f8fafc",
        margin={"l": 12, "r": 12, "t": 40, "b": 40},
        legend={
            "bgcolor": "rgba(255,255,255,0.9)",
            "bordercolor": "#e2e8f0",
            "borderwidth": 1,
            "font": {"size": 11, "color": "#374151"},
        },
        hoverlabel={
            "bgcolor": "#1e293b",
            "font_size": 12,
            "font_color": "#f8fafc",
            "bordercolor": "#334155",
        },
    )
    fig.update_xaxes(
        gridcolor="#e2e8f0",
        linecolor="#e2e8f0",
        tickfont={"size": 11, "color": "#6b7280"},
        zeroline=False,
    )
    fig.update_yaxes(
        gridcolor="#e2e8f0",
        linecolor="#e2e8f0",
        tickfont={"size": 11, "color": "#6b7280"},
        zeroline=False,
    )


# pylint: disable=too-many-locals
def plot_percentage_bar(
    data_points: dict[str, float | None], total_key: str
) -> go.Figure:
    """Render a stacked percentage bar showing contributions to a total.

    Args:
        data_points: Mapping of labels to numeric values.
        total_key: Key representing the total value in ``data_points``.

    Returns:
        Plotly figure containing the stacked bar chart.

    Raises:
        ValueError: If ``total_key`` is missing from ``data_points``.
    """
    if total_key not in data_points:
        raise ValueError(f"Total key '{total_key}' not found.")

    clean = {k: (float(v) if v is not None else 0.0) for k, v in data_points.items()}
    total = clean[total_key]

    if total <= 0:
        fig = go.Figure()
        fig.update_layout(
            paper_bgcolor="#ffffff",
            plot_bgcolor="#f8fafc",
            showlegend=False,
            annotations=[
                {
                    "text": "Keine Daten zur Anzeige",
                    "x": 0.5,
                    "xref": "paper",
                    "y": 0.5,
                    "yref": "paper",
                    "showarrow": False,
                    "font": {
                        "size": 13,
                        "color": "#94a3b8",
                        "family": "Inter, sans-serif",
                    },
                }
            ],
        )
        return fig

    segments = {
        k: v for k, v in clean.items() if k != total_key and isfinite(v) and v != 0.0
    }
    residual = total - sum(segments.values())
    if abs(residual) > 1e-6:
        segments["Sonstige"] = residual

    seg_with_pct = [
        (k, v, (v / total * 100.0 if total != 0 else 0.0)) for k, v in segments.items()
    ]
    seg_with_pct.sort(key=lambda x: abs(x[1]), reverse=True)

    # Assign palette colours in order; "Sonstige" always gets slate
    color_map: dict[str, str] = {}
    palette_idx = 0
    for label, _, _ in seg_with_pct:
        if label == "Sonstige":
            color_map[label] = _OTHERS_COLOR
        else:
            color_map[label] = _PROFESSIONAL_PALETTE[
                palette_idx % len(_PROFESSIONAL_PALETTE)
            ]
            palette_idx += 1

    fig = go.Figure()
    for label, value, pct in seg_with_pct:
        fig.add_trace(
            go.Bar(
                x=[pct],
                y=[""],
                name=label,
                orientation="h",
                marker={
                    "color": color_map[label],
                    "line": {"color": "rgba(255,255,255,0.6)", "width": 1.5},
                },
                text=f"{pct:.1f}%",
                textposition="inside",
                insidetextanchor="middle",
                textfont={
                    "size": 11,
                    "color": "#ffffff",
                    "family": "Inter, sans-serif",
                },
                customdata=[value],
                hovertemplate=(
                    f"<b>{label}</b><br>"
                    "Anteil: %{x:.1f}%<br>"
                    "Energie: %{customdata[0]:,.0f} kWh"
                    "<extra></extra>"
                ),
            )
        )

    pos_total = sum(pct for _, _, pct in seg_with_pct if pct > 0)
    neg_total = sum(pct for _, _, pct in seg_with_pct if pct < 0)

    fig.update_layout(
        barmode="relative",
        font={"family": "Inter, Segoe UI, Arial, sans-serif", "size": 12},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#f8fafc",
        xaxis={
            "title": None,
            "range": [min(0.0, neg_total * 1.1), max(100.0, pos_total * 1.05)],
            "tickformat": ".0f%%",
            "showgrid": False,
            "zeroline": False,
            "tickfont": {"size": 11, "color": "#9ca3af"},
        },
        yaxis={"showticklabels": False, "showgrid": False},
        height=150,
        margin={"l": 0, "r": 0, "t": 48, "b": 44},
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.3,
            "xanchor": "center",
            "x": 0.5,
            "font": {"size": 11, "color": "#374151"},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
        },
        hoverlabel={
            "bgcolor": "#1e293b",
            "font_size": 12,
            "font_color": "#f8fafc",
            "bordercolor": "#334155",
        },
        separators=",.",
        annotations=[
            {
                "text": f"<b>{total_key}:</b> {total:,.0f}".replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
                + " kWh",
                "x": 0.5,
                "xref": "paper",
                "y": 1.35,
                "yref": "paper",
                "showarrow": False,
                "font": {
                    "size": 13,
                    "color": "#374151",
                    "family": "Inter, Segoe UI, Arial, sans-serif",
                },
            }
        ],
    )
    return fig
