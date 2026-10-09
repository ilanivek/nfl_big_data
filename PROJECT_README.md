# 🏈 Pocket Replay — Pass Protection Visualizer

A hackathon prototype that animates NFL tracking data to replay a single play,
showing the 22 players + ball moving frame by frame, the collapsing pass-protection
"pocket," and a live time-to-throw stat. Built for a coach / scout / broadcaster.

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

No data yet? Tick **"Use mock data"** in the sidebar to run against a synthetic
play. This lets everyone build immediately without the 825 MB download.

## Data

The `data/` folder (~825 MB) is **not** committed to git — it's too large for
GitHub and is excluded via `.gitignore`. Each teammate needs their own copy
placed at the project root:

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

## How the code is split (3 people, clean seams)

The one shared contract is the **play bundle** produced by `data_loader.get_play_bundle()`:

```python
bundle = {
    "frames": DataFrame[frameId, nflId, team, jerseyNumber, x, y, s, o, dir, event],
    "meta": {playDescription, snap_frame, throw_frame, playDirection, gameId, playId},
}
```

| File | Owner | Responsibility |
|------|-------|----------------|
| `data_loader.py` | Person A | Load CSVs, build dropdowns, produce the play bundle, `mock_bundle()` |
| `field.py` | Person B | Draw the field, animate players, play/pause + frame slider |
| `pocket.py` | Person C | Convex-hull pocket polygon, time-to-throw, pocket area |
| `app.py` | Person A | Streamlit shell that wires A + B + C together |

Persons B and C develop against `mock_bundle()` so nobody waits on the data loader.

## Git workflow

- `main` stays runnable at all times.
- Work on a branch: `git checkout -b person-b-field`
- Push + open a PR, quick review, merge to `main`.
- Pull often: `git checkout main && git pull`

## Next steps / TODO

- [ ] Person A: tag possession team in `meta` so field.py can color offense vs defense correctly
- [ ] Person B: color offense blue / defense red using possession info
- [ ] Person C: restrict the pocket hull to the 5 offensive linemen (join `pffScoutingData` on `pff_role == "Pass block"`)
- [ ] Stretch: draw blocker→rusher matchup lines from `pff_nflIdBlockedPlayer`
- [ ] Stretch: highlight the rusher who gets closest to the QB
