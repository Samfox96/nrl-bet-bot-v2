# NRL V2 SYSTEM STATUS
_This file is the single source of truth for "is the data trustworthy right now." Read this first, every session._

---

## Last Updated
**2026-06-22** — Round 16 merged in (single-round scrape workflow)

## Current Data Coverage

| File | Rows | Coverage | Status |
|------|------|----------|--------|
| `nrl_master.csv` | 4,560 | 2026, Rounds 1–16 | ✅ CURRENT |
| `historical_player_match_rows.csv` | 28,935 | 2021–2025, all rounds | ✅ Clean, team/position-level only |
| `historical_position_tpg_baseline.csv` | — | 2021–2025 by position/season | ✅ Built |
| `historical_zcr_baseline.csv` | — | 2021–2025 by team/position | ✅ Built |
| `match_data_FINAL_fixed.csv` | 1,121 | 2021–2026 | ✅ Round-numbering bug fixed |
| `team_aliases.json` | — | All 17 teams | ✅ Canonical standard locked |
| `position_aliases.json` | — | All positions | ✅ Canonical standard locked |

## Round 16 Validation Summary (2026-06-22)
- Scraped via `nrl_update_single_round.py` (new single-round workflow — scrapes only the target round, saves to a separate file for review before merging, never touches `nrl_master.csv` directly)
- 266 rows, 0 duplicates
- Team coverage: 14/17, correctly missing Broncos/Eels/Rabbitohs (R16 byes per official draw)
- Internal consistency checks passed: try distribution sensible (Storm 8 highest, no outliers), minutes played correctly clustered around 80:00
- Bulldogs vs Sea Eagles correctly shows 83:00 minutes for full-game players — golden point game, not a data error
- Merged into `nrl_master.csv` cleanly: 4,294 → 4,560 rows, 0 dedup conflicts (confirms no prior R16 data existed)

## NEW WORKFLOW: Single-Round Scraping
As of 2026-06-22, the weekly update process changed from "rescrape everything" to "scrape just the new round":
1. Edit `ROUND_TO_SCRAPE = X` in `nrl_update_single_round.py`
2. Run it — produces `nrl_round_X_new.csv`, does NOT touch `nrl_master.csv`
3. Upload that file + console output to Claude for validation
4. Claude merges into `nrl_master.csv` after validation passes
This is faster and lower-risk than full rescrapes — existing rounds are never re-touched.

## Known Issues Fixed (Phase 0, prior sessions)
1. Three inconsistent team-naming schemes → unified via `team_aliases.json`
2. Three inconsistent position-coding schemes → unified via `position_aliases.json`
3. `match_id` join key issue between historical files → resolved via score-fingerprint matching (852/860, 99%)
4. 8 matches excluded from historical join (incomplete scrape, zero player-points)
5. `match_data_FINAL.csv` had a +1 round-numbering bug for all of 2026 from Round 2 onward — fixed and verified
6. `player_data_FINAL.csv` has no player names (opaque `player_id` only) — retained for team/position-level baselines only
7. Erroneous R13 `dolphins-v-rabbitohs` fallback URL removed (both teams were on bye, fixture never existed)

## Outstanding Gaps
- [ ] No scraper running automatically yet — still manual (you run it, paste results)
- [ ] `try_minute` column not yet present — still arriving via weekly scorecard screenshots only
- [ ] No GitHub repo/Actions workflow created yet (Phase 2-3)
- [ ] Recency-weighted position TPG baseline calculated but not yet wired into the live model (Phase 7)
- [ ] No team lists received yet for Round 17 predictions

## Validation Checks Run Every Update
- Row count sanity check (expected range per round, bye-adjusted)
- Zero unmapped team names / positions
- Zero duplicate (player, team, round, season) rows
- Round numbers match expected NRL draw sequence
- Internal consistency: try distribution, minutes played, position spread per team
- Cross-check against known results where available (golden point games, blowout scores, etc.)

## Failsafe Rule
**Nothing gets marked "data_complete: true" in `nrl_master.csv` until both the scrape AND validation against known results have passed.** Partial or unverified data is flagged, never silently treated as final.
