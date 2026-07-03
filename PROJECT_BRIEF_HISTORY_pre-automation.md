# ⚠️ ARCHIVED — PRE-AUTOMATION PROJECT BRIEF (SUPERSEDED)

> **Do not treat this file as current.** It describes the project as it
> stood **before** Phases 2–8 were built (before the GitHub repo, before
> any GitHub Actions automation, back when every weekly update was
> manual and Claude merged data by hand). It is kept **only** for its
> Phase 0 data-integrity history, which remains accurate and genuinely
> useful.
>
> **For the real, current state of the project, read `PROJECT_BRIEF.md`
> and `STATUS.md` — not this file.**
>
> Specifically, the following sections below are now FALSE and are
> retained only as historical record:
> - "Workflow established (currently manual, not yet automated)" — the
>   full scrape → validate → merge → digest cycle is now automated via
>   GitHub Actions (Job A / `weekly-update.yml`), running unattended.
>   Claude no longer merges data by hand.
> - "Nothing is automated yet" — four GitHub Actions workflows now run
>   the pipeline end to end.
> - "The scraper does not yet capture try-minute data" — try-minute
>   capture is fully coded (`parse_try_minutes.py`, wired into the merge
>   pipeline). (Its live population was still being verified as of
>   2026-07-03 — see STATUS.md — but it is built, not screenshot-based.)
> - "The recency-weighted baseline has been calculated but not yet
>   wired into live predictions" — it is now wired into xTry
>   Components 1 and 4 via `generate_predictions.py`, not just DUE WATCH.
> - The Roadmap below lists Phases 2, 3, 6, 7, 8 (and the odds
>   comparison work) as future — all have since shipped. Per the live
>   `PROJECT_BRIEF.md`, Phases 0–8 are complete; only the Phase 9
>   GitHub Pages dashboard remains open.
>
> Archived 2026-07-03. The Phase 0 section below is unaltered and
> remains a trustworthy record of the original data-integrity audit.

---

# NRL BET BOT V2 — PROJECT BRIEF & HISTORY

## Background — why this project exists

The original NRL Predictor system had grown organically over many sessions, accumulating files, naming conventions, and assumptions that were never fully audited against each other. A full data-integrity review was conducted before this V2 project began, and it found several real, previously-undetected problems. This project starts from validated ground truth, not from the old assumptions.

## What was found and fixed (Phase 0)

- Three inconsistent team-naming schemes existed across the data files simultaneously (e.g. "Knights" vs "Newcastle" vs "Newcastle Knights"). Fixed by creating team_aliases.json — a single canonical mapping every script and every session must use.
- Three inconsistent position-coding schemes similarly existed. Fixed via position_aliases.json.
- match_id was not a usable join key between the two main historical files — one file didn't even have a match_id column, and naive positional alignment between them drifted after about 40 rows. This was solved by deriving each match's score from summed player points and fingerprint-matching it against recorded scorelines, which resolved 852 of 860 matches (99%) unambiguously.
- 8 matches were excluded from the historical merge — these turned out to be the most recent 2026 fixtures in the old player-level file, which had zero player-points data (an incomplete scrape, not a join failure). Excluded rather than padded with placeholders.
- A genuine, previously undetected bug: the historical match-results file had all of 2026's round numbers shifted +1 from Round 2 onward, caused by the Las Vegas season-opener being mis-split into its own round. This was proven against real results (Storm's 52-4 win over Eels was actually Round 1, not Round 2 as the file claimed; Dragons' 16-62 loss to Roosters was actually Round 8, not Round 9) and corrected.
- The historical player-level file has no player names — only an opaque numeric player_id, with no lookup table anywhere in the project. This was confirmed unrecoverable at scale (757 unique IDs across ~29,000 rows; matching them by hand via screenshots isn't practical). Decision made: this file is retained for team-level and position-level historical baselines only (league-average tries-per-game by position, zone concede rates by team) — not for individual player history before 2026.
- A leftover bug in the scraper script was found and removed: it had a fallback URL for a "Dolphins v Rabbitohs" Round 13 match that could never have existed, since both those teams (plus the Titans) had a bye that round.

## Current data state (Phase 1 — complete)

- nrl_master.csv contains 2026 season data, player-level, every round scraped so far, validated round by round.
- Validation method for every new round: zero duplicate (player, team, round, season) rows; team coverage matches the official NRL draw's bye schedule exactly; try-count distributions are internally sensible (no impossible outliers); spot-checks against known scorelines where available (including catching a golden-point game correctly showing 83 minutes played, which is real, not an error).
- The historical baseline files (historical_player_match_rows.csv, historical_position_tpg_baseline.csv, historical_zcr_baseline.csv) cover 2021-2025 and are clean for team/position-level use.
- match_data_FINAL_fixed.csv has the round-numbering bug corrected and is otherwise validated.

## Workflow established

_(HISTORICAL — this manual workflow has been replaced by GitHub Actions automation. See STATUS.md.)_

Weekly data update (currently manual, not yet automated):

- Sam edits ROUND_TO_SCRAPE in nrl_update_single_round.py to the new round number and runs it locally.
- This produces a separate file (nrl_round_X_new.csv) — it does not touch nrl_master.csv directly, by design, so a bad scrape can never corrupt the existing validated data.
- Sam uploads that file plus the console output.
- Claude validates it (duplicates, bye-schedule coverage, internal consistency, scoreline spot-checks where possible) before merging it into nrl_master.csv and updating STATUS.md with a timestamp and summary of what changed.

Weekly predictions:

- Team lists are authoritative — no player receives a probability unless confirmed in that week's actual named squad.
- Sam provides team lists (and optionally scorecards/try-minute detail) each week; Claude runs the xTry model and returns structured predictions (win %, margin, confidence, top try scorers with reasoning and flags).

## Known limitations, stated honestly

_(HISTORICAL — several of these are now resolved; see the header notice at the top of this file.)_

- Individual player history before 2026 cannot be reconstructed (no name lookup exists for the historical player_id field). **(Still true.)**
- The scraper does not yet capture try-minute data automatically — this still relies on Sam's weekly screenshots. **(No longer true — try-minute capture is coded and wired in.)**
- Nothing is automated yet. Every update is manual: Sam runs the scraper, uploads results, Claude validates and merges. **(No longer true — fully automated via GitHub Actions.)**
- The recency-weighted historical baseline (2025 weighted 100%, 2024 at 75%, 2023 at 50%, per the original model spec) has been calculated but not yet wired into live predictions. **(No longer true — wired into xTry Components 1 and 4.)**

## Roadmap (full phased plan, agreed with Sam)

_(HISTORICAL — Phases 0–8 are now complete per the live PROJECT_BRIEF.md; only the Phase 9 dashboard remains. The phase numbering below differs slightly from the live brief's, another reason to defer to the live file.)_

- Phase 0 ✅ Historical data integrity audit and fixes (complete)
- Phase 1 ✅ Current 2026 season fully caught up and validated (complete, currently through Round 16)
- Phase 2 — Stand up a public GitHub repository as the single source of truth for all data, scripts, and workflows (folder structure: data/, scripts/, .github/workflows/, logs/)
- Phase 3 — Weekly automation: a GitHub Actions job that scrapes nrl.com every Thursday morning, validates the result, and commits it automatically. Also includes an accuracy ledger (logging predicted vs actual results week over week) and player heat/form tracking that persists over time.
- Phase 4 — Email notification when the weekly data is ready, including an auto-generated digest (biggest line movements, new DUE flags, notable ZCR shifts). Sam still manually triggers prediction generation; the automation only confirms data readiness.
- Phase 5 — A second, daily scraper for nrl.com's "late mail" team-list page, to catch lineup changes between rounds (page structure not yet reviewed — deferred until needed).
- Phase 6 — Claude reads data directly from the live GitHub repo (via raw file URLs) instead of requiring manual file uploads each session.
- Phase 7 — Properly wire the recency-weighted historical baselines (2025/2024/2023) into the live xTry model, replacing the current static, seemingly unweighted position-TPG table.
- Phase 8 — Add a try_minute column to the scraper's output so minute-of-try data persists automatically rather than depending on weekly screenshots.
- Phase 9 — A real, standalone, bookmarkable dashboard hosted via GitHub Pages (same repo), not just a chat-embedded artifact. Planned in two stages: first a static read-only dashboard (predictions, ladder, player trends, the accuracy ledger, ZCR heatmaps), then an interactive layer where Sam selects team lists directly in the interface and gets predictions back instantly, removing the need to paste team lists into chat.
- Phase 10 — TAB/Sportsbet odds comparison, to flag where the model's numbers diverge meaningfully from market odds. Starting manually (Sam pastes in odds) since betting sites are generally more resistant to scraping than nrl.com and may have terms of service against it; automation options to be investigated only once this phase is actually reached.

## Important standing instructions for whoever picks this up

_(These remain evergreen and still apply.)_

- Always normalise team names through team_aliases.json and positions through position_aliases.json — never hardcode either.
- Always read STATUS.md first in any new session to confirm what data is current before doing anything else.
- Never treat a new scrape as final until it's passed validation (duplicates, bye-schedule coverage, internal consistency).
- Be upfront about data limitations rather than papering over them — if something can't be verified or reconstructed, say so plainly and explain what would change if better data were available.
- Team lists override every other source for a given week's predictions.
