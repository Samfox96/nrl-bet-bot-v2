# NRL V2 SYSTEM STATUS
_This file is the single source of truth for "is the data trustworthy right now." Read this first, every session._

---

## Last Updated
**2026-10-13 (backfill session)** — Started the "backfill the rest of the 2026 season" catch-up job, now that the Round 20 stall (below) is fixed. This session's real, verified work:
- Finished the Round 20 player-stats merge itself (the fix below only repaired the mechanism; the actual Round 20 pending file still needed running through it once): `nrl_master.csv` 5319 → 5623 rows.
- Found and fixed a second real, independent bug while scoring Round 18/19/20's predictions to fill a gap in the accuracy ledger (only Round 20 had ever actually been scored, even though Round 18 and 19 both had real archived predictions sitting unscored): `score_predictions.py`'s `print_cumulative_summary()` used an f-string with a conditional INSIDE the format spec (`{wb_mkt:.4f if ... else ...}`) — not valid Python; it crashed with "Invalid format specifier" every time a market Brier score was a real float (the normal case once 2+ rounds have market odds data). The round's own ledger entry is written before this runs, so no real data was lost, but the script exited non-zero — which matters a lot for a loop that calls it once per round. Fixed; added `tests/test_score_predictions.py` reproducing the exact crash. Rounds 18, 19, 20 are now all genuinely scored in `accuracy_ledger.json`.
- Built `scripts/backfill_rounds.py` — the one-off, reusable catch-up script the goal asked for: loops the SAME per-round scrape → validate → merge pipeline `weekly-update.yml` already runs (unmodified — this orchestrates the existing, already-proven scripts, it doesn't reimplement them) across a range of rounds instead of one round a week. Added `tests/test_backfill_rounds.py` (orchestration logic only, via an injected fake subprocess runner — no real browser/network in tests, same approach as `test_merge_round.py`).
- Proved the new tool end-to-end against the REAL, live nrl.com for Round 21: `python3 scripts/backfill_rounds.py --start-round 21 --end-round 21 --season 2026` scraped, validated, and merged both player stats (304 rows, `nrl_master.csv` 5623 → 5927) and match results (8 matches, `match_data_FINAL_fixed.csv` 1189 → 1197) in one run. `data/pending/` is empty afterward — no leftover files, confirming the per-round isolated-temp-dir fix for match results actually prevents the kind of cross-round contamination that caused the Round 20 stall in the first place.
- Confirmed via nrl.com's own draw page (`?competition=111&season=2026&round=28..31`) that the 2026 finals use round numbers 28 (Finals Week 1), 29 (Finals Week 2), 30 (Finals Week 3), 31 (Grand Final) — the SAME `round=N` query param every other scrape already uses. **Not yet handled:** `validate_round.py` and `merge_match_results_backfill.py` both cross-check row counts against `scripts/bye_schedule.json`, which only covers rounds 1–27 (the regular season) — a finals round's much smaller, ladder-dependent team count will fail that check as-is. Extending those two checks for finals is a real follow-up step, not yet built.
- **Still to do** (tracked as this big job's remaining steps): backfill rounds 22–27 (regular season — no code changes needed, `backfill_rounds.py` already handles these, just needs to be run); extend validation to support the 2026 finals, then backfill rounds 28–31; re-run `score_predictions.py` for any round that gains an archive along the way. Rounds 21–27 and the finals have NO archived predictions at all right now (the predictions pipeline was stuck behind the same Round 20 stall), so there is currently nothing real to score for them — generating a "prediction" for an already-finished match after the fact would be fabricated, not a real forecast, so the accuracy ledger will honestly stay silent on those rounds unless Sam decides otherwise.

**2026-10-13** — Found and fixed the real Round 20 stall: every weekly run since 19 Aug had committed "Round 20: scrape/validation needs review" while reporting success overall. Root cause: `merge_round.py` picked the first pending file alphabetically (`sorted(PENDING_DIR.glob(...))[0]`) instead of the one the workflow actually expected that week. A stale `data/pending/nrl_round_19_new.csv` was left behind after Round 19's first attempt failed and got committed "for review" — Round 19's later retry merged cleanly, but `weekly-update.yml`'s "Commit changes" step only `git add`s `data/nrl_master.csv` and `STATUS.md`, never `data/pending/`, so the retry's local file deletion was never actually committed. That zombie file sorted before every later round's real pending file, so `merge_round.py` kept handing round 19's data to `validate_round.py` while asking it to validate the current round — an automatic "round mismatch" failure, every single week, while that week's genuinely fine scrape sat right next to it untouched. Fixed `find_pending_file()` in `merge_round.py` to look up the exact filename for the expected round instead of guessing from a sorted list (any other leftover pending file is now logged as a warning, not silently used or ignored-into-invisibility). Deleted the stale `data/pending/nrl_round_19_new.csv` zombie. Added `tests/test_merge_round.py` (stdlib `unittest`, no new dependency) reproducing the exact leftover-file directory state and asserting the right round's file is always chosen. Verified locally end-to-end: with the zombie removed, `merge_round.py` now validates and merges the real Round 20 pending file successfully (304 rows, 5319 → 5623) — reverted that local test merge so the real scrape still runs fresh next Wednesday. **One remaining gap, needs a workflow edit I can't push:** the root enabler (pending-file deletions never being committed on a successful merge) is still present in `weekly-update.yml`'s "Commit changes" step. Recommended one-line fix for Sam: change `git add data/nrl_master.csv STATUS.md` to `git add data/nrl_master.csv STATUS.md data/pending` in that step (and the matching match-results commit step, if it also leaves pending files behind). Without it, this exact zombie-file pattern can recur for a future round; with the `find_pending_file` fix in place it will no longer silently block the pipeline, but tidying it up properly still needs that workflow line.

**2026-07-04** — Model improvement sprint (Stages 1–4 of the architect doc's improvement plan). Full list of what shipped this session:

**Stage 1 — Wire dead xTry components:**
- `generate_predictions.py`: wired `due_flag_severity` and `scored_last_game` into Component 8 (`build_raw_scores`). Both were "dead but present" — the logic existed, the call site never passed real values. `due_flag_severity` flows from the same `due_watch_by_team` entries that feed the email badge (DUE badge and try-probability can no longer contradict each other). `scored_last_game` derived from `games[-1]["tries"]`. Verified live via R18 `workflow_dispatch` run. Three inputs deliberately left neutral: `games_since_return_from_injury`, `games_since_rep_return`, `was_dropped_and_recalled` — no unambiguous data source for any of them.
- `xtry_model.py`: Component 1 minutes reprojection (Option B). Base TPG now computed as `tries_per_min × expected_minutes` (rolling last-5-played-games, capped at 80) rather than raw tries-per-game. Near-no-op for stable starters (Dylan Edwards −0.3%), correctly adjusts role-changing fringe players (Alex Seyfarth role expanding +63%, Soni Luke role shrinking −9%). `n_games` exposed in the components dict for downstream uncertainty penalty.
- Component 6 audit: proxy (`receipts` weighting) confirmed healthy against live R17 data — 0 speed-present-but-receipts-zero rows, 89.3% coverage. No change needed. Scraper `play_the_ball` diagnosis: P5 DIAG block already in live scraper (committed 04:02 UTC 2026-07-03); predated the R17 Job A run by 2.5h so didn't fire. Will fire on R18 scrape — look for `[P5 DIAG]` lines in that run's log.

**Stage 2 — Brier scores + EV log:**
- `score_predictions.py`: extended with `brier_winner_ours`, `brier_winner_market`, `brier_tryscorer_ours`, `brier_tryscorer_market` (MSE between probability and binary outcome). Prediction-time EV log added (`prediction_time_ev_log`): one entry per positive-edge try-scorer with `our_probability`, `market_probability`, `edge`, `outcome_scored`, and `closing_market_probability: null` (slot for CLV once closing odds are captured). `print_cumulative_summary()` prints rolling season-to-date Brier + accuracy across all scored rounds after each run. NOTE: scorer can't run until R18 is played and merged — R17 has no archive (archiving added this session).

**Stages 3–4 — Uncertainty penalty, decision engine, CLV capture:**
- `xtry_model.py`: `n_games` added to components dict.
- `edge_finder.py`: passes `n_games` through from `components` dict so the decision engine can apply the sample-size penalty.
- `decision_engine.py`: uncertainty penalty `1/sqrt(n_games)` applied to effective_edge before the minimum threshold check. A 4-game player at raw_edge=0.08 is discounted to 0.04 (below MINIMUM_EDGE=0.05); a 16-game starter survives. `effective_edge`, `uncertainty_penalty`, `n_games` now exposed in each candidate entry.
- `capture_closing_odds.py` (new): re-fetches Sportsbet odds ~1h before kickoff, back-fills `closing_market_probability` and `clv = our_p / closing_p − 1` into the round's EV log in `predictions_history/`. Called by `team-list-polling.yml`'s new closing-odds step. 2 credits per match, 16 credits/round — within 500/month budget.
- `team-list-polling.yml`: new "Capture closing odds" step fires only on `workflow_dispatch` (cron-job.org triggers), not Tuesday schedule. Gates on `fixture`/`round`/`season` inputs.
- `schedule_kickoff_triggers.py`: dispatch body now includes `inputs` dict (`fixture`, `round`, `season`) so the new workflow step receives fixture details.
- `generate_predictions.py`: Sportsbet-only filter on try-scorer odds. Sam bets on Sportsbet; multi-book output produced entries he can't act on. H2H consensus stays multi-book (better de-margining). Credit cost unchanged (scales by markets×regions, not bookmakers).
- `manual_notes.json` (new, `data/`): Stage 5 intangibles file. Empty R18 template. Update `notes` array before each round's predictions run to declare any manual adjustments. Applied transparently at decision layer only — never alters model probabilities.

Also this session: R17 scrape ran successfully via Job A (01:42 UTC 2026-07-03, 304 rows, 4560→4864). Match results merge raised a false-alarm GitHub Issue (R17 results were already present — duplicate guard working correctly). **Close that issue manually.** `try_minutes` empty for all R17 rows — confirmed caused by `team_aliases.json` path error already fixed in live scraper at line 594; will populate correctly on R18 scrape. Wrong-file paste into `generate-predictions.yml` during session — recovered from last-good commit (c61460a), same class of incident as 2026-06-25.

**2026-07-03** — Stage 1 (xTry model) started. Wired two of Component 8's previously-dead situational inputs from real data: `due_flag_severity` and `scored_last_game`. Also wired Component 1 minutes reprojection. Also: recovered a `generate-predictions.yml` that was accidentally overwritten with Python source.

**2026-06-25** — Found and fixed a real, serious silent-staleness bug: `match_data_FINAL_fixed.csv` had been stuck at Round 10 since a one-time upload on June 21. Backfilled Rounds 11–16. Built and wired real, ongoing automation. Also fixed: Tuesday team-list gap; DUE WATCH ordering bug (Campbell Graham case); cron-job.org duplicate-trigger bug; `weekly-update.yml` overwrite incident.

---

## Automation Status

**Job A — completed-round stats + match results** (`weekly-update.yml`): runs Thursday mornings.
- Scrapes player stats, validates, merges into `nrl_master.csv`.
- Scrapes match results, validates, merges into `match_data_FINAL_fixed.csv`.
- Extends `season_draw_2026.json` with a 2-round buffer.
- Any failure opens a GitHub Issue and leaves the file untouched.

**Job B — team-list polling** (`team-list-polling.yml`):
- **Tuesday ~4:10pm AEST**: baseline scrape captures the round's initial team list.
- **Near kickoff (cron-job.org)**: re-scrapes for late changes, 1h before each match.
- **NEW (2026-07-04)**: closing odds capture step fires on the cron-job.org trigger — calls `capture_closing_odds.py` for that fixture, back-fills CLV into the predictions archive.

**Predictions pipeline** (`generate-predictions.yml`): runs weekly ~3h after Job A.
- Produces `data/predictions_current.json`, `data/predictions_current.csv`, `data/predictions_history/{season}_round_{N}.json`.
- Calls `decision_engine.py` → `data/betting_decisions.json` (advisory, best-effort).
- Try-scorer odds filtered to Sportsbet only (2026-07-04).

**Precise per-match triggering** (`schedule-kickoffs.yml`): creates one cron-job.org trigger per match, 1h before kickoff. Now passes `fixture`/`round`/`season` inputs to the dispatched workflow.

Credentials (`CRONJOB_API_KEY`, `WORKFLOW_DISPATCH_TOKEN`, `RESEND_API_KEY`, `DIGEST_TO_EMAIL`, `ODDS_API_KEY`) all live as GitHub Actions repository secrets only.

---

## Predictions Pipeline — Model Components

| Component | Status | Notes |
|---|---|---|
| Elo (win prob + margin) | ✅ Live | 64.8% backtest accuracy, ±14pt MAE |
| xTry Component 1 (base TPG) | ✅ Updated 2026-07-04 | Minutes reprojection: `tries_per_min × expected_min` |
| xTry Component 8 (context) | ✅ Updated 2026-07-03 | `due_flag_severity` + `scored_last_game` now wired; 3 inputs still neutral |
| xTry Component 6 (ruck speed) | ✅ Healthy | `receipts` proxy confirmed 89.3% coverage |
| Edge finding | ✅ Live | Sportsbet-only (2026-07-04) |
| Decision engine | ✅ Updated 2026-07-04 | ¼ Kelly, uncertainty penalty, exposure cap, same-match discount |
| Accuracy ledger | ✅ Live | Brier scores added 2026-07-04; first scoreable round = R18 |
| CLV capture | ✅ Wired 2026-07-04 | `closing_market_probability` populated per-match near kickoff |
| `play_the_ball` scraper fix | ⏳ Pending | P5 DIAG fires on R18 scrape — check log for `[P5 DIAG]` lines |
| DUE WATCH injury-return modifier | ⬜ Not built | Documented open limitation |
| Calibration map (Platt/isotonic) | ⬜ Blocked | Needs full season of scored rounds; revisit mid-2027 |

---

## Current Data Coverage

| File | Rows | Coverage | Status |
|------|------|----------|--------|
| `nrl_master.csv` | 5,927 | 2026, Rounds 1–21 | ✅ CURRENT (updated 2026-10-13 backfill session; this table had drifted out of sync with the per-round summaries below it since Round 17 — rows/rounds corrected) |
| `match_data_FINAL_fixed.csv` | 1,197 | 2021–2026, through Round 21 | ✅ CURRENT (same correction) |
| `historical_player_match_rows.csv` | 28,935 | 2021–2025, all rounds | ✅ Static — baselines only |
| `historical_position_tpg_baseline.csv` | 50 | 2021–2025 by position/season | ✅ Static |
| `historical_zcr_baseline.csv` | 170 | 2021–2025 by team/position | ✅ Static |
| `team_aliases.json` | — | All 17 teams | ✅ Canonical standard locked |
| `position_aliases.json` | — | All positions | ✅ Canonical standard locked |
| `season_draw_2026.json` | — | Rounds 17–19 | ✅ Auto-extended weekly |
| `team_lists_current.csv` | — | R18 (current round) | ✅ Present |
| `predictions_history/2026_round_18.json` | — | R18 predictions archive | ✅ Present — scoreable after R18 results merge |
| `betting_decisions.json` | — | Latest decision engine output | ✅ Advisory |
| `manual_notes.json` | — | R18 template | ✅ Empty — update before predictions run |

---

## Outstanding Gaps (real, current)
- [ ] `play_the_ball` scraper fix — P5 DIAG fires on R18 scrape; one-line `HEADER_MAP` addition once the log confirms the real header string
- [x] `EXPECTED_BYES` in `merge_match_results_backfill.py` — this bullet was stale: that script already loads `scripts/bye_schedule.json` directly (see its own 2026-07-03 docstring note), which covers all of rounds 1–27. Confirmed during the 2026-10-13 backfill session. Real remaining gap: `bye_schedule.json` (and `validate_round.py`'s own `ALL_TEAMS`-vs-bye check) has NO entries for round 28+ (the 2026 finals) — see new bullet below.
- [ ] **2026 finals (rounds 28–31) aren't validatable yet.** Confirmed on nrl.com's own draw page (2026-10-13) that Finals Week 1/2/3 and the Grand Final are rounds 28, 29, 30, 31 respectively, using the exact same `round=N` scrape path as every regular round. But `validate_round.py` and `merge_match_results_backfill.py` both check scraped row counts against a fixed bye list (`scripts/bye_schedule.json`, rounds 1–27 only) — finals rounds have a much smaller, ladder-dependent team count with no fixed bye list, so both checks will reject real finals data as-is. Needs a finals-aware validation path before `scripts/backfill_rounds.py` can process rounds 28–31.
- [ ] DUE WATCH has no injury-return modifier — pre-absence games count as recent form
- [ ] Calibration map (Platt/isotonic on ledger history) — blocked until mid-2027 when enough scored rounds exist
- [ ] `totals` (over/under) line-mismatch across bookmakers — confirmed real, still unsolved
- [ ] No week-over-week DUE-flag diffing yet
- [ ] False-alarm GitHub Issue from R17 match results merge — **close manually** (R17 results were already present; duplicate guard fired correctly)
- [ ] `weekly-update.yml`'s "Commit changes" step (and the match-results equivalent) never commits `data/pending/` — a successfully-merged pending file's deletion is never pushed, so it can resurface as a zombie that confuses the NEXT round's file lookup (this is exactly what caused the Round 20 stall). **Needs Sam:** add `data/pending` to that step's `git add` line.

## Known Issues Fixed (historical)
1. Three inconsistent team-naming schemes → `team_aliases.json`
2. Three inconsistent position-coding schemes → `position_aliases.json`
3. `match_id` join key issue → score-fingerprint matching (852/860, 99%)
4. `match_data_FINAL.csv` +1 round-numbering bug for 2026 from R2 onward → fixed
5. Erroneous R13 `dolphins-v-rabbitohs` fallback URL → removed
6. `nrl_master.csv` raw unnormalized values → one-time migration + `merge_round.py` going forward
7. `match_data_FINAL_fixed.csv` silently stale for 6+ rounds → automated refresh + R11–16 backfill
8. DUE WATCH ordering bug (unselected players flagged) → squad filter applied before flag attachment
9. cron-job.org duplicate triggers (16 jobs instead of 8) → idempotency check added
10. `beautifulsoup4` missing from `weekly-update.yml` → added
11. Component 8 context inputs all defaulting to neutral → `due_flag_severity` + `scored_last_game` wired

## Failsafe Rule
**Nothing gets merged into a real data file until it has passed validation against the known schedule and internal consistency checks.** A failed validation leaves the existing file untouched and raises a GitHub Issue — never a silent partial merge.

## Validation Checks Run Every Update
- Row count sanity (expected range per round, bye-adjusted) — player stats AND match results
- Zero unmapped team names / positions
- Zero duplicate rows (player+team+round+season; home+away+season+round)
- Round numbers match expected NRL draw sequence
- Content-based pre-send sanity check before email (fixture count, valid probabilities, valid odds, no missing per-game entries)

## Round 18 Auto-Merge Summary (2026-07-08)
- Scraped and validated automatically via GitHub Actions (Phase 3)
- 190 rows added, 4864 -> 5054 total rows in nrl_master.csv
- Validation: PASSED (see workflow log for full report)

## Round 19 Auto-Merge Summary (2026-07-29)
- Scraped and validated automatically via GitHub Actions (Phase 3)
- 265 rows added, 5054 -> 5319 total rows in nrl_master.csv
- Validation: PASSED (see workflow log for full report)

## Round 20 Auto-Merge Summary (2026-10-13)
- Scraped and validated automatically via GitHub Actions (Phase 3)
- 304 rows added, 5319 -> 5623 total rows in nrl_master.csv
- Validation: PASSED (see workflow log for full report)

## Round 21 Auto-Merge Summary (2026-10-13)
- Scraped and validated automatically via GitHub Actions (Phase 3)
- 304 rows added, 5623 -> 5927 total rows in nrl_master.csv
- Validation: PASSED (see workflow log for full report)
