# NRL BET BOT V2 — PROJECT BRIEF
_Read STATUS.md first, every session, before doing anything else._

---

## WHAT THIS PROJECT IS

A rigorous, data-driven NRL prediction system (Elo-based win/margin model + 8-component xTry try-scoring model + real bookmaker odds comparison) built on data that has actually been validated — not assumed. This project replaces the old NRL_Predictor setup after a full data-integrity audit found and fixed several silent bugs (see "Known Issues Fixed" in STATUS.md).

**Institutional memory note (2026-06-24)**: the actual xTry formula spec (`NRL_MASTER_PROMPT_V2.md`) was discovered to have never been committed to this repo, despite being cited by name elsewhere in this very file. Recovered directly from Sam and reconstructed as `xtry_model.py`. **Lesson: a citation is not a committed artifact — verify files exist before trusting that they're real.**

**Institutional memory note (2026-06-25)**: `match_data_FINAL_fixed.csv` had exactly one real commit — silently stale for 6+ rounds while its sibling file updated weekly. **Lesson: "this file exists and looks fine" is not the same as "this file is being kept current" — check each data file's own commit history independently.**

**Institutional memory note (2026-07-03/04)**: `generate-predictions.yml` was accidentally overwritten with Python source twice in two sessions (the second time being the same class of wrong-file-paste as the 2026-06-25 `weekly-update.yml` incident). **Lesson: after uploading any file via the GitHub web UI, immediately check the committed file's first line. If it's not what you expect, revert before the next workflow run finds it.**

---

## FILES IN THIS PROJECT

### Data files (`data/`)
| File | What it is | Use for |
|---|---|---|
| `nrl_master.csv` | 2026 season, player-level, all rounds scraped so far | All current-season xTry calculations |
| `match_data_FINAL_fixed.csv` | Match results 2021–2026 (scores, venue, weather, attendance) | Elo ratings, win probability, predicted margin, h2h history, form streaks |
| `historical_player_match_rows.csv` | 2021–2025, player-level, **no player names** (opaque player_id only) | Team/position-level baselines ONLY — never individual player history |
| `historical_position_tpg_baseline.csv` | League-average TPG by position, by season (2021–2025) | xTry Component 1 position normalisation |
| `historical_zcr_baseline.csv` | Tries conceded by team by position (2021–2025) | Zone Concede Rate (xTry Component 4) |
| `team_aliases.json` | Canonical team name mapping | ALWAYS use to normalise team names — never hardcode |
| `position_aliases.json` | Canonical position code mapping | ALWAYS use to normalise positions |
| `season_draw_2026.json` | NRL season fixture pairings by round | Opponent-matchup factor, h2h/form lookups — auto-extended weekly with 2-round buffer |
| `team_lists_current.csv` | Most recent real team-list scrape | Resolving each week's actual starting squad |
| `predictions_current.json` | Latest round's predictions | Source for digest email and decision engine |
| `predictions_history/{season}_round_{N}.json` | Immutable per-round predictions archive | Scored by `score_predictions.py` after results merge |
| `accuracy_ledger.json` | Rolling accuracy log (one entry per scored round) | Brier scores, winner %, margin MAE, edge hit rates — built up over the season |
| `betting_decisions.json` | Decision engine output — ranked bets with Kelly stakes | Advisory only — Sam reviews before acting |
| `manual_notes.json` | Stage 5 intangibles — declared manual adjustments | Applied transparently at decision layer; update each round |

### Scripts (`scripts/`)
| File | What it does |
|---|---|
| `nrl_update_single_round.py` | Player-stats scraper. Has P5 DIAG block to identify `play_the_ball` header — check R18 log for `[P5 DIAG]` output |
| `scrape_match_results.py` | Match-results scraper (scores, venue, weather, attendance) |
| `merge_match_results_backfill.py` | Validates + merges match results |
| `validate_round.py` / `merge_round.py` | Validation gate + safe merge for player stats |
| `scrape_team_lists.py` / `parse_team_list.py` / `parse_draw_link_text.py` / `find_team_list_url.py` | Job B team-list scraping |
| `schedule_kickoff_triggers.py` | Creates per-match cron-job.org triggers. Now passes `fixture`/`round`/`season` inputs for closing odds capture |
| `extend_season_draw.py` | Extends `season_draw_2026.json` buffer |
| `nrl_elo.py` | Elo rating system | 64.8% real backtest accuracy, ±14pt MAE |
| `xtry_model.py` | 8-component xTry formula. Component 1 uses minutes reprojection (2026-07-04); `n_games` exposed for uncertainty penalty |
| `odds_fetcher.py` | Live odds via the-odds-api.com (Sportsbet-filtered for try-scorer since 2026-07-04) |
| `edge_finder.py` | Connects xTry output to bookmaker odds. Passes `n_games` through for uncertainty penalty |
| `odds_probability.py` | Probability / edge maths |
| `due_flags_v2.py` | Composite DUE WATCH scoring |
| `generate_predictions.py` | Main predictions pipeline — Elo, xTry, odds, DUE WATCH, h2h, form. Calls decision engine as best-effort step |
| `decision_engine.py` | Stage 4 decision + risk engine — ranked EV, ¼ Kelly, uncertainty penalty, exposure cap, same-match discount, `NO_POSITIVE_EV_BETS_FOUND` state |
| `capture_closing_odds.py` | Stage 4 CLV capture — re-fetches Sportsbet odds ~1h before kickoff, back-fills `closing_market_probability` and `clv` into predictions archive |
| `score_predictions.py` | Accuracy scoring — correct winner %, margin MAE, DUE hit rate, edge hit rate, Brier scores (ours vs market), prediction-time EV log |
| `send_predictions_digest.py` | Builds and sends weekly predictions email |
| `recency_weighted_baselines.py` | Phase 7 recency-weighted TPG and ZCR baselines |
| `generate_round_digest.py` / `send_round_digest.py` | Round data digest (DUE flags, form, notable changes) |
| `STATUS.md` | **Read this first every session** |

### Workflows (`.github/workflows/`)
| File | Trigger | What it does |
|---|---|---|
| `weekly-update.yml` | Thursday 20:00 UTC | Job A: scrape R+1 player stats + match results, validate, merge, extend season draw |
| `team-list-polling.yml` | Tuesday 06:10 UTC + cron-job.org per-match | Job B: team lists + closing odds capture (kickoff only) |
| `generate-predictions.yml` | Thursday 23:00 UTC + `workflow_dispatch` | Predictions, digest email, decision engine |
| `schedule-kickoffs.yml` | Tuesday + Wednesday | Creates cron-job.org triggers for each match |

---

## CANONICAL STANDARDS (locked in, do not deviate)

**Team names** — full canonical names: "New Zealand Warriors", "Canterbury-Bankstown Bulldogs", "Cronulla-Sutherland Sharks", "Manly-Warringah Sea Eagles", "St George Illawarra Dragons". Full mapping in `team_aliases.json`.

**Positions** — codes: FB, WG, CE, FE, HB, HK, PR, 2RF, LK, IC. Full mapping in `position_aliases.json`.

---

## WEEKLY WORKFLOW — fully automated

**Tuesday ~4:10pm AEST**: Job B baseline scrape captures round's initial team lists.

**Thursday morning (Job A)**: scrapes the finished round's player stats AND match results, validates independently, merges each, extends `season_draw_2026.json`. Any failure = GitHub Issue + file untouched.

**~3 hours after Job A**: predictions generate, sanity-checked, email sends. Decision engine writes `betting_decisions.json` (best-effort).

**Throughout the week**: cron-job.org fires 1h before each kickoff — updates team lists AND captures closing odds for CLV.

**What Sam does manually**: nothing in the normal case. Action needed when a GitHub Issue appears, or to update `manual_notes.json` with any intangibles before the predictions run.

---

## DATA QUALITY RULES (non-negotiable)

- Always divide tries by games actually appeared in, never by rounds elapsed
- DUE flag base rate uses season TPG, not recent-drought-period TPG
- A player must be in the week's real resolved squad to appear in DUE WATCH or try-scorer predictions
- Team lists override all other sources for jersey numbers/positions
- Never fabricate data — unknown = say so and explain what would change if known
- `historical_player_match_rows.csv` has no player names — do not attempt individual cross-season player tracking from it
- Try-scorer edges are Sportsbet prices only — do not compare against other bookmakers

---

## KNOWN LIMITATIONS (be upfront about these)

- Pre-2026 individual player history is not recoverable (no name lookup for `player_id`)
- DUE WATCH has no injury-return modifier — pre-absence games count toward recent form
- `play_the_ball` column is `'0'` for all rows — scraper captures the speed string correctly but the count column maps to the wrong header; fix pending P5 DIAG log from R18 scrape
- Calibration map (Platt/isotonic) is blocked until mid-2027 — one season of scored rounds needed before fitting
- `EXPECTED_BYES` (match-results validation) only covers rounds 11–17 — extends round-by-round
- Tuesday baseline scrape drifts 1h at daylight-saving transitions (early April / early October)
- `totals` (over/under) line-mismatch across bookmakers — real, unsolved
- CLV is `null` until the first R18 kickoff trigger fires with the new dispatch inputs
- Odds API budget: 500 credits/month. Current usage: ~40 credits/round (24 predictions + 16 closing) = ~160/month with 4 rounds. Comfortable headroom.

---

## AUTOMATION STATUS (as of 2026-07-04)

- **Job A** (`weekly-update.yml`) ✅ — player stats + match results + season draw extension, all validated
- **Job B** (`team-list-polling.yml`) ✅ — Tuesday baseline + near-kickoff updates + closing odds capture (new)
- **Predictions pipeline** (`generate-predictions.yml`) ✅ — Sportsbet-filtered edges, decision engine, content-based sanity check
- **Decision engine** (`decision_engine.py`) ✅ — ¼ Kelly, uncertainty penalty, exposure cap, same-match discount
- **Accuracy ledger** (`score_predictions.py`) ✅ — Brier scores, prediction-time EV log, cumulative summary
- **CLV pipeline** ✅ — closing odds captured near kickoff, `clv` field back-filled into predictions archive

---

## ROADMAP

Phase 0 ✅ Data integrity | Phase 1 ✅ Current season caught up | Phase 2 ✅ GitHub repo | Phase 3 ✅ Weekly automation | Phase 4 ✅ try_minute parser built (live validation pending R18 scrape log) | Phase 5 ✅ Digest notifications | Phase 6 ✅ Live repo connection | Phase 7 ✅ Recency weighting | Phase 8 ✅ Odds comparison, xTry model, edge-finding, DUE WATCH, decision engine, CLV pipeline | Phase 9 ⬜ Dashboard (GitHub Pages) — not yet started

**Model improvement stages (per architect doc, 2026-07-04):**
- Stage 1 ✅ Wire dead xTry components (Component 8 context + Component 1 minutes reprojection)
- Stage 2 ✅ Brier scores + prediction-time EV log
- Stage 3 ✅ Uncertainty penalty (n_games discount); full calibration map blocked until mid-2027
- Stage 4 ✅ Decision engine + CLV pipeline; Sportsbet-only filter
- Stage 5 ✅ manual_notes.json intangibles layer
- Remaining: `play_the_ball` scraper fix (awaiting P5 DIAG log), DUE WATCH injury-return modifier, calibration map
