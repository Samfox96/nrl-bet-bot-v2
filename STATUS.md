# NRL V2 SYSTEM STATUS
_This file is the single source of truth for "is the data trustworthy right now." Read this first, every session._

---

## Last Updated
**2026-06-24** — Team-name and position-code canonical migration completed (`nrl_master.csv`, `season_draw_2026.json`, `merge_round.py` all fixed and proven, closing a real structural risk found via full system audit); Phase 7 (recency-weighted baselines) wired into the live digest pipeline and proven via real end-to-end test — `due_watch_used_weighted_baseline: True` confirmed against live committed files; Phase 8 (odds comparison) exploratory build started — real market data fetched from the-odds-api.com for an actual upcoming fixture, core probability/edge module built and tested against real bookmaker prices, NOT yet committed to the repo (see Phase 8 section below). **Job A's first-ever real automated run fires tonight, 20:00 UTC 2026-06-24** — check the Actions log next session before doing anything else.

## Automation Status (Phase 3)

**Job A — completed-round stats** (`weekly-update.yml`): runs Thursday mornings, scrapes the round that just finished, validates (zero dupes, bye-schedule match, per-team row-count sanity), merges into `nrl_master.csv` only on a clean pass; opens a GitHub Issue and leaves data untouched on failure. Proven live against real Round 17 fixtures (2026-06-22).

**Job B — team-list polling near kickoff** (`team-list-polling.yml`): fetches the current round's published team list, extracts player/position/jersey data plus exact kickoff times, writes `data/team_lists_current.csv` only when a match is within 1 hour of kickoff. Self-contained — no dependency on Job A. Proven live end-to-end (2026-06-23).

**Precise per-match triggering** (`schedule-kickoffs.yml`, runs Tue/Wed): GitHub's native hourly cron for Job B was confirmed unreliable in practice (real observed gaps of 1–5 hours between supposedly-hourly runs, 2026-06-22) — GitHub's shared-runner scheduling is documented to be imprecise, especially at the top of the hour. Replaced with **cron-job.org** as an external scheduler: each week, `schedule_kickoff_triggers.py` reads the round's real kickoff times and creates one precisely-timed job per match via cron-job.org's REST API, each firing a `workflow_dispatch` call to Job B exactly 1 hour before that match's kickoff. Confirmed live end-to-end (2026-06-23): all 8 of Round 17's triggers created successfully and verified against the console.

Credentials: `CRONJOB_API_KEY` and `WORKFLOW_DISPATCH_TOKEN` are stored as GitHub Actions repository secrets (Settings → Secrets and variables → Actions). Never pasted in chat or hardcoded — this was deliberately enforced after an earlier session accidentally had a token pasted into chat (immediately revoked).

**Known gotcha**: cron-job.org's job-creation API allows 1 request/second AND 5/minute. The script must space calls ~13 seconds apart — a tighter delay caused real `HTTP 429` failures on a round's 6th–8th match in testing (2026-06-22), since 8 matches at less than 12s apart breaches the per-minute cap even though each individual call respects the per-second cap.

**Still outstanding**: Job A's first genuine full-cycle success (real scrape → validate → merge of a just-finished round, not just a "round not played yet" test) fires **tonight, 20:00 UTC 2026-06-24** (≈6am AEST Thursday). This is the first time the team-name migration, Phase 4's try-minute parser, and Phase 7's weighted DUE WATCH all run together for real, automatically, with no one watching. Check the Actions log first thing next session.

## Try-Minute Capture (Phase 4)

Parser (`parse_try_minutes.py`) built and tested against 2 real captured DOM structures (Knights v Dragons R16; Bulldogs v Sea Eagles R16 golden-point game). Wired into `nrl_update_single_round.py`: captures the Tries summary box via `driver.page_source` before the Player Stats tab click, merges `try_minutes` (e.g. `"5;8"` for multiple tries) onto each player row, validates parsed counts against the existing `tries` column.

**Known, deliberate gap**: extra-time TRY minute format unconfirmed (both real captures only showed a golden-point FIELD GOAL in extra time, not a try). The parser's regex will not silently mishandle an unexpected format — it flags via `unparsed_entries` in `validate_try_minutes()` rather than guessing. Revisit when a real extra-time try is captured.

**Not yet proven live**: this has not yet run against a real finished round through the actual GitHub Actions Job A pipeline. First real test fires tonight, 20:00 UTC 2026-06-24, alongside Job A's own first full-cycle proof.

## Weekly Digest Email (Phase 5)

Built, tested, and **proven live** 2026-06-23 — a real email was sent and received with correct content.

**Components**: `generate_round_digest.py` (content), `send_round_digest.py` (Resend API send), `due_flags_v2.py` (composite DUE WATCH scoring), `season_draw_2026.json` (fixture data for the opponent-matchup factor, currently covers rounds 17-18 only, **must be extended** as the season progresses or DUE WATCH will raise a clear error for rounds beyond what's transcribed).

**Real bugs found and fixed during build-and-test** (kept here as institutional memory, same spirit as the Phase 0 issues list below):
1. `zcr_shift_facts()` hardcoded a bare `"position_aliases.json"` path instead of using the function's own parameter — worked in every local test (coincidentally run from a directory containing that bare filename) but failed immediately on the real GitHub Actions checkout structure (`scripts/` and `data/` as separate folders). Fixed by passing the already-loaded dict through, matching the pattern `due_flags()` already used correctly.
2. Resend's API returns `HTTP 403 / error code 1010` for any request missing a `User-Agent` header — Python's `urllib` doesn't set one by default, unlike most HTTP clients/SDKs. Fixed by adding an explicit header. **This fix was accidentally dropped between commits once** (an older local copy of `send_round_digest.py` got committed alongside an unrelated change) and had to be reapplied a second time after a real test run reproduced the exact same error — worth being careful, when editing multiple files in one session, to always re-pull the live version of a file immediately before editing it, not reuse an in-memory copy that might predate a later commit.
3. **Original DUE WATCH logic was conceptually wrong, not just buggy**: it measured "season TPG below position average," which surfaces chronic non-scorers (e.g. a winger with 0.08 TPG against a 0.62 league average) as "due" — caught from real user feedback after the first live email, since this is *the opposite* of a genuine DUE signal. Rebuilt as a weighted composite (drought 50%, opponent matchup 25%, team form/usage/structure-share 8.3% each) gated by a "proven scorer" check. That gate itself needed two further fixes once tested against the FULL real 2026 prop/hooker/lock dataset, not just one borderline case — see `due_flags_v2.py`'s own header comment for the detailed history.

## Live Repo Reads (Phase 6)

Done 2026-06-23. The repo was changed from private to **public** specifically to enable this — Claude fetches `https://raw.githubusercontent.com/Samfox96/nrl-bet-bot-v2/main/<path>` directly via `bash_tool`/`curl` at the start of each session rather than relying on uploaded file snapshots. Confirmed safe: `CRONJOB_API_KEY`, `WORKFLOW_DISPATCH_TOKEN`, `RESEND_API_KEY`, and `DIGEST_TO_EMAIL` have always lived only as GitHub Actions repository secrets, never in committed files.

## Team-Name / Position Canonical Migration (2026-06-24)

A full system audit found `nrl_master.csv` had stored raw, unnormalized team names ("Knights" not "Newcastle Knights") and position labels ("2nd Row" not "2RF") since the scraper was first built — normalization only ever happened at point-of-use in consumer scripts, never at the source. This worked only because every current consumer happened to remember to normalize correctly — a real structural risk, not a guarantee.

**Fixed**: a one-time migration (`migrate_nrl_master_to_canonical.py`) converted all 4,560 existing rows (4,028 team values, 4,560 position values changed). `season_draw_2026.json` was converted to match (programmatically, via `team_aliases.json`, to avoid any hand-typed spelling mismatch). `merge_round.py` got a `normalize_to_canonical()` step so every future merge stays canonical going forward — confirmed via a real simulated future-round test (raw "Knights"/"2nd Row" input correctly became "Newcastle Knights"/"2RF" output), and confirmed the failure path raises loudly on an unmapped value rather than silently passing it through.

**Real finding during the fix**: `due_flags_v2.py`'s `opponent_of[team]` lookup is keyed off `nrl_master.csv`'s `team` column directly — migrating that column to full names without ALSO converting `season_draw_2026.json` would have silently broken the opponent-matchup factor (every lookup would return nothing). Caught by deliberately testing the full pipeline after the migration, before declaring it done — confirmed broken, then confirmed fixed once both files were updated together.

**Verified live** (2026-06-24): re-pulled `nrl_master.csv` fresh from GitHub and confirmed canonical team names/position codes are genuinely committed, not just locally fixed.

## Recency-Weighted Baselines (Phase 7) — NOW LIVE

Previously the project docs described this as "not started," which was stale — it's been built, wired in, and proven against the real live pipeline as of 2026-06-24.

**What it does**: applies a gentler recency decay than the original plan (2025=100%/2024=75%/2023=50%, which only covered 3 of 5 years) — final curve is 2025=1.00, 2024=0.85, 2023=0.70, 2022=0.55, 2021=0.40 — combined with a sqrt-based confidence discount, since 2025's source data has roughly 1/8th the sample size of every other year (850 vs ~7,000+ player-games, confirmed in BOTH `historical_position_tpg_baseline.csv` and `historical_player_match_rows.csv`). Without the confidence discount, the thinnest year would also be the most-trusted year, which is backwards. 2024 ends up the most-trusted year overall (combined weight 0.850) — confirmed against real data, not assumed.

**Real finding during the fix**: the ZCR baseline (`historical_zcr_baseline.csv`) has no per-season column at all — it's a flat 2021-2025 aggregate. Rebuilt a per-season version from `historical_player_match_rows.csv` (which does have season + team + opponent + position + tries), and validated the reconstruction logic exactly reproduces all 170 rows of the existing flat baseline before any weighting was applied.

**Wired in as opt-in-by-default**: `due_flags_v2.py`'s `build_due_watch()` accepts optional `weighted_zcr_lookup`/`weighted_league_tpg_by_position` parameters; `generate_round_digest.py` computes and passes these by default now, with automatic fallback to the flat baseline if anything fails (confirmed this fallback genuinely works by deliberately pointing it at a nonexistent file and confirming it still produced 5 due_flags, just using the flat baseline instead).

**A real near-miss caught during verification**: the actual wiring code for this (the import + parameter passing in `generate_round_digest.py`) was generated and handed over correctly earlier in the session, but never actually got committed to the repo — only its two dependencies (`due_flags_v2.py`, `recency_weighted_baselines.py`) made it in. Caught by re-pulling every live file and checking for the literal new parameter name, not by assuming a prior handoff succeeded. Confirmed fixed and committed as of 2026-06-24.

## Odds Comparison (Phase 8) — EXPLORATORY, NOT YET COMMITTED

Started 2026-06-24. Nothing in this section is in the GitHub repo yet — it exists only in chat session outputs and must be manually committed before being relied on.

**Provider confirmed**: `the-odds-api.com` (NOT the similarly-named `theoddsapi.com`, a different product). Free tier confirmed real: 500 credits/month, NRL active (`rugbyleague_nrl`), AU bookmakers confirmed present including `betfair_ex_au`. API key in use: `7e44be4828b5acedcca16eb62dfa14ce` (free tier, no card — low risk if it needs regenerating later).

**Real findings from actually fetching live data** (not docs, not assumptions) for a genuine upcoming fixture (Newcastle Knights v Wests Tigers, Round 17):
1. Betfair Exchange's price on this real match showed a 36.3% apparent overround 4 days out — an illiquid/stale quote, NOT a genuine "true market, zero margin" price as originally planned. Fixed via a reliability filter (only trust an exchange price if its own overround is under 8%; otherwise fall back to a consensus average across the fixed-odds bookmakers).
2. Market availability varies hugely by bookmaker on the same real fixture: 11/11 bookmakers had `h2h`, only 7/11 had `player_try_scorer_anytime`, only 1/11 had `halftime_fulltime` or `odd_even`. Any comparison logic must handle 1 to 11 real prices, never assume a minimum.
3. `totals` (over/under) lines are NOT standardized across bookmakers — confirmed two bookmakers quoting 50.5 while the rest quoted 51.5 for the SAME real match. Not yet solved — comparing across different lines isn't a fair comparison.
4. `player_try_scorer_anytime` and similar player-prop markets ONLY return a "Yes" price, never "No" — confirmed real, not a data gap. This is because it's a single independent yes/no proposition, not a two-outcome market — there's no second side to de-margin against. The bookmaker's "Yes" price (margin included) gets compared DIRECTLY against our own model's probability for the same proposition.
5. The-odds-api.com's team names have minor real spelling differences from `team_aliases.json` ("Canterbury Bulldogs" vs canonical "Canterbury-Bankstown Bulldogs", missing hyphens) — not yet fixed, will need handling before this odds data can be joined against `nrl_master.csv`.

**Built and tested against this real data, NOT yet committed**: `odds_probability.py` — `implied_probability()`, `overround()`, `de_margin()`, `is_exchange_price_reliable()`, `yes_no_market_probability()`, `calculate_edge()`, `best_price_per_outcome()`, `consensus_true_probability()`. A real bug (an accidentally-deleted function during editing) was introduced and caught within the same session by re-running the test script immediately after the edit — the version handed over at session end is the corrected one.

**The real, honest gap**: there is still no actual "our model's probability" output for ANY market — only the market-side plumbing exists. Phase 8 cannot produce a real edge for anyone yet, only show bookmaker prices. This was a deliberate build-order choice (plumbing first, our-model-probability per market type after), not an oversight.

**My sandbox cannot reach `api.the-odds-api.com` directly** (same network restriction that applied to Resend earlier in the project) — all real API verification this session was done by Sam manually opening URLs in his own browser and pasting back JSON. Claude in Chrome was checked and found not connected. Expect to repeat the manual-paste workflow next session for further real API testing, unless that changes.

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
| `season_draw_2026.json` | — | Rounds 17-18 only | ⚠️ Must be extended round-by-round — DUE WATCH raises a clear error for rounds beyond what's transcribed |
| `due_flags_last_run.json` | — | Most recent digest run | ✅ Snapshot only, no diffing logic built yet (Phase 5 future work) |

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
- [x] ~~Claude requires manual file uploads each session~~ — repo is public, Claude reads live files directly (Phase 6)
- [x] ~~No weekly digest notification~~ — built and proven live (Phase 5), fires as the final step of a successful Job A merge
- [x] ~~nrl_master.csv stores raw, unnormalized team/position values~~ — fixed via one-time migration + `merge_round.py` going forward (2026-06-24)
- [x] ~~Recency-weighted position TPG baseline calculated but not wired into the live model~~ — wired in, proven live (Phase 7, 2026-06-24)
- [ ] `try_minute` column logic is wired into `nrl_update_single_round.py` (Phase 4) but has NOT yet run against a real finished round through the actual Job A pipeline — first real test fires tonight, 20:00 UTC 2026-06-24
- [ ] `season_draw_2026.json` only covers rounds 17-18 — needs manual extension from the official NRL draw PDF before DUE WATCH can run for round 19 onward
- [ ] No team lists received yet for Round 17 *predictions* specifically — team-list data IS now being captured automatically via Job B, but this hasn't yet been used to generate actual xTry predictions for an upcoming round
- [ ] Job A's first full real-world cycle (scrape a just-finished round, not a "too early" test) not yet observed — fires tonight, 20:00 UTC 2026-06-24
- [ ] No week-over-week DUE-flag diffing yet — `due_flags_last_run.json` snapshot mechanism exists, but the actual diff logic is deliberately not built until there are two real runs to compare against
- [ ] Phase 8 (odds comparison) is exploratory only — `odds_probability.py` built and tested against real data but NOT committed to the repo yet; no actual "our model's probability" exists for any market; `totals` line-mismatch and team-name spelling mismatch (the-odds-api.com vs `team_aliases.json`) both unresolved

## Validation Checks Run Every Update
- Row count sanity check (expected range per round, bye-adjusted)
- Zero unmapped team names / positions
- Zero duplicate (player, team, round, season) rows
- Round numbers match expected NRL draw sequence
- Internal consistency: try distribution, minutes played, position spread per team
- Cross-check against known results where available (golden point games, blowout scores, etc.)

## Failsafe Rule
**Nothing gets marked "data_complete: true" in `nrl_master.csv` until both the scrape AND validation against known results have passed.** Partial or unverified data is flagged, never silently treated as final.
