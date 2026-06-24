# NRL V2 SYSTEM STATUS
_This file is the single source of truth for "is the data trustworthy right now." Read this first, every session._

---

## Last Updated
**2026-06-24** — Phase 8 substantially progressed: the real `NRL_MASTER_PROMPT_V2.md` xTry spec was discovered to have NEVER been committed to the repo (a more serious instance of the same silent-loss pattern flagged elsewhere in this doc — this time it was the foundational model spec itself, not a small function). Recovered from Sam directly and reconstructed as `xtry_model.py`, all 8 components built and validated against real data across two full real rounds (17 fixtures total). One real gap found and fixed in `team_aliases.json` (`"Canterbury Bulldogs"` was missing, confirmed against the real `/v4/sports/rugbyleague_nrl/participants/` API response — 16 of 17 already resolved correctly, only this one was a genuine gap). `edge_finder.py` built and tested as the connective layer between `xtry_model.py` and `odds_probability.py` — **this closes the "no our-model-probability exists" gap**, though only against synthetic odds shaped to match the real API format, not a live call (sandbox still can't reach `api.the-odds-api.com` directly). Team-name and position-code canonical migration completed (`nrl_master.csv`, `season_draw_2026.json`, `merge_round.py` all fixed and proven, closing a real structural risk found via full system audit); Phase 7 (recency-weighted baselines) wired into the live digest pipeline and proven via real end-to-end test — `due_watch_used_weighted_baseline: True` confirmed against live committed files. **Job A's first-ever real automated run fired tonight, 20:00 UTC 2026-06-24** — check the Actions log next session before doing anything else; this status predates that result.

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

## Odds Comparison & xTry Model (Phase 8) — MAJOR PROGRESS, ONE GAP REMAINS

### The real xTry spec was never in the repo -- found and fixed 2026-06-24

`PROJECT_BRIEF.md` has referenced "xTry Component 1" and "xTry Component 4" by name for a while, as if the reader already had the spec -- but the actual formula (8 multiplicative components, locked weights) lived in a file called `NRL_MASTER_PROMPT_V2.md` that was confirmed to **never have been committed to this repo** (404 on every plausible path, checked 2026-06-24). This is the same silent-loss failure pattern already documented elsewhere in this file (the dropped Phase 7 wiring, the dropped `User-Agent` fix) -- except this time it was the foundational model spec itself, not a small function, and it had gone unnoticed for multiple sessions because every doc only ever cited the spec by name, never reproduced its contents.

**Fixed**: Sam pasted the real original spec text directly. Reconstructed as `scripts/xtry_model.py` (now committed and verified live). All 8 components built and individually unit-tested against real `nrl_master.csv` / historical baseline data, then validated end-to-end across **all 8 real Round 17 fixtures** (zero crashes, NaNs, or out-of-range values) and stress-tested against **Round 5** (early-season, most players on only 3-4 real games) specifically to probe small-sample behaviour rather than just a comfortable late-season sample.

**Three real bugs caught and fixed during the build, not after**:
1. Component 1's literal "50% raw + 50% position-normalised" spec wording was mathematically a no-op (the league average algebraically cancels out, confirmed against real data: Alex Johnston's 1.583 raw TPG reproduced exactly either way) -- fixed with genuine shrinkage-toward-league-mean instead.
2. `play_the_ball` is confirmed `'0'` for **every single row** in the entire `nrl_master.csv` (4,560 rows checked) -- `nrl_update_single_round.py`'s `HEADER_MAP` believes it's capturing this column but isn't, in practice. Component 6 (ruck factor) uses `receipts` as a working fallback weight, but **this scraper gap should be looked at independently of the xTry model** -- it may silently affect anything else that assumes this column is populated.
3. Confirmed via dimensional reasoning that FMI must collapse into base TPG as a single blended try-rate rather than being multiplied as an independent ratio -- multiplying two raw tries-per-game figures together would produce tries²/game², not a valid rate.

**Real, accepted limitation found via Round 5 stress-testing**: early-season volatility produces somewhat more 65%-display-cap-hits than late season (Round 5: ~4% of modelled players vs Round 17: ~3%), traced to two real causes: Component 1's blend always leaves half the figure unshrunk regardless of sample size (the spec's literal wording, deliberately left as-is), and Component 7's attack-share ratio computed off small early-season team-tries denominators (a real, fixable issue -- see below). One targeted fix WAS applied as a result: Component 7 now shrinks `player_try_share` toward the league-average share using team-games-played credibility weighting, confirmed via real data to meaningfully reduce (not eliminate) the effect.

### team_aliases.json gap found and fixed

Pulled the real, authoritative list of all 17 NRL team names directly from `the-odds-api.com`'s `/v4/sports/rugbyleague_nrl/participants/` endpoint (not guessed). Result: **16 of 17 already resolved correctly** via the existing alias map -- including Sharks and Sea Eagles, which earlier framing had suggested were broken alongside Bulldogs but actually weren't. The one real gap: `"Canterbury Bulldogs"` (the API's exact string) wasn't in the alias dict at all -- existing entries only covered `"Canterbury"`, `"Canterbury Bankstown Bulldogs"`, and `"Canterbury-Bankstown Bulldogs"`, none matching. Fixed with a single added line, re-verified against all 17 real API names after a genuine CDN-cache false-negative scare (the fix WAS live, a 5-minute CDN cache window just made it look like it wasn't -- worth remembering: if a live-repo check fails right after an edit, wait out the cache window before concluding something's wrong).

### edge_finder.py -- the actual connective layer

Built and committed as `scripts/edge_finder.py`. This is the piece that finally closes the literal gap this file has flagged for a while ("no real 'our model's probability' output for any market yet"): it takes `xtry_model.py`'s per-player probability output, matches player names against real bookmaker odds (explicitly surfacing any unmatched names rather than silently dropping them -- the same lesson as the team-name mismatches, applied proactively to player names this time), converts the bookmaker's "Yes" price via `yes_no_market_probability()` (confirmed correct for this market shape -- no de-margining, since there's no second side), and calls `calculate_edge()`. Tested end-to-end against the real, already-validated Knights v Wests Tigers Round 17 squads, including two deliberate test cases (a fake name-mismatch and a genuinely-unpriced player) to confirm the unmatched-name safety net actually works, not just that it compiles.

**The one real caveat**: this was tested against **synthetic odds shaped to match the real, documented API response format** (confirmed via a real MLB `batter_home_runs` example, which is structurally identical to how an NRL anytime try-scorer market returns -- `{"name": "Yes", "description": "<player full name>", "price": ...}`), not a live API call. The sandbox still can't reach `api.the-odds-api.com` directly. **The first time this runs against genuinely live odds, the `unmatched_in_model` output deserves real scrutiny** -- that's exactly where a real player-name formatting mismatch would show up, the same category of problem the team-name fix caught.

### What's still genuinely unbuilt (the honest remaining gap)

- `odds_fetcher.py` -- an actual script that calls the real API automatically. Still doesn't exist. Everything built today assumed odds arrive already in the right shape; nothing yet fetches them live.
- No decision made on **when** in the Thu-Sun window odds should be fetched, given prices shift over time -- flagged as an open question in an earlier session, still unresolved.
- `totals` (over/under) line-mismatch problem (different bookmakers quoting different lines for the same match) -- confirmed real, still unsolved.
- No wiring into the weekly automation pipeline at all yet -- `xtry_model.py` and `edge_finder.py` exist as standalone, tested modules, not yet called from any GitHub Actions workflow.

**Provider reminder**: `the-odds-api.com` (NOT `theoddsapi.com`, a different product). Free tier: 500 credits/month, NRL active (`rugbyleague_nrl`), AU bookmakers confirmed present including `betfair_ex_au`. API key in use: `7e44be4828b5acedcca16eb62dfa14ce` (free tier, no card attached -- low risk, but Sam may want to regenerate it at some point for peace of mind).

**My sandbox still cannot reach `api.the-odds-api.com` directly** (same network restriction that applied to Resend earlier in the project). Real API verification continues to require Sam manually opening URLs in his own browser and pasting back JSON, or Claude in Chrome if connected (checked again 2026-06-24, still not connected).

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
- [x] ~~No real "our model's probability" output for any market~~ — `xtry_model.py` built, validated against 17 real fixtures across 2 full rounds, committed (Phase 8, 2026-06-24)
- [x] ~~No connective layer between our probability and market odds~~ — `edge_finder.py` built and committed, tested end-to-end against real squad data with synthetic odds (Phase 8, 2026-06-24)
- [x] ~~team_aliases.json missing "Canterbury Bulldogs"~~ — confirmed against real the-odds-api.com participants endpoint, fixed (2026-06-24)
- [ ] `try_minute` column logic is wired into `nrl_update_single_round.py` (Phase 4) but has NOT yet run against a real finished round through the actual Job A pipeline — first real test fires tonight, 20:00 UTC 2026-06-24
- [ ] `season_draw_2026.json` only covers rounds 17-18 — needs manual extension from the official NRL draw PDF before DUE WATCH can run for round 19 onward
- [ ] No team lists received yet for Round 17 *predictions* specifically — team-list data IS now being captured automatically via Job B, but this hasn't yet been used to generate actual xTry predictions for an upcoming round
- [ ] Job A's first full real-world cycle (scrape a just-finished round, not a "too early" test) not yet observed — fires tonight, 20:00 UTC 2026-06-24
- [ ] No week-over-week DUE-flag diffing yet — `due_flags_last_run.json` snapshot mechanism exists, but the actual diff logic is deliberately not built until there are two real runs to compare against
- [ ] Phase 8: `odds_fetcher.py` (actual live API-calling script) does not exist yet — `xtry_model.py` and `edge_finder.py` are built, committed, and tested, but nothing yet fetches real odds automatically; everything tested so far used synthetic odds shaped to match the real documented format
- [ ] Phase 8: no decision made yet on WHEN in the Thu-Sun window odds should be fetched, given prices shift over time
- [ ] Phase 8: `totals` line-mismatch (different bookmakers quoting different lines for the same match) confirmed real, still unsolved
- [ ] Phase 8: not yet wired into the weekly automation pipeline — `xtry_model.py`/`edge_finder.py` exist as standalone tested modules only, no GitHub Actions workflow calls them yet
- [ ] Phase 8: `edge_finder.py`'s player-name matching has only been tested against synthetic odds — first live API run should get real scrutiny on its `unmatched_in_model` output specifically

## Validation Checks Run Every Update
- Row count sanity check (expected range per round, bye-adjusted)
- Zero unmapped team names / positions
- Zero duplicate (player, team, round, season) rows
- Round numbers match expected NRL draw sequence
- Internal consistency: try distribution, minutes played, position spread per team
- Cross-check against known results where available (golden point games, blowout scores, etc.)

## Failsafe Rule
**Nothing gets marked "data_complete: true" in `nrl_master.csv` until both the scrape AND validation against known results have passed.** Partial or unverified data is flagged, never silently treated as final.
