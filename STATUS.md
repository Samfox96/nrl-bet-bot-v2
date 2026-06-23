# NRL V2 SYSTEM STATUS
_This file is the single source of truth for "is the data trustworthy right now." Read this first, every session._

---

## Last Updated
**2026-06-23** — Round 16 merged in (single-round scrape workflow); full weekly automation (Job A, Job B, precise cron-job.org triggers) built and live-tested

## Automation Status (Phase 3)

**Job A — completed-round stats** (`weekly-update.yml`): runs Thursday mornings, scrapes the round that just finished, validates (zero dupes, bye-schedule match, per-team row-count sanity), merges into `nrl_master.csv` only on a clean pass; opens a GitHub Issue and leaves data untouched on failure. Proven live against real Round 17 fixtures (2026-06-22).

**Job B — team-list polling near kickoff** (`team-list-polling.yml`): fetches the current round's published team list, extracts player/position/jersey data plus exact kickoff times, writes `data/team_lists_current.csv` only when a match is within 1 hour of kickoff. Self-contained — no dependency on Job A. Proven live end-to-end (2026-06-23).

**Precise per-match triggering** (`schedule-kickoffs.yml`, runs Tue/Wed): GitHub's native hourly cron for Job B was confirmed unreliable in practice (real observed gaps of 1–5 hours between supposedly-hourly runs, 2026-06-22) — GitHub's shared-runner scheduling is documented to be imprecise, especially at the top of the hour. Replaced with **cron-job.org** as an external scheduler: each week, `schedule_kickoff_triggers.py` reads the round's real kickoff times and creates one precisely-timed job per match via cron-job.org's REST API, each firing a `workflow_dispatch` call to Job B exactly 1 hour before that match's kickoff. Confirmed live end-to-end (2026-06-23): all 8 of Round 17's triggers created successfully and verified against the console.

Credentials: `CRONJOB_API_KEY` and `WORKFLOW_DISPATCH_TOKEN` are stored as GitHub Actions repository secrets (Settings → Secrets and variables → Actions). Never pasted in chat or hardcoded — this was deliberately enforced after an earlier session accidentally had a token pasted into chat (immediately revoked).

**Known gotcha**: cron-job.org's job-creation API allows 1 request/second AND 5/minute. The script must space calls ~13 seconds apart — a tighter delay caused real `HTTP 429` failures on a round's 6th–8th match in testing (2026-06-22), since 8 matches at less than 12s apart breaches the per-minute cap even though each individual call respects the per-second cap.

**Still outstanding**: Job A's first genuine full-cycle success (real scrape → validate → merge of a just-finished round, not just a "round not played yet" test) is expected **Thursday July 2, 2026**, once Round 17 finishes.

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
- [x] ~~No scraper running automatically~~ — Job A + Job B both automated and live-tested (see Automation Status above)
- [x] ~~No GitHub repo/Actions workflow~~ — repo live at github.com/Samfox96/nrl-bet-bot-v2, both jobs + the cron-job.org scheduler all wired in
- [ ] `try_minute` column not yet present in `nrl_master.csv` — parser for the match-summary "Tries" box is built and tested against real captured HTML (2026-06-22), but NOT yet wired into `nrl_update_single_round.py`, and no validation cross-check against the existing `tries` column exists yet (Phase 4, next up)
- [ ] Recency-weighted position TPG baseline calculated but not yet wired into the live model (Phase 7)
- [ ] No team lists received yet for Round 17 *predictions* specifically — team-list data IS now being captured automatically via Job B, but this hasn't yet been used to generate actual xTry predictions for an upcoming round
- [ ] Job A's first full real-world cycle (scrape a just-finished round, not a "too early" test) not yet observed — expected Thursday July 2, 2026

## Validation Checks Run Every Update
- Row count sanity check (expected range per round, bye-adjusted)
- Zero unmapped team names / positions
- Zero duplicate (player, team, round, season) rows
- Round numbers match expected NRL draw sequence
- Internal consistency: try distribution, minutes played, position spread per team
- Cross-check against known results where available (golden point games, blowout scores, etc.)

## Failsafe Rule
**Nothing gets marked "data_complete: true" in `nrl_master.csv` until both the scrape AND validation against known results have passed.** Partial or unverified data is flagged, never silently treated as final.
