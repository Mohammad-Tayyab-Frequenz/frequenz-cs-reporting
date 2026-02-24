# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Chart rendering functions for the reporting module."""

from math import isfinite

import plotly.express as px
import plotly.graph_objects as go


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

    # sanitize values
    clean = {k: (float(v) if v is not None else 0.0) for k, v in data_points.items()}
    total = clean[total_key]
    if total <= 0:
        fig = go.Figure()
        fig.update_layout(
            showlegend=False,
            annotations=[
                {
                    "text": "No data to display: total is zero or negative",
                    "x": 0.5,
                    "xref": "paper",
                    "y": 0.5,
                    "yref": "paper",
                    "showarrow": False,
                    "font": {"size": 14, "color": "gray"},
                }
            ],
        )
        return fig

    # segments
    segments = {
        k: v for k, v in clean.items() if k != total_key and isfinite(v) and v != 0.0
    }
    display_base = total
    residual = display_base - sum(segments.values())

    # Only add "Others" if there is a meaningful residual
    if abs(residual) > 1e-6:
        segments["Others"] = residual

    # compute percentages
    seg_with_pct = [
        (k, v, (v / display_base * 100.0 if display_base != 0 else 0.0))
        for k, v in segments.items()
    ]

    # sort left → right by descending absolute value (so largest chunk comes first in bar)
    seg_with_pct.sort(key=lambda x: abs(x[1]), reverse=True)

    # colors
    palette = px.colors.qualitative.Plotly
    color_map, i = {}, 0
    for label, _, _ in seg_with_pct:
        if label == "Others":
            color_map[label] = "#7f7f7f"
        else:
            color_map[label] = palette[i % len(palette)]
            i += 1

    # figure
    fig = go.Figure()

    for label, value, pct in seg_with_pct:
        text = f"{pct:.1f}%"
        fig.add_trace(
            go.Bar(
                x=[pct],
                y=[""],
                name=label,
                orientation="h",
                marker={"color": color_map[label]},
                text=text,
                textposition="inside",
                insidetextanchor="middle",
                customdata=[value],
                hovertemplate=(
                    f"{label}: %{{x:.1f}}%<br>"
                    "Wert: %{customdata[0]:,.2f} kWh<extra></extra>"
                ),
            )
        )

    pos_total = sum(pct for _, _, pct in seg_with_pct if pct > 0)
    neg_total = sum(pct for _, _, pct in seg_with_pct if pct < 0)

    fig.update_layout(
        barmode="relative",
        xaxis={
            "title": None,
            "range": [min(0.0, neg_total * 1.1), max(0.0, pos_total * 1.1)],
            "tickformat": ".0f%%",  # show % ticks
            "showgrid": False,
            "zeroline": False,
        },
        yaxis={"showticklabels": False},
        height=160,  # controls bar thickness
        margin={"l": 0, "r": 0, "t": 20, "b": 40},
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.35,  # place legend below bar
            "xanchor": "center",
            "x": 0.5,
        },
    )

    fig.update_layout(
        annotations=[
            {
                "text": f"{total_key}: {total:.0f} kWh",
                "x": 0.5,
                "xref": "paper",
                "y": 1.3,
                "yref": "paper",
                "showarrow": False,
                "font": {"size": 14, "color": "black"},
            }
        ],
        margin={"t": 40},  # add extra top margin for annotation
    )
    return fig
