# NRL Bet Bot V2

A data-driven NRL prediction system (xTry model: win probability, margin, try-scorer odds) built on validated, audited data.

This is V2 — it replaces an earlier system after a full data-integrity audit found and fixed several silent bugs (inconsistent team/position naming across files, a join-key mismatch between historical files, a round-numbering bug affecting all of 2026, and more). See `PROJECT_BRIEF.md` for the full history of what was found and fixed.

## Read first, every session

- **`STATUS.md`** — live checkpoint: what data is current, what's outstanding, last update date. Always check this before trusting any file's freshness.
- **`PROJECT_BRIEF.md`** — full project history, data dictionary, workflow, and roadmap.

## Repo structure

```
nrl-bet-bot-v2/
├── data/
│   ├── nrl_master.csv                          # 2026 season, player-level, current through latest round
│   ├── historical_player_match_rows.csv        # 2021–2025, player-level (no names — player_id only)
│   ├── historical_position_tpg_baseline.csv    # League-avg tries-per-game by position/season
│   ├── historical_zcr_baseline.csv             # Tries conceded by team/position (zone concede rate)
│   ├── match_data_FINAL_fixed.csv              # Match results 2021–2026, round numbers corrected
│   ├── team_aliases.json                       # Canonical team name mapping — always use this
│   └── position_aliases.json                   # Canonical position code mapping — always use this
├── scripts/
│   └── nrl_update_single_round.py              # Scraper — scrapes ONE round at a time
├── STATUS.md
├── PROJECT_BRIEF.md
└── README.md
```

## Canonical standards (locked in)

- **Team names**: full names only (e.g. "New Zealand Warriors", not "Warriors"). Mapping in `data/team_aliases.json`.
- **Positions**: codes only — FB, WG, CE, FE, HB, HK, PR, 2RF, LK, IC. Mapping in `data/position_aliases.json`.

Never hardcode team names or positions in scripts — always resolve through these two files.

## Current workflow (manual — Phase 3 will automate this)

1. Edit `ROUND_TO_SCRAPE` in `scripts/nrl_update_single_round.py` to the new round number.
2. Run it locally — produces a separate `nrl_round_X_new.csv`. It does **not** touch `data/nrl_master.csv` directly.
3. Upload that file + console output for validation.
4. Only after validation passes (zero duplicates, bye-schedule coverage matches the official draw, internal consistency checks) does it get merged into `data/nrl_master.csv`, and `STATUS.md` gets updated.

## Known limitations

- Individual player history before 2026 can't be reconstructed — `historical_player_match_rows.csv` has no player names, only an opaque `player_id`.
- `try_minute` data isn't captured by the scraper yet — still relies on manual screenshots.
- No automation yet — every update is run manually and uploaded for validation.

## Roadmap

See `PROJECT_BRIEF.md` for the full phased roadmap (Phase 0 data integrity → Phase 10 odds comparison). Currently at the end of **Phase 2** (this repo).
