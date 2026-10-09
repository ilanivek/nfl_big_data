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
BALL_COLOR = "#ff7f0e"  # orange


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


def _team_colors(teams: list, meta: dict) -> dict:
    """Map each team tag to a color using possession info from meta.

    `meta["possessionTeam"]` is the offense and `meta["defensiveTeam"]` the
    defense. These are "OFF"/"DEF" in the mock bundle and real abbreviations
    (e.g. "TB"/"DAL") in real data, so keying on them works in both modes.
    Any team not matched (shouldn't happen) falls back to a neutral palette so
    the replay never crashes.
    """
    possession = meta.get("possessionTeam")
    defense = meta.get("defensiveTeam")
    color_for = {}
    fallback = ["#ff7f0e", "#9467bd"]
    fi = 0
    for t in teams:
        if possession is not None and t == possession:
            color_for[t] = OFFENSE_COLOR
        elif defense is not None and t == defense:
            color_for[t] = DEFENSE_COLOR
        else:
            # Unknown team (missing possession info): neutral, but still distinct.
            color_for[t] = fallback[fi % len(fallback)]
            fi += 1
    return color_for


def _frame_traces(frame_df: pd.DataFrame, pocket_fn=None, meta: dict | None = None) -> list[go.Scatter]:
    """Build the scatter traces for a single frame.

    Offense is colored blue and defense red by matching each row's `team`
    against `meta["possessionTeam"]`/`meta["defensiveTeam"]`. Works for both the
    mock bundle (OFF/DEF) and real data (team abbreviations).
    """
    meta = meta or {}
    traces = []

    ball = frame_df[frame_df["team"] == "football"]
    non_ball = frame_df[frame_df["team"] != "football"]
    teams = [t for t in non_ball["team"].dropna().unique()]
    color_for = _team_colors(teams, meta)

    for t in teams:
        grp = non_ball[non_ball["team"] == t]
        is_offense = t == meta.get("possessionTeam")
        traces.append(go.Scatter(
            x=grp["x"], y=grp["y"], mode="markers+text",
            marker=dict(size=20, color=color_for[t], symbol="square",
                        line=dict(color="white", width=1)),
            text=grp["jerseyNumber"].fillna("").astype(str).str.replace(".0", "", regex=False),
            textposition="middle center", textfont=dict(size=11, color="white"),
            name=f"{t} (offense)" if is_offense else str(t), hoverinfo="text",
        ))

    if not ball.empty:
        traces.append(go.Scatter(
            x=ball["x"], y=ball["y"], mode="markers",
            marker=dict(size=13, color=BALL_COLOR, symbol="circle"),
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
    fig = go.Figure(data=_frame_traces(first, pocket_fn, meta))

    # Animation frames — each carries its own per-frame caption so the viewer
    # always knows how far into the play they are and what just happened.
    anim_frames = []
    for fid in frame_ids:
        fdf = frames_df[frames_df["frameId"] == fid]
        anim_frames.append(go.Frame(
            data=_frame_traces(fdf, pocket_fn, meta),
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
        margin=dict(l=10, r=10, t=40, b=10), height=650,
        showlegend=False,
        updatemenus=[dict(
            type="buttons", showactive=False, x=0.05, y=1.15,
            buttons=[
                # Single toggle: Plotly alternates between `args` (play) and
                # `args2` (pause) on each click, so one button does both.
                dict(label="▶ / ⏸", method="animate",
                     args=[None, dict(frame=dict(duration=100, redraw=True),
                                      fromcurrent=True)],
                     args2=[[None], dict(frame=dict(duration=0, redraw=False),
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
