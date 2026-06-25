# NRL Bet Bot V2

A data-driven NRL prediction system: an Elo-based win/margin model, an 8-component xTry try-scoring model, and real bookmaker odds comparison, combined into a weekly automated email digest.

This is V2 — it replaces an earlier system after a full data-integrity audit found and fixed several silent bugs. See `PROJECT_BRIEF.md` for the full history.

## Read first, every session

- **`STATUS.md`** — live checkpoint: what data is current, what's outstanding, last update date, and a real, dated log of bugs found and fixed. Always check this before trusting any file's freshness.
- **`PROJECT_BRIEF.md`** — full project history, data dictionary, and roadmap.

## Repo structure

```
nrl-bet-bot-v2/
├── data/
│   ├── nrl_master.csv                          # 2026 season, player-level, current through latest round
│   ├── match_data_FINAL_fixed.csv              # Match results 2021–2026 (scores, venue, weather, attendance)
│   ├── historical_player_match_rows.csv        # 2021–2025, player-level (no names — player_id only)
│   ├── historical_position_tpg_baseline.csv    # League-avg tries-per-game by position/season
│   ├── historical_zcr_baseline.csv             # Tries conceded by team/position (zone concede rate)
│   ├── season_draw_2026.json                   # Fixture pairings by round — auto-extended weekly
│   ├── team_aliases.json                       # Canonical team name mapping — always use this
│   ├── position_aliases.json                   # Canonical position code mapping — always use this
│   ├── team_lists_current.csv                  # Most recent real team-list scrape (Tuesday baseline + near-kickoff updates)
│   └── predictions_current.json / .csv         # Latest generated predictions
├── scripts/
│   ├── nrl_update_single_round.py              # Player-stats scraper (Job A)
│   ├── scrape_match_results.py                 # Match-results scraper (Job A) — scores, venue, weather, attendance
│   ├── merge_match_results_backfill.py         # Validates + merges match results into match_data_FINAL_fixed.csv
│   ├── validate_round.py / merge_round.py      # Validation gate + safe merge for player stats
│   ├── scrape_team_lists.py / parse_team_list.py / find_team_list_url.py / parse_draw_link_text.py
│   │                                            # Job B — team-list scraping (Tuesday baseline + near-kickoff)
│   ├── schedule_kickoff_triggers.py            # Creates precise per-match cron-job.org triggers, idempotent
│   ├── extend_season_draw.py                   # Extends season_draw_2026.json with upcoming fixtures
│   ├── nrl_elo.py                              # Elo rating system — win probability, predicted margin
│   ├── xtry_model.py                           # 8-component xTry try-scoring probability model
│   ├── odds_fetcher.py                         # Live odds via the-odds-api.com
│   ├── edge_finder.py                          # Connects xTry output to bookmaker odds, finds value
│   ├── due_flags_v2.py                         # Composite DUE WATCH scoring
│   ├── generate_predictions.py                 # Round-level orchestration — the main predictions pipeline
│   └── send_predictions_digest.py              # Builds and sends the weekly email digest
├── .github/workflows/
│   ├── weekly-update.yml                       # Job A — player stats + match results + season-draw extension
│   ├── team-list-polling.yml                   # Job B — Tuesday baseline + near-kickoff team-list scrape
│   ├── schedule-kickoffs.yml                   # Creates this week's precise cron-job.org triggers
│   └── generate-predictions.yml                # Weekly predictions run + email
├── STATUS.md
├── PROJECT_BRIEF.md
└── README.md
```

## Canonical standards (locked in)

- **Team names**: full names only (e.g. "New Zealand Warriors", not "Warriors"). Mapping in `data/team_aliases.json`.
- **Positions**: codes only — FB, WG, CE, FE, HB, HK, PR, 2RF, LK, IC. Mapping in `data/position_aliases.json`.

Never hardcode team names or positions in scripts — always resolve through these two files.

## Current workflow — fully automated

**Weekly, no manual steps in the normal case:**
1. **Tuesday ~4:10pm AEST**: Job B scrapes that round's just-announced team lists.
2. **Thursday morning**: Job A scrapes the just-finished round's player stats and match results, validates both, merges on a clean pass.
3. **~3 hours later**: predictions generate from the now-current data, run a content-based sanity check, and send the weekly email.
4. **Throughout the week**: cron-job.org fires a precise trigger 1 hour before each match's kickoff, re-checking team lists for any late changes.

**A GitHub Issue is opened automatically** if any validation step fails — the relevant data file is left untouched, never partially or silently merged.

**Manual intervention only needed**: if a GitHub Issue appears, or for a one-off backfill/extension outside the normal weekly cadence.

## Known limitations

- Individual player history before 2026 can't be reconstructed — `historical_player_match_rows.csv` has no player names, only an opaque `player_id`.
- DUE WATCH has no concept of a player returning from a long injury/suspension layoff — their pre-absence games can still count as "recent form" once they're back.
- `season_draw_2026.json`'s auto-extension keeps a 2-round buffer; `merge_match_results_backfill.py`'s bye-schedule safety net needs manual extending round-by-round.
- The Tuesday team-list baseline scrape uses a fixed UTC cron time tuned for AEST — will drift an hour around daylight-saving changes (early April / October).

## Roadmap

See `PROJECT_BRIEF.md` for the full phased roadmap. Phases 0–8 are built and live; Phase 9 (GitHub Pages dashboard) is not yet started.
