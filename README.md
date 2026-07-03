# NRL Bet Bot V2

A rigorous, data-driven NRL prediction and betting-intelligence system. Elo win/margin model + 8-component xTry try-scoring model + live Sportsbet odds comparison → weekly plain-English email digest + ranked bet recommendations with Kelly staking.

**For anyone picking this up:** read `STATUS.md` first, every session. It's the single source of truth for what data is current and what's broken.

---

## What it does

Every week, automatically:
1. **Thursday morning** — scrapes the finished round's player stats and match results, validates both, merges into the master data files
2. **~3 hours later** — generates predictions for the upcoming round: win probabilities, predicted margins, top try-scorer probabilities, DUE WATCH flags, value edges against Sportsbet prices
3. **Before each match** — re-checks team lists for late changes and captures closing odds for CLV (closing line value) tracking
4. **Email** — sends a plain-English digest to a non-technical end user summarising the round's key predictions and value bets

---

## How it works

### Data pipeline
- `nrl_master.csv` — player-level stats, 2026 season (scraped weekly from nrl.com via Selenium)
- `match_data_FINAL_fixed.csv` — match results 2021–2026 (scraped weekly)
- Historical baselines (`historical_position_tpg_baseline.csv`, `historical_zcr_baseline.csv`) — 2021–2025 team/position data for model priors

### Models
- **Elo** (`nrl_elo.py`) — win probability and predicted margin; 64.8% backtest accuracy, ±14pt MAE
- **xTry** (`xtry_model.py`) — 8-component try-scoring probability per player per game:
  1. Position-adjusted base TPG (minutes-reprojected, Bayesian-shrunk toward league average)
  2. Form momentum index (recent vs season TPG ratio)
  3. Involvement quality score (per-minute weighted stats blend)
  4. Zone concede rate (how many tries the opposition gives up at this position)
  5. Personnel context (home/away side, position group)
  6. Ruck speed factor (attacking PTB speed vs speed allowed by defence)
  7. Team attacking volume (season-wide try rate, home advantage scaled)
  8. Situational context (DUE flag severity, scored last game — 3 inputs still neutral pending data sources)

### Decision engine (`decision_engine.py`)
- Ranks all positive-edge try-scorer entries by EV
- Applies sample-size uncertainty penalty (`1/sqrt(n_games)`) — new players discounted heavily
- ¼ Kelly staking, 5% per-bet cap, 20% round exposure cap
- Same-match correlation discount (50%) for multiple bets in the same fixture
- Explicit `NO_POSITIVE_EV_BETS_FOUND` state when nothing clears the minimum edge threshold
- `manual_notes.json` — declared intangible adjustments, applied transparently

### Accuracy tracking (`score_predictions.py`)
- Correct winner %, margin MAE, DUE hit rate, edge hit rate
- Brier scores (our model vs market, for both winner and try-scorer markets)
- Prediction-time EV log with `closing_market_probability` back-filled near kickoff for CLV

---

## Repository structure

```
data/
  nrl_master.csv                          # Core player stats store
  match_data_FINAL_fixed.csv              # Match results (feeds Elo)
  historical_*.csv                        # Static baselines (2021-2025)
  team_aliases.json                       # CANONICAL team names — always use this
  position_aliases.json                   # CANONICAL position codes — always use this
  season_draw_2026.json                   # Fixture schedule (auto-extended)
  team_lists_current.csv                  # Latest team lists
  predictions_current.json                # Latest round's predictions
  predictions_history/                    # Immutable per-round archives
  accuracy_ledger.json                    # Rolling accuracy log
  betting_decisions.json                  # Decision engine output (advisory)
  manual_notes.json                       # Weekly intangibles (update before predictions run)

scripts/
  nrl_update_single_round.py              # Player stats scraper
  scrape_match_results.py                 # Match results scraper
  merge_round.py / merge_match_results_backfill.py  # Validation + merge
  scrape_team_lists.py                    # Team list scraper
  schedule_kickoff_triggers.py            # Creates cron-job.org per-match triggers
  nrl_elo.py                              # Elo model
  xtry_model.py                           # xTry model (8 components)
  edge_finder.py                          # xTry → bookmaker edge comparison
  decision_engine.py                      # Kelly staking + risk controls
  capture_closing_odds.py                 # CLV capture (near kickoff)
  generate_predictions.py                 # Main predictions orchestrator
  score_predictions.py                    # Accuracy ledger + Brier scores
  send_predictions_digest.py              # Email digest
  due_flags_v2.py                         # DUE WATCH composite scoring

.github/workflows/
  weekly-update.yml                       # Job A: Thursday stats + results scrape
  team-list-polling.yml                   # Job B: team lists + closing odds
  generate-predictions.yml                # Predictions + email
  schedule-kickoffs.yml                   # Creates per-match cron-job.org triggers
```

---

## Canonical standards

**Team names** — always full canonical form: "New Zealand Warriors", "Canterbury-Bankstown Bulldogs", "Cronulla-Sutherland Sharks", "Manly-Warringah Sea Eagles", "St George Illawarra Dragons". Full mapping in `team_aliases.json`. Never hardcode.

**Positions** — always codes: FB, WG, CE, FE, HB, HK, PR, 2RF, LK, IC. Full mapping in `position_aliases.json`. Never hardcode.

---

## Known limitations

- Pre-2026 individual player history is not recoverable (`player_id` in historical files has no name lookup)
- DUE WATCH has no injury-return modifier — pre-absence games count toward recent form
- `play_the_ball` count column is `0` for all rows — scraper fix pending (check R18 scrape log for `[P5 DIAG]` output)
- Calibration map (Platt/isotonic) blocked until mid-2027 — needs a full season of scored rounds
- Odds API: ~40 credits/round, ~160/month; 500/month budget; current headroom is comfortable

---

## Infrastructure

- **GitHub Actions** — four workflows handle all automation
- **cron-job.org** — external scheduler for precise per-match kickoff triggers (free tier; ~190 jobs/season capacity)
- **The Odds API** — bookmaker odds (Sportsbet, AU market; 500 credits/month budget)
- **Resend** — email delivery
- **Selenium** — required for JS-rendered nrl.com pages
