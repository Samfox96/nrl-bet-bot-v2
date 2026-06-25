# NRL V2 SYSTEM STATUS
_This file is the single source of truth for "is the data trustworthy right now." Read this first, every session._

---

## Last Updated
**2026-06-25** — Found and fixed a real, serious silent-staleness bug: `match_data_FINAL_fixed.csv` (match results — feeds Elo ratings, win probability, predicted margins, h2h history, form streaks) had been stuck at Round 10 since a one-time upload on June 21, while `nrl_master.csv` (player stats) was correctly refreshed weekly. Backfilled Rounds 11–16 (40 real matches, independently cross-checked against the live NRL ladder, including confirming Round 11 was genuinely Magic Round). Built and wired in real, ongoing automation so this specific gap cannot silently recur. Also fixed: a genuine architecture gap where no real mechanism existed to capture the Tuesday team-list announcement (only late-mail near kickoff was ever built); a DUE WATCH ordering bug that let unselected players be flagged as "due" (real, confirmed case: Campbell Graham); a cron-job.org duplicate-trigger bug (Tuesday + Wednesday safety-net runs had no idempotency check, silently doubling every trigger each week); and a real incident where `weekly-update.yml` was accidentally overwritten with email text across three commits (found via 3 consecutive workflow failures, recovered).

## Automation Status (Phase 3)

**Job A — completed-round stats + match results** (`weekly-update.yml`): runs Thursday mornings.
- Scrapes the just-finished round's player stats, validates, merges into `nrl_master.csv` on a clean pass.
- **NEW (2026-06-25)**: also scrapes that round's real match results (scores, venue, weather, attendance) via `scrape_match_results.py`, validates against the known bye schedule, merges into `match_data_FINAL_fixed.csv` via `merge_match_results_backfill.py`. Opens a GitHub Issue and leaves the file untouched on failure — same discipline as the player-stats path.
- **NEW (2026-06-25)**: extends `season_draw_2026.json` to keep a 2-round buffer ahead of whatever round is being processed, via `extend_season_draw.py`. Genuinely tested against a simulated mid-loop failure (a real bug was found and fixed here — see below) before being trusted.

**Job B — team-list polling** (`team-list-polling.yml`):
- **Precise, near-kickoff path** (unchanged): triggered exclusively by cron-job.org, fires 1 hour before each real match, writes `data/team_lists_current.csv`.
- **NEW (2026-06-25) — Tuesday baseline scrape**: a genuine, separate `schedule:` trigger (~4:10pm AEST Tuesday, confirmed against 5 independent real sources for the actual 4pm release time) calls the same script with a wide `--hours-before 96` window, so the round's *initial* team list is captured as soon as it's published — not just late-mail near kickoff. **Why this matters**: before this fix, there was no real mechanism anywhere in the codebase to ever populate `data/team_lists_current.csv` outside the 1-hour-pre-kickoff window. A predictions run any earlier in the week had no real team-list data to work from at all, silently falling back to "everyone with history" — this is what let an unselected player (Campbell Graham) be modelled and flagged as DUE in a real Round 17 run.
- **Known, real limitation**: the Tuesday cron is a fixed UTC time tuned for AEST (no daylight saving). Will drift by 1 real hour around early April / early October when Australia's clocks change — revisit then.

**Precise per-match triggering** (`schedule-kickoffs.yml`): reads the round's real kickoff times, creates one precisely-timed cron-job.org trigger per match, 1 hour before kickoff.
- **REAL BUG FOUND AND FIXED (2026-06-25)**: this workflow runs on BOTH Tuesday and Wednesday (Wednesday as a safety net in case Tuesday's list wasn't out yet) — but had zero check for already-existing jobs, so a successful Tuesday run was silently duplicated by Wednesday's run, every single week, compounding indefinitely. Confirmed via a real cron-job.org screenshot: all 8 Round 17 triggers present twice (16 real jobs). Fixed: `schedule_kickoff_triggers.py` now lists existing job titles first (titles are fully deterministic) and skips creating a duplicate. The 8 pre-existing duplicate jobs were manually deleted; the fix prevents new ones.

Credentials (`CRONJOB_API_KEY`, `WORKFLOW_DISPATCH_TOKEN`, `RESEND_API_KEY`, `DIGEST_TO_EMAIL`, `ODDS_API_KEY`) all live as GitHub Actions repository secrets only — never in chat or hardcoded in any committed file.

**Known gotcha (unchanged)**: cron-job.org's job-creation API allows 1 request/second AND 5/minute — calls are spaced 13 seconds apart to stay under both caps.

## Predictions Pipeline (`generate-predictions.yml`)

Runs weekly, ~3 hours after Job A (so that round's freshly-merged data is genuinely current before predictions generate). Produces `data/predictions_current.json` and sends the weekly email.

**Real bugs found and fixed (2026-06-25), all confirmed via real Actions logs or real email output, not assumed:**
1. **Missing `beautifulsoup4` dependency** — the live team-list fallback (`parse_team_list.py`) genuinely needs it; the workflow's install step only ever had `pandas`. Confirmed via the real log line `No module named 'bs4'`.
2. **YAML/bash/Python indentation conflict** — an inline multi-line `python3 -c "..."` had its script body indented to match the YAML block, which is a literal `IndentationError` in Python. Only surfaced on the workflow's first genuine *scheduled* run, since every prior manual test used `workflow_dispatch` with `round_override` set, taking the other branch of the relevant `if/else`. A heredoc-based first attempt at a fix hit a second, genuine YAML-parsing conflict (block-scalar indentation vs. bash heredoc delimiter rules are mutually exclusive); fixed properly with a single-line, semicolon-separated `python3 -c "..."`.
3. **Position-changes false positives** — `resolve_squad_positions()` compared raw label strings (e.g. `'FB'` vs `'Fullback'`) instead of resolving both through `position_aliases.json` first, flagging almost every player on a roster as "changed" even when nothing real changed. Fixed: compare resolved canonical codes.
4. **Position-changes scope narrowed, per explicit request**: only genuine **starting-XV** swaps are now reported (neither side of the swap is the `IC`/bench code) — real bench-rotation moves (e.g. a Prop now listed as Interchange) are real, non-buggy changes, but deliberately excluded from the email as noise, not signal.
5. **DUE WATCH ordering bug** — `due_watch` was being attached to each fixture *before* that week's real resolved squad even existed in the code's execution order, so there was nothing to cross-check against. Moved the attachment to after squad resolution; entries are now filtered to only players actually present in the resolved squad.
6. **`get_real_head_to_head()`'s winner-determination logic** had a genuinely broken conditional chain that could report the *losing* team as the winner of a historical match (confirmed real case: Gold Coast Titans 18 – Canterbury Bulldogs 38, originally misreported as a Titans win). Found by manually checking output against the raw match row, not by trusting a plausible-looking result. Fixed with simple, directly-correct logic.
7. **Real form-streak convention clarified, not a bug**: this project's `get_real_form_streak()` counts the last N games *actually played* (skips byes), which is a genuinely different, equally legitimate convention from the public NRL ladder's "Form" column (counts by *round number* — a bye creates a real gap). Confirmed via a real, traced example (Dolphins: this function found 5 straight real wins across rounds 11/12/14/15/16, while the public ladder showed "4-0" for the same team at the same moment). Kept the games-played convention; narrative wording now says "games played" explicitly so it can't read as contradicting the public ladder again.
8. **Pre-send sanity check added** (`validate_digest_before_send()`) — every checkpoint before this was exception-based ("did the code crash"), not content-based ("does the output look right"). Now checks: fixture count within the real normal NRL range (4–9), no win probability outside (0,1), no odds ≤ 1.0, no fixture with real edges elsewhere in the round but a missing per-game entry. A failed check blocks the email and raises a GitHub Issue.

**Outstanding, real, deliberately unfinished**: a "returning from injury/absence" modifier for DUE WATCH was discussed but not yet built — the underlying `games[-4:]` window has no concept of real elapsed time, so a player's pre-absence games could still be counted as "recent form" once they return, regardless of how long they were actually out. Flagged, not yet fixed.

## Real Data Backfill — Round 11-16 Match Results (2026-06-25)

`match_data_FINAL_fixed.csv` was discovered to have exactly one commit, ever (June 21 upload), and was genuinely 6+ rounds stale despite `nrl_master.csv` being correctly current — meaning every Elo rating, win probability, predicted margin, h2h history, and form-streak in every prediction was computed from outdated match results. Caught via a real, direct symptom: Sam noticed a predictions email claiming "Roosters red-hot, 5 wins from 5" while the real live ladder showed their actual recent form was 2-2.

**Backfilled and merged**: Rounds 11–16, 40 real matches, scraped via a new `scrape_match_results.py` (built from selectors confirmed against real captured HTML, not guessed), validated (team-name resolution, no duplicates, sane scores, correct per-round counts against the known bye schedule) and merged via `merge_match_results_backfill.py`. Round 11 was independently cross-checked against a third-party source after looking suspicious (all 8 matches showing the same venue) — confirmed genuinely correct: Round 11, 2026 was NRL Magic Round, all 8 matches at Suncorp Stadium, crowd figures matching exactly.

**Schema extended**: two new real columns, `ground_conditions` and `weather`, captured from the same scrape (the original schema didn't have them; confirmed safe to add since every real consumer of this file uses named-key access, not positional).

## Current Data Coverage

| File | Rows | Coverage | Status |
|------|------|----------|--------|
| `nrl_master.csv` | 4,560 | 2026, Rounds 1–16 | ✅ CURRENT |
| `match_data_FINAL_fixed.csv` | 1,161 | 2021–2026, 2026 through Round 16 | ✅ CURRENT (was stuck at Round 10 until 2026-06-25's backfill) |
| `historical_player_match_rows.csv` | 28,935 | 2021–2025, all rounds | ✅ Correctly static — team/position-level baselines only |
| `historical_position_tpg_baseline.csv` | 50 | 2021–2025 by position/season | ✅ Correctly static |
| `historical_zcr_baseline.csv` | 170 | 2021–2025 by team/position | ✅ Correctly static |
| `team_aliases.json` | — | All 17 teams | ✅ Canonical standard locked |
| `position_aliases.json` | — | All positions | ✅ Canonical standard locked |
| `season_draw_2026.json` | — | Rounds 17, 18, 19 | ✅ Now auto-extended weekly (2-round buffer) — was manually extended only, stuck at 17-18 |
| `data/team_lists_current.csv` | — | Most recent real scrape | ⚠️ Only exists once a real scrape (Tuesday baseline or precise kickoff trigger) has actually fired for the current round — genuinely absent between rounds, this is expected, not a bug |

## Known Issues Fixed (Phase 0, historical)
1. Three inconsistent team-naming schemes → unified via `team_aliases.json`
2. Three inconsistent position-coding schemes → unified via `position_aliases.json`
3. `match_id` join key issue between historical files → resolved via score-fingerprint matching (852/860, 99%)
4. `match_data_FINAL.csv` had a +1 round-numbering bug for all of 2026 from Round 2 onward — fixed and verified
5. Erroneous R13 `dolphins-v-rabbitohs` fallback URL removed (both teams were on bye, fixture never existed)
6. `nrl_master.csv` stored raw, unnormalized team/position values — fixed via one-time migration + `merge_round.py` going forward

## Outstanding Gaps (real, current, as of 2026-06-25)
- [ ] DUE WATCH has no "returning from injury/absence" modifier — a long layoff doesn't distort the recent-TPG *rate* (byes/absences are correctly excluded from the games-played window), but the pre-absence games could still be stale once a player returns. Not yet built.
- [ ] `EXPECTED_BYES` (in `merge_match_results_backfill.py`) only covers rounds 11–17 — the real safety-net cross-check degrades gracefully (skips itself) for any round beyond that, rather than crashing, but stops actively protecting. Extend round-by-round.
- [ ] `season_draw_2026.json`'s real auto-extension keeps a 2-round buffer, but a single missed/failed run could still need the buffer to be re-established — watch for the dedicated GitHub Issue this raises on failure.
- [ ] No week-over-week DUE-flag diffing yet.
- [ ] `totals` (over/under) line-mismatch problem (different bookmakers quoting different lines for the same match) — confirmed real, still unsolved.
- [ ] `play_the_ball` column confirmed `'0'` for every row in `nrl_master.csv` — the scraper's `HEADER_MAP` believes it's capturing this column but isn't. Not yet investigated independently of the model components that have working fallbacks.

## Validation Checks Run Every Update
- Row count sanity check (expected range per round, bye-adjusted) — now applies to BOTH player stats and match results
- Zero unmapped team names / positions
- Zero duplicate (player, team, round, season) rows; zero duplicate (season, round, home_team, away_team) match-result rows
- Round numbers match expected NRL draw sequence
- Real content-based sanity check before sending the weekly email (fixture count, valid probabilities, valid odds, no missing per-game entries when edges exist elsewhere)

## Failsafe Rule
**Nothing gets merged into a real data file until it has passed validation against the known schedule and internal consistency checks.** A failed validation leaves the existing file untouched and raises a GitHub Issue — never a silent partial merge.
