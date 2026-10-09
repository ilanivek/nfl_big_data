"""Real-data smoke test for Person A's play bundle.

Run AFTER placing the real `data/` folder in the project root:

    .venv/bin/python verify_real_data.py

Auto-picks a real pass play, builds the bundle, and asserts that every piece
Person B and Person C depend on actually populated from the real CSVs.
Read-only: it never writes anything.
"""

from __future__ import annotations

import os
import sys

import data_loader as dl


def ok(msg): print(f"  [OK] {msg}")
def bad(msg): print(f"  [!!] {msg}")


def main() -> int:
    if not os.path.isdir(dl.DATA_DIR):
        print(f"No data/ folder at {dl.DATA_DIR}")
        return 1

    print("=== reference tables ===")
    plays = dl.load_plays()
    pff = dl.load_pff_scouting()
    ok(f"plays.csv rows: {len(plays)}")
    ok(f"pffScoutingData.csv rows: {len(pff)}")

    # Pick a real pass play whose tracking file we actually have on disk.
    have_games = {
        int(fn.split("_")[1].split(".")[0])
        for fn in os.listdir(dl.TRACKING_DIR) if fn.startswith("tracking_")
    }
    cand = plays[plays["passResult"].notna() & plays["gameId"].isin(have_games)]
    if cand.empty:
        bad("no pass play with a local tracking file found")
        return 1
    row = cand.iloc[0]
    game_id, play_id = int(row["gameId"]), int(row["playId"])
    print(f"\n=== sample play: game {game_id}, play {play_id} ===")
    print(f'  "{str(row["playDescription"])[:90]}"')

    bundle = dl.get_play_bundle(game_id, play_id)
    frames, meta = bundle["frames"], bundle["meta"]

    print("\n=== frames ===")
    expected = ["frameId", "nflId", "team", "jerseyNumber",
                "x", "y", "s", "o", "dir", "event", "pff_role"]
    miss = [c for c in expected if c not in frames.columns]
    (ok if not miss else bad)(f"columns: {list(frames.columns)}")
    (ok if not frames.empty else bad)(f"rows: {len(frames)}, frames: {frames['frameId'].nunique()}")

    print("\n=== pff_role join (Person C) ===")
    roles = frames.drop_duplicates("nflId")["pff_role"].value_counts(dropna=False)
    print(roles.to_string())
    nblock = frames[frames["pff_role"] == "Pass Block"]["nflId"].nunique()
    (ok if nblock >= 3 else bad)(f"Pass Block players: {nblock} (expect ~5)")

    print("\n=== meta (Person B + captions) ===")
    for k in ("possessionTeam", "defensiveTeam", "passResult", "down",
              "yardsToGo", "quarter", "gameClock", "playDirection"):
        v = meta.get(k)
        (ok if v is not None else bad)(f"{k} = {v!r}")
    (ok if meta.get("possessionTeam") != meta.get("defensiveTeam")
        else bad)("possessionTeam != defensiveTeam")

    print("\n=== event detection ===")
    snap, throw = meta.get("snap_frame"), meta.get("throw_frame")
    (ok if snap is not None else bad)(f"snap_frame = {snap}")
    (ok if throw is not None else bad)(f"throw_frame = {throw}")
    if snap is not None and throw is not None:
        (ok if throw >= snap else bad)(f"throw {throw} after snap {snap}")

    teams = sorted(t for t in frames["team"].dropna().unique() if t != "football")
    print(f"\n  teams on field: {teams}")
    (ok if meta.get("possessionTeam") in teams
        else bad)("possessionTeam appears in tracking data")

    print("\nDone. Review any [!!] marks above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
