"""Pocket + analytics overlays (Person C).

Owns: the collapsing-pocket polygon and the pass-protection stats
(time-to-throw, pocket area over time).

Public contract (consumed by field.py and app.py):
    pocket_shape(frame_df) -> list[(x, y)]      # convex hull of pass blockers
    time_to_throw(meta) -> float | None         # seconds between snap and throw
    pocket_area(frame_df) -> float              # area of the pocket polygon

`frame_df` is one frame's worth of rows from the play bundle (same columns as
bundle["frames"]). These functions must tolerate the mock bundle (team values
"OFF"/"DEF") and the real data (team abbreviations) alike, so the pocket is
built from the offensive players nearest the line rather than a hard-coded role.
"""

from __future__ import annotations

import pandas as pd

FRAMES_PER_SECOND = 10.0


def _offensive_players(frame_df: pd.DataFrame) -> pd.DataFrame:
    """Best-effort offensive players for one frame (excludes ball)."""
    non_ball = frame_df[(frame_df["team"] != "football") & frame_df["team"].notna()]
    # Mock bundle uses explicit OFF/DEF tags.
    if "OFF" in non_ball["team"].values:
        return non_ball[non_ball["team"] == "OFF"]
    # Real data: team is an abbreviation. Without possession info here, fall back
    # to the team with the most players clustered (refine once app.py passes the
    # possession team through meta). For now return all non-ball players and let
    # the hull approximate the line of scrimmage cluster.
    return non_ball


def pocket_shape(frame_df: pd.DataFrame) -> list[tuple[float, float]]:
    """Convex hull of the pass blockers — the visible 'pocket'.

    Returns an ordered list of (x, y) vertices, or [] if not computable.
    """
    pts = _offensive_players(frame_df)[["x", "y"]].dropna().to_numpy()
    if len(pts) < 3:
        return []
    try:
        from scipy.spatial import ConvexHull

        hull = ConvexHull(pts)
        return [(float(pts[v, 0]), float(pts[v, 1])) for v in hull.vertices]
    except Exception:
        # Fallback: axis-aligned bounding box so the overlay still shows.
        xs, ys = pts[:, 0], pts[:, 1]
        return [
            (float(xs.min()), float(ys.min())),
            (float(xs.max()), float(ys.min())),
            (float(xs.max()), float(ys.max())),
            (float(xs.min()), float(ys.max())),
        ]


def pocket_area(frame_df: pd.DataFrame) -> float:
    """Area (sq yards) of the pocket polygon via the shoelace formula."""
    poly = pocket_shape(frame_df)
    if len(poly) < 3:
        return 0.0
    area = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def time_to_throw(meta: dict) -> float | None:
    """Seconds between ball snap and throw/sack. None if frames unknown."""
    snap = meta.get("snap_frame")
    throw = meta.get("throw_frame")
    if snap is None or throw is None:
        return None
    return (throw - snap) / FRAMES_PER_SECOND
