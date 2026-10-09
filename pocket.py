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
# NOTE: matched case-insensitively (see _offensive_players). The README documents
# these as "Pass block"/"Pass", but the actual CSV ships "Pass Block"/"Pass" —
# so we normalize to lowercase before comparing to avoid a casing mismatch.
BLOCKER_ROLES = {"pass block", "pass"}  # include the QB ("pass")

# Just the blockers (no QB), for the tightest pocket.
PASS_BLOCK_ROLES = {"pass block"}


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
        # Case-insensitive match: the CSV ships "Pass Block" but the README says
        # "Pass block". Normalize both sides to lowercase so either works.
        role_norm = non_ball[role_col].astype(str).str.strip().str.lower()
        blockers = non_ball[role_norm.isin(wanted)]
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


# --------------------------------------------------------------------------
# Pocket Integrity Score — the headline metric
# --------------------------------------------------------------------------
# A single 0-100 grade for how well the offensive line protected the QB on a
# play. It blends three things a coach actually cares about, each scored 0-1
# then weighted:
#   1. TIME HELD   (45%) — how long the pocket survived before the throw/sack.
#                  2.5s is "clean"; under ~1.5s is a quick loss.
#   2. RETENTION   (35%) — pocket area at the throw vs. its post-snap peak.
#                  A pocket that keeps its space protects better than one that
#                  caves in, even if both last the same time.
#   3. STABILITY   (20%) — how steadily it held vs. collapsing in a rush.
#                  Measured as the worst (min) area as a share of the peak.
# Weights are tunable; these are sensible hackathon defaults, not gospel.

SCORE_WEIGHTS = {"time": 0.45, "retention": 0.35, "stability": 0.20}

# Time-held normalization: seconds that map to a "full marks" pocket.
IDEAL_TIME_TO_THROW = 2.5

# Outcome multiplier applied to the blended score. Protection that ends in a
# sack failed by definition, no matter how long it lasted, so we cap it hard.
# A hit/hurry is a partial failure; a clean pass/scramble keeps full credit.
#   S = sack, IN = interception (often pressure-driven), I = incomplete,
#   C = complete, R = scramble.
OUTCOME_MULTIPLIER = {
    "S": 0.35,   # sack — protection broke down
    "IN": 0.80,  # interception — not purely an OL failure
    "I": 0.95,   # incomplete — mostly on the throw, not protection
    "C": 1.00,   # complete — protection did its job
    "R": 0.90,   # scramble — QB had to leave a breaking pocket
}


def _post_snap_series(bundle: dict) -> pd.DataFrame:
    """Area series restricted to snap..throw (the window that matters)."""
    series = pocket_area_series(bundle)
    meta = bundle["meta"]
    snap, throw = meta.get("snap_frame"), meta.get("throw_frame")
    if snap is not None:
        series = series[series["frameId"] >= snap]
    if throw is not None:
        series = series[series["frameId"] <= throw]
    return series.reset_index(drop=True)


def pocket_integrity_score(bundle: dict) -> dict:
    """Compute the 0-100 Pocket Integrity Score for a play.

    Returns a dict with the overall `score` plus the three component sub-scores
    (0-100 each) and the raw numbers behind them, so the UI can show a
    breakdown rather than an unexplained number.
    """
    series = _post_snap_series(bundle)
    if series.empty or series["area"].max() <= 0:
        return {
            "score": None,
            "components": {"time": None, "retention": None, "stability": None},
            "detail": {"reason": "pocket not computable for this play"},
        }

    peak = float(series["area"].max())
    area_at_throw = float(series["area"].iloc[-1])
    area_min = float(series["area"].min())

    # 1. Time held (clamped 0..1 against the ideal).
    ttt = time_to_throw(bundle["meta"])
    time_component = min(ttt / IDEAL_TIME_TO_THROW, 1.0) if ttt is not None else 0.5

    # 2. Retention: area kept at the throw vs. the peak.
    retention_component = max(0.0, min(area_at_throw / peak, 1.0))

    # 3. Stability: worst area vs. peak (penalizes a deep collapse mid-play).
    stability_component = max(0.0, min(area_min / peak, 1.0))

    components01 = {
        "time": time_component,
        "retention": retention_component,
        "stability": stability_component,
    }
    blended = sum(SCORE_WEIGHTS[k] * v for k, v in components01.items())

    # Apply the play-outcome multiplier so a sack can't score as "good" protection.
    outcome = bundle["meta"].get("passResult")
    mult = OUTCOME_MULTIPLIER.get(outcome, 1.0)
    overall = blended * mult

    return {
        "score": round(overall * 100, 1),
        "components": {k: round(v * 100, 1) for k, v in components01.items()},
        "detail": {
            "time_to_throw_s": ttt,
            "peak_area": round(peak, 1),
            "area_at_throw": round(area_at_throw, 1),
            "min_area": round(area_min, 1),
            "outcome": outcome,
            "outcome_multiplier": mult,
            "grade": _letter_grade(overall * 100),
        },
    }


def _letter_grade(score: float) -> str:
    """A quick letter grade for the demo (A protection ... F got crushed)."""
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def integrity_trace(bundle: dict) -> pd.DataFrame:
    """Per-frame 'live' pocket integrity (0-100), for a running gauge.

    Integrity at a frame = current area as a percentage of the post-snap peak
    area, so it starts near 100 right after the snap and falls as the pocket
    collapses. Columns: [frameId, seconds, integrity].
    """
    series = pocket_area_series(bundle)
    post = _post_snap_series(bundle)
    peak = float(post["area"].max()) if not post.empty and post["area"].max() > 0 else None
    if peak is None:
        series = series.assign(integrity=float("nan"))
        return series[["frameId", "seconds", "integrity"]]
    series = series.assign(
        integrity=(series["area"] / peak * 100).clip(lower=0, upper=100)
    )
    return series[["frameId", "seconds", "integrity"]]
