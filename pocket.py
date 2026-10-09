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

# Column names the bundle might use for a player's role (Person A will add one
# of these when joining pffScoutingData). We check all common spellings so the
# filter "just works" whatever Person A names it.
ROLE_COLUMNS = ("role", "pff_role")

# pff_role values that identify a pass blocker — the players who form the pocket.
BLOCKER_ROLES = {"Pass block", "Pass"}  # include the QB ("Pass"); drop him via QB_ONLY below if desired

# Just the blockers (no QB), for the tightest pocket.
PASS_BLOCK_ROLES = {"Pass block"}


def _role_column(frame_df: pd.DataFrame) -> str | None:
    """Return the name of the role column present in the frame, if any."""
    for col in ROLE_COLUMNS:
        if col in frame_df.columns:
            return col
    return None


def _offensive_players(frame_df: pd.DataFrame, blockers_only: bool = True) -> pd.DataFrame:
    """Players used to build the pocket hull, best available precision first.

    Priority:
      1. A role column (real data, once Person A joins pffScoutingData):
         keep only pass blockers — the five O-linemen that actually form the
         pocket. This is the correct, distortion-free input.
      2. The mock bundle's explicit OFF/DEF tags: keep OFF.
      3. Fallback: all non-ball players (least precise, but never crashes).

    `blockers_only` keeps just the blockers (`Pass block`). Set False to also
    include the QB, who sits inside the pocket.
    """
    non_ball = frame_df[(frame_df["team"] != "football") & frame_df["team"].notna()]

    # 1. Best case: an explicit role column exists.
    role_col = _role_column(frame_df)
    if role_col is not None:
        wanted = PASS_BLOCK_ROLES if blockers_only else BLOCKER_ROLES
        blockers = non_ball[non_ball[role_col].isin(wanted)]
        # Only trust the role filter if it actually found blockers; otherwise
        # fall through so a sparse/odd play still renders something.
        if len(blockers) >= 3:
            return blockers

    # 2. Mock bundle uses explicit OFF/DEF tags.
    if "OFF" in non_ball["team"].values:
        return non_ball[non_ball["team"] == "OFF"]

    # 3. Fallback: all non-ball players.
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


def pocket_area_series(bundle: dict) -> pd.DataFrame:
    """Pocket area at every frame of the play.

    Returns a DataFrame with columns [frameId, seconds, area], where `seconds`
    is time since the snap (negative before the snap). Feed this to a line chart
    to show the pocket collapsing over the course of the play.
    """
    frames = bundle["frames"]
    snap = bundle["meta"].get("snap_frame")
    rows = []
    for fid in sorted(frames["frameId"].unique()):
        fdf = frames[frames["frameId"] == fid]
        secs = (fid - snap) / FRAMES_PER_SECOND if snap is not None else None
        rows.append({"frameId": int(fid), "seconds": secs, "area": pocket_area(fdf)})
    return pd.DataFrame(rows)


def pressure_moment(bundle: dict, threshold: float = 10.0) -> dict | None:
    """First frame where pocket area drops below `threshold` sq yds.

    This approximates the moment protection breaks down. Returns a dict with
    frameId/seconds/area, or None if the pocket never collapses that far.
    """
    series = pocket_area_series(bundle)
    collapsed = series[series["area"] < threshold]
    if collapsed.empty:
        return None
    row = collapsed.iloc[0]
    return {"frameId": int(row["frameId"]), "seconds": row["seconds"], "area": row["area"]}
