# NRL BET BOT V2 — PROJECT BRIEF
_Read STATUS.md first, every session, before doing anything else._

---

## WHAT THIS PROJECT IS

A rigorous, data-driven NRL prediction system (xTry model: win probability, margin, try scorer odds) built on data that has actually been validated — not assumed. This project replaces the old NRL_Predictor setup after a full data-integrity audit found and fixed several silent bugs (see "Known Issues Fixed" in STATUS.md).

**Institutional memory note (2026-06-24)**: the actual xTry formula spec (`NRL_MASTER_PROMPT_V2.md`) was discovered to have never been committed to this repo, despite being cited by name elsewhere in this very file for a while. This is the same silent-loss pattern documented in STATUS.md's Phase 5 section (the dropped Phase 7 wiring, the dropped `User-Agent` fix) — but this time it was the foundational model spec, not a small function, and it went unnoticed across multiple sessions because every doc only ever cited it, never reproduced its contents. Recovered directly from Sam and reconstructed as `xtry_model.py` (now committed). **Lesson for future sessions: if a doc cites a spec or file by name, confirm that file actually exists in the repo before trusting that the citation means the thing is real and available — a citation is not the same as a committed artifact.**

---

## FILES IN THIS PROJECT

| File | What it is | Use for |
|---|---|---|
| `nrl_master.csv` | 2026 season, player-level, all rounds scraped so far | All current-season xTry calculations |
| `historical_player_match_rows.csv` | 2021-2025, player-level, **no player names** (opaque player_id only) | Team/position-level baselines ONLY — not individual player history |
| `historical_position_tpg_baseline.csv` | League-average TPG by position, by season (2021-2025) | Position normalisation in xTry Component 1 (`xtry_model.py`) |
| `historical_zcr_baseline.csv` | Tries conceded by team by position (2021-2025) | Zone Concede Rate (xTry Component 4, `xtry_model.py`) baseline |
| `match_data_FINAL_fixed.csv` | Match results 2021-2026, round numbers corrected | Historical match context, H2H |
| `team_aliases.json` | Canonical team name mapping | ALWAYS use this to normalise team names — never hardcode |
| `position_aliases.json` | Canonical position code mapping | ALWAYS use this to normalise positions |
| `nrl_update_single_round.py` | Scraper — scrapes ONE round at a time | Job A, weekly automation |
| `validate_round.py` / `merge_round.py` | Validation gate + safe merge logic for Job A | Weekly automation |
| `scrape_team_lists.py` / `parse_team_list.py` / `parse_draw_link_text.py` / `find_team_list_url.py` | Job B — team-list polling near kickoff | Weekly automation |
| `schedule_kickoff_triggers.py` | Creates precise per-match triggers via cron-job.org | Weekly automation (runs Tue/Wed) |
| `parse_try_minutes.py` | Try-minute parser, wired into the scraper | Phase 4 — adds `try_minutes` column (e.g. "5;8") to scraped rows |
| `generate_round_digest.py` | Builds the weekly digest content (top performances, form trends, DUE WATCH, defense watch) | Phase 5 — called by Job A's final step on a successful merge |
| `send_round_digest.py` | Sends the digest via Resend's API | Phase 5 — needs `RESEND_API_KEY` + `DIGEST_TO_EMAIL` secrets |
| `due_flags_v2.py` | Composite DUE WATCH scoring (drought + opponent matchup + team form + usage trend + structure share) | Phase 5 — see its own header comment for the real-data-driven design history |
| `season_draw_2026.json` | NRL season fixture pairings by round (sourced from official draw PDF, canonical team names) | Phase 5's opponent-matchup factor — currently covers rounds 17-18 only, extend manually as the season progresses |
| `recency_weighted_baselines.py` | Recency + confidence-weighted historical baselines (TPG and ZCR) | Phase 7 — wired into `due_flags_v2.py` by default as of 2026-06-24, with automatic fallback to flat baseline |
| `migrate_nrl_master_to_canonical.py` | One-time migration tool, NOT part of the regular pipeline | Run only if `nrl_master.csv` ever needs re-normalizing (e.g. after a manual edit reintroduces raw values) |
| `odds_probability.py` | Implied probability, de-margining, exchange-reliability filter, edge calculation | Phase 8 — committed and live |
| `xtry_model.py` | The actual 8-component xTry formula (reconstructed 2026-06-24 from the original `NRL_MASTER_PROMPT_V2.md` spec, which was confirmed to have never been committed to this repo — see STATUS.md's Phase 8 section). Produces "our probability" a player scores, per match | Phase 8 — committed and validated against 17 real fixtures across 2 full rounds |
| `edge_finder.py` | Connects `xtry_model.py`'s output to `odds_probability.py`'s market-side functions; matches player names against real bookmaker odds (explicitly surfacing unmatched names rather than dropping them) and calls `calculate_edge()` | Phase 8 — committed, tested against real squad data with synthetic odds (not yet a live API call) |
| `STATUS.md` | Live checkpoint — data freshness, known issues, outstanding gaps | Read FIRST every session |

---

## CANONICAL STANDARDS (locked in, do not deviate)

**Team names** — full names, e.g. "New Zealand Warriors", "Canterbury-Bankstown Bulldogs", "Cronulla-Sutherland Sharks", "Manly-Warringah Sea Eagles", "St George Illawarra Dragons". Full mapping in `team_aliases.json`.

**Positions** — codes: FB, WG, CE, FE, HB, HK, PR, 2RF, LK, IC. Full mapping in `position_aliases.json`.

---

## WEEKLY WORKFLOW (automated as of 2026-06-23 — see AUTOMATION STATUS below for detail)

**Stats (Job A)**: runs automatically Thursday mornings. Scrapes the round that just finished, validates, and merges into `nrl_master.csv` on a clean pass — no manual steps unless validation fails, in which case a GitHub Issue is opened and the data is held for review.

**Team lists (Job B + cron-job.org scheduler)**: a weekly script reads the round's real kickoff times and schedules a precise trigger 1 hour before each match. At that moment, Job B fetches the latest team list and writes `data/team_lists_current.csv` if anything's changed.

**What Sam still does manually**: nothing, day to day. Only needed if something fails (a GitHub Issue will say so) or when actually requesting predictions from Claude for an upcoming round — team lists are authoritative and override all other sources, same as always. **`xtry_model.py` and `edge_finder.py` are now committed, real, tested modules** (as of 2026-06-24) that produce an actual per-player try-scoring probability and compare it against real bookmaker odds — but neither is wired into the weekly automation pipeline yet (no GitHub Actions workflow calls them), and the odds side has only ever been tested against synthetic data shaped to match the real API format, not a genuine live call. See STATUS.md's Phase 8 section for the real, current state — don't assume this is fully automated yet, but also don't assume "no model exists" the way earlier versions of this doc said.

---

## DATA QUALITY RULES (non-negotiable)

- Always divide tries by games actually appeared in, never by rounds elapsed
- DUE flag base rate uses season TPG, not recent-drought-period TPG
- Team lists override all other sources for jersey numbers/positions
- Never fabricate data — if something's unknown, say so and explain what would change if known
- `historical_player_match_rows.csv` has no player names — do not attempt individual cross-season player tracking from it

---

## KNOWN LIMITATIONS (be upfront about these, don't paper over them)

- Pre-2026 individual player history is not recoverable (no name lookup exists for `player_id`)
- `try_minute` parser is wired into the scraper (Phase 4) but has not yet run against a real finished round through the actual Job A pipeline — first real test fires tonight, 20:00 UTC 2026-06-24, alongside Job A's own first full-cycle proof. Extra-time try-minute formatting is also unconfirmed — see `parse_try_minutes.py`'s own header comment.
- `season_draw_2026.json` only covers rounds 17-18 — needs manual extension before DUE WATCH can run for later rounds
- The repo is **public** as of 2026-06-23 (changed specifically to let Claude read live files directly each session, Phase 6) — confirmed no secrets have ever lived in committed files, only as GitHub Actions repository secrets
- Phase 8 (odds comparison / xTry model) — `xtry_model.py` and `edge_finder.py` are both built, committed, and validated against real data (17 real fixtures across 2 full rounds for the model; real squad data with synthetic odds for the edge-matching). What's still missing: `odds_fetcher.py` (an actual live API-calling script) doesn't exist yet, nothing is wired into the weekly automation pipeline, the `totals` line-mismatch problem is unsolved, and the player-name matching in `edge_finder.py` has never been tested against a genuinely live odds response. See STATUS.md's Phase 8 section for full detail.

---

## AUTOMATION STATUS (as of 2026-06-23)

Weekly automation (Phase 3) is fully built and live-tested, including a precise external scheduler:

- **Job A** (`weekly-update.yml`) — scrapes the round that just finished, validates, merges into `nrl_master.csv` on a clean pass only. Live-tested (2026-06-22): correctly found real Round 17 fixtures and correctly declined to merge since the round hadn't been played yet — confirms the scrape, fast-fail, and safety-gate logic all work against real data. A genuine successful merge of real finished-round data has not yet been observed; fires tonight, 20:00 UTC 2026-06-24.
- **Job B** (`team-list-polling.yml`) — fetches the current round's team list, writes `data/team_lists_current.csv` only within 1 hour of a match's kickoff. Self-contained, no dependency on Job A. Proven live end-to-end (2026-06-23).
- **cron-job.org external scheduler** (`schedule-kickoffs.yml`) — GitHub's native cron was confirmed unreliable for Job B's precision needs (real observed gaps of 1–5 hours, 2026-06-22). Replaced with cron-job.org: a weekly script reads real kickoff times and creates one precisely-timed trigger per match via cron-job.org's REST API. Confirmed live end-to-end (2026-06-23) — all 8 of Round 17's triggers fired correctly.
- Credentials (`CRONJOB_API_KEY`, `WORKFLOW_DISPATCH_TOKEN`) live as GitHub Actions repository secrets — never in chat or hardcoded.

See `STATUS.md` for full detail, known gotchas (e.g. cron-job.org's rate limit needing ~13s spacing between job-creation calls), and exact dates.

---

## ROADMAP (for context — full detail tracked in chat, not duplicated here)

Reordered 2026-06-22 — the ORIGINAL Phase 5 concept (daily late-mail scraping) was merged into Phase 3, since Job B's hourly-turned-precise team-list polling already covers and exceeds that scope. The phase NUMBER 5 was then reassigned to weekly digest notifications (built and proven live 2026-06-23) — these are two unrelated things that happen to share a number across the project's history; don't confuse them.

Phase 0 ✅ Data integrity | Phase 1 ✅ Current season caught up | Phase 2 ✅ GitHub repo | Phase 3 🔶 Weekly automation — Job A + Job B + cron-job.org scheduler all built and live-tested; full real-world cycle fired tonight, 20:00 UTC 2026-06-24 (check Actions log next session for the result) | Phase 4 🔶 try_minute capture — parser built and wired into the live scraper, not yet proven against a real finished round (same test tonight) | Phase 5 ✅ Digest notifications — built, fixed through 3 real bugs, proven live end-to-end | Phase 6 ✅ Live repo connection — repo made public, Claude reads raw files directly each session | Phase 7 ✅ Recency weighting — wired into the live digest pipeline, proven via real end-to-end test 2026-06-24 | Phase 8 🔶 Odds comparison & xTry model — `xtry_model.py` (the real 8-component formula, recovered after discovering its spec was never committed) and `edge_finder.py` both built, committed, and validated against real data 2026-06-24; still missing: live odds fetching (`odds_fetcher.py`), automation wiring, and the `totals` line-mismatch fix | Phase 9 ⬜ Dashboard (GitHub Pages)
