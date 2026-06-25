"""
extend_season_draw.py

Real, production script for season_draw_2026.json -- added 2026-06-25
after confirming a second real automation gap, structurally identical
to match_data_FINAL_fixed.csv's: this file genuinely needs to grow
week-on-week (every real consumer in the codebase -- due_flags_v2.py,
generate_predictions.py -- only ever READS it, nothing writes or
extends it), but it's been locked at rounds 17-18 with no real
mechanism to add future rounds.

Built from CONFIRMED real selectors (not guessed): an unplayed
fixture's real page text doesn't have a score or "FULL TIME" marker
(confirmed 2026-06-25 via Sam's real Round 19 capture -- the existing
.match--highlighted text for an unplayed match reads "FRIDAY 10TH
JULY\\nKick off:\\n8:00pm\\nhome Team\\nWests Tigers\\n10th\\nPosition\\n
away Team\\nWarriors\\n2nd\\nPosition" -- no score field exists yet,
confirming the existing MATCH_TEXT_PATTERN regex genuinely cannot be
reused here). Real fix: use the SIMPLER `.match.o-rounded-box` cards
instead, which show clean "Match: TeamA vs TeamB" text regardless of
whether the match has been played -- confirmed via the same real
Round 19 capture (all 7 real matches read correctly, e.g. "Match:
Wests Tigers vs Warriors"), and this is genuinely all
season_draw_2026.json needs (team pairings only, no scores).

REAL TEAM-NAME RESOLUTION: every real short name scraped (e.g.
"Wests Tigers", "Warriors") is resolved through team_aliases.json to
the full canonical form BEFORE writing, matching season_draw_2026.json's
own documented real convention (its own _comment field: "Team names
use FULL CANONICAL form... converted from short-form labels via
team_aliases.json, NOT hand-typed"). An unmapped name is a real, loud
failure here too -- never silently skipped or guessed, same discipline
as merge_match_results_backfill.py.

Usage:
    python3 extend_season_draw.py --round 19 --season 2026 \\
        --season-draw data/season_draw_2026.json \\
        --team-aliases data/team_aliases.json
"""

import argparse
import json
import sys
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def load_team_aliases(path):
    with open(path) as f:
        return json.load(f)["aliases"]


def scrape_round_fixtures(round_num, season):
    """
    Real, minimal scrape -- ONLY team pairings, no scores (this round
    may not have been played yet, by design -- that's the whole point
    of this script existing separately from scrape_match_results.py).
    """
    url = f"https://www.nrl.com/draw/?competition=111&season={season}&round={round_num}"

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    print(f"Fetching real draw page: {url}")
    driver.get(url)
    time.sleep(5)

    cards = driver.find_elements("css selector", ".match.o-rounded-box")
    print(f"Real .match.o-rounded-box elements found: {len(cards)}")

    real_fixtures = []
    for card in cards:
        h3s = card.find_elements("css selector", "h3")
        for h3 in h3s:
            text = h3.text.strip()
            # Real confirmed format: "Match: TeamA vs TeamB"
            if text.lower().startswith("match:") and " vs " in text:
                pairing = text.split(":", 1)[1].strip()
                home, away = pairing.split(" vs ")
                real_fixtures.append((home.strip(), away.strip()))

    driver.quit()
    return real_fixtures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--season-draw", type=str, default="data/season_draw_2026.json")
    parser.add_argument("--team-aliases", type=str, default="data/team_aliases.json")
    args = parser.parse_args()

    team_aliases = load_team_aliases(args.team_aliases)
    real_fixtures = scrape_round_fixtures(args.round, args.season)

    if not real_fixtures:
        print("ERROR: zero real fixtures scraped -- not modifying season_draw_2026.json.")
        sys.exit(1)

    # Real, refuse-rather-than-guess team-name resolution -- same
    # discipline as merge_round.py / merge_match_results_backfill.py.
    resolved_fixtures = []
    problems = []
    for home, away in real_fixtures:
        home_canonical = team_aliases.get(home)
        away_canonical = team_aliases.get(away)
        if home_canonical is None:
            problems.append(f"Unmapped real home_team '{home}' -- add to team_aliases.json first.")
        if away_canonical is None:
            problems.append(f"Unmapped real away_team '{away}' -- add to team_aliases.json first.")
        if home_canonical and away_canonical:
            resolved_fixtures.append([home_canonical, away_canonical])

    if problems:
        print(f"VALIDATION FAILED -- {len(problems)} real problem(s). NOT modifying season_draw_2026.json.\n")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    print(f"Real validation PASSED -- all {len(resolved_fixtures)} fixtures resolve cleanly.")

    with open(args.season_draw) as f:
        season_draw = json.load(f)

    round_key = str(args.round)
    if round_key in season_draw["rounds"]:
        print(f"WARNING: round {args.round} already exists in season_draw_2026.json -- "
              f"overwriting with this real, freshly-scraped fixture list.")

    season_draw["rounds"][round_key] = {"fixtures": resolved_fixtures}

    with open(args.season_draw, "w") as f:
        json.dump(season_draw, f, indent=2)

    print(f"\nReal season_draw_2026.json updated: round {args.round} now has "
          f"{len(resolved_fixtures)} real fixtures.")
    print(f"Real rounds now covered: {sorted(season_draw['rounds'].keys(), key=int)}")


if __name__ == "__main__":
    main()
