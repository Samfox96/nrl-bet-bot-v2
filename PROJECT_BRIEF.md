# NRL BET BOT V2 — PROJECT BRIEF
_Read STATUS.md first, every session, before doing anything else._

---

## WHAT THIS PROJECT IS

A rigorous, data-driven NRL prediction system (xTry model: win probability, margin, try scorer odds) built on data that has actually been validated — not assumed. This project replaces the old NRL_Predictor setup after a full data-integrity audit found and fixed several silent bugs (see "Known Issues Fixed" in STATUS.md).

---

## FILES IN THIS PROJECT

| File | What it is | Use for |
|---|---|---|
| `nrl_master.csv` | 2026 season, player-level, all rounds scraped so far | All current-season xTry calculations |
| `historical_player_match_rows.csv` | 2021-2025, player-level, **no player names** (opaque player_id only) | Team/position-level baselines ONLY — not individual player history |
| `historical_position_tpg_baseline.csv` | League-average TPG by position, by season (2021-2025) | Position normalisation in xTry Component 1 |
| `historical_zcr_baseline.csv` | Tries conceded by team by position (2021-2025) | Zone Concede Rate (xTry Component 4) baseline |
| `match_data_FINAL_fixed.csv` | Match results 2021-2026, round numbers corrected | Historical match context, H2H |
| `team_aliases.json` | Canonical team name mapping | ALWAYS use this to normalise team names — never hardcode |
| `position_aliases.json` | Canonical position code mapping | ALWAYS use this to normalise positions |
| `nrl_update_single_round.py` | Scraper — scrapes ONE round at a time | Weekly update workflow |
| `STATUS.md` | Live checkpoint — data freshness, known issues, outstanding gaps | Read FIRST every session |

---

## CANONICAL STANDARDS (locked in, do not deviate)

**Team names** — full names, e.g. "New Zealand Warriors", "Canterbury-Bankstown Bulldogs", "Cronulla-Sutherland Sharks", "Manly-Warringah Sea Eagles", "St George Illawarra Dragons". Full mapping in `team_aliases.json`.

**Positions** — codes: FB, WG, CE, FE, HB, HK, PR, 2RF, LK, IC. Full mapping in `position_aliases.json`.

---

## WEEKLY WORKFLOW

1. Sam runs `nrl_update_single_round.py` after changing `ROUND_TO_SCRAPE` to the new round number
2. Output is a SEPARATE file (`nrl_round_X_new.csv`) — does NOT touch `nrl_master.csv` automatically
3. Sam uploads that file + console output
4. Claude validates: zero duplicates, team coverage matches official bye schedule, internal consistency (try distribution, minutes played), spot-check against known scores where possible
5. Only after validation passes does Claude merge it into `nrl_master.csv` and update `STATUS.md`
6. Sam provides team lists for the upcoming round — team lists are AUTHORITATIVE, no player gets a probability unless confirmed in the named sheet
7. Claude runs xTry model predictions

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
- `try_minute` data is not yet captured by the scraper — still relies on Sam's weekly screenshots
- No automation yet — everything is manual (Sam runs scraper, uploads, Claude validates/merges)
- Recency-weighted historical baselines (2025=100%/2024=75%/2023=50%) are built but not yet wired into live model calculations

---

## ROADMAP (for context — full detail tracked in chat, not duplicated here)

Phase 0 ✅ Data integrity | Phase 1 ✅ Current season caught up | Phase 2 GitHub repo | Phase 3 Weekly automation | Phase 4 Notifications | Phase 5 Daily late mail | Phase 6 Live repo connection | Phase 7 Recency weighting | Phase 8 try_minute capture | Phase 9 Dashboard (GitHub Pages) | Phase 10 TAB/Sportsbet comparison
