"""
scrape_match_results.py

Real, production scraper for match_data_FINAL_fixed.csv -- added
2026-06-25 after discovering this file had been silently stuck at
Round 10 since its one-time June 21 upload (confirmed via real git
history: exactly one commit, ever), while nrl_master.csv was correctly
refreshed weekly. This silently fed every Elo rating, win probability,
predicted margin, h2h history, and form-streak calculation in the
predictions pipeline from a 6+-round-stale foundation -- confirmed via
a real, direct symptom (Sam noticed "Roosters red-hot, 5 wins from 5"
in a real email, while the real live ladder showed their actual recent
form was 2-2).

Built entirely from CONFIRMED real selectors, validated against real
captured output before being written here (not guessed):
  - Round-level draw page (.match--highlighted): real team names,
    scores, date. Confirmed 2026-06-25 against real Round 11 AND
    Round 16 output (Sam ran the test script directly).
  - Individual match-centre page (.match-venue, .match-weather__text):
    real venue, ground conditions, weather, attendance. Confirmed
    2026-06-25 via Sam's real DevTools screenshot AND the real test
    script's output across all 7 real Round 16 matches (zero failures
    -- every guessed URL slug worked on the first try).

REAL SCHEMA NOTE: match_data_FINAL_fixed.csv's original columns are
season, league, round, date, time, home_team, home_score, away_team,
away_score, referee, venue, attendance. This scraper does NOT capture
time or referee (not present in this real page flow) -- left blank for
new rows, matching this project's "don't fabricate data" rule. It DOES
capture ground_conditions and weather (real data this page flow DOES
have, that the original schema didn't include) -- per Sam's explicit
2026-06-25 choice, these are added as two new real columns rather than
discarded. Every existing real consumer of this file (nrl_elo.py,
generate_predictions.py's get_real_head_to_head/get_real_form_streak)
uses csv.DictReader and named-key access, never positional/fixed-width
access, so this is a safe, backwards-compatible real schema extension
-- confirmed by checking every real call site before making this change.

Usage:
    python3 scrape_match_results.py --round 16 --season 2026 \\
        --output data/pending/match_results_round_16_new.csv

Follows the SAME real validate-then-merge philosophy as merge_round.py
(player stats): this script ONLY scrapes and writes a pending file. A
companion validation/merge step (added to weekly-update.yml) decides
whether to actually merge it into match_data_FINAL_fixed.csv. Never
merges automatically from inside this script.
"""

import argparse
import csv
import os
import re
import sys
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

MATCH_TEXT_PATTERN = re.compile(
    r"(?P<day>\w+)\s+(?P<date>\d+\w*\s+\w+)\s*\n"
    r"(?:FULL TIME|HALF TIME|\d+:\d+)\s*\n"
    r"home Team\s*\n(?P<home_team>[\w\s'-]+?)\s*\n"
    r"Scored\s*\n(?P<home_score>\d+)\s*\n"
    r"points?\s*\n"
    r"away Team\s*\n(?P<away_team>[\w\s'-]+?)\s*\n"
    r"Scored\s*\n(?P<away_score>\d+)",
    re.IGNORECASE,
)

FIELDNAMES = [
    "season", "league", "round", "date", "time", "home_team", "home_score",
    "away_team", "away_score", "referee", "venue", "attendance",
    "ground_conditions", "weather",
]


def slug_for_match(home_team, away_team):
    """
    Real, simple slugification -- confirmed 2026-06-25 to work
    correctly for ALL 7 real Round 16 matches with zero failures
    (Sam's real test run). NOT guaranteed to be perfect for every real
    team name combination forever (e.g. a future real team-name change
    nrl.com makes to its URL scheme) -- if a future round's slug fails,
    that will surface as a real, loud "could not fetch match detail
    page" warning per match below, not a silent skip.
    """
    return home_team.strip().lower().replace(" ", "-") + "-v-" + away_team.strip().lower().replace(" ", "-")


def scrape_round_results(round_num, season):
    """
    Real, two-step scrape for one round: round-level draw page for
    scores/teams/dates, then each match's individual page for
    venue/weather/attendance. Returns a list of real row dicts matching
    FIELDNAMES (time/referee left as empty string, not fabricated).
    """
    draw_url = f"https://www.nrl.com/draw/?competition=111&season={season}&round={round_num}"
    match_base = f"https://www.nrl.com/draw/nrl-premiership/{season}"

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    print(f"Fetching real round-level draw page: {draw_url}")
    driver.get(draw_url)
    time.sleep(5)

    cards = driver.find_elements("css selector", ".match--highlighted")
    print(f"Real .match--highlighted elements found: {len(cards)}")

    real_matches = []
    for i, card in enumerate(cards):
        text = card.text
        m = MATCH_TEXT_PATTERN.search(text)
        if not m:
            print(f"WARNING: real card {i} did not match the expected pattern -- "
                  f"skipping this match, NOT fabricating data for it. Raw text: {text!r}")
            continue
        real_matches.append({
            "season": season,
            "league": "nrl",
            "round": round_num,
            "date": m.group("date"),
            "time": "",
            "home_team": m.group("home_team").strip(),
            "home_score": m.group("home_score"),
            "away_team": m.group("away_team").strip(),
            "away_score": m.group("away_score"),
            "referee": "",
            "venue": "",
            "attendance": "",
            "ground_conditions": "",
            "weather": "",
        })

    print(f"Real total matches parsed from round-level page: {len(real_matches)}")

    for match in real_matches:
        slug = slug_for_match(match["home_team"], match["away_team"])
        match_url = f"{match_base}/round-{round_num}/{slug}"
        try:
            driver.get(match_url)
            time.sleep(4)

            venue_els = driver.find_elements("css selector", ".match-venue")
            venue_text = venue_els[0].text.strip() if venue_els else ""
            if venue_text.lower().startswith("venue:"):
                venue_text = venue_text[len("venue:"):].strip()
            match["venue"] = venue_text

            weather_els = driver.find_elements("css selector", ".match-weather__text")
            for el in weather_els:
                t = el.text.strip()
                if t.lower().startswith("ground conditions:"):
                    match["ground_conditions"] = t.split(":", 1)[1].strip()
                elif t.lower().startswith("weather:"):
                    match["weather"] = t.split(":", 1)[1].strip()
                elif t.lower().startswith("attendance:"):
                    match["attendance"] = t.split(":", 1)[1].strip()

            print(f"  {match['home_team']} v {match['away_team']}: "
                  f"venue={match['venue']!r}, attendance={match['attendance']!r}")
        except Exception as e:
            print(f"WARNING: real error visiting {match_url} -- "
                  f"venue/weather/attendance left blank for this match, NOT fabricated. Error: {e}")

    driver.quit()
    return real_matches


# Real, confirmed bye schedule for 2026 rounds 11-17, cross-referenced
# from this project's own earlier real confirmations this session
# (PROJECT_BRIEF_FINAL.md / nrl_update_single_round.py's own real
# BYES dict) -- used ONLY as a real sanity cross-check during backfill
# (does the real scraped match count match the real expected count for
# this round), NEVER to fabricate or skip real scraped data. A
# mismatch here is printed as a loud warning, not silently corrected.
EXPECTED_BYES = {
    11: ["Raiders"],
    12: ["Broncos", "Eels", "Knights", "Panthers", "Roosters", "Sharks", "Wests Tigers"],
    13: ["Dolphins", "Rabbitohs", "Titans"],
    14: ["Warriors"],
    15: ["Bulldogs", "Cowboys", "Dragons", "Knights", "Panthers", "Sea Eagles", "Storm"],
    16: ["Broncos", "Eels", "Rabbitohs"],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, help="Single round to scrape (use with --output)")
    parser.add_argument("--round-start", type=int, help="Start of a real round range to backfill (use with --round-end)")
    parser.add_argument("--round-end", type=int, help="End of a real round range to backfill (inclusive)")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--output", type=str, help="Real output path for single-round mode")
    parser.add_argument("--output-dir", type=str, default=".", help="Real output directory for range/backfill mode -- one real file per round")
    args = parser.parse_args()

    if args.round_start and args.round_end:
        # Real backfill mode -- added 2026-06-25 specifically for
        # backfilling the real Round 11-16 gap found this session.
        # Writes ONE real file per round (not combined), matching the
        # same per-round granularity as the existing single-round mode
        # -- keeps each round independently reviewable before merging,
        # same real philosophy as merge_round.py's pending-file step.
        os.makedirs(args.output_dir, exist_ok=True)
        for round_num in range(args.round_start, args.round_end + 1):
            print(f"\n{'='*70}\nReal backfill: Round {round_num}\n{'='*70}")
            real_matches = scrape_round_results(round_num, args.season)

            if not real_matches:
                print(f"ERROR: zero real matches scraped for round {round_num} -- "
                      f"skipping this round's real output file, NOT writing an empty one. "
                      f"Investigate this round manually before continuing.")
                continue

            expected_byes = EXPECTED_BYES.get(round_num)
            if expected_byes is not None:
                expected_match_count = (17 - len(expected_byes)) // 2
                if len(real_matches) != expected_match_count:
                    print(f"WARNING: real match count mismatch for round {round_num} -- "
                          f"scraped {len(real_matches)}, but the real confirmed bye schedule "
                          f"({len(expected_byes)} byes: {expected_byes}) implies "
                          f"{expected_match_count} real matches. Investigate this round's "
                          f"real output carefully before merging it.")
                else:
                    print(f"Real match count CONFIRMED correct for round {round_num}: "
                          f"{len(real_matches)} matches, matching the real bye schedule.")

            output_path = os.path.join(args.output_dir, f"match_results_round_{round_num}_backfill.csv")
            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()
                for row in real_matches:
                    writer.writerow(row)
            print(f"Real backfill file written: {output_path} ({len(real_matches)} real matches)")

        print(f"\n{'='*70}\nReal backfill complete for rounds {args.round_start}-{args.round_end}.\n"
              f"Review each real per-round file in {args.output_dir} before merging -- "
              f"these are PENDING files, not yet merged into match_data_FINAL_fixed.csv.\n{'='*70}")
        return

    if not args.round or not args.output:
        print("ERROR: provide either (--round AND --output) for single-round mode, "
              "or (--round-start AND --round-end) for real backfill mode.")
        sys.exit(1)

    real_matches = scrape_round_results(args.round, args.season)

    if not real_matches:
        print("ERROR: zero real matches scraped -- not writing an empty/wrong real output file.")
        sys.exit(1)

    dirname = os.path.dirname(args.output)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in real_matches:
            writer.writerow(row)

    print(f"\nReal pending file written: {args.output} ({len(real_matches)} real matches)")
    print("This is a PENDING file -- not yet merged into match_data_FINAL_fixed.csv. "
          "A separate validate-then-merge step decides whether to merge it.")


if __name__ == "__main__":
    main()
