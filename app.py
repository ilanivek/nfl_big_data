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

# --- Pocket Integrity Score: the headline metric (Person C) ---------------
pis = pocket.pocket_integrity_score(bundle)
if pis["score"] is not None:
    comp = pis["components"]
    det = pis["detail"]
    grade = det["grade"]
    grade_color = {"A": "#2e7d32", "B": "#689f38", "C": "#f9a825",
                   "D": "#ef6c00", "F": "#c62828"}.get(grade, "#555")
    sc1, sc2 = st.columns([1, 2])
    with sc1:
        st.markdown(
            f"<div style='text-align:center'>"
            f"<div style='font-size:0.9rem;color:#666'>POCKET INTEGRITY</div>"
            f"<div style='font-size:3.5rem;font-weight:700;line-height:1;"
            f"color:{grade_color}'>{pis['score']:.0f}</div>"
            f"<div style='font-size:1.2rem;color:{grade_color}'>Grade {grade}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with sc2:
        st.markdown("**What drove the score** (based on QB-to-rusher distance)")
        st.progress(min(comp["time"] / 100, 1.0),
                    text=f"Time kept clean — {comp['time']:.0f}/100  ({det.get('time_clean_s')}s)")
        st.progress(min(comp["separation"] / 100, 1.0),
                    text=f"Avg separation — {comp['separation']:.0f}/100  ({det.get('avg_separation_yd')} yd)")
        st.progress(min(comp["worst"] / 100, 1.0),
                    text=f"Worst-case approach — {comp['worst']:.0f}/100  (closest {det.get('closest_approach_yd')} yd)")
        if det.get("outcome_multiplier", 1.0) < 1.0:
            st.caption(
                f"Outcome ({PASS_RESULT_LABELS.get(det.get('outcome'), det.get('outcome'))}) "
                f"applied a ×{det['outcome_multiplier']:.2f} adjustment — "
                f"protection that ends badly can't grade as clean."
            )
    st.markdown("")

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

# --- Live pocket integrity over the play (Person C) -----------------------
with st.expander("📉 Pocket integrity over the play", expanded=True):
    import plotly.express as px

    trace = pocket.integrity_trace(bundle)
    if trace["seconds"].notna().any():
        post = trace[trace["seconds"] >= 0]
        # Only chart up to the throw/sack — after that players scatter and the
        # "pocket" is meaningless, so showing it would misleadingly recover.
        if ttt is not None:
            post = post[post["seconds"] <= ttt]
    else:
        post = trace
    if not post.empty:
        line = px.line(post, x="seconds", y="integrity",
                       labels={"seconds": "Seconds since snap",
                               "integrity": "Pocket integrity (%)"})
        line.update_traces(line=dict(width=3, color="#1f77b4"))
        line.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10),
                           yaxis=dict(range=[0, 105]))
        # Mark the throw/sack moment.
        if ttt is not None:
            line.add_vline(x=ttt, line_dash="dash", line_color="red",
                           annotation_text="throw/sack")
        st.plotly_chart(line, use_container_width=True)
    else:
        st.caption("Integrity trace unavailable for this play.")

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Team ownership**\n\n"
    "- `data_loader.py` — Person A\n"
    "- `field.py` — Person B\n"
    "- `pocket.py` — Person C"
)
