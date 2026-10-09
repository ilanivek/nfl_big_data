"""Field + player animation (Person B).

Owns: the static football field drawing and the animated Plotly figure that
moves the 22 players + ball frame by frame.

Public contract:
    build_field_figure(bundle, pocket_fn=None) -> plotly.graph_objects.Figure

`pocket_fn` is optional and comes from Person C (pocket.py). If provided, it is
called per frame as pocket_fn(frame_df) -> list[(x, y)] and drawn as a shaded
polygon. Keeping it optional means the replay works fully even if C's piece
isn't ready — graceful degradation.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# Field dimensions in yards (per the dataset README / Figure 1).
FIELD_LENGTH = 120.0  # includes both 10-yard end zones
FIELD_WIDTH = 53.3

TEAM_COLORS = {
    "football": "#8B4513",
}
OFFENSE_COLOR = "#1f77b4"  # blue
DEFENSE_COLOR = "#d62728"  # red
BALL_COLOR = "#8B4513"


def _field_shapes() -> list[dict]:
    """Static shapes: green field, end zones, yard lines every 5 yards."""
    shapes = []
    # Playing field background.
    shapes.append(dict(type="rect", x0=0, y0=0, x1=FIELD_LENGTH, y1=FIELD_WIDTH,
                       fillcolor="#2e7d32", line=dict(width=0), layer="below"))
    # End zones (0-10 and 110-120).
    for x0 in (0, 110):
        shapes.append(dict(type="rect", x0=x0, y0=0, x1=x0 + 10, y1=FIELD_WIDTH,
                           fillcolor="#1b5e20", line=dict(width=0), layer="below"))
    # Yard lines every 5 yards between the end zones.
    for x in range(10, 111, 5):
        shapes.append(dict(type="line", x0=x, y0=0, x1=x, y1=FIELD_WIDTH,
                           line=dict(color="white", width=1), layer="below"))
    return shapes


def _frame_traces(frame_df: pd.DataFrame, pocket_fn=None) -> list[go.Scatter]:
    """Build the scatter traces for a single frame."""
    off = frame_df[frame_df["team"] == "OFF"] if "OFF" in frame_df["team"].values \
        else frame_df[(frame_df["team"] != "football") & (frame_df["team"].notna())]
    # In real data, team is an abbreviation (e.g. "TB"/"DAL"), not OFF/DEF.
    # We split by the two non-football teams; offense vs defense coloring can be
    # refined once Person A tags possession. For now: football is brown, and the
    # two teams get blue/red by first-seen order.
    traces = []

    ball = frame_df[frame_df["team"] == "football"]
    non_ball = frame_df[frame_df["team"] != "football"]
    teams = [t for t in non_ball["team"].dropna().unique()]
    color_for = {}
    palette = [OFFENSE_COLOR, DEFENSE_COLOR, "#ff7f0e", "#9467bd"]
    for i, t in enumerate(teams):
        color_for[t] = palette[i % len(palette)]

    for t in teams:
        grp = non_ball[non_ball["team"] == t]
        traces.append(go.Scatter(
            x=grp["x"], y=grp["y"], mode="markers+text",
            marker=dict(size=14, color=color_for[t], line=dict(color="white", width=1)),
            text=grp["jerseyNumber"].fillna("").astype(str).str.replace(".0", "", regex=False),
            textposition="middle center", textfont=dict(size=8, color="white"),
            name=str(t), hoverinfo="text",
        ))

    if not ball.empty:
        traces.append(go.Scatter(
            x=ball["x"], y=ball["y"], mode="markers",
            marker=dict(size=9, color=BALL_COLOR, symbol="diamond"),
            name="ball", hoverinfo="skip",
        ))

    # Optional pocket polygon from Person C.
    if pocket_fn is not None:
        try:
            poly = pocket_fn(frame_df)
            if poly:
                xs = [p[0] for p in poly] + [poly[0][0]]
                ys = [p[1] for p in poly] + [poly[0][1]]
                traces.insert(0, go.Scatter(
                    x=xs, y=ys, mode="lines", fill="toself",
                    fillcolor="rgba(255,255,0,0.25)", line=dict(color="yellow", width=1),
                    name="pocket", hoverinfo="skip",
                ))
        except Exception:
            # Pocket is additive; never let it break the replay.
            pass

    return traces


def _frame_label(frame_df: pd.DataFrame, meta: dict, fid: int) -> str:
    """Human-readable caption for a frame: time since snap + any event tag."""
    snap = meta.get("snap_frame")
    secs = f"{(fid - snap) / 10:+.1f}s" if snap is not None else f"frame {fid}"
    # Surface a real event tag on this frame (ball_snap, pass_forward, qb_sack...).
    events = [e for e in frame_df["event"].dropna().unique()
              if e not in ("None", "none", "")]
    event_txt = f" — {events[0]}" if events else ""
    return f"{secs}{event_txt}"


def build_field_figure(bundle: dict, pocket_fn=None) -> go.Figure:
    """Build the animated replay figure from a play bundle."""
    frames_df = bundle["frames"]
    meta = bundle.get("meta", {})
    frame_ids = sorted(frames_df["frameId"].unique())

    # Initial frame.
    first = frames_df[frames_df["frameId"] == frame_ids[0]]
    fig = go.Figure(data=_frame_traces(first, pocket_fn))

    # Animation frames — each carries its own per-frame caption so the viewer
    # always knows how far into the play they are and what just happened.
    anim_frames = []
    for fid in frame_ids:
        fdf = frames_df[frames_df["frameId"] == fid]
        anim_frames.append(go.Frame(
            data=_frame_traces(fdf, pocket_fn),
            name=str(fid),
            layout=go.Layout(
                title=dict(text=_frame_label(fdf, meta, fid), x=0.5,
                           font=dict(size=14)),
            ),
        ))
    fig.frames = anim_frames

    # Pre-compute the frames where snap/throw happen, to label the slider.
    snap = meta.get("snap_frame")
    throw = meta.get("throw_frame")

    def _slider_label(fid: int) -> str:
        if fid == snap:
            return "SNAP"
        if fid == throw:
            return "THROW"
        return f"{(fid - snap) / 10:.1f}" if snap is not None else str(fid)

    # Play/pause controls + slider.
    fig.update_layout(
        shapes=_field_shapes(),
        title=dict(text=_frame_label(first, meta, frame_ids[0]), x=0.5,
                   font=dict(size=14)),
        xaxis=dict(range=[0, FIELD_LENGTH], showgrid=False, zeroline=False,
                   visible=False, constrain="domain"),
        yaxis=dict(range=[0, FIELD_WIDTH], showgrid=False, zeroline=False,
                   visible=False, scaleanchor="x", scaleratio=1),
        plot_bgcolor="#2e7d32", paper_bgcolor="white",
        margin=dict(l=10, r=10, t=40, b=10), height=430,
        showlegend=False,
        updatemenus=[dict(
            type="buttons", showactive=False, x=0.05, y=1.15,
            buttons=[
                dict(label="▶ Play", method="animate",
                     args=[None, dict(frame=dict(duration=100, redraw=True),
                                      fromcurrent=True)]),
                dict(label="⏸ Pause", method="animate",
                     args=[[None], dict(frame=dict(duration=0, redraw=False),
                                        mode="immediate")]),
            ],
        )],
        sliders=[dict(
            steps=[dict(method="animate", label=_slider_label(fid),
                        args=[[str(fid)], dict(frame=dict(duration=0, redraw=True),
                                               mode="immediate")])
                   for fid in frame_ids],
            x=0.05, len=0.9, y=0,
            currentvalue=dict(prefix="Time: ", suffix="s since snap"),
        )],
    )
    return fig
