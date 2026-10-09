# 🏈 Pocket Replay — Pass Protection Visualizer

An interactive tool that turns raw NFL player-tracking data into a readable story
about **pass protection**: how well the offensive line kept rushers away from the
quarterback on a given play. Built for a coach, scout, or broadcaster — someone who
wants to *see* what happened and *measure* how good the protection was, not read a
spreadsheet.

Pick a game and a play, and the app replays all 22 players and the ball frame by
frame on the field, overlays the live pressure on the quarterback, and grades the
protection with a single headline score.

## What we built

**1. A play replay.** The 22 players + ball animate across the field at 10 frames
per second (the native tracking rate), with play/pause and a scrubber. The timeline
is labeled by seconds since the snap and marks the key moments (**SNAP**, **THROW/
SACK**), so you can jump straight to the decisive instant.

**2. A live "pressure line."** A line drawn from the quarterback to the nearest pass
rusher every frame, colored **green when the QB is clean → red when a rusher is in
his lap**, with a running distance label. This is the visual heart of the tool: you
watch protection hold, then break.

**3. The offensive-line "pocket."** A faint shaded polygon (the convex hull of the
five pass blockers) showing the shape of the line as it moves — the classic "pocket."

**4. The Pocket Integrity Score.** A single 0–100 grade (with a letter grade) that
summarizes how well the line protected the QB on the play, broken into the
components that drove it. This is the headline metric a scout can rank linemen by.

Everything runs in a Streamlit web app; no data is shown until you pick a real play.

## The metrics (and why they're in here)

### Pocket Integrity Score (0–100)
A single grade for pass protection on a play. We deliberately built it on the
**distance from the QB to the nearest pass rusher**, measured every frame — a direct,
physical measure of pressure. (We first tried using the *area* of the offensive-line
pocket, but learned that area mostly reflects how spread out the linemen are, not how
threatened the QB is — it can even grow as a play falls apart. Rusher distance is the
honest signal.) The score blends three components:

| Component | Weight | What it measures | Why it matters |
|-----------|--------|------------------|----------------|
| **Time clean** | 40% | Seconds before the first rusher gets within the pressure radius (2 yd) | The longer the QB stays unthreatened, the better the protection. |
| **Average separation** | 35% | Mean QB-to-nearest-rusher distance over the play | Rewards consistent cushion, not just a clean start. |
| **Worst case** | 25% | The single closest a rusher got all play | A rusher in the QB's lap is bad even if only for a moment. |

A **play-outcome multiplier** is then applied: a play that ended in a **sack** is a
protection failure by definition, so its score is capped hard regardless of the
geometry (a hit/hurry is a partial penalty; a clean completion keeps full credit).
This keeps the score honest — it can't call a play "great protection" when the QB
hit the turf.

*Validated on real plays: a Dak Prescott sack grades F (nearest rusher got to 0.6 yd);
a clean completion grades B.*

### Time to throw
Seconds between the ball snap and the throw (or sack). The most fundamental number in
pass protection — how long the line bought the quarterback. Shown as a headline stat
and used inside the integrity score.

### Live pocket integrity (over time)
A per-frame 0–100 trace of the same pressure signal, charted against time since the
snap. It starts high and falls as a rusher closes in — the "EKG" of the play. Lets a
coach see *when* protection broke, not just *that* it did.

### Pressure moment
The exact instant the first rusher breaches the pressure radius (2 yd of the QB).
Pinpoints when the play turned.

> **Honest caveats** (worth stating in a demo): the thresholds (2 yd pressure radius,
> 4 yd ideal separation, 2.5 s ideal time) are tunable defaults, not league truth; and
> the pressure signal is raw QB-to-rusher distance — it doesn't account for a blocker
> standing in between. Both are reasonable prototype simplifications.

## Quick start

```bash
# 1. Clone
git clone https://github.com/ilanivek/nfl_big_data.git
cd nfl_big_data

# 2. Add the data (NOT in git — see "Data" below)
#    Put the dataset's `data/` folder in the project root.

# 3. Install
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 4. Run
streamlit run app.py
```

No data yet? Tick **"Use mock data"** in the sidebar to run against a synthetic play.
Note the metrics only tell a real story on real plays — the mock is for wiring/dev.

## Data

The `data/` folder (~825 MB) is **not** committed to git — too large for GitHub, and
excluded via `.gitignore`. Each teammate needs their own copy at the project root:

```
nfl_big_data/
├── data/
│   ├── games.csv
│   ├── plays.csv
│   ├── players.csv
│   ├── pffScoutingData.csv
│   └── tracking/
│       └── tracking_*.csv
├── app.py
├── data_loader.py
├── field.py
├── pocket.py
└── requirements.txt
```

Get the data from the shared Drive/zip link, or the original Kaggle dataset.

## How the code is organized

The one shared contract is the **play bundle** produced by
`data_loader.get_play_bundle(gameId, playId)`: a per-frame table of player positions
plus play-level `meta` (snap/throw frames, possession team, outcome). Each player row
carries its `pff_role` so the pocket and pressure logic can tell blockers, rushers,
and the QB apart.

| File | Responsibility |
|------|----------------|
| `data_loader.py` | Load CSVs, build the game/play pickers, join roles, produce the play bundle (+ a mock for offline dev) |
| `field.py` | Draw the field, animate players, play/pause + scrubber, draw the pressure line and pocket overlays |
| `pocket.py` | The metrics: Pocket Integrity Score, time-to-throw, rusher distance, pressure line geometry, live integrity trace |
| `app.py` | The Streamlit UI that wires it all together |

## Possible next steps

- Blocker → rusher **matchup lines** (`pff_nflIdBlockedPlayer`) to show *who* lost each rep
- Aggregate scores into an **offensive-line report card** across many plays
- Calibrate the score thresholds against league-wide pressure rates
