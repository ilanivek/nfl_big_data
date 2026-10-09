"""Streamlit app shell (Person A owns; integrates B and C).

Run with:
    streamlit run app.py

Toggle "Use mock data" in the sidebar to develop without the CSVs present.
"""

from __future__ import annotations

import streamlit as st

import data_loader as dl
import field
import pocket

st.set_page_config(page_title="NFL Pocket Replay", layout="wide")
st.title("🏈 Pocket Replay — Pass Protection Visualizer")

# --------------------------------------------------------------------------
# Sidebar: data source + play selection
# --------------------------------------------------------------------------
use_mock = st.sidebar.checkbox("Use mock data (no CSVs needed)", value=False)

bundle = None
if use_mock:
    bundle = dl.mock_bundle()
    st.sidebar.info("Showing synthetic play. Uncheck to use real data.")
else:
    try:
        games = dl.game_options()
        game_label = st.sidebar.selectbox("Game", games["label"])
        game_id = int(games.loc[games["label"] == game_label, "gameId"].iloc[0])

        plays = dl.play_options(game_id)
        play_label = st.sidebar.selectbox("Play", plays["label"])
        play_id = int(plays.loc[plays["label"] == play_label, "playId"].iloc[0])

        bundle = dl.get_play_bundle(game_id, play_id)
    except FileNotFoundError:
        st.error(
            "Data files not found. Place the `data/` folder in the project root, "
            "or tick 'Use mock data' in the sidebar."
        )
        st.stop()

# --------------------------------------------------------------------------
# Header stats (Person C)
# --------------------------------------------------------------------------
meta = bundle["meta"]
st.caption(meta["playDescription"])

# Situation line: "TB ball — 3rd & 7, Q2 02:00" (skips any missing pieces).
PASS_RESULT_LABELS = {
    "C": "Complete", "I": "Incomplete", "S": "Sack",
    "IN": "Interception", "R": "Scramble",
}


def _ordinal(n):
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(n, f"{n}th")


situation_bits = []
if meta.get("possessionTeam"):
    situation_bits.append(f"{meta['possessionTeam']} ball")
if meta.get("down") and meta.get("yardsToGo") is not None:
    situation_bits.append(f"{_ordinal(int(meta['down']))} & {int(meta['yardsToGo'])}")
if meta.get("quarter"):
    clock = f" {meta['gameClock']}" if meta.get("gameClock") else ""
    situation_bits.append(f"Q{int(meta['quarter'])}{clock}")
if situation_bits:
    st.markdown(" — ".join(situation_bits))

col1, col2, col3, col4 = st.columns(4)
ttt = pocket.time_to_throw(meta)
col1.metric("Time to throw", f"{ttt:.1f}s" if ttt is not None else "—")
outcome = PASS_RESULT_LABELS.get(meta.get("passResult"), meta.get("passResult") or "—")
col2.metric("Outcome", outcome)
col3.metric("Snap frame", meta.get("snap_frame") or "—")
col4.metric("Throw frame", meta.get("throw_frame") or "—")

# --------------------------------------------------------------------------
# The replay (Person B figure + Person C pocket overlay)
# --------------------------------------------------------------------------
show_pocket = st.sidebar.checkbox("Show pocket", value=True)
fig = field.build_field_figure(
    bundle, pocket_fn=pocket.pocket_shape if show_pocket else None
)
st.plotly_chart(fig, use_container_width=True)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Team ownership**\n\n"
    "- `data_loader.py` — Person A\n"
    "- `field.py` — Person B\n"
    "- `pocket.py` — Person C"
)
