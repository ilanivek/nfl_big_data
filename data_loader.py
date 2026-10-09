"""Data layer (Person A).

Owns: loading the CSVs and producing the shared "play bundle" that every
other module consumes. The play bundle is the single contract between the
three pieces of the app:

    bundle = {
        "frames": DataFrame[frameId, nflId, team, jerseyNumber, x, y, s, o, dir, event],
        "meta": {
            "playDescription": str,
            "snap_frame": int | None,
            "throw_frame": int | None,
            "playDirection": "left" | "right",
            "gameId": int,
            "playId": int,
        },
    }

While Person A wires the real loaders, Persons B and C build against
`mock_bundle()` so nobody is blocked.
"""

from __future__ import annotations

import os
from functools import lru_cache

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TRACKING_DIR = os.path.join(DATA_DIR, "tracking")

# Events that mark the start/end of the protection window.
SNAP_EVENTS = {"ball_snap", "autoevent_ballsnap"}
THROW_EVENTS = {"pass_forward", "autoevent_passforward", "qb_sack", "run"}


# --------------------------------------------------------------------------
# Reference tables (small, safe to cache)
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_games() -> pd.DataFrame:
    """games.csv — one row per game."""
    return pd.read_csv(os.path.join(DATA_DIR, "games.csv"))


@lru_cache(maxsize=1)
def load_plays() -> pd.DataFrame:
    """plays.csv — one row per play."""
    return pd.read_csv(os.path.join(DATA_DIR, "plays.csv"))


@lru_cache(maxsize=1)
def load_pff_scouting() -> pd.DataFrame:
    """pffScoutingData.csv — one row per player per play (roles, block info)."""
    return pd.read_csv(os.path.join(DATA_DIR, "pffScoutingData.csv"))


@lru_cache(maxsize=16)
def load_tracking(game_id: int) -> pd.DataFrame:
    """tracking_[gameId].csv — one row per player per frame for a single game."""
    path = os.path.join(TRACKING_DIR, f"tracking_{game_id}.csv")
    return pd.read_csv(path)


# --------------------------------------------------------------------------
# Dropdown helpers for the app shell
# --------------------------------------------------------------------------
def game_options() -> pd.DataFrame:
    """Return games with a human-readable label for a selectbox."""
    games = load_games().copy()
    games["label"] = (
        games["gameId"].astype(str)
        + " — "
        + games["visitorTeamAbbr"]
        + " @ "
        + games["homeTeamAbbr"]
        + " (Wk "
        + games["week"].astype(str)
        + ")"
    )
    return games[["gameId", "label"]]


def play_options(game_id: int) -> pd.DataFrame:
    """Return plays for one game with a readable label for a selectbox."""
    plays = load_plays()
    g = plays[plays["gameId"] == game_id].copy()
    g["label"] = (
        "Q"
        + g["quarter"].astype(str)
        + " — "
        + g["playDescription"].str.slice(0, 80)
    )
    return g[["playId", "label", "playDescription"]]


# --------------------------------------------------------------------------
# THE CONTRACT: build a play bundle
# --------------------------------------------------------------------------
def _first_frame_for_events(frames: pd.DataFrame, events: set[str]) -> int | None:
    hit = frames[frames["event"].isin(events)]
    if hit.empty:
        return None
    return int(hit["frameId"].min())


def get_play_bundle(game_id: int, play_id: int) -> dict:
    """Produce the shared play bundle for one play. This is the hand-off."""
    tracking = load_tracking(game_id)
    frames = tracking[
        (tracking["gameId"] == game_id) & (tracking["playId"] == play_id)
    ].copy()

    # Attach each player's role on this play (Pass block / Pass / Pass rush /
    # Pass route / Coverage) so Person C can build the pocket hull from just the
    # pass blockers. Role is per-play, so it broadcasts across every frame.
    # The ball (nflId = NaN) won't match and gets a NaN role — expected.
    roles = load_pff_scouting()
    roles = roles[
        (roles["gameId"] == game_id) & (roles["playId"] == play_id)
    ][["nflId", "pff_role"]]
    frames = frames.merge(roles, on="nflId", how="left")

    keep = [
        "frameId", "nflId", "team", "jerseyNumber",
        "x", "y", "s", "o", "dir", "event", "pff_role",
    ]
    frames = frames[keep].sort_values(["frameId", "nflId"]).reset_index(drop=True)

    plays = load_plays()
    play_row = plays[(plays["gameId"] == game_id) & (plays["playId"] == play_id)]
    description = (
        play_row["playDescription"].iloc[0] if not play_row.empty else "(unknown play)"
    )
    play_direction = frames["playDirection"].iloc[0] if "playDirection" in frames else (
        tracking.loc[tracking["playId"] == play_id, "playDirection"].iloc[0]
    )

    def _play_field(col):
        """Safely pull a scalar play-level field; None if absent/missing."""
        if play_row.empty or col not in play_row:
            return None
        val = play_row[col].iloc[0]
        return None if pd.isna(val) else val

    return {
        "frames": frames,
        "meta": {
            "playDescription": description,
            "snap_frame": _first_frame_for_events(frames, SNAP_EVENTS),
            "throw_frame": _first_frame_for_events(frames, THROW_EVENTS),
            "playDirection": play_direction,
            "gameId": game_id,
            "playId": play_id,
            # Possession tagging (unblocks Person B: color offense vs defense).
            "possessionTeam": _play_field("possessionTeam"),
            "defensiveTeam": _play_field("defensiveTeam"),
            # Broadcaster caption / outcome fields.
            "passResult": _play_field("passResult"),
            "down": _play_field("down"),
            "yardsToGo": _play_field("yardsToGo"),
            "quarter": _play_field("quarter"),
            "gameClock": _play_field("gameClock"),
        },
    }


# --------------------------------------------------------------------------
# Mock bundle so B and C can start at minute 0 without the real data
# --------------------------------------------------------------------------
def mock_bundle() -> dict:
    """A tiny synthetic play: QB drops back, two rushers collapse a pocket."""
    import numpy as np

    n_frames = 40
    rows = []
    # 5 offensive linemen set up in a CUP (arc), not a straight line — this is
    # how a real O-line forms the pocket. The arc gives the convex hull real
    # 2D area so the pocket is visible and measurable.
    #   x = depth behind the line of scrimmage, y = across the field.
    # Tackles (ends) sit slightly deeper than the center (middle), bowing the
    # cup backward toward the QB.
    ol_start = [
        (41.0, 19.0),  # left tackle
        (41.8, 21.5),  # left guard
        (42.2, 24.0),  # center (shallowest, front of the cup)
        (41.8, 26.5),  # right guard
        (41.0, 29.0),  # right tackle
    ]
    # QB behind the line.
    qb_start = (38.0, 24.0)
    # 2 edge rushers starting wide, collapsing inward toward the QB.
    rush_start = [(44.0, 17.0), (44.0, 31.0)]

    for f in range(1, n_frames + 1):
        t = f / n_frames  # 0 -> 1 over the play

        # QB drifts straight back a little.
        rows.append(dict(frameId=f, nflId=1, team="OFF", jerseyNumber=12,
                         x=qb_start[0] - t * 1.5, y=qb_start[1], s=1.0, o=90, dir=270,
                         event="ball_snap" if f == 5 else ("pass_forward" if f == 32 else "None"),
                         pff_role="Pass"))

        # Linemen get pushed backward toward the QB AND squeezed inward in y,
        # so the cup both retreats and narrows — the pocket collapses.
        for i, (ox, oy) in enumerate(ol_start):
            squeeze = (oy - 24.0) * 0.35 * t   # pull each lineman toward center-y
            rows.append(dict(frameId=f, nflId=10 + i, team="OFF", jerseyNumber=70 + i,
                             x=ox - t * 2.5, y=oy - squeeze,
                             s=0.8, o=90, dir=270, event="None",
                             pff_role="Pass block"))

        # Edge rushers loop in toward the QB from both sides.
        for j, (rx, ry) in enumerate(rush_start):
            rows.append(dict(frameId=f, nflId=20 + j, team="DEF", jerseyNumber=90 + j,
                             x=rx - t * 4.0, y=ry + (24.0 - ry) * t * 0.7,
                             s=2.0, o=270, dir=90, event="None",
                             pff_role="Pass rush"))

        # Ball tracks with the QB (no role — not a player).
        rows.append(dict(frameId=f, nflId=np.nan, team="football", jerseyNumber=np.nan,
                         x=qb_start[0] - t * 1.5, y=qb_start[1], s=0.0, o=0, dir=0, event="None",
                         pff_role=np.nan))

    frames = pd.DataFrame(rows)
    return {
        "frames": frames,
        "meta": {
            "playDescription": "MOCK: QB dropback, pocket collapses from both edges.",
            "snap_frame": 5,
            "throw_frame": 32,
            "playDirection": "left",
            "gameId": 0,
            "playId": 0,
            # Mock uses OFF/DEF team tags; mirror them here so B's offense/defense
            # coloring keys on the same values in mock and real mode.
            "possessionTeam": "OFF",
            "defensiveTeam": "DEF",
            "passResult": "S",   # ends in a sack — the pocket collapsed
            "down": 3,
            "yardsToGo": 7,
            "quarter": 2,
            "gameClock": "02:00",
        },
    }


if __name__ == "__main__":
    b = mock_bundle()
    print(b["meta"])
    print(b["frames"].head())
