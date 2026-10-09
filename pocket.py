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


# Role values (lowercased) for the QB and the pass rushers — the two sides of
# the "how close is pressure" question.
QB_ROLES = {"pass"}
RUSHER_ROLES = {"pass rush"}


def _players_by_role(frame_df: pd.DataFrame, wanted: set[str]) -> pd.DataFrame:
    """Rows for one frame whose (lowercased) role is in `wanted`. Excludes ball."""
    role_col = _role_column(frame_df)
    if role_col is None:
        return frame_df.iloc[0:0]
    non_ball = frame_df[(frame_df["team"] != "football") & frame_df["team"].notna()]
    role_norm = non_ball[role_col].astype(str).str.strip().str.lower()
    return non_ball[role_norm.isin(wanted)]


def qb_position(frame_df: pd.DataFrame):
    """(x, y) of the QB this frame, or None if not identifiable."""
    qb = _players_by_role(frame_df, QB_ROLES)
    if qb.empty:
        return None
    row = qb.iloc[0]
    return float(row["x"]), float(row["y"])


def nearest_rusher_distance(frame_df: pd.DataFrame) -> float | None:
    """Distance (yards) from the QB to the closest pass rusher this frame.

    This is the real signal for pocket integrity: a big number means the QB is
    protected; a small number means a rusher is bearing down. Returns None if
    the QB or rushers can't be identified (e.g. mock without rusher roles).
    """
    qb = qb_position(frame_df)
    rushers = _players_by_role(frame_df, RUSHER_ROLES)[["x", "y"]].dropna()
    if qb is None or rushers.empty:
        return None
    qx, qy = qb
    d = ((rushers["x"] - qx) ** 2 + (rushers["y"] - qy) ** 2) ** 0.5
    return float(d.min())


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


def pressure_moment(bundle: dict, threshold: float | None = None) -> dict | None:
    """First frame where a rusher gets within `threshold` yards of the QB.

    This is the moment pressure arrives. Returns a dict with
    frameId/seconds/distance, or None if the QB is never pressured that close.
    Defaults `threshold` to PRESSURE_RADIUS when not given.
    """
    if threshold is None:
        threshold = PRESSURE_RADIUS
    series = _post_snap_distance(bundle)
    breached = series[series["distance"] < threshold]
    if breached.empty:
        return None
    row = breached.iloc[0]
    return {"frameId": int(row["frameId"]), "seconds": row["seconds"],
            "distance": round(float(row["distance"]), 1)}


# --------------------------------------------------------------------------
# Pocket Integrity Score — the headline metric
# --------------------------------------------------------------------------
# A single 0-100 grade for how well the offensive line kept pass rushers away
# from the QB. The signal is QB-to-nearest-rusher distance each frame — a
# direct, physically meaningful measure of pressure (unlike raw pocket area,
# which mostly reflects how spread out the linemen are). Three components:
#   1. TIME CLEAN   (40%) — how long before the first rusher breaches the
#                   pressure radius. Longer clean = better protection.
#   2. SEPARATION   (35%) — average QB-to-nearest-rusher distance over the
#                   play. More cushion = better.
#   3. WORST CASE   (25%) — the closest any rusher got (minimum distance).
#                   A rusher in the QB's lap is bad even if only briefly.
# A play-outcome multiplier then caps plays that ended in a sack/pressure,
# since protection that fails is a failure regardless of the geometry.

SCORE_WEIGHTS = {"time": 0.40, "separation": 0.35, "worst": 0.25}

# Distance thresholds (yards).
PRESSURE_RADIUS = 2.0       # a rusher within this is "pressuring" the QB
IDEAL_SEPARATION = 4.0      # avg separation that earns full marks
IDEAL_TIME_CLEAN = 2.5      # seconds clean that earns full marks

# Outcome multiplier applied to the blended score. Protection that ends in a
# sack failed by definition, no matter the geometry, so we cap it hard.
#   S = sack, IN = interception, I = incomplete, C = complete, R = scramble.
OUTCOME_MULTIPLIER = {
    "S": 0.35,   # sack — protection broke down
    "IN": 0.80,  # interception — not purely an OL failure
    "I": 0.95,   # incomplete — mostly on the throw, not protection
    "C": 1.00,   # complete — protection did its job
    "R": 0.90,   # scramble — QB had to leave a breaking pocket
}


def rusher_distance_series(bundle: dict) -> pd.DataFrame:
    """QB-to-nearest-rusher distance at every frame.

    Columns: [frameId, seconds, distance]. `distance` is NaN on frames where
    the QB or rushers can't be identified.
    """
    frames = bundle["frames"]
    snap = bundle["meta"].get("snap_frame")
    rows = []
    for fid in sorted(frames["frameId"].unique()):
        fdf = frames[frames["frameId"] == fid]
        secs = (fid - snap) / FRAMES_PER_SECOND if snap is not None else None
        rows.append({"frameId": int(fid), "seconds": secs,
                     "distance": nearest_rusher_distance(fdf)})
    return pd.DataFrame(rows)


def _post_snap_distance(bundle: dict) -> pd.DataFrame:
    """Rusher-distance series restricted to snap..throw (the window that matters)."""
    series = rusher_distance_series(bundle)
    meta = bundle["meta"]
    snap, throw = meta.get("snap_frame"), meta.get("throw_frame")
    if snap is not None:
        series = series[series["frameId"] >= snap]
    if throw is not None:
        series = series[series["frameId"] <= throw]
    return series.dropna(subset=["distance"]).reset_index(drop=True)


def pocket_integrity_score(bundle: dict) -> dict:
    """Compute the 0-100 Pocket Integrity Score from QB-to-rusher distance.

    Returns the overall `score`, the three component sub-scores (0-100), and
    the raw numbers behind them so the UI can explain the grade.
    """
    series = _post_snap_distance(bundle)
    if series.empty:
        return {
            "score": None,
            "components": {"time": None, "separation": None, "worst": None},
            "detail": {"reason": "QB/rusher positions not available for this play"},
        }

    distances = series["distance"]
    avg_sep = float(distances.mean())
    min_sep = float(distances.min())

    # 1. Time clean: seconds before the first pressure-radius breach.
    breaches = series[series["distance"] < PRESSURE_RADIUS]
    if breaches.empty:
        time_clean = float(series["seconds"].iloc[-1])  # never breached
    else:
        time_clean = float(breaches["seconds"].iloc[0])
    time_component = max(0.0, min(time_clean / IDEAL_TIME_CLEAN, 1.0))

    # 2. Separation: average cushion vs. the ideal.
    separation_component = max(0.0, min(avg_sep / IDEAL_SEPARATION, 1.0))

    # 3. Worst case: closest approach vs. the pressure radius. At/under the
    #    radius scores 0; at/over the ideal separation scores 1.
    span = IDEAL_SEPARATION - PRESSURE_RADIUS
    worst_component = max(0.0, min((min_sep - PRESSURE_RADIUS) / span, 1.0))

    components01 = {
        "time": time_component,
        "separation": separation_component,
        "worst": worst_component,
    }
    blended = sum(SCORE_WEIGHTS[k] * v for k, v in components01.items())

    outcome = bundle["meta"].get("passResult")
    mult = OUTCOME_MULTIPLIER.get(outcome, 1.0)
    overall = blended * mult

    return {
        "score": round(overall * 100, 1),
        "components": {k: round(v * 100, 1) for k, v in components01.items()},
        "detail": {
            "time_clean_s": round(time_clean, 1),
            "avg_separation_yd": round(avg_sep, 1),
            "closest_approach_yd": round(min_sep, 1),
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


# Distance that maps to "fully clear" (100) on the live integrity gauge.
CLEAR_DISTANCE = 6.0


def integrity_trace(bundle: dict) -> pd.DataFrame:
    """Per-frame 'live' pocket integrity (0-100), for a running gauge.

    Integrity = QB-to-nearest-rusher distance mapped onto 0-100: at or below the
    pressure radius reads 0 (rusher on the QB), at or above CLEAR_DISTANCE reads
    100 (QB clean). Starts high and falls as a rusher closes in — the physically
    correct direction. Columns: [frameId, seconds, integrity].
    """
    series = rusher_distance_series(bundle)
    span = CLEAR_DISTANCE - PRESSURE_RADIUS
    series = series.assign(
        integrity=((series["distance"] - PRESSURE_RADIUS) / span * 100).clip(
            lower=0, upper=100
        )
    )
    # Short rolling median to tame single-frame tracking jitter.
    series["integrity"] = (
        series["integrity"].rolling(window=3, center=True, min_periods=1).median()
    )
    return series[["frameId", "seconds", "integrity"]]
