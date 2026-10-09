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

    keep = [
        "frameId", "nflId", "team", "jerseyNumber",
        "x", "y", "s", "o", "dir", "event",
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

    return {
        "frames": frames,
        "meta": {
            "playDescription": description,
            "snap_frame": _first_frame_for_events(frames, SNAP_EVENTS),
            "throw_frame": _first_frame_for_events(frames, THROW_EVENTS),
            "playDirection": play_direction,
            "gameId": game_id,
            "playId": play_id,
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
    # 5 offensive linemen in a rough arc, drifting slightly back.
    ol_start = [(40, 20), (40, 22), (40, 24), (40, 26), (40, 28)]
    # QB behind the line.
    qb_start = (37, 24)
    # 2 rushers closing in.
    rush_start = [(42, 21), (42, 27)]

    for f in range(1, n_frames + 1):
        t = f / n_frames
        # QB drifts back a touch.
        rows.append(dict(frameId=f, nflId=1, team="OFF", jerseyNumber=12,
                         x=qb_start[0] - t * 2, y=qb_start[1], s=1.0, o=90, dir=270,
                         event="ball_snap" if f == 5 else ("pass_forward" if f == 32 else "None")))
        for i, (ox, oy) in enumerate(ol_start):
            rows.append(dict(frameId=f, nflId=10 + i, team="OFF", jerseyNumber=70 + i,
                             x=ox - t * 1.0, y=oy, s=0.8, o=90, dir=270, event="None"))
        for j, (rx, ry) in enumerate(rush_start):
            # rushers converge toward the QB
            rows.append(dict(frameId=f, nflId=20 + j, team="DEF", jerseyNumber=90 + j,
                             x=rx - t * 3.0, y=ry + (24 - ry) * t * 0.6,
                             s=2.0, o=270, dir=90, event="None"))
        # ball tracks with QB
        rows.append(dict(frameId=f, nflId=np.nan, team="football", jerseyNumber=np.nan,
                         x=qb_start[0] - t * 2, y=qb_start[1], s=0.0, o=0, dir=0, event="None"))

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
        },
    }


if __name__ == "__main__":
    b = mock_bundle()
    print(b["meta"])
    print(b["frames"].head())
