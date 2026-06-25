# NRL BET BOT V2 — PROJECT BRIEF
_Read STATUS.md first, every session, before doing anything else._

---

## WHAT THIS PROJECT IS

A rigorous, data-driven NRL prediction system (Elo-based win/margin model + xTry try-scoring model + real bookmaker odds comparison) built on data that has actually been validated — not assumed. This project replaces the old NRL_Predictor setup after a full data-integrity audit found and fixed several silent bugs (see "Known Issues Fixed" in STATUS.md).

**Institutional memory note (2026-06-24)**: the actual xTry formula spec (`NRL_MASTER_PROMPT_V2.md`) was discovered to have never been committed to this repo, despite being cited by name elsewhere in this very file. Recovered directly from Sam and reconstructed as `xtry_model.py`. **Lesson for future sessions: if a doc cites a spec or file by name, confirm that file actually exists in the repo before trusting that the citation means the thing is real and available — a citation is not the same as a committed artifact.**

**Institutional memory note (2026-06-25)**: `match_data_FINAL_fixed.csv` was discovered to have exactly one real commit, ever — a one-time upload that was never refreshed by any automation, while every other data file had genuine weekly automation. It silently fed every Elo rating, win probability, and margin prediction for 6+ rounds before being caught, via a direct, real symptom (a predictions email claiming a team was "red-hot" when the public ladder showed the opposite). **Lesson for future sessions: "this file exists and looks fine" is not the same as "this file is actually being kept current" — check each data file's own real commit/update history independently, don't assume parity just because a sibling file is automated.** Also discovered the same session: `weekly-update.yml` was accidentally overwritten with unrelated email text across three separate commits before anyone noticed (each commit's workflow run failed with an identical YAML syntax error, which is what surfaced it). **Lesson: after uploading a file via the GitHub web UI, a quick look at the first few lines of the committed result catches a wrong-file mistake immediately — waiting for a workflow run to fail is a much slower way to find out.**

---

## FILES IN THIS PROJECT

| File | What it is | Use for |
|---|---|---|
| `nrl_master.csv` | 2026 season, player-level, all rounds scraped so far | All current-season xTry calculations |
| `match_data_FINAL_fixed.csv` | Match results 2021-2026 (scores, venue, weather, attendance) | Elo ratings, win probability, predicted margin, h2h history, recent-form streaks |
| `historical_player_match_rows.csv` | 2021-2025, player-level, **no player names** (opaque player_id only) | Team/position-level baselines ONLY — not individual player history |
| `historical_position_tpg_baseline.csv` | League-average TPG by position, by season (2021-2025) | Position normalisation in xTry Component 1 |
| `historical_zcr_baseline.csv` | Tries conceded by team by position (2021-2025) | Zone Concede Rate (xTry Component 4) baseline |
| `team_aliases.json` | Canonical team name mapping | ALWAYS use this to normalise team names — never hardcode |
| `position_aliases.json` | Canonical position code mapping | ALWAYS use this to normalise positions |
| `season_draw_2026.json` | NRL season fixture pairings by round | Opponent-matchup factor (DUE WATCH), h2h/form lookups — auto-extended weekly with a 2-round buffer |
| `team_lists_current.csv` | Most recent real team-list scrape | Resolving each week's actual starting squad — only exists once a real scrape has fired for the current round |
| `nrl_update_single_round.py` | Player-stats scraper | Job A, weekly automation |
| `scrape_match_results.py` | Match-results scraper (scores, venue, weather, attendance) | Job A, weekly automation — added 2026-06-25 after `match_data_FINAL_fixed.csv` was found to be silently stale |
| `merge_match_results_backfill.py` | Validates + merges match results | Job A, weekly automation — also used for the real Round 11-16 backfill |
| `validate_round.py` / `merge_round.py` | Validation gate + safe merge logic for player stats | Weekly automation |
| `scrape_team_lists.py` / `parse_team_list.py` / `parse_draw_link_text.py` / `find_team_list_url.py` | Job B — team-list scraping | Weekly automation: Tuesday baseline scrape (added 2026-06-25) + near-kickoff updates |
| `schedule_kickoff_triggers.py` | Creates precise per-match triggers via cron-job.org | Weekly automation — made idempotent 2026-06-25 after a real duplicate-trigger bug |
| `extend_season_draw.py` | Extends `season_draw_2026.json` with upcoming real fixtures | Weekly automation — added 2026-06-25 |
| `nrl_elo.py` | Validated Elo rating system | Win probability, predicted margin — 64.8% real backtest accuracy, ±14pt MAE |
| `xtry_model.py` | The 8-component xTry formula | Per-player try-scoring probability |
| `odds_fetcher.py` | Live odds via the-odds-api.com | h2h, anytime try-scorer, spreads markets |
| `edge_finder.py` | Connects `xtry_model.py`'s output to real bookmaker odds | Finds genuine value (our probability vs market probability) |
| `due_flags_v2.py` | Composite DUE WATCH scoring (drought + opponent matchup + team form + usage trend + structure share) | Now cross-checked against each week's real resolved squad (2026-06-25 fix) — see its own header comment for the full real-data-driven design history |
| `generate_predictions.py` | Round-level orchestration | The main predictions pipeline — combines Elo, xTry, odds, DUE WATCH, h2h, form |
| `send_predictions_digest.py` | Builds and sends the weekly predictions email | Includes a real, content-based pre-send sanity check (added 2026-06-25) |
| `STATUS.md` | Live checkpoint — data freshness, known issues, outstanding gaps | Read FIRST every session |

---

## CANONICAL STANDARDS (locked in, do not deviate)

**Team names** — full names, e.g. "New Zealand Warriors", "Canterbury-Bankstown Bulldogs", "Cronulla-Sutherland Sharks", "Manly-Warringah Sea Eagles", "St George Illawarra Dragons". Full mapping in `team_aliases.json`.

**Positions** — codes: FB, WG, CE, FE, HB, HK, PR, 2RF, LK, IC. Full mapping in `position_aliases.json`.

---

## WEEKLY WORKFLOW — fully automated as of 2026-06-25

**Tuesday ~4:10pm AEST**: Job B's new baseline scrape captures the round's just-announced team lists.

**Thursday morning (Job A)**: scrapes the just-finished round's player stats AND match results, validates both independently, merges each on a clean pass, then extends `season_draw_2026.json`'s buffer. Any failure opens a GitHub Issue and leaves the relevant file untouched.

**~3 hours after Job A**: predictions generate from the now-current data, pass a real content-based sanity check, and the weekly email sends.

**Throughout the week**: cron-job.org fires a precise, idempotent trigger 1 hour before each match's kickoff, re-checking for late team-list changes.

**What Sam does manually**: nothing in the normal weekly case. Only needed when a GitHub Issue appears, or for occasional manual extension of `EXPECTED_BYES` (match-results validation) as new rounds are played.

---

## DATA QUALITY RULES (non-negotiable)

- Always divide tries by games actually appeared in, never by rounds elapsed
- DUE flag base rate uses season TPG, not recent-drought-period TPG
- A player must be in that week's real resolved squad to be eligible for DUE WATCH or try-scorer predictions — historical activity alone is not enough (2026-06-25 fix)
- Team lists override all other sources for jersey numbers/positions
- Never fabricate data — if something's unknown, say so and explain what would change if known
- `historical_player_match_rows.csv` has no player names — do not attempt individual cross-season player tracking from it

---

## KNOWN LIMITATIONS (be upfront about these, don't paper over them)

- Pre-2026 individual player history is not recoverable (no name lookup exists for `player_id`)
- DUE WATCH has no "returning from injury/absence" modifier — pre-absence games can still count toward "recent form" once a player returns, since the games-played window has no concept of real elapsed time
- `EXPECTED_BYES` (match-results validation safety net) only covers rounds 11–17 — degrades gracefully but stops actively protecting beyond that until extended
- The Tuesday baseline scrape uses a fixed UTC cron tuned for AEST — drifts an hour around daylight-saving changes
- The repo is public (since 2026-06-23) specifically so Claude can read live files directly each session — confirmed no secrets have ever lived in committed files, only as GitHub Actions repository secrets
- `totals` (over/under) line-mismatch problem (different bookmakers quoting different lines for the same match) — confirmed real, still unsolved
- `play_the_ball` column is `'0'` for every row in `nrl_master.csv` — the scraper believes it's capturing this column but isn't; not yet investigated independently

---

## AUTOMATION STATUS (as of 2026-06-25)

- **Job A** (`weekly-update.yml`) — player stats AND match results, both validated and merged independently; also extends `season_draw_2026.json`'s buffer. Real bugs found and fixed this session: missing `beautifulsoup4` dependency, a YAML/bash/Python indentation conflict, and a mid-loop failure that was being silently swallowed in the season-draw extension logic (caught by deliberately testing a simulated failure before trusting it).
- **Job B** (`team-list-polling.yml`) — now has TWO real real-world triggers: the Tuesday baseline (new) and the precise near-kickoff updates (existing). Closes a genuine, previously-unaddressed gap where no team list existed at all for most of the week.
- **cron-job.org external scheduler** (`schedule-kickoffs.yml`) — made idempotent after a real, confirmed duplicate-trigger bug (Tuesday + Wednesday safety-net runs had no check for already-existing jobs, silently doubling every trigger weekly).
- **Predictions pipeline** (`generate-predictions.yml`) — now has a real, content-based pre-send sanity check, on top of the existing exception-based checkpoints.

See `STATUS.md` for full detail, exact dates, and the complete list of real bugs found and fixed.

---

## ROADMAP

Phase 0 ✅ Data integrity | Phase 1 ✅ Current season caught up | Phase 2 ✅ GitHub repo | Phase 3 ✅ Weekly automation (player stats + match results + team lists + cron-job.org scheduler, all idempotent and validated) | Phase 4 🔶 try_minute capture — parser built, not yet proven against a real finished round through the live pipeline | Phase 5 ✅ Digest notifications | Phase 6 ✅ Live repo connection | Phase 7 ✅ Recency weighting | Phase 8 ✅ Odds comparison & xTry model — Elo, xTry, edge-finding, and DUE WATCH all live and wired into weekly automation | Phase 9 ⬜ Dashboard (GitHub Pages) — not yet started
